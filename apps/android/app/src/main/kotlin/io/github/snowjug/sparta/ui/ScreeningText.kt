package io.github.snowjug.sparta.ui

import androidx.annotation.StringRes
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningReason

/** Maps the pure screening vocabulary to user-facing copy (kept honest: Sparta never answers calls on this phone). */
object ScreeningText {
    @StringRes
    fun action(wire: String?): Int = when (wire) {
        ScreeningAction.ALLOW.wire -> R.string.action_allow
        ScreeningAction.SILENCE.wire -> R.string.action_silence
        ScreeningAction.REJECT.wire -> R.string.action_reject
        else -> R.string.reason_unrecognised
    }

    @StringRes
    fun reasonLabel(wire: String?): Int = when (ScreeningReason.fromWire(wire)) {
        ScreeningReason.OUTGOING_CALL -> R.string.reason_outgoing_call
        ScreeningReason.BLOCKED_NUMBER -> R.string.reason_blocked_number
        ScreeningReason.TRUSTED_NUMBER -> R.string.reason_trusted_number
        ScreeningReason.SAVED_CONTACT -> R.string.reason_saved_contact
        ScreeningReason.KNOWN_SCREENED_ANYWAY -> R.string.reason_known_screened_anyway
        ScreeningReason.VERIFICATION_FAILED_REJECTED -> R.string.reason_verification_failed_rejected
        ScreeningReason.VERIFICATION_FAILED_SILENCED -> R.string.reason_verification_failed_silenced
        ScreeningReason.UNKNOWN_ALLOWED -> R.string.reason_unknown_allowed
        ScreeningReason.UNKNOWN_SILENCED -> R.string.reason_unknown_silenced
        ScreeningReason.UNKNOWN_SCREENED -> R.string.reason_unknown_screened
        ScreeningReason.HIDDEN_NUMBER_SCREENED -> R.string.reason_hidden_number_screened
        ScreeningReason.SILENCE_UNSUPPORTED -> R.string.reason_silence_unsupported
        ScreeningReason.DEADLINE_EXCEEDED -> R.string.reason_deadline_exceeded
        ScreeningReason.INTERNAL_ERROR -> R.string.reason_internal_error
        null -> R.string.reason_unrecognised
    }

    @StringRes
    fun reasonExplanation(wire: String?): Int = when (ScreeningReason.fromWire(wire)) {
        ScreeningReason.OUTGOING_CALL -> R.string.reason_outgoing_call_explain
        ScreeningReason.BLOCKED_NUMBER -> R.string.reason_blocked_number_explain
        ScreeningReason.TRUSTED_NUMBER -> R.string.reason_trusted_number_explain
        ScreeningReason.SAVED_CONTACT -> R.string.reason_saved_contact_explain
        ScreeningReason.KNOWN_SCREENED_ANYWAY -> R.string.reason_known_screened_anyway_explain
        ScreeningReason.VERIFICATION_FAILED_REJECTED -> R.string.reason_verification_failed_rejected_explain
        ScreeningReason.VERIFICATION_FAILED_SILENCED -> R.string.reason_verification_failed_silenced_explain
        ScreeningReason.UNKNOWN_ALLOWED -> R.string.reason_unknown_allowed_explain
        ScreeningReason.UNKNOWN_SILENCED -> R.string.reason_unknown_silenced_explain
        ScreeningReason.UNKNOWN_SCREENED -> R.string.reason_unknown_screened_explain
        ScreeningReason.HIDDEN_NUMBER_SCREENED -> R.string.reason_hidden_number_screened_explain
        ScreeningReason.SILENCE_UNSUPPORTED -> R.string.reason_silence_unsupported_explain
        ScreeningReason.DEADLINE_EXCEEDED -> R.string.reason_deadline_exceeded_explain
        ScreeningReason.INTERNAL_ERROR -> R.string.reason_internal_error_explain
        null -> R.string.reason_unrecognised_explain
    }
}
