package io.github.snowjug.sparta.core.screening

/** What the platform lets a call-screening app do with a call. Sparta cannot answer a call or touch call audio. */
enum class ScreeningAction(val wire: String) {
    ALLOW("allow"),
    SILENCE("silence"),
    REJECT("reject"),
}

/** Stable reason codes (also uploaded as `reason` and shown in history/diagnostics). */
enum class ScreeningReason(val wire: String) {
    OUTGOING_CALL("outgoing_call"),
    BLOCKED_NUMBER("blocked_number"),
    TRUSTED_NUMBER("trusted_number"),
    SAVED_CONTACT("saved_contact"),
    KNOWN_SCREENED_ANYWAY("known_screened_anyway"),
    VERIFICATION_FAILED_REJECTED("verification_failed_rejected"),
    VERIFICATION_FAILED_SILENCED("verification_failed_silenced"),
    UNKNOWN_ALLOWED("unknown_allowed"),
    UNKNOWN_SILENCED("unknown_silenced"),
    UNKNOWN_SCREENED("unknown_screened"),
    HIDDEN_NUMBER_SCREENED("hidden_number_screened"),
    SILENCE_UNSUPPORTED("silence_unsupported"),
    DEADLINE_EXCEEDED("deadline_exceeded"),
    INTERNAL_ERROR("internal_error"),
    ;

    companion object {
        fun fromWire(value: String?): ScreeningReason? = entries.firstOrNull { it.wire == value }
    }
}

enum class UnknownCallerBehavior(val wire: String) {
    SCREEN("screen"),
    SILENCE("silence"),
    ALLOW("allow"),
    ;

    companion object {
        fun fromWire(value: String?): UnknownCallerBehavior = entries.firstOrNull { it.wire == value } ?: SCREEN
    }
}

enum class TrustedContactBehavior(val wire: String) {
    ALLOW_DIRECTLY("allow_directly"),
    SCREEN_ANYWAY("screen_anyway"),
    ;

    companion object {
        fun fromWire(value: String?): TrustedContactBehavior = entries.firstOrNull { it.wire == value } ?: ALLOW_DIRECTLY
    }
}

enum class Strictness(val wire: String) {
    RELAXED("relaxed"),
    BALANCED("balanced"),
    STRICT("strict"),
    ;

    companion object {
        fun fromWire(value: String?): Strictness = entries.firstOrNull { it.wire == value } ?: BALANCED
    }
}

/** UNAVAILABLE = READ_CONTACTS not granted (or the lookup failed): never treated as "not a contact". */
enum class ContactMatch { FOUND, NOT_FOUND, UNAVAILABLE }

enum class CallerVerification(val wire: String) {
    PASSED("passed"),
    FAILED("failed"),
    NOT_VERIFIED("not_verified"),
    UNKNOWN("unknown"),
}

enum class CallDirection(val wire: String) {
    INCOMING("incoming"),
    OUTGOING("outgoing"),
    UNKNOWN("unknown"),
}

/** User policy. Everything the fast path needs is local so it also works offline. */
data class ScreeningPolicy(
    val unknownCallerBehavior: UnknownCallerBehavior = UnknownCallerBehavior.SCREEN,
    val trustedContactBehavior: TrustedContactBehavior = TrustedContactBehavior.ALLOW_DIRECTLY,
    val strictness: Strictness = Strictness.BALANCED,
    val treatContactsAsKnown: Boolean = false,
)

/** Facts gathered from local data only (Room lists, contacts, call details). */
data class ScreeningFacts(
    val direction: CallDirection,
    val numberPresent: Boolean,
    val blocked: Boolean = false,
    val trusted: Boolean = false,
    val contact: ContactMatch = ContactMatch.UNAVAILABLE,
    val verification: CallerVerification = CallerVerification.UNKNOWN,
)

data class ScreeningDecision(
    val action: ScreeningAction,
    val reason: ScreeningReason,
    val notifyOwner: Boolean = false,
) {
    companion object {
        /** The fail-open default used whenever a real decision cannot be produced in time. */
        fun safeDefault(reason: ScreeningReason): ScreeningDecision =
            ScreeningDecision(ScreeningAction.ALLOW, reason, notifyOwner = false)
    }
}
