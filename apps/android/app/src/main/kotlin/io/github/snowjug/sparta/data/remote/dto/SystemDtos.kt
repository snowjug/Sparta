package io.github.snowjug.sparta.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class TelephonyStatusDto(
    val provider: String = "",
    /** Defaults to true: when the backend does not say, the UI must not imply real telephony. */
    val simulated: Boolean = true,
    val liveCallsSupported: Boolean = false,
    val forwardingNumber: String? = null,
    val note: String = "",
)

@Serializable
data class FeaturesDto(
    val simulator: Boolean = false,
    val personalVoice: Boolean = false,
    val llmSummaries: Boolean = false,
    val translation: Boolean = false,
    val rawAudioStorage: Boolean = false,
)

@Serializable
data class LanguageInfoDto(
    val code: String = "",
    val name: String = "",
    val nativeName: String = "",
    val status: String = "planned",
)

@Serializable
data class LimitsDto(
    val maxCallDurationS: Int? = null,
    val maxAudioBytes: Long? = null,
    val maxAudioSeconds: Int? = null,
    val dailyCallCap: Int? = null,
)

@Serializable
data class SystemStatusDto(
    val version: String = "",
    val env: String = "",
    val authMode: String = "dev",
    val devBanner: Boolean = false,
    val telephony: TelephonyStatusDto = TelephonyStatusDto(),
    val sttProvider: String = "",
    val ttsProvider: String = "",
    val llmProvider: String = "",
    val llmModel: String? = null,
    val features: FeaturesDto = FeaturesDto(),
    val policyVersion: String = "",
    val languagePackVersion: String = "",
    val languages: List<LanguageInfoDto> = emptyList(),
    val limits: LimitsDto = LimitsDto(),
)

@Serializable
data class MeDto(
    val id: String = "",
    val displayName: String = "",
    val authMode: String = "dev",
)

@Serializable
data class HomeProtectionDto(
    val status: String = "setup_needed",
    val headline: String = "",
    val detail: String = "",
    val provider: String = "",
    val simulated: Boolean = true,
    val liveCallsSupported: Boolean = false,
)

@Serializable
data class HomeTodayDto(
    val handled: Int = 0,
    val highRisk: Int = 0,
    val escalations: Int = 0,
    val endedSpam: Int = 0,
    val minutesHandled: Double = 0.0,
)

@Serializable
data class HomeNextActionDto(
    val kind: String = "none",
    val label: String = "",
    val route: String = "",
)

@Serializable
data class HomeSummaryDto(
    val protection: HomeProtectionDto = HomeProtectionDto(),
    val today: HomeTodayDto = HomeTodayDto(),
    val nextAction: HomeNextActionDto = HomeNextActionDto(),
    val attention: List<CallListItemDto> = emptyList(),
    val recent: List<CallListItemDto> = emptyList(),
)

@Serializable
data class VoiceOptionDto(
    val id: String,
    val locale: String = "",
    val displayName: String = "",
    val gender: String = "neutral",
    val provider: String = "",
    val verified: Boolean = false,
    val note: String? = null,
)

@Serializable
data class VoiceProfileViewDto(
    val status: VoiceStatus = VoiceStatus.NOT_ENROLLED,
    val consentRecordedAt: String? = null,
    val consentVersion: String? = null,
    val providerVoiceId: String? = null,
    val active: Boolean = false,
    val detail: String = "",
    val requiresProviderApproval: Boolean = true,
)

@Serializable
data class VoiceConsentDto(
    val version: String = "",
    val text: String = "",
    val requiresProviderApproval: Boolean = true,
    val supportedLocales: List<String> = emptyList(),
)

@Serializable
data class AssistantPreviewRequestDto(
    val language: String? = null,
    val sampleText: String? = null,
)

@Serializable
data class AssistantPreviewDto(
    val disclosure: SpeechPlanDto = SpeechPlanDto(),
    val reply: SpeechPlanDto? = null,
    val risk: RiskAssessmentDto? = null,
    val detectedLanguage: String? = null,
)

@Serializable
data class ProtectedInfoDto(
    val code: String = "",
    val label: String = "",
)

/** The slice of `GET /safety/policies` the phone shows: what Sparta never lets a caller extract. */
@Serializable
data class SafetyPolicyDto(
    val version: String = "",
    val name: String = "",
    val protectedInformation: List<ProtectedInfoDto> = emptyList(),
    val strictness: String = "balanced",
)

@Serializable
data class ScreeningConfigDto(
    /** Base64 HMAC key for number fingerprints. Never logged, never shown. */
    val fingerprintSalt: String = "",
    val unknownCallerBehavior: String = "screen",
    val trustedContactBehavior: String = "allow_directly",
    val strictness: String = "balanced",
    val forwardingNumber: String? = null,
    val provider: String = "",
    val liveCallsSupported: Boolean = false,
)

@Serializable
data class ScreeningListEntryDto(
    val id: String = "",
    val fingerprint: String,
    val numberDisplay: String = "",
    val label: String? = null,
)

@Serializable
data class ScreeningListsDto(
    val blocked: List<ScreeningListEntryDto> = emptyList(),
    val trusted: List<ScreeningListEntryDto> = emptyList(),
)

/** `POST /screening/events`: the device sends only a keyed fingerprint and a masked display, never the raw number. */
@Serializable
data class ScreeningEventRequestDto(
    val clientEventId: String,
    val numberFingerprint: String,
    val numberDisplay: String,
    val decision: String,
    val reason: String,
    val verificationStatus: String? = null,
    val direction: String? = null,
    val occurredAt: String,
)

@Serializable
data class LiveTicketRequestDto(val callId: String? = null)

@Serializable
data class LiveTicketDto(
    val ticket: String = "",
    val expiresIn: Int = 0,
    val wsUrl: String = "",
)

/** WebSocket envelope. `data` is decoded per `type`. */
@Serializable
data class LiveEventDto(
    val type: String,
    val callId: String = "",
    val seq: Long = 0,
    val ts: String? = null,
    val simulated: Boolean = false,
    val data: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class FieldErrorDto(
    val field: String = "",
    val message: String = "",
)

@Serializable
data class ErrorBodyDto(
    val code: String = "",
    val message: String = "",
    val traceId: String = "",
    val details: List<FieldErrorDto>? = null,
)

@Serializable
data class ErrorEnvelopeDto(val error: ErrorBodyDto = ErrorBodyDto())
