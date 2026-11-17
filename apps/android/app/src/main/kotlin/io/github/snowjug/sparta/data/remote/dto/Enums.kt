package io.github.snowjug.sparta.data.remote.dto

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder

/**
 * Enums travel as their Python string values. Unknown values (a newer backend) decode to [fallback] instead of
 * failing the whole response, which is why every enum below has an UNKNOWN entry.
 */
abstract class WireEnumSerializer<T : Enum<T>>(
    serialName: String,
    private val entries: List<T>,
    private val wireOf: (T) -> String,
    private val fallback: T,
) : KSerializer<T> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor(serialName, PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: T) = encoder.encodeString(wireOf(value))

    override fun deserialize(decoder: Decoder): T {
        val text = decoder.decodeString()
        return entries.firstOrNull { wireOf(it) == text } ?: fallback
    }
}

@Serializable(with = CallStateSerializer::class)
enum class CallState(val wire: String) {
    INITIALIZING("INITIALIZING"),
    DISCLOSURE("DISCLOSURE"),
    IDENTIFY_CALLER("IDENTIFY_CALLER"),
    IDENTIFY_PURPOSE("IDENTIFY_PURPOSE"),
    CLARIFY("CLARIFY"),
    ASSESSING("ASSESSING"),
    SAFE_CONTINUE("SAFE_CONTINUE"),
    ESCALATE("ESCALATE"),
    REFUSE_SENSITIVE_REQUEST("REFUSE_SENSITIVE_REQUEST"),
    END_SPAM("END_SPAM"),
    END_SILENCE("END_SILENCE"),
    OWNER_TAKEOVER("OWNER_TAKEOVER"),
    COMPLETED("COMPLETED"),
    FAILED("FAILED"),
    UNKNOWN("unknown"),
    ;

    val isTerminal: Boolean get() = this == COMPLETED || this == FAILED
}

object CallStateSerializer : WireEnumSerializer<CallState>("CallState", CallState.entries, { it.wire }, CallState.UNKNOWN)

@Serializable(with = CallStatusSerializer::class)
enum class CallStatus(val wire: String) {
    ACTIVE("active"),
    ENDED("ended"),
    FAILED("failed"),
    UNKNOWN("unknown"),
}

object CallStatusSerializer : WireEnumSerializer<CallStatus>("CallStatus", CallStatus.entries, { it.wire }, CallStatus.UNKNOWN)

@Serializable(with = RiskLevelSerializer::class)
enum class RiskLevel(val wire: String) {
    UNKNOWN("unknown"),
    LOW("low"),
    MEDIUM("medium"),
    HIGH("high"),
}

object RiskLevelSerializer : WireEnumSerializer<RiskLevel>("RiskLevel", RiskLevel.entries, { it.wire }, RiskLevel.UNKNOWN)

@Serializable(with = RecommendedActionSerializer::class)
enum class RecommendedAction(val wire: String) {
    CONTINUE_SCREENING("continue_screening"),
    ASK_CLARIFYING_QUESTION("ask_clarifying_question"),
    ESCALATE_TO_OWNER("escalate_to_owner"),
    REFUSE_AND_END("refuse_and_end"),
    END_SPAM("end_spam"),
    BLOCK_RECOMMENDED("block_recommended"),
    REPORT_RECOMMENDED("report_recommended"),
    HUMAN_REVIEW("human_review"),
    UNKNOWN("unknown"),
}

object RecommendedActionSerializer :
    WireEnumSerializer<RecommendedAction>("RecommendedAction", RecommendedAction.entries, { it.wire }, RecommendedAction.UNKNOWN)

@Serializable(with = SignalSeveritySerializer::class)
enum class SignalSeverity(val wire: String) {
    INFO("info"),
    LOW("low"),
    MEDIUM("medium"),
    HIGH("high"),
    CRITICAL("critical"),
    UNKNOWN("unknown"),
}

object SignalSeveritySerializer :
    WireEnumSerializer<SignalSeverity>("SignalSeverity", SignalSeverity.entries, { it.wire }, SignalSeverity.UNKNOWN)

@Serializable(with = SignalKindSerializer::class)
enum class SignalKind(val wire: String) {
    RISK("risk"),
    LEGITIMATE("legitimate"),
}

object SignalKindSerializer : WireEnumSerializer<SignalKind>("SignalKind", SignalKind.entries, { it.wire }, SignalKind.RISK)

@Serializable(with = CallCategorySerializer::class)
enum class CallCategory(val wire: String) {
    UNKNOWN("unknown"),
    SILENT("silent"),
    POSSIBLE_FINANCIAL_IMPERSONATION("possible_financial_impersonation"),
    POSSIBLE_GOVERNMENT_IMPERSONATION("possible_government_impersonation"),
    POSSIBLE_COURIER_IMPERSONATION("possible_courier_impersonation"),
    POSSIBLE_TECH_SUPPORT_SCAM("possible_tech_support_scam"),
    POSSIBLE_PRIZE_SCAM("possible_prize_scam"),
    POSSIBLE_EMPLOYER_IMPERSONATION("possible_employer_impersonation"),
    PROMPT_INJECTION_ATTEMPT("prompt_injection_attempt"),
    TELEMARKETING("telemarketing"),
    HARASSMENT("harassment"),
    LEGITIMATE_DELIVERY("legitimate_delivery"),
    LEGITIMATE_APPOINTMENT("legitimate_appointment"),
    LEGITIMATE_RECRUITER("legitimate_recruiter"),
    LEGITIMATE_SUPPORT_CALLBACK("legitimate_support_callback"),
    LEGITIMATE_PERSONAL("legitimate_personal"),
    LEGITIMATE_URGENT("legitimate_urgent"),
    ;

