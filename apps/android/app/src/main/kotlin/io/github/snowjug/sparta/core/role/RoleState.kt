package io.github.snowjug.sparta.core.role

enum class RoleStatus {
    /** Android 10+ and the role is held: the system will call SpartaCallScreeningService. */
    GRANTED,

    /** Role exists but Sparta does not hold it. */
    NOT_GRANTED,

    /** Android 9 and lower: third-party screening requires being the default dialer, which Sparta is not. */
    UNSUPPORTED_API,

    /** Android 10+ but this build/OEM does not offer the call-screening role. */
    ROLE_UNAVAILABLE,
}

data class RoleState(
    val status: RoleStatus,
    /** True when the owner dismissed the system role dialog and has not granted the role since. */
    val requestDeclined: Boolean = false,
) {
    val canRequestRole: Boolean get() = status == RoleStatus.NOT_GRANTED
    val isScreeningActive: Boolean get() = status == RoleStatus.GRANTED
}

object RoleStateMapper {
    /** Android 10 (API 29) introduced ROLE_CALL_SCREENING. */
    const val MIN_ROLE_SDK = 29

    /**
     * [roleAvailable] and [roleHeld] are only consulted on API 29+, so callers on older devices may pass null
     * (the RoleManager does not exist there).
     */
    fun map(sdkInt: Int, roleAvailable: Boolean?, roleHeld: Boolean?, requestDeclined: Boolean = false): RoleState =
        when {
            sdkInt < MIN_ROLE_SDK -> RoleState(RoleStatus.UNSUPPORTED_API)
            roleAvailable != true -> RoleState(RoleStatus.ROLE_UNAVAILABLE)
            roleHeld == true -> RoleState(RoleStatus.GRANTED)
            else -> RoleState(RoleStatus.NOT_GRANTED, requestDeclined)
        }
}
