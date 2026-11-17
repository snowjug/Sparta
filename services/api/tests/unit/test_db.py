"""Persistence behaviour on every available engine (SQLite always, PostgreSQL when SPARTA_TEST_POSTGRES_URL is set)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from tests.factories import T0, call_row, turn

from sparta.db import models as m
from sparta.db.crypto import DecryptionError, FieldCipher, generate_key
from sparta.db.repository import CallFilter, decode_cursor
from sparta.db.types import set_cipher
from sparta.domain.enums import FeedbackKind, Speaker
from sparta.domain.models import FeedbackRecord, UserPreferences

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


async def seed_user(db, user_id: str = "u1") -> None:
    async with db.uow() as repo:
        await repo.ensure_user(user_id, user_id, NOW)


@pytest.mark.asyncio
async def test_call_content_is_encrypted_at_rest(db):
    await seed_user(db)
    secret = "my one time password is 482913 and I live at Lake View Road"
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a", purpose="tuition fees", summary_text=secret, claim={"name": "Rahul"}))
        await repo.add_turns([turn("call_a", 1, secret)])

    async with db.engine.connect() as conn:
        raw_turn = (await conn.execute(text("SELECT text FROM call_turns"))).scalar_one()
        raw_call = (await conn.execute(text("SELECT purpose, summary_text, claim FROM call_sessions"))).one()
    for stored in (raw_turn, *raw_call):
        assert (
            "482913" not in stored and "Lake View" not in stored and "Rahul" not in stored and "tuition" not in stored
        )

    async with db.uow() as repo:
        assert [t.text for t in await repo.list_turns("call_a")] == [secret]
        row = await repo.get_call_row("u1", "call_a")
        assert row.purpose == "tuition fees" and row.claim == {"name": "Rahul"}


@pytest.mark.asyncio
async def test_rows_cannot_be_read_with_a_different_key(db, field_cipher):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a"))
        await repo.add_turns([turn("call_a", 1, "private words")])
    set_cipher(FieldCipher([generate_key()]))  # an unrelated key: the old ciphertext must be unreadable
    try:
        async with db.uow() as repo:
            with pytest.raises(DecryptionError):
                await repo.list_turns("call_a")
    finally:
        set_cipher(field_cipher)


@pytest.mark.asyncio
async def test_key_rotation_new_key_first_old_key_still_reads(db, field_cipher):
    old_key = generate_key()
    set_cipher(FieldCipher([old_key]))
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a"))
        await repo.add_turns([turn("call_a", 1, "written with the old key")])
    set_cipher(FieldCipher([generate_key(), old_key]))
    async with db.uow() as repo:
        assert (await repo.list_turns("call_a"))[0].text == "written with the old key"
    set_cipher(field_cipher)


@pytest.mark.asyncio
async def test_users_cannot_see_or_change_each_others_calls(db):
    await seed_user(db, "alice")
    await seed_user(db, "bob")
    async with db.uow() as repo:
        await repo.create_call(call_row("call_alice", "alice"))
        await repo.create_call(call_row("call_bob", "bob", minutes=1))
    async with db.uow() as repo:
        assert await repo.get_call_row("bob", "call_alice") is None
        assert await repo.load_detail("bob", "call_alice") is None
        assert [c.id for c in (await repo.list_calls("alice", CallFilter()))[0]] == ["call_alice"]
        assert await repo.delete_call("bob", "call_alice") is False
        assert await repo.delete_call_content("bob", "call_alice") is False
    async with db.uow() as repo:
        assert await repo.get_call_row("alice", "call_alice") is not None


@pytest.mark.asyncio
async def test_deleting_content_leaves_a_privacy_safe_shell(db):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(
            call_row(
                "call_a",
                category="possible_financial_impersonation",
                risk_level="high",
                purpose="KYC",
                summary_text="s",
                claim={"name": "x"},
                signal_codes=["OTP_REQUEST"],
                caller_number_enc="+919876543221",
            )
        )
        await repo.add_turns([turn("call_a", 1, "hello"), turn("call_a", 2, "hi", Speaker.ASSISTANT)])
    async with db.uow() as repo:
        assert await repo.delete_call_content("u1", "call_a") is True
    async with db.uow() as repo:
        detail = await repo.load_detail("u1", "call_a")
        assert detail is not None
        assert detail.turns == [] and detail.summary_text is None and detail.purpose is None
        assert detail.has_content is False
        assert detail.risk_level.value == "high" and detail.category.value == "possible_financial_impersonation"
        row = await repo.get_call_row("u1", "call_a")
        assert row.caller_number_enc is None and row.signal_codes == []


@pytest.mark.asyncio
async def test_delete_all_content_and_delete_call(db):
    await seed_user(db)
    async with db.uow() as repo:
        for i in range(3):
            await repo.create_call(call_row(f"call_{i}", minutes=i))
            await repo.add_turns([turn(f"call_{i}", 1, f"text {i}")])
    async with db.uow() as repo:
        assert await repo.delete_all_content("u1") == 3
    async with db.uow() as repo:
        assert all(not c.has_content for c in (await repo.list_calls("u1", CallFilter()))[0])
        assert await repo.delete_call("u1", "call_1") is True
        assert len((await repo.list_calls("u1", CallFilter()))[0]) == 2


@pytest.mark.asyncio
async def test_feedback_is_idempotent_per_kind_and_stored_apart_from_the_call(db):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a"))
        _first, created = await repo.add_feedback(
            FeedbackRecord(id="fb_1", call_id="call_a", kind=FeedbackKind.WAS_SPAM, note="n1", created_at=NOW), "u1"
        )
        again, created_again = await repo.add_feedback(
            FeedbackRecord(id="fb_2", call_id="call_a", kind=FeedbackKind.WAS_SPAM, note="n2", created_at=NOW), "u1"
        )
        other, _ = await repo.add_feedback(
            FeedbackRecord(id="fb_3", call_id="call_a", kind=FeedbackKind.WRONG_SUMMARY, created_at=NOW), "u1"
        )
    assert created and not created_again
    assert again.id == "fb_1" and other.id == "fb_3"
    async with db.uow() as repo:
        assert {f.kind for f in await repo.list_feedback("call_a")} == {
            FeedbackKind.WAS_SPAM,
            FeedbackKind.WRONG_SUMMARY,
        }
        assert (await repo.feedback_counts("u1"))["was_spam"] == 1


@pytest.mark.asyncio
async def test_duplicate_provider_events_are_detected(db):
    async with db.uow() as repo:
        assert await repo.add_provider_event("azure", "evt-1", "IncomingCall", None, "x", NOW) is True
        assert await repo.add_provider_event("azure", "evt-1", "IncomingCall", None, "x", NOW) is False
        assert await repo.add_provider_event("azure", "evt-2", "IncomingCall", None, "x", NOW) is True
        assert await repo.add_provider_event("other", "evt-1", "IncomingCall", None, "x", NOW) is True


@pytest.mark.asyncio
async def test_listing_filters_search_and_cursor_pagination(db):
    await seed_user(db)
    async with db.uow() as repo:
        for i in range(7):
            await repo.create_call(
                call_row(
                    f"call_{i}",
                    minutes=i,
                    risk_level="high" if i % 2 == 0 else "low",
                    category="telemarketing" if i == 3 else "unknown",
                    languages=["kn-IN", "en-IN"] if i == 5 else ["en-IN"],
                    claim={"name": "Priya", "organization": "Acme Bank"} if i == 1 else None,
                    owner_attention=i == 6,
                )
            )
    async with db.uow() as repo:
        items, cursor = await repo.list_calls("u1", CallFilter(limit=3))
        assert [c.id for c in items] == ["call_6", "call_5", "call_4"] and cursor
        assert decode_cursor(cursor) is not None
        page2, cursor2 = await repo.list_calls("u1", CallFilter(limit=3, cursor=cursor))
        assert [c.id for c in page2] == ["call_3", "call_2", "call_1"] and cursor2
        page3, cursor3 = await repo.list_calls("u1", CallFilter(limit=3, cursor=cursor2))
        assert [c.id for c in page3] == ["call_0"] and cursor3 is None

        assert {c.id for c in (await repo.list_calls("u1", CallFilter(risk_level="high")))[0]} == {
            "call_0",
            "call_2",
            "call_4",
            "call_6",
        }
        assert [c.id for c in (await repo.list_calls("u1", CallFilter(category="telemarketing")))[0]] == ["call_3"]
        assert [c.id for c in (await repo.list_calls("u1", CallFilter(language="kn-IN")))[0]] == ["call_5"]
        assert [c.id for c in (await repo.list_calls("u1", CallFilter(attention=True)))[0]] == ["call_6"]
        assert [c.id for c in (await repo.list_calls("u1", CallFilter(q="acme")))[0]] == ["call_1"]
        since = T0 + timedelta(minutes=5)
        assert [c.id for c in (await repo.list_calls("u1", CallFilter(since=since)))[0]] == ["call_6", "call_5"]
        assert (await repo.list_calls("u1", CallFilter(q="nothing matches this")))[0] == []


@pytest.mark.asyncio
async def test_block_and_trust_are_mutually_exclusive_and_update_calls(db):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a", caller_fingerprint="fp1"))
        await repo.add_trusted("u1", "tr_1", "fp1", "+91 98•••• ••21", None, "Ravi", "call_a", NOW)
        assert await repo.caller_status("u1", "fp1") == (False, True)
        await repo.add_blocked("u1", "bl_1", "fp1", "+91 98•••• ••21", None, "spam", "call_a", NOW)
        assert await repo.caller_status("u1", "fp1") == (True, False)
        blocked, trusted = await repo.screening_lists("u1")
        assert blocked == [("bl_1", "fp1", "+91 98•••• ••21")] and trusted == []
        assert await repo.remove_blocked("u1", "bl_1") is True
        assert await repo.caller_status("u1", "fp1") == (False, False)


@pytest.mark.asyncio
async def test_preferences_and_profile_round_trip_with_defaults(db):
    await seed_user(db)
    async with db.uow() as repo:
        assert (await repo.get_preferences("u1")) == UserPreferences()
        prefs = UserPreferences(onboarding_completed=True, primary_language="kn-IN")
        await repo.save_preferences("u1", prefs, NOW)
    async with db.uow() as repo:
        assert (await repo.get_preferences("u1")).primary_language == "kn-IN"
        assert await repo.get_assistant_profile("u1") is None


@pytest.mark.asyncio
async def test_idempotency_keys_expire_and_live_events_replay_in_order(db):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.save_idempotent("u1", "POST /x", "k1", "h", 201, {"ok": True}, NOW, timedelta(hours=1))
    async with db.uow() as repo:
        row = await repo.get_idempotent("u1", "POST /x", "k1", NOW + timedelta(minutes=5))
        assert row is not None and row.response == {"ok": True}
        assert await repo.get_idempotent("u1", "POST /x", "k1", NOW + timedelta(hours=2)) is None
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a"))
        from sparta.domain.models import LiveEvent

        for seq in (1, 2, 3):
            await repo.add_live_event(
                LiveEvent(type="call.listening", call_id="call_a", seq=seq, ts=NOW, data={"n": seq})
            )
        assert [e.seq for e in await repo.list_live_events("call_a", after_seq=1)] == [2, 3]
        assert await repo.next_event_seq("call_a") == 1


@pytest.mark.asyncio
async def test_cascading_delete_removes_dependent_rows(db):
    await seed_user(db)
    async with db.uow() as repo:
        await repo.create_call(call_row("call_a"))
        await repo.add_turns([turn("call_a", 1, "x")])
        await repo.add_audit("u1", "call.delete", "call", "call_a", {"n": 1}, "req", NOW)
    async with db.uow() as repo:
        await repo.delete_call("u1", "call_a")
    async with db.engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM call_turns"))).scalar_one() == 0
        assert (await conn.execute(text("SELECT count(*) FROM audit_events"))).scalar_one() == 1  # audit survives
    assert isinstance(m.CallTurnRow, type)
