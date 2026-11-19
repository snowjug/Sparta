"""The TCP listener Asterisk connects its AudioSocket media to.

A connection is dropped before a single byte is read unless it comes from an allowed peer and the connection limit has
room. Allowed peers are IP addresses, CIDR ranges or host names (a Compose service name such as ``asterisk``); names are
resolved when a connection arrives and cached briefly.
"""

import asyncio
import contextlib
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable, Sequence

from sparta.clock import Clock
from sparta.observability import metrics as mt
from sparta.observability.metrics import Metrics

log = logging.getLogger("sparta.asterisk.media")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
ConnectionHandler = Callable[[asyncio.StreamReader, asyncio.StreamWriter, str], Awaitable[None]]
RESOLVE_TIMEOUT_S = 2.0


class PeerPolicy:
    """Which addresses may open a media connection."""

    def __init__(self, entries: Sequence[str], *, clock: Clock, resolve_ttl_s: float = 30.0) -> None:
        self._clock = clock
        self._ttl = resolve_ttl_s
        self._networks: list[IPNetwork] = []
        self._hosts: list[str] = []
        for entry in entries:
            try:
                self._networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                self._hosts.append(entry.lower())
        self._resolved: dict[str, tuple[float, frozenset[IPAddress]]] = {}

    async def allows(self, peer_ip: str) -> bool:
        try:
            address: IPAddress = ipaddress.ip_address(peer_ip.split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if any(address in network for network in self._networks):
            return True
        for host in self._hosts:
            if address in await self._addresses(host):
                return True
        return False

    async def _addresses(self, host: str) -> frozenset[IPAddress]:
        now = self._clock.monotonic()
        cached = self._resolved.get(host)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        found: set[IPAddress] = set()
        try:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), RESOLVE_TIMEOUT_S
            )
            for info in infos:
                with contextlib.suppress(ValueError):
                    address: IPAddress = ipaddress.ip_address(str(info[4][0]))
                    found.add(address)
        except (OSError, TimeoutError):
            log.warning("media peer host name did not resolve", extra={"host": host})
        result = frozenset(found)
        self._resolved[host] = (now, result)
        return result


class AudioSocketServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        peers: PeerPolicy,
        handler: ConnectionHandler,
        max_connections: int,
        metrics: Metrics,
    ) -> None:
        self._host = host
        self._port = port
        self._peers = peers
        self._handler = handler
        self._max = max_connections
        self._metrics = metrics
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def port(self) -> int:
        """The port actually bound (differs from the configured one only when that is 0)."""
        if self._server is not None and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self._port

    @property
    def connections(self) -> int:
        return len(self._tasks)

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._on_connect, self._host, self._port, backlog=32)

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        peername = writer.get_extra_info("peername")
        peer = str(peername[0]) if peername else ""
        try:
            if len(self._tasks) > self._max:
                self._reject(writer, "too_many_connections")
                return
            if not await self._peers.allows(peer):
                self._reject(writer, "peer_not_allowed")
                return
            await self._handler(reader, writer, peer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("media connection failed", extra={"error_type": type(exc).__name__})
        finally:
            if task is not None:
                self._tasks.discard(task)
            with contextlib.suppress(Exception):
                writer.close()

    def _reject(self, writer: asyncio.StreamWriter, reason: str) -> None:
        self._metrics.inc(mt.MEDIA_REJECTED, provider="asterisk", reason=reason)
        log.warning("media connection refused", extra={"reason": reason})
        writer.close()

    async def aclose(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if server is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), 2.0)
