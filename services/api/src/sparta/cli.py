"""Command line entry point: ``python -m sparta <command>`` (or the ``sparta`` script).

Commands: ``serve`` (HTTP API), ``migrate`` (database schema), ``seed`` (development owner), ``openapi`` (export the API
contract), ``evaluate`` (run the evaluation dataset) and ``keygen`` (generate secrets for ``.env``).
"""

import argparse
import asyncio
import json
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from sparta.config import ConfigurationError, Settings

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _settings() -> Settings:
    from sparta.config import get_settings

    return get_settings()


def _dependencies_ok(settings: Settings, *, redis: bool) -> bool:
    """Print one readable line per unreachable dependency instead of letting the server die with a stack trace."""
    from sparta.preflight import check_dependencies

    problems = asyncio.run(check_dependencies(settings, include_redis=redis))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return not problems


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from sparta.logging_setup import configure_logging

    settings = _settings()
    configure_logging(settings.log_level, settings.log_json)
    if not _dependencies_ok(settings, redis=True):
        return 2
    if settings.auth_mode == "dev" and args.host not in LOOPBACK:
        print(
            "WARNING: development identity is active and this server listens on a non-loopback address "
            f"({args.host}). Anyone who can reach it acts as the owner. Use it only on a trusted network.",
            file=sys.stderr,
        )
    uvicorn.run(
        "sparta.api.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,  # our JSON logging; uvicorn's access log would print WebSocket tickets in query strings
        access_log=False,
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips=args.forwarded_allow_ips if args.proxy_headers else None,
    )
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from sparta.db.session import downgrade, run_migrations

    settings = _settings()
    if not _dependencies_ok(settings, redis=False):
        return 2
    if args.revision.startswith("-") or args.direction == "down":
        asyncio.run(downgrade(settings.database_url, args.revision))
    else:
        asyncio.run(run_migrations(settings.database_url, args.revision))
    print(f"database is at revision '{args.revision}'")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    from sparta.services.container import Container
    from sparta.services.dto import Principal

    async def run() -> str:
        settings = _settings()
        container = await Container.build(settings)
        await container.start()
        try:
            principal = Principal(id=settings.dev_user_id, display_name=settings.dev_user_name)
            await container.owner.ensure_user(principal)
            await container.owner.get_preferences(principal)
            return principal.id
        finally:
            await container.stop()

    if not _dependencies_ok(_settings(), redis=True):
        return 2
    owner = asyncio.run(run())
    print(f"development owner '{owner}' is ready")
    return 0


def _openapi_text() -> str:
    from sparta.api.main import create_app

    app = create_app(Settings(_env_file=None, env="test"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def cmd_openapi(args: argparse.Namespace) -> int:
    text = _openapi_text()
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(
                f"{out} is out of date: run `python -m sparta openapi --out {out}` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(text):,} bytes)")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from sparta.evaluation.cli import run_evaluation

    return run_evaluation(args)


def cmd_keygen(_: argparse.Namespace) -> int:
    from sparta.db.crypto import generate_key

    print("# Add these to your .env (never commit them). Rotating SPARTA_DATA_KEYS: put the new key first.")
    print(f"SPARTA_DATA_KEYS={generate_key()}")
    print(f"SPARTA_PEPPER={secrets.token_urlsafe(32)}")
    print(f"SPARTA_WEBHOOK_SECRET={secrets.token_urlsafe(32)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparta", description="Sparta call-screening backend")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="development auto-reload")
    serve.add_argument("--proxy-headers", action="store_true", help="trust X-Forwarded-* from --forwarded-allow-ips")
    serve.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    serve.set_defaults(func=cmd_serve)

    migrate = sub.add_parser("migrate", help="apply database migrations")
    migrate.add_argument("revision", nargs="?", default="head")
    migrate.add_argument("--direction", choices=("up", "down"), default="up")
    migrate.set_defaults(func=cmd_migrate)

    sub.add_parser("seed", help="create the development owner").set_defaults(func=cmd_seed)

    openapi = sub.add_parser("openapi", help="export the OpenAPI contract")
    openapi.add_argument("--out", default="../../packages/contracts/openapi.json")
    openapi.add_argument("--check", action="store_true", help="fail if the file on disk differs (CI drift check)")
    openapi.set_defaults(func=cmd_openapi)

    evaluate = sub.add_parser("evaluate", help="run the evaluation dataset against the engine")
    evaluate.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    evaluate.add_argument("--dataset", default="../../packages/evaluation/dataset/v1")
    evaluate.add_argument("--out", default=None, help="write the JSON report here ({split} is substituted)")
    evaluate.add_argument("--markdown", default=None, help="write a Markdown summary here ({split} is substituted)")
    evaluate.add_argument("--stt-noise", action="store_true", help="also run the synthetic-noise robustness sweep")
    evaluate.add_argument(
        "--details", action="store_true", help="include failing test-split scenarios (do not tune on them)"
    )
    evaluate.set_defaults(func=cmd_evaluate)

    sub.add_parser("keygen", help="generate secrets for .env").set_defaults(func=cmd_keygen)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
