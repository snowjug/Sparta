package io.github.snowjug.sparta.data.remote.dto

import kotlinx.serialization.Serializable

/*
 * DTOs mirror services/api/src/sparta/domain/models.py. JSON names are the Python attribute names (snake_case; the
 * shared Json instance applies a snake_case naming strategy). Every field except identifiers has a default so a
 * backend that omits or adds fields never breaks decoding.
 */

@Serializable
data class CallerClaimDto(
    val name: String? = null,
    val organization: String? = null,
    val role: String? = null,
)

@Serializable
data class LatencyBreakdownDto(
    val audioInputMs: Double? = null,
    val vadMs: Double? = null,
    val sttMs: Double? = null,
    val languageDetectMs: Double? = null,
    val policyMs: Double? = null,
    val modelMs: Double? = null,
    val ttsFirstAudioMs: Double? = null,
    val playbackStartMs: Double? = null,
    val interruptionMs: Double? = null,
    val totalMs: Double? = null,
    val simulatedStages: List<String> = emptyList(),
)

@Serializable
data class LanguageSegmentDto(
    val language: String = "und",
    val script: String = "Other",
    val romanized: Boolean = false,
    val start: Int = 0,
    val end: Int = 0,
    val confidence: Double = 0.0,
    val variant: String? = null,
)

@Serializable
data class SpeechPlanDto(
    val text: String = "",
    val locale: String = "",
    val voiceId: String? = null,
    val rate: Double = 1.0,
    val style: String? = null,
    val ssml: String? = null,
    val transliteration: String? = null,
    val estDurationMs: Int = 0,
)

@Serializable
data class RiskSignalDto(
    /** Stable signal identifier (SignalCode); kept as a string so new codes never break decoding. */
    val code: String = "",
    val kind: SignalKind = SignalKind.RISK,
    val severity: SignalSeverity = SignalSeverity.UNKNOWN,
    val weight: Double = 0.0,
    val evidenceTurnIds: List<String> = emptyList(),
    val evidenceExcerpt: String? = null,
    val description: String = "",
)

@Serializable
data class RiskAssessmentDto(
    val callId: String = "",
    val detectedLanguages: List<String> = emptyList(),
    val languageProfile: String? = null,
    val callerClaim: CallerClaimDto = CallerClaimDto(),
    val purpose: String? = null,
    val category: CallCategory = CallCategory.UNKNOWN,
    val riskLevel: RiskLevel = RiskLevel.UNKNOWN,
    val riskScore: Double = 0.0,
    val confidence: Double = 0.0,
    val signals: List<RiskSignalDto> = emptyList(),
    val recommendedAction: RecommendedAction = RecommendedAction.CONTINUE_SCREENING,
    val additionalActions: List<RecommendedAction> = emptyList(),
    val requiresOwnerAttention: Boolean = false,
    val reasons: List<String> = emptyList(),
    val policyVersion: String = "",
    val assessedAt: String? = null,
    val turnCount: Int = 0,
)

@Serializable
data class CallTurnDto(
    val id: String,
    val callId: String = "",
    val seq: Int = 0,
    val speaker: Speaker = Speaker.UNKNOWN,
    val text: String = "",
    val transliteration: String? = null,
    val translation: String? = null,
    val language: String? = null,
    val languageConfidence: Double? = null,
    val languageProfile: String? = null,
    val segments: List<LanguageSegmentDto> = emptyList(),
    val isFinal: Boolean = true,
    val confidence: Double? = null,
    val source: TurnSource = TurnSource.UNKNOWN,
    val interrupted: Boolean = false,
    val spokenFraction: Double? = null,
    val stateAfter: CallState? = null,
    val createdAt: String? = null,
    val latency: LatencyBreakdownDto? = null,
    val speech: SpeechPlanDto? = null,
)

@Serializable
data class EscalationDto(
    val id: String,
    val callId: String = "",
    val reason: String = "",
    val status: EscalationStatus = EscalationStatus.UNKNOWN,
    val createdAt: String? = null,
    val resolvedAt: String? = null,
    val importantLines: List<String> = emptyList(),
)

@Serializable
data class OwnerActionDto(
    val id: String,
    val callId: String = "",
    val action: OwnerActionType = OwnerActionType.UNKNOWN,
    val createdAt: String? = null,
    val simulated: Boolean = false,
    val result: String = "ok",
    val detail: String? = null,
)

@Serializable
data class CallSummaryDto(
    val callId: String = "",
    val text: String = "",
    val category: CallCategory = CallCategory.UNKNOWN,
    val riskLevel: RiskLevel = RiskLevel.UNKNOWN,
    val actionTaken: String? = null,
    val ownerActionRequired: Boolean = false,
    val generatedBy: String = "",
    val createdAt: String? = null,
)

@Serializable
data class FeedbackRecordDto(
    val id: String,
    val callId: String = "",
    val kind: FeedbackKind = FeedbackKind.UNKNOWN,
    val note: String? = null,
    val createdAt: String? = null,
)

@Serializable
data class ProviderEventRecordDto(
    val id: String = "",
    val provider: String = "",
    val eventType: String = "",
    val externalId: String? = null,
    val receivedAt: String? = null,
    val detail: String? = null,
)

@Serializable
data class TimelineEntryDto(
    val at: String? = null,
    val kind: String = "system",
    val label: String = "",
    val detail: String? = null,
)

