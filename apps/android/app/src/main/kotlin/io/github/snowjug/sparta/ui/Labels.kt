package io.github.snowjug.sparta.ui

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.HelpOutline
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.ui.graphics.vector.ImageVector
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.OwnerActionType
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RecommendedAction
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.ui.components.Tone
import java.util.Locale

/** Wording and presentation rules for backend vocabulary. Colour is never the only carrier of meaning (icon + text too). */
object Labels {
    @StringRes
    fun risk(level: RiskLevel): Int = when (level) {
        RiskLevel.LOW -> R.string.risk_low
        RiskLevel.MEDIUM -> R.string.risk_medium
        RiskLevel.HIGH -> R.string.risk_high
        RiskLevel.UNKNOWN -> R.string.risk_unknown
    }

    /** Green is reserved for verified/low risk, amber for caution, risk red only for confirmed high risk. */
    fun riskTone(level: RiskLevel): Tone = when (level) {
        RiskLevel.LOW -> Tone.SAFE
        RiskLevel.MEDIUM -> Tone.CAUTION
        RiskLevel.HIGH -> Tone.RISK
        RiskLevel.UNKNOWN -> Tone.NEUTRAL
    }

    fun riskIcon(level: RiskLevel): ImageVector = when (level) {
        RiskLevel.LOW -> Icons.Rounded.CheckCircle
        RiskLevel.MEDIUM -> Icons.Rounded.Warning
        RiskLevel.HIGH -> Icons.Rounded.Error
        RiskLevel.UNKNOWN -> Icons.AutoMirrored.Rounded.HelpOutline
    }

    @StringRes
    fun category(category: CallCategory): Int = when (category) {
        CallCategory.UNKNOWN -> R.string.category_unknown
        CallCategory.SILENT -> R.string.category_silent
        CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION -> R.string.category_possible_financial_impersonation
        CallCategory.POSSIBLE_GOVERNMENT_IMPERSONATION -> R.string.category_possible_government_impersonation
        CallCategory.POSSIBLE_COURIER_IMPERSONATION -> R.string.category_possible_courier_impersonation
        CallCategory.POSSIBLE_TECH_SUPPORT_SCAM -> R.string.category_possible_tech_support_scam
        CallCategory.POSSIBLE_PRIZE_SCAM -> R.string.category_possible_prize_scam
        CallCategory.POSSIBLE_EMPLOYER_IMPERSONATION -> R.string.category_possible_employer_impersonation
        CallCategory.PROMPT_INJECTION_ATTEMPT -> R.string.category_prompt_injection_attempt
        CallCategory.TELEMARKETING -> R.string.category_telemarketing
        CallCategory.HARASSMENT -> R.string.category_harassment
        CallCategory.LEGITIMATE_DELIVERY -> R.string.category_legitimate_delivery
        CallCategory.LEGITIMATE_APPOINTMENT -> R.string.category_legitimate_appointment
        CallCategory.LEGITIMATE_RECRUITER -> R.string.category_legitimate_recruiter
        CallCategory.LEGITIMATE_SUPPORT_CALLBACK -> R.string.category_legitimate_support_callback
        CallCategory.LEGITIMATE_PERSONAL -> R.string.category_legitimate_personal
        CallCategory.LEGITIMATE_URGENT -> R.string.category_legitimate_urgent
    }

    @StringRes
    fun state(state: CallState): Int = when (state) {
        CallState.INITIALIZING -> R.string.state_initializing
        CallState.DISCLOSURE -> R.string.state_disclosure
        CallState.IDENTIFY_CALLER -> R.string.state_identify_caller
        CallState.IDENTIFY_PURPOSE -> R.string.state_identify_purpose
        CallState.CLARIFY -> R.string.state_clarify
        CallState.ASSESSING -> R.string.state_assessing
        CallState.SAFE_CONTINUE -> R.string.state_safe_continue
        CallState.ESCALATE -> R.string.state_escalate
        CallState.REFUSE_SENSITIVE_REQUEST -> R.string.state_refuse_sensitive_request
        CallState.END_SPAM -> R.string.state_end_spam
        CallState.END_SILENCE -> R.string.state_end_silence
        CallState.OWNER_TAKEOVER -> R.string.state_owner_takeover
        CallState.COMPLETED -> R.string.state_completed
        CallState.FAILED -> R.string.state_failed
        CallState.UNKNOWN -> R.string.state_unknown
    }

    @StringRes
    fun status(status: CallStatus): Int = when (status) {
        CallStatus.ACTIVE -> R.string.call_status_active
        CallStatus.ENDED -> R.string.call_status_ended
        CallStatus.FAILED -> R.string.call_status_failed
        CallStatus.UNKNOWN -> R.string.call_status_unknown
    }

