"""Retention, background jobs and the committed API contract."""

import asyncio
from datetime import timedelta
from pathlib import Path

from call_harness import OWNER, Harness, running_container

from sparta.cli import _openapi_text, build_parser
from sparta.domain.enums import CallStatus, OwnerActionType
from sparta.services.jobs import BackgroundJobs

SCAM = "Hello, this is Rahul from State Bank of India. Please share the OTP sent to your phone."
CONTRACT = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "openapi.json"


async def finished_call(h: Harness, number: str) -> str:
    created = await h.start(number=number)
    await h.say(created.id, SCAM)
    await h.settle(created.id)
    return created.id


# ------------------------------------------------------------------------------------------- retention
async def test_transcripts_expire_before_summaries_and_records_expire_last():
    async with running_container() as c:
        h = Harness(c)
        async with c.db.uow() as repo:
            prefs = await repo.get_preferences(OWNER.id)
            prefs.retention.transcript_retention_days = 7
            prefs.retention.summary_retention_days = 90
            await repo.ensure_user(OWNER.id, "Atharv", c.clock.now())
            await repo.save_preferences(OWNER.id, prefs, c.clock.now())
        call_id = await finished_call(h, "+919800000051")

        assert (await c.retention.run_once()).content_deleted == 0  # too early: everything is kept
        await c.clock.advance(timedelta(days=8).total_seconds())
        report = await c.retention.run_once()
        assert report.content_deleted == 1 and report.records_deleted == 0
        detail = await h.detail(call_id)
        assert detail.turns == [] and detail.has_content is False
        assert detail.summary is not None and detail.risk_level.value == "high"  # the summary and level survive
        assert detail.risk is not None and detail.risk.signals  # so does the "why", without quoting the caller
        assert all(s.evidence_excerpt is None for s in detail.risk.signals)
        async with c.db.uow() as repo:
            row = await repo.get_call_row(OWNER.id, call_id)
            ctx = repo.context_of(row)
            assert all(s.evidence_excerpt is None for s in ctx.signals)
            assert all(s.evidence_excerpt is None for s in (ctx.risk.signals if ctx.risk else []))
            assert await repo.list_live_events(call_id) == []  # partial transcripts and turns are gone too

        await c.clock.advance(timedelta(days=83).total_seconds())
        report = await c.retention.run_once()
        assert report.records_deleted == 1
        items, _ = await c.calls.list_calls(
            OWNER, __import__("sparta.db.repository", fromlist=["CallFilter"]).CallFilter()
        )
        assert items == []
        async with c.db.uow() as repo:
            actions = [a.action for a in await repo.list_audit(OWNER.id)]
        assert actions.count("retention.applied") == 2


async def test_each_owner_keeps_their_own_retention_policy():
    async with running_container() as c:
        short, long_ = Harness(c), Harness(c, __import__("call_harness").OTHER)
        async with c.db.uow() as repo:
            for principal, days in ((OWNER, 1), (long_.p, 30)):
                await repo.ensure_user(principal.id, principal.display_name, c.clock.now())
                prefs = await repo.get_preferences(principal.id)
                prefs.retention.transcript_retention_days = days
                await repo.save_preferences(principal.id, prefs, c.clock.now())
        a = await finished_call(short, "+919800000052")
        b = await finished_call(long_, "+919800000053")
        await c.clock.advance(timedelta(days=2).total_seconds())
        await c.retention.run_once()
        assert (await short.detail(a)).has_content is False
        assert (await long_.detail(b)).has_content is True


async def test_zero_day_retention_clears_content_at_the_next_run_and_active_calls_are_never_touched():
    async with running_container() as c:
        h = Harness(c)
        async with c.db.uow() as repo:
            await repo.ensure_user(OWNER.id, "Atharv", c.clock.now())
            prefs = await repo.get_preferences(OWNER.id)
            prefs.retention.transcript_retention_days = 0
            await repo.save_preferences(OWNER.id, prefs, c.clock.now())
        live = await h.start(number="+919800000054")
        done = await finished_call(h, "+919800000055")
        await c.clock.advance(5)
        await c.retention.run_once()
        assert (await h.detail(done)).has_content is False
        still = await h.detail(live.id)
        assert still.status is CallStatus.ACTIVE and still.has_content is True


async def test_technical_rows_are_purged_after_their_time(tmp_path):
    async with running_container() as c:
        now = c.clock.now()
        async with c.db.uow() as repo:
            await repo.ensure_user(OWNER.id, "Atharv", now)
            await repo.save_idempotent(OWNER.id, "POST /x", "key-1", "h", 201, {"ok": True}, now, timedelta(hours=24))
            await repo.add_provider_event("generic", "old-event-id", "call.incoming", None, None, now)
        await c.clock.advance(timedelta(days=2).total_seconds())
        await c.retention.run_once()
        async with c.db.uow() as repo:
            assert await repo.get_idempotent(OWNER.id, "POST /x", "key-1", c.clock.now()) is None
            assert await repo.has_provider_event("generic", "old-event-id") is True  # 30 days, not 2
        await c.clock.advance(timedelta(days=30).total_seconds())
        await c.retention.run_once()
        async with c.db.uow() as repo:
            assert await repo.has_provider_event("generic", "old-event-id") is False


# --------------------------------------------------------------------------------------- background jobs
async def test_the_reaper_job_closes_abandoned_calls_and_survives_failures():
    async with running_container(abandoned_call_timeout_s=30) as c:
        h = Harness(c)
        created = await h.start(number=None)
        await h.settle(created.id)
        jobs = BackgroundJobs(calls=c.calls, retention=c.retention, reaper_interval_s=0.05, retention_interval_s=3600)
        await c.clock.advance(31)
        jobs.start()
        try:
            for _ in range(200):
                if (await h.detail(created.id)).status is CallStatus.ENDED:
                    break
                await asyncio.sleep(0.02)
            assert (await h.detail(created.id)).status is CallStatus.ENDED
            c.calls.reap_abandoned = _raise_once(c.calls.reap_abandoned)  # type: ignore[method-assign]
            await asyncio.sleep(0.3)  # a failing run must not kill the loop
            assert all(not t.done() for t in jobs._tasks)
        finally:
            await jobs.stop()
        assert jobs._tasks == []


def _raise_once(original):  # type: ignore[no-untyped-def]
    state = {"raised": False}

    async def wrapper():  # type: ignore[no-untyped-def]
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("boom")
        return await original()

    return wrapper


# ------------------------------------------------------------------------------------------ API contract
def test_the_committed_openapi_document_matches_the_application():
    """Fails when an endpoint or model changes without regenerating `packages/contracts/openapi.json`."""
    assert CONTRACT.exists(), "run: python -m sparta openapi --out ../../packages/contracts/openapi.json"
    assert CONTRACT.read_text(encoding="utf-8") == _openapi_text(), (
        "packages/contracts/openapi.json is out of date: run "
        "`python -m sparta openapi --out ../../packages/contracts/openapi.json` and commit the result"
    )


def test_the_cli_exposes_the_documented_commands():
    parser = build_parser()
    for command in ("serve", "migrate", "seed", "openapi", "evaluate", "keygen"):
        assert parser.parse_args([command]).command == command
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000


def test_takeover_is_the_only_owner_action_that_needs_a_provider_that_can_transfer():
    assert OwnerActionType.TAKEOVER.value == "takeover"
