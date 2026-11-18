"""Conversation model backed by Sparta's deterministic rules.

This is the default provider and the only one that is *always* safe to run: it never calls out, never hallucinates, and
produces the same output for the same input. It is a real implementation, not a mock. It simply does not add any model
reasoning on top of the engine's own analysis, cannot rephrase, and cannot translate.
"""

from sparta.domain.models import RiskAssessment
from sparta.providers.base import (
    ProviderMeta,
    ReplyRequest,
    ReplySuggestion,
    SummaryRequest,
    SummaryResult,
    TranslationResult,
    TurnAnalysis,
    TurnEvaluationRequest,
    Usage,
)


class RulesConversationModel:
    meta = ProviderMeta(provider="rules", simulated=False, model="sparta-rules", version="1")

    async def evaluate_turn(self, request: TurnEvaluationRequest) -> TurnAnalysis:
        return TurnAnalysis(
            notes="rules provider: the deterministic engine is the only analyst", usage=Usage(requests=0)
        )

    async def generate_safe_reply(self, request: ReplyRequest) -> ReplySuggestion | None:
        return None  # replies come from the vetted template set

    async def summarize_call(self, request: SummaryRequest) -> SummaryResult:
        return SummaryResult(text=request.rules_summary, usage=Usage(requests=0))

    async def classify_call(self, request: SummaryRequest) -> RiskAssessment | None:
        return request.risk

    async def translate(
        self, text: str, source_language: str, target_language: str, trace_id: str
    ) -> TranslationResult | None:
        return None