    @StringRes
    fun advice(action: RecommendedAction): Int = when (action) {
        RecommendedAction.CONTINUE_SCREENING -> R.string.advice_continue_screening
        RecommendedAction.ASK_CLARIFYING_QUESTION -> R.string.advice_ask_clarifying_question
        RecommendedAction.ESCALATE_TO_OWNER -> R.string.advice_escalate_to_owner
        RecommendedAction.REFUSE_AND_END -> R.string.advice_refuse_and_end
        RecommendedAction.END_SPAM -> R.string.advice_end_spam
        RecommendedAction.BLOCK_RECOMMENDED -> R.string.advice_block_recommended
        RecommendedAction.REPORT_RECOMMENDED -> R.string.advice_report_recommended
        RecommendedAction.HUMAN_REVIEW -> R.string.advice_human_review
        RecommendedAction.UNKNOWN -> R.string.advice_unknown
    }

    @StringRes
    fun ownerAction(type: OwnerActionType): Int = when (type) {
        OwnerActionType.TAKEOVER -> R.string.owner_action_takeover
        OwnerActionType.CONTINUE -> R.string.owner_action_continue
        OwnerActionType.END -> R.string.owner_action_end
        OwnerActionType.BLOCK -> R.string.owner_action_block
        OwnerActionType.TRUST -> R.string.owner_action_trust
        OwnerActionType.UNBLOCK -> R.string.owner_action_unblock
        OwnerActionType.UNTRUST -> R.string.owner_action_untrust
        OwnerActionType.UNKNOWN -> R.string.owner_action_unknown
    }

    @StringRes
    fun feedback(kind: FeedbackKind): Int = when (kind) {
        FeedbackKind.CORRECT_CLASSIFICATION -> R.string.feedback_correct_classification
        FeedbackKind.WAS_SPAM -> R.string.feedback_was_spam
        FeedbackKind.WAS_LEGITIMATE -> R.string.feedback_was_legitimate
        FeedbackKind.WRONG_LANGUAGE -> R.string.feedback_wrong_language
        FeedbackKind.POOR_TRANSCRIPTION -> R.string.feedback_poor_transcription
        FeedbackKind.WRONG_SUMMARY -> R.string.feedback_wrong_summary
        FeedbackKind.TRUST_CALLER -> R.string.feedback_trust_caller
        FeedbackKind.BLOCK_CALLER -> R.string.feedback_block_caller
        FeedbackKind.UNKNOWN -> R.string.owner_action_unknown
    }

    @StringRes
    fun provider(kind: ProviderKind): Int = when (kind) {
        ProviderKind.SIMULATOR -> R.string.provider_simulator
        ProviderKind.AZURE -> R.string.provider_azure
        ProviderKind.ANDROID_SCREENING -> R.string.provider_android_screening
        ProviderKind.OTHER -> R.string.provider_other
        ProviderKind.UNKNOWN -> R.string.provider_unknown
    }

    /** "hi-IN" -> "Hindi (India)" using the platform's locale data; falls back to the raw tag. */
    fun languageName(tag: String): String {
        val locale = Locale.forLanguageTag(tag)
        if (locale.language.isNullOrEmpty()) return tag
        val name = locale.getDisplayName(Locale.ENGLISH)
        return if (name.isNullOrBlank()) tag else name
    }

    /** Backend signal codes are stable identifiers; the backend's own description is preferred, this is the fallback. */
    fun humanizeCode(code: String): String =
        code.lowercase(Locale.ROOT).replace('_', ' ').replaceFirstChar { it.titlecase(Locale.ROOT) }
}

/** Relative time without Android types so the rule is unit tested. */
sealed interface Ago {
    data object Unknown : Ago

    data object JustNow : Ago

    data class Minutes(val value: Int) : Ago

    data class Hours(val value: Int) : Ago

    data class Days(val value: Int) : Ago
}

object Formatters {
    /** How long before [nowMs] something at [thenMs] happened. A time in the future (clock skew) reads as "just now". */
    fun ago(nowMs: Long, thenMs: Long?): Ago {
        if (thenMs == null) return Ago.Unknown
        val diff = nowMs - thenMs
        return when {
            diff < MINUTE_MS -> Ago.JustNow
            diff < HOUR_MS -> Ago.Minutes((diff / MINUTE_MS).toInt())
            diff < DAY_MS -> Ago.Hours((diff / HOUR_MS).toInt())
            else -> Ago.Days((diff / DAY_MS).toInt())
        }
    }

    private const val MINUTE_MS = 60_000L
    private const val HOUR_MS = 60 * MINUTE_MS
    private const val DAY_MS = 24 * HOUR_MS

    /** 70_000 -> "1:10", 3_725_000 -> "1:02:05". */
    fun duration(ms: Long?): String {
        if (ms == null || ms < 0) return "--:--"
        val totalSeconds = ms / 1000
        val hours = totalSeconds / 3600
        val minutes = (totalSeconds % 3600) / 60
        val seconds = totalSeconds % 60
        return if (hours > 0) "%d:%02d:%02d".format(Locale.ROOT, hours, minutes, seconds) else "%d:%02d".format(Locale.ROOT, minutes, seconds)
    }

    fun percent(score: Double): Int = (score.coerceIn(0.0, 1.0) * 100).toInt()
}
