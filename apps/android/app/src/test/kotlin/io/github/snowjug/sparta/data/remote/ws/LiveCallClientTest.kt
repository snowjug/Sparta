package io.github.snowjug.sparta.data.remote.ws

import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.BaseUrlProvider
import io.github.snowjug.sparta.testutil.ApiHarness
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveCallClientTest {

    private val harnesses = mutableListOf<ApiHarness>()

    private fun harness() = ApiHarness().also { harnesses += it }

    @After
    fun tearDown() = harnesses.forEach { it.close() }

    private fun client(h: ApiHarness, base: BaseUrlProvider = BaseUrlProvider { h.baseUrl }) =
        LiveCallClient(h.api, h.client, base, maxFailures = 3, backoffMs = { 0L })

    private fun ticket(h: ApiHarness, ticket: String = "T1", wsUrl: String = "wss://elsewhere.invalid/api/v1/live/c1?ticket=$ticket") =
        h.enqueueJson("""{"ticket":"$ticket","expires_in":60,"ws_url":"$wsUrl"}""")

    private fun upgrade(h: ApiHarness, onOpen: (WebSocket) -> Unit) {
        h.server.enqueue(
            MockResponse().withWebSocketUpgrade(
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) = onOpen(webSocket)
                },
            ),
        )
    }

    private fun collect(flow: Flow<LiveSocketEvent>): List<LiveSocketEvent> = runBlocking { withTimeout(15_000) { flow.toList() } }

    @Test
    fun `requests a ticket then connects with it and streams messages until a normal close`() {
        val h = harness()
        ticket(h)
        upgrade(h) { socket ->
            socket.send("""{"type":"call.snapshot","call_id":"c1","seq":0,"data":{}}""")
            socket.send("""{"type":"ping"}""")
            socket.send("""{"type":"call.listening","call_id":"c1","seq":1,"simulated":true,"data":{}}""")
            socket.send("this is not json")
            socket.close(1000, "done")
        }

        val events = collect(client(h).events("c1"))

        assertEquals(LiveSocketEvent.Connecting, events.first())
        assertTrue(events.contains(LiveSocketEvent.Open))
        val types = events.filterIsInstance<LiveSocketEvent.Message>().map { it.event.type }
        assertEquals(listOf("call.snapshot", "call.listening"), types)
        val closed = events.last() as LiveSocketEvent.Closed
        assertEquals(1000, closed.code)
        assertTrue(!closed.fatal)

        val ticketRequest = h.takeRequest()
        assertEquals("POST", ticketRequest.method)
        assertEquals("/api/v1/live/ticket", ticketRequest.path)
        assertEquals("""{"call_id":"c1"}""", ticketRequest.body.readUtf8())
        val handshake = h.takeRequest()
        assertEquals("/api/v1/live/c1?ticket=T1", handshake.path)
        assertEquals("websocket", handshake.getHeader("Upgrade"))
    }

    @Test
    fun `the ws url hint in the ticket response is ignored so tickets only go to the configured backend`() {
        val h = harness()
        ticket(h, wsUrl = "wss://evil.invalid/api/v1/live/c1?ticket=T1")
        upgrade(h) { it.close(1000, "done") }
        val events = collect(client(h).events("c1"))
        assertTrue(events.contains(LiveSocketEvent.Open))
        assertEquals(2, h.server.requestCount)
    }

    @Test
    fun `all calls subscription omits the call id`() {
        val h = harness()
        ticket(h)
        upgrade(h) { it.close(1000, "done") }
        collect(client(h).events(null))
        assertEquals("{}", h.takeRequest().body.readUtf8())
        assertEquals("/api/v1/live?ticket=T1", h.takeRequest().path)
    }

    @Test
    fun `unknown call close code is fatal and not retried`() {
        val h = harness()
        ticket(h)
        upgrade(h) { it.close(4404, "call not found") }
        val events = collect(client(h).events("missing"))
        val closed = events.last() as LiveSocketEvent.Closed
        assertEquals(4404, closed.code)
        assertTrue(closed.fatal)
        assertEquals(2, h.server.requestCount)
    }

    @Test
    fun `origin not allowed close code is fatal`() {
        val h = harness()
        ticket(h)
        upgrade(h) { it.close(4403, "origin") }
        val closed = collect(client(h).events("c1")).last() as LiveSocketEvent.Closed
        assertTrue(closed.fatal)
        assertEquals(4403, closed.code)
    }

    @Test
    fun `an expired ticket close fetches a fresh ticket and reconnects`() {
        val h = harness()
        ticket(h, "OLD")
        upgrade(h) { it.close(4401, "expired") }
        ticket(h, "NEW")
        upgrade(h) { socket ->
            socket.send("""{"type":"call.listening","call_id":"c1","seq":1,"data":{}}""")
            socket.close(1000, "done")
        }

        val events = collect(client(h).events("c1"))

        assertTrue(events.any { it is LiveSocketEvent.Reconnecting })
        assertEquals(1, events.filterIsInstance<LiveSocketEvent.Message>().size)
        h.takeRequest()
        assertEquals("/api/v1/live/c1?ticket=OLD", h.takeRequest().path)
        h.takeRequest()
        assertEquals("/api/v1/live/c1?ticket=NEW", h.takeRequest().path)
    }

    @Test
    fun `a rejected ticket request ends with the api error`() {
        val h = harness()
        h.enqueueJson("""{"error":{"code":"unauthorized","message":"Sign in required","trace_id":"t"}}""", 401)
        val failed = collect(client(h).events("c1")).last() as LiveSocketEvent.Failed
        assertEquals(ApiErrorKind.UNAUTHORIZED, failed.error.kind)
    }

    @Test
    fun `a missing ticket is reported as malformed`() {
        val h = harness()
        h.enqueueJson("""{"ticket":"","expires_in":0,"ws_url":""}""")
        val failed = collect(client(h).events("c1")).last() as LiveSocketEvent.Failed
        assertEquals(ApiErrorKind.MALFORMED, failed.error.kind)
    }

    @Test
    fun `no configured backend fails immediately`() {
        val h = harness()
        val failed = collect(client(h, BaseUrlProvider { null }).events("c1")).last() as LiveSocketEvent.Failed
        assertEquals(ApiErrorKind.NOT_CONFIGURED, failed.error.kind)
        assertEquals(0, h.server.requestCount)
    }

    @Test
    fun `repeated transient ticket failures give up after the failure budget`() {
        val h = harness()
        repeat(3) { h.enqueueJson("boom", 503) }
        val events = collect(client(h).events("c1"))
        val failed = events.last() as LiveSocketEvent.Failed
        assertTrue(failed.error.isTransient)
        assertEquals(3, h.server.requestCount)
    }

    @Test
    fun `backoff grows and stays within the cap`() {
        val delays = (1..8).map { defaultLiveBackoff(it) }
        assertTrue(delays[0] in 800L..1200L)
        assertTrue(delays[1] in 1600L..2400L)
        assertTrue(delays[4] in 12_000L..18_000L)
        assertTrue(delays.all { it <= 18_000L })
    }
}