@Serializable
data class VersionInfoDto(
    val appVersion: String = "",
    val policyVersion: String = "",
    val languagePackVersion: String = "",
    val telephonyProvider: String = "",
    val sttProvider: String = "",
    val ttsProvider: String = "",
    val llmProvider: String = "",
    val llmModel: String? = null,
)

/** Which owner controls are honest for this call. Authoritative: UIs must disable what is not supported. */
@Serializable
data class CallCapabilitiesDto(
    val canTakeOver: Boolean = false,
    val canContinue: Boolean = false,
    val canEnd: Boolean = false,
    val canBlock: Boolean = true,
    val takeoverNote: String? = null,
    val simulated: Boolean = false,
    val twoWayAudio: Boolean = false,
    val audioNote: String? = null,
)

@Serializable
data class CallListItemDto(
    val id: String,
    val provider: ProviderKind = ProviderKind.UNKNOWN,
    val mode: CallMode = CallMode.CONVERSATIONAL,
    val simulated: Boolean = true,
    val status: CallStatus = CallStatus.UNKNOWN,
    val state: CallState = CallState.UNKNOWN,
    val startedAt: String? = null,
    val endedAt: String? = null,
    val durationMs: Long? = null,
    val callerDisplay: String = "",
    val callerClaim: CallerClaimDto = CallerClaimDto(),
    val purpose: String? = null,
    val category: CallCategory = CallCategory.UNKNOWN,
    val riskLevel: RiskLevel = RiskLevel.UNKNOWN,
    val riskScore: Double = 0.0,
    val confidence: Double = 0.0,
    val languages: List<String> = emptyList(),
    val languageProfile: String? = null,
    val summaryText: String? = null,
    val actionTaken: String? = null,
    val ownerAttentionRequired: Boolean = false,
    val blocked: Boolean = false,
    val trusted: Boolean = false,
    val hasContent: Boolean = true,
)

@Serializable
data class CallDetailDto(
    val id: String,
    val provider: ProviderKind = ProviderKind.UNKNOWN,
    val mode: CallMode = CallMode.CONVERSATIONAL,
    val simulated: Boolean = true,
    val status: CallStatus = CallStatus.UNKNOWN,
    val state: CallState = CallState.UNKNOWN,
    val startedAt: String? = null,
    val endedAt: String? = null,
    val durationMs: Long? = null,
    val callerDisplay: String = "",
    val callerClaim: CallerClaimDto = CallerClaimDto(),
    val purpose: String? = null,
    val category: CallCategory = CallCategory.UNKNOWN,
    val riskLevel: RiskLevel = RiskLevel.UNKNOWN,
    val riskScore: Double = 0.0,
    val confidence: Double = 0.0,
    val languages: List<String> = emptyList(),
    val languageProfile: String? = null,
    val summaryText: String? = null,
    val actionTaken: String? = null,
    val ownerAttentionRequired: Boolean = false,
    val blocked: Boolean = false,
    val trusted: Boolean = false,
    val hasContent: Boolean = true,
    val languageMode: String = "auto",
    val turns: List<CallTurnDto> = emptyList(),
    val risk: RiskAssessmentDto? = null,
    val escalations: List<EscalationDto> = emptyList(),
    val ownerActions: List<OwnerActionDto> = emptyList(),
    val summary: CallSummaryDto? = null,
    val feedback: List<FeedbackRecordDto> = emptyList(),
    val timeline: List<TimelineEntryDto> = emptyList(),
    val providerEvents: List<ProviderEventRecordDto> = emptyList(),
    val versions: VersionInfoDto = VersionInfoDto(),
    val traceId: String = "",
    val metrics: Map<String, Double> = emptyMap(),
    val capabilities: CallCapabilitiesDto = CallCapabilitiesDto(),
) {
    fun toListItem(): CallListItemDto = CallListItemDto(
        id = id,
        provider = provider,
        mode = mode,
        simulated = simulated,
        status = status,
        state = state,
        startedAt = startedAt,
        endedAt = endedAt,
        durationMs = durationMs,
        callerDisplay = callerDisplay,
        callerClaim = callerClaim,
        purpose = purpose,
        category = category,
        riskLevel = riskLevel,
        riskScore = riskScore,
        confidence = confidence,
        languages = languages,
        languageProfile = languageProfile,
        summaryText = summaryText,
        actionTaken = actionTaken,
        ownerAttentionRequired = ownerAttentionRequired,
        blocked = blocked,
        trusted = trusted,
        hasContent = hasContent,
    )
}

@Serializable
data class CallPageDto(
    val items: List<CallListItemDto> = emptyList(),
    val nextCursor: String? = null,
)

@Serializable
data class OwnerActionResultDto(
    val action: OwnerActionDto,
    val call: CallListItemDto,
    val capabilities: CallCapabilitiesDto = CallCapabilitiesDto(),
)

@Serializable
data class BlockedCallerDto(
    val id: String,
    val numberDisplay: String = "",
    val reason: String? = null,
    val createdAt: String? = null,
    val sourceCallId: String? = null,
)

@Serializable
data class TrustedCallerDto(
    val id: String,
    val numberDisplay: String = "",
    val label: String? = null,
    val createdAt: String? = null,
    val sourceCallId: String? = null,
)

/** Request bodies: the backend rejects unknown fields, so these carry exactly the documented fields. */
@Serializable
class EmptyBody

@Serializable
data class BlockRequestDto(val reason: String? = null)

@Serializable
data class TrustRequestDto(val label: String? = null)

@Serializable
data class FeedbackRequestDto(val kind: FeedbackKind, val note: String? = null)
