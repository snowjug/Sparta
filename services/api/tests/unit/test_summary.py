import pytest

from sparta.domain.enums import OwnerActionType, TurnSource
from sparta.orchestrator.engine import CallerInput, ConversationEngine, EngineConfig
from sparta.orchestrator.summary import build_summary


def run(engine: ConversationEngine, turns: list[str], owner: OwnerActionType | None = None):
    cfg = EngineConfig(call_id="call_sum00001", owner_name="Atharv")
    r = engine.start(cfg)
    ctx, prev = r.ctx, None
    for text in turns:
        r = engine.on_caller_turn(ctx, cfg, CallerInput(text=text, source=TurnSource.TYPED, previous_text=prev))
        ctx, prev = r.ctx, text
        if r.end_reason:
            break
    if owner:
        ctx = engine.on_owner_action(ctx, cfg, owner).ctx
    ctx = engine.complete(ctx, ctx.ended_reason or "completed")
    return ctx, build_summary(cfg.call_id, ctx, ctx.risk)


def test_bank_otp_call_summary_matches_the_product_example(engine):
    _, s = run(
        engine,
        [
            "Hello, I'm Rahul from State Bank. Your KYC is pending.",
            "Your account will be blocked today. Please tell me the OTP you just received.",
        ],
    )
    assert "claimed to represent a bank (State Bank)" in s.text
    assert "one-time password (OTP)" in s.text
    assert "Sparta refused and ended the call." in s.text
    assert "No owner action is required" in s.text
    assert s.owner_action_required is False and s.generated_by == "rules-v1"


def test_legitimate_escalation_summary_asks_the_owner_to_call_back(engine):
    _, s = run(engine, ["Sir I am the delivery boy, I am at your gate but can't find the building, which floor?"])
    assert "delivery" in s.text and "Sparta alerted the owner" in s.text
    assert s.owner_action_required
    assert "owner's address" not in s.text, "a landmark question must not be reported as an address probe"


def test_emergency_summary_is_urgent(engine):
    _, s = run(engine, ["I'm calling from City Hospital. Your mother has been admitted after an accident."])
    assert "emergency" in s.text and "promptly" in s.text


def test_simulated_takeover_is_labelled_simulated(engine):
    ctx, _ = run(engine, ["Delivery boy at your gate, can't find the building"], owner=OwnerActionType.TAKEOVER)
    s = build_summary("call_sum00001", ctx, ctx.risk, simulated=True)
    assert "took over the call (simulated)" in s.text
    assert not s.owner_action_required


@pytest.mark.parametrize(
    "turns",
    [
        ["Hello, my name is Priya and this is about the tuition fee receipt"],
        ["Hi, it's Ravi, can you tell Atharv I called back"],
    ],
)
def test_summary_never_invents_facts_that_were_not_in_the_call(engine, turns):
    _, s = run(engine, turns)
    for invented in ("bank", "police", "OTP", "arrest", "lottery", "gift card", "remote", "blocked"):
        assert invented.lower() not in s.text.lower(), f"{invented!r} hallucinated in: {s.text}"


def test_silent_call_summary(engine):
    cfg = EngineConfig(call_id="call_sum00002", owner_name="Atharv")
    r = engine.start(cfg)
    ctx = engine.on_silence(r.ctx, cfg).ctx
    ctx = engine.on_silence(ctx, cfg).ctx
    s = build_summary(cfg.call_id, engine.complete(ctx, "silence"), ctx.risk)
    assert "stayed silent" in s.text


def test_unsupported_language_summary_mentions_the_limitation(engine):
    _, s = run(engine, ["நீங்கள் யார் பேசுகிறீர்கள்", "எனக்கு உதவி வேண்டும்", "தயவுசெய்து உதவுங்கள்"])
    assert "does not support" in s.text
    assert s.owner_action_required


def test_summary_without_an_assessment_is_honest():
    from sparta.domain.models import ConversationContext

    s = build_summary("call_x", ConversationContext(), None)
    assert "before Sparta could assess" in s.text
