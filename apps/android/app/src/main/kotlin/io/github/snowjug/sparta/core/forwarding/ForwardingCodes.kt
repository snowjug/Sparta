package io.github.snowjug.sparta.core.forwarding

/**
 * GSM conditional call-forwarding codes (3GPP TS 22.030) that the owner can dial from the phone dialer.
 * The app only PRE-FILLS the dialer; the owner reviews the code and presses call. Nothing is sent by the app, and
 * whether a carrier honours a code is carrier-specific and cannot be verified from the app.
 */
enum class ForwardingMode(val ssCode: String) {
    NO_ANSWER("61"),
    BUSY("67"),
    UNREACHABLE("62"),
}

object ForwardingCodes {
    /** Cancels every forwarding rule on the line (standard "erase all" code). */
    const val CANCEL_ALL = "##002#"

    private val SAFE_NUMBER = Regex("^\\+?[0-9]{6,15}$")

    /**
     * The forwarding number comes from the backend, so it is validated before it can become dialer input:
     * digits with an optional leading "+" only. Anything containing "*", "#", spaces or letters could otherwise
     * smuggle in a different network code.
     */
    fun isSafeNumber(number: String?): Boolean = number != null && SAFE_NUMBER.matches(number)

    /** "**61*+918012345678#" style activation string, or null when [number] is not a plain phone number. */
    fun activation(mode: ForwardingMode, number: String?): String? =
        if (isSafeNumber(number)) "**${mode.ssCode}*$number#" else null

    fun deactivation(mode: ForwardingMode): String = "##${mode.ssCode}#"
}
