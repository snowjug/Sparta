"""Command line entry point: ``python -m sparta <command>`` (or the ``sparta`` script).

Commands: ``serve`` (HTTP API), ``migrate`` (database schema), ``seed`` (development owner), ``openapi`` (export the API
contract), ``evaluate`` (run the evaluation dataset), ``keygen`` (generate secrets for ``.env``), ``doctor`` (provider
preflight: can a real call work with this configuration?) and ``models`` (list, fetch and verify the local speech models).
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
    if settings.auth_mode == "dev" and args.host not in LOOPBACK:
        if not settings.allow_network_dev_auth:
            print(
                f"error: refusing to listen on {args.host} with the development identity: anyone who can reach the "
                "server would act as the owner. Bind 127.0.0.1, set SPARTA_AUTH_MODE=oidc, or (trusted network or "
                "container only) set SPARTA_ALLOW_NETWORK_DEV_AUTH=true.",
                file=sys.stderr,
            )
            return 2
        print(
            "WARNING: development identity is active and this server listens on a non-loopback address "
            f"({args.host}), as SPARTA_ALLOW_NETWORK_DEV_AUTH allows. Use it only on a trusted network.",
            file=sys.stderr,
        )
    if not _dependencies_ok(settings, redis=True):
        return 2
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that a real telephone, speech and model setup can work. Prints no secret; exit status 1 when blocked."""
    from sparta.doctor import run_doctor
    from sparta.doctor.runner import load_settings

    if args.env_file and not Path(args.env_file).is_file():
        print(f"error: --env-file {args.env_file}: no such file", file=sys.stderr)
        return 2
    settings = load_settings(args.env_file)
    try:
        report = asyncio.run(
            run_doctor(
                settings,
                providers=args.provider or ["azure"],
                online=args.online,
                allow_billable=args.allow_billable,
                callback_url=args.callback_url,
                timeout_s=args.timeout,
            )
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(report.render_json() if args.json else report.render_text(colour=sys.stdout.isatty()))
    return report.exit_code()


def _size(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e3:.0f} KB" if n >= 1e3 else f"{n} B"


def _wrapped(text: str, indent: str) -> str:
    import textwrap

    return textwrap.fill(text, width=100, initial_indent=indent, subsequent_indent=indent)


def cmd_models_list(args: argparse.Namespace) -> int:
    """The manifest of local speech models and what is installed (no network, no hashing)."""
    from sparta.providers.local_models import ENGINE_NOTE, STT_MODELS, VOICES, model_root, model_status

    settings = _settings()
    root = model_root(settings, args.dir)
    statuses = {(s.kind, s.name): s for s in model_status(settings, root=root)}
    print(f"Local speech models in {root}")
    print(f"{ENGINE_NOTE} Install the engines with: pip install 'sparta-api[local-speech]'")
    print("'*' marks what the current settings use (SPARTA_LOCAL_STT_MODEL, SPARTA_LOCAL_TTS_VOICES).")
    print("\nSpeech-to-text (faster-whisper)")
    for spec in STT_MODELS.values():
        status = statuses[("stt", spec.key)]
        print(f" {'*' if status.selected else ' '} {spec.key:<16}{_size(spec.total_bytes):>8}  {status.detail}")
        print(_wrapped(f"{spec.summary}. Licence: {spec.licence}. {spec.caveat}", "      "))
    custom = [s for s in statuses.values() if s.kind == "stt" and s.name not in STT_MODELS]
    for status in custom:
        print(f" * {status.name:<16}{'':>8}  {status.detail}")
    print("\nText-to-speech voices (Piper)")
    for spec in VOICES.values():
        status = statuses[("tts", spec.key)]
        where = f" [{status.locale}]" if status.locale else ""
        print(f" {'*' if status.selected else ' '} {spec.key:<26}{_size(spec.total_bytes):>8}  {status.detail}{where}")
        print(_wrapped(f"{spec.summary}. Licence: {spec.licence}. {spec.caveat}", "      "))
    for status in (s for s in statuses.values() if s.kind == "tts" and s.name not in VOICES):
        print(f" * {status.name:<26}{'':>8}  {status.detail} [{status.locale}]")
    return 0


def cmd_models_verify(args: argparse.Namespace) -> int:
    """Hash every installed model file and compare it with the pinned SHA-256. Exit status 1 when one does not match."""
    from sparta.providers.local_models import model_root, model_status

    settings = _settings()
    root = model_root(settings, args.dir)
    print(f"Verifying installed speech models in {root} (reads every file once)")
    failed = False
    seen = False
    for status in model_status(settings, verify=True, root=root):
        if status.verified is True:
            seen = True
            print(f"  OK       {status.name}: {status.detail}")
        elif status.verified is False or (not status.installed and "not installed" not in status.detail):
            seen = failed = True
            print(f"  FAILED   {status.name}: {status.detail}")
        elif status.installed:
            seen = True
            print(f"  skipped  {status.name}: {status.detail}")
    if not seen:
        print("  nothing is installed yet: run `python -m sparta models fetch`")
    return 1 if failed else 0


def cmd_models_fetch(args: argparse.Namespace) -> int:
    """Download pinned speech models (HTTPS, Hugging Face only, SHA-256 verified). The only code that downloads."""
    from sparta.providers.local_models import (
        ENGINE_NOTE,
        ModelFetchError,
        default_selection,
        fetch_models,
        model_root,
        pending_bytes,
        resolve_stt,
        resolve_voices,
    )

    settings = _settings()
    root = model_root(settings, args.dir)
    try:
        stt, voices = default_selection(settings)
        if args.stt is not None:
            stt = resolve_stt(args.stt)
        if args.voices is not None:
            voices = resolve_voices([part for item in args.voices for part in item.split(",")])
    except ModelFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    chosen = [*stt, *voices]
    if not chosen:
        print("Nothing to fetch: name a model with --stt small|large-v3-turbo and/or voices with --voices en,hi,kn.")
        return 0
    print(f"Fetching into {root}")
    print(f"{ENGINE_NOTE}")
    for spec in chosen:
        todo = pending_bytes(spec, root)
        print(f"  {spec.key}: {_size(todo) + ' to download' if todo else 'already complete'}")
        print(_wrapped(f"Licence: {spec.licence}. {spec.caveat}", "      "))
    last: dict[str, int] = {}

    def progress(label: str, done: int, total: int) -> None:
        step = done * 10 // total
        if step > last.get(label, -1):
            last[label] = step
            print(f"    {label}: {done * 100 // total}% ({_size(done)} of {_size(total)})", flush=True)

    try:
        results = fetch_models(chosen, root, progress=progress)
    except (ModelFetchError, OSError) as exc:
        message = (
            exc
            if isinstance(exc, ModelFetchError)
            else f"could not write to {root} ({exc.strerror or type(exc).__name__})"
        )
        print(f"error: {message}", file=sys.stderr)
        return 1
    for key, files in results.items():
        fresh = sum(1 for _, how in files if how == "downloaded")
        print(f"  {key}: {fresh} file(s) downloaded, {len(files) - fresh} already present, all SHA-256 verified")
    print("Done. Check any time with `python -m sparta models verify`.")
    return 0


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

    doctor = sub.add_parser(
        "doctor",
        help="check that a real telephone, speech and model setup can work (prints no secret)",
        description="Provider preflight. Reports PASS, WARNING, BLOCKED or UNVERIFIED per check and exits 1 when "
        "anything is BLOCKED. Without --online nothing leaves this machine.",
    )
    doctor.add_argument(
        "--provider",
        action="append",
        choices=("azure", "twilio", "asterisk", "simulator", "all"),
        default=None,
        help="telephony provider to check (repeatable; default: azure). Azure and Twilio use Azure speech and the language "
        "model; asterisk (free local SIP, no phone number) uses the speech that SPARTA_STT_PROVIDER and "
        "SPARTA_TTS_PROVIDER select (local or azure)",
    )
    doctor.add_argument(
        "--online",
        action="store_true",
        help="also make free network requests (health, keys, voices; for asterisk one SIP OPTIONS over UDP and one TCP connect)",
    )
    doctor.add_argument(
        "--allow-billable",
        action="store_true",
        help="with --online: also run tiny probes that cost a fraction of a cent (a speech round trip, one model turn)",
    )
    doctor.add_argument("--callback-url", default=None, help="check this public https origin instead of the setting")
    doctor.add_argument(
        "--env-file",
        default=None,
        help="read the settings from this .env file instead of ./.env (from services/api, ../../.env is the file "
        "that scripts/sip_local.py init writes in the repository root); variables already set in the environment still win",
    )
    doctor.add_argument("--timeout", type=float, default=8.0, help="seconds per network request (default 8)")
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(func=cmd_doctor)

    models = sub.add_parser(
        "models",
        help="list, download and verify the local (free, open-source) speech models",
        description="The local speech providers (SPARTA_STT_PROVIDER=local, SPARTA_TTS_PROVIDER=local) never download "
        "anything at run time: `models fetch` is the only command that does, from Hugging Face over HTTPS, pinned to a "
        "commit and a SHA-256 per file.",
    )
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list", help="what the manifest offers and what is installed")
    models_list.add_argument("--dir", default=None, help="model directory (default: SPARTA_LOCAL_MODEL_DIR)")
    models_list.set_defaults(func=cmd_models_list)
    models_fetch = models_sub.add_parser("fetch", help="download pinned models (default: those the settings use)")
    models_fetch.add_argument(
        "--stt",
        action="append",
        default=None,
        metavar="MODEL",
        help="speech-to-text model: small or large-v3-turbo (repeatable; 'none' skips it)",
    )
    models_fetch.add_argument(
        "--voices",
        action="append",
        default=None,
        metavar="LIST",
        help="voices as languages or ids, e.g. en,hi,kn (or 'all' / 'none')",
    )
    models_fetch.add_argument("--dir", default=None, help="model directory (default: SPARTA_LOCAL_MODEL_DIR)")
    models_fetch.set_defaults(func=cmd_models_fetch)
    models_verify = models_sub.add_parser("verify", help="check every installed file against its pinned SHA-256")
    models_verify.add_argument("--dir", default=None, help="model directory (default: SPARTA_LOCAL_MODEL_DIR)")
    models_verify.set_defaults(func=cmd_models_verify)
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