    val isLegitimate: Boolean get() = wire.startsWith("legitimate_")
}

object CallCategorySerializer : WireEnumSerializer<CallCategory>("CallCategory", CallCategory.entries, { it.wire }, CallCategory.UNKNOWN)

@Serializable(with = SpeakerSerializer::class)
enum class Speaker(val wire: String) {
    CALLER("caller"),
    ASSISTANT("assistant"),
    OWNER("owner"),
    SYSTEM("system"),
    UNKNOWN("unknown"),
}

object SpeakerSerializer : WireEnumSerializer<Speaker>("Speaker", Speaker.entries, { it.wire }, Speaker.UNKNOWN)

@Serializable(with = TurnSourceSerializer::class)
enum class TurnSource(val wire: String) {
    TYPED("typed"),
    BROWSER_STT("browser_stt"),
    PROVIDER_STT("provider_stt"),
    UPLOADED_AUDIO("uploaded_audio"),
    SCRIPTED("scripted"),
    ASSISTANT("assistant"),
    SYSTEM("system"),
    UNKNOWN("unknown"),
}

object TurnSourceSerializer : WireEnumSerializer<TurnSource>("TurnSource", TurnSource.entries, { it.wire }, TurnSource.UNKNOWN)

@Serializable(with = ProviderKindSerializer::class)
enum class ProviderKind(val wire: String) {
    SIMULATOR("simulator"),
    AZURE("azure"),
    ANDROID_SCREENING("android_screening"),
    OTHER("other"),
    UNKNOWN("unknown"),
}

object ProviderKindSerializer : WireEnumSerializer<ProviderKind>("ProviderKind", ProviderKind.entries, { it.wire }, ProviderKind.UNKNOWN)

@Serializable(with = CallModeSerializer::class)
enum class CallMode(val wire: String) {
    CONVERSATIONAL("conversational"),
    SCREENING_ONLY("screening_only"),
}

object CallModeSerializer : WireEnumSerializer<CallMode>("CallMode", CallMode.entries, { it.wire }, CallMode.CONVERSATIONAL)

@Serializable(with = OwnerActionTypeSerializer::class)
enum class OwnerActionType(val wire: String) {
    TAKEOVER("takeover"),
    CONTINUE("continue"),
    END("end"),
    BLOCK("block"),
    TRUST("trust"),
    UNBLOCK("unblock"),
    UNTRUST("untrust"),
    UNKNOWN("unknown"),
}

object OwnerActionTypeSerializer :
    WireEnumSerializer<OwnerActionType>("OwnerActionType", OwnerActionType.entries, { it.wire }, OwnerActionType.UNKNOWN)

@Serializable(with = EscalationStatusSerializer::class)
enum class EscalationStatus(val wire: String) {
    REQUESTED("requested"),
    TAKEN_OVER("taken_over"),
    CONTINUED("continued"),
    ENDED("ended"),
    EXPIRED("expired"),
    UNKNOWN("unknown"),
}

object EscalationStatusSerializer :
    WireEnumSerializer<EscalationStatus>("EscalationStatus", EscalationStatus.entries, { it.wire }, EscalationStatus.UNKNOWN)

@Serializable(with = FeedbackKindSerializer::class)
enum class FeedbackKind(val wire: String) {
    CORRECT_CLASSIFICATION("correct_classification"),
    WAS_SPAM("was_spam"),
    WAS_LEGITIMATE("was_legitimate"),
    WRONG_LANGUAGE("wrong_language"),
    POOR_TRANSCRIPTION("poor_transcription"),
    WRONG_SUMMARY("wrong_summary"),
    TRUST_CALLER("trust_caller"),
    BLOCK_CALLER("block_caller"),
    UNKNOWN("unknown"),
}

object FeedbackKindSerializer :
    WireEnumSerializer<FeedbackKind>("FeedbackKind", FeedbackKind.entries, { it.wire }, FeedbackKind.UNKNOWN)

@Serializable(with = VoiceStatusSerializer::class)
enum class VoiceStatus(val wire: String) {
    NOT_ENROLLED("not_enrolled"),
    CONSENT_RECORDED("consent_recorded"),
    PENDING_PROVIDER_APPROVAL("pending_provider_approval"),
    READY("ready"),
    FAILED("failed"),
    DELETED("deleted"),
    UNKNOWN("unknown"),
}

object VoiceStatusSerializer : WireEnumSerializer<VoiceStatus>("VoiceStatus", VoiceStatus.entries, { it.wire }, VoiceStatus.UNKNOWN)
