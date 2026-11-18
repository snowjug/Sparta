"""Missing dependencies produce one readable line, never credentials and never only a stack trace."""

import socket

import pytest

from sparta import cli
from sparta.config import Settings
from sparta.preflight import check_database, check_dependencies, check_redis, describe_target, reason_for


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_describe_target_never_includes_credentials():
    assert describe_target("postgresql+asyncpg://sparta:hunter2@db.internal:5432/sparta") == (
        "postgresql at db.internal:5432/sparta"
    )
    assert "hunter2" not in describe_target("redis://:hunter2@cache.internal:6379/0")
    assert describe_target("sqlite+aiosqlite:///./var/sparta.db") == "SQLite file ./var/sparta.db"
    assert describe_target("not a url") == "an unparseable URL"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionRefusedError(), "connection refused"),
        (OSError("Multiple exceptions: [Errno 111] Connect call failed ('127.0.0.1', 5432)"), "connection refused"),
        (socket.gaierror(), "host name not found"),
        (TimeoutError(), "timed out"),
        (RuntimeError("password=hunter2"), "unexpected RuntimeError"),
    ],
)
def test_reason_for_is_short_and_leaks_nothing(exc, expected):
    assert reason_for(exc) == expected


def test_reason_for_follows_the_cause_chain():
    outer = RuntimeError("wrapped")
    outer.__cause__ = ConnectionRefusedError()
    assert reason_for(outer) == "connection refused"


@pytest.mark.asyncio
async def test_a_reachable_database_passes(tmp_path):
    assert await check_database(f"sqlite+aiosqlite:///{(tmp_path / 'var' / 'ok.db').as_posix()}") is None


@pytest.mark.asyncio
async def test_an_unreachable_database_is_explained_without_the_password():
    message = await check_database(f"postgresql+asyncpg://sparta:hunter2@127.0.0.1:{_closed_port()}/sparta")
    assert message is not None
    assert "Cannot reach the database" in message and "connection refused" in message
    assert "SPARTA_DATABASE_URL" in message and "hunter2" not in message and "Traceback" not in message


@pytest.mark.asyncio
async def test_an_unreachable_redis_is_explained():
    message = await check_redis(f"redis://:hunter2@127.0.0.1:{_closed_port()}/0")
    assert message is not None
    assert "Cannot reach Redis" in message and "SPARTA_REDIS_URL" in message and "hunter2" not in message


@pytest.mark.asyncio
async def test_check_dependencies_reports_every_problem_and_skips_redis_when_not_configured(tmp_path):
    port = _closed_port()
    broken = Settings(
        _env_file=None,
        database_url=f"postgresql+asyncpg://u:p@127.0.0.1:{port}/db",
        redis_url=f"redis://127.0.0.1:{port}/0",
    )
    assert len(await check_dependencies(broken)) == 2
    assert len(await check_dependencies(broken, include_redis=False)) == 1
    fine = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{(tmp_path / 'fine.db').as_posix()}")
    assert await check_dependencies(fine) == []


def test_cli_migrate_fails_with_exit_code_2_and_a_readable_message(monkeypatch, capsys):
    broken = Settings(_env_file=None, database_url=f"postgresql+asyncpg://u:hunter2@127.0.0.1:{_closed_port()}/db")
    monkeypatch.setattr(cli, "_settings", lambda: broken)
    assert cli.main(["migrate"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: Cannot reach the database") and "hunter2" not in err and "Traceback" not in err


def test_cli_serve_does_not_start_when_the_database_is_unreachable(monkeypatch, capsys):
    broken = Settings(_env_file=None, database_url=f"postgresql+asyncpg://u:p@127.0.0.1:{_closed_port()}/db")
    monkeypatch.setattr(cli, "_settings", lambda: broken)
    assert cli.main(["serve", "--port", "0"]) == 2
    assert "Cannot reach the database" in capsys.readouterr().err


def test_cli_serve_refuses_the_development_identity_on_a_network_address(monkeypatch, capsys):
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: started.append(kwargs))
    monkeypatch.setattr(cli, "_dependencies_ok", lambda *args, **kwargs: True)

    monkeypatch.setattr(cli, "_settings", lambda: Settings(_env_file=None, auth_mode="dev"))
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "SPARTA_ALLOW_NETWORK_DEV_AUTH" in capsys.readouterr().err and not started

    assert cli.main(["serve", "--host", "127.0.0.1"]) == 0  # loopback is always fine
    assert started

    monkeypatch.setattr(
        cli, "_settings", lambda: Settings(_env_file=None, auth_mode="dev", allow_network_dev_auth=True)
    )
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 0
    assert "WARNING" in capsys.readouterr().err and len(started) == 2
