"""What the call service hands to a language-model provider: the owner's name is replaced, nothing else changes."""

from call_harness import OWNER, Harness, running_container

from sparta.providers.base import ProviderMeta, SummaryResult, TurnAnalysis

SCAM = "Hello, I am Rahul from State Bank of India. Please tell me the OTP sent to your phone."


class RecordingModel:
    """A stand-in provider that records every request it is given."""

    meta = ProviderMeta(provider="recording", simulated=True)

    def __init__(self) -> None:
        self.turn_requests: list = []
        self.summary_requests: list = []

    async def evaluate_turn(self, request):
        self.turn_requests.append(request)
        return TurnAnalysis()

    async def generate_safe_reply(self, request):
        return None

    async def summarize_call(self, request):
        self.summary_requests.append(request)
        return SummaryResult(text="A summary written by the model.")

    async def classify_call(self, request):
        return None

    async def translate(self, text, source_language, target_language, trace_id):
        return None


async def test_the_owners_name_never_reaches_the_model_provider():
    async with running_container() as c:
        model = RecordingModel()
        c.calls.llm = model  # type: ignore[assignment]
        c.calls.settings = c.calls.settings.model_copy(update={"feature_llm_summaries": True})
        h = Harness(c)
        created = await h.start(number="+919876543210")
        opening = (await h.detail(created.id)).turns[0].text
        assert OWNER.display_name in opening  # the assistant's own opening line names the owner

        await h.say(created.id, f"Hello, is {OWNER.display_name} at home? I am calling about the water tank")
        await h.say(created.id, SCAM)
        await h.settle(created.id)

        assert len(model.turn_requests) == 2 and len(model.summary_requests) == 1
        for request in model.turn_requests:
            assert OWNER.display_name not in request.caller_text
            assert all(OWNER.display_name not in text for _, text in request.recent_turns)
        assert model.turn_requests[0].caller_text.startswith("Hello, is the owner at home?")
        assert any("the owner" in text for _, text in model.turn_requests[1].recent_turns)  # context kept, name gone
        summary = model.summary_requests[0]
        assert OWNER.display_name not in summary.rules_summary
        assert all(OWNER.display_name not in text for _, text in summary.turns)
        assert any("OTP" in text for _, text in summary.turns)  # everything else is passed through unchanged
