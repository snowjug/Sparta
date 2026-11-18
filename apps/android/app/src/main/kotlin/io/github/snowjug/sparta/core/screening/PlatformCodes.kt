package io.github.snowjug.sparta.core.screening

/**
 * Translates raw platform constants (android.telecom) into the pure model, keeping the Android-only numbers in one
 * tested place. Values: Call.Details.DIRECTION_* and Connection.VERIFICATION_STATUS_*.
 */
object PlatformCodes {
    const val DIRECTION_UNKNOWN = -1
    const val DIRECTION_INCOMING = 0
    const val DIRECTION_OUTGOING = 1

    const val VERIFICATION_NOT_VERIFIED = 0
    const val VERIFICATION_PASSED = 1
    const val VERIFICATION_FAILED = 2

    fun direction(code: Int?): CallDirection = when (code) {
        DIRECTION_INCOMING -> CallDirection.INCOMING
        DIRECTION_OUTGOING -> CallDirection.OUTGOING
        else -> CallDirection.UNKNOWN
    }

    /** [code] is null before Android 11 (API 30), when the platform reports no STIR/SHAKEN status. */
    fun verification(code: Int?): CallerVerification = when (code) {
        VERIFICATION_PASSED -> CallerVerification.PASSED
        VERIFICATION_FAILED -> CallerVerification.FAILED
        VERIFICATION_NOT_VERIFIED -> CallerVerification.NOT_VERIFIED
        else -> CallerVerification.UNKNOWN
    }
}
