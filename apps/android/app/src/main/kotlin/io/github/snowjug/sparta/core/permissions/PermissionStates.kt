package io.github.snowjug.sparta.core.permissions

/** What the UI needs to know about a runtime permission, including how to react to a refusal. */
enum class PermissionUiState {
    /** Never asked: show the explanation first, then the system prompt. */
    NOT_ASKED,
    GRANTED,

    /** Refused once; Android will show the prompt again if the owner presses the button. */
    DENIED_CAN_ASK_AGAIN,

    /** Refused with "don't ask again" (or twice): only the system settings screen can change it. */
    DENIED_PERMANENTLY,

    /** Not a runtime permission on this Android version (for example notifications before Android 13). */
    NOT_REQUIRED,
}

object PermissionStates {
    /** Interprets the result of a system permission prompt. [shouldShowRationale] is read AFTER the result. */
    fun afterRequest(granted: Boolean, shouldShowRationale: Boolean): PermissionUiState = when {
        granted -> PermissionUiState.GRANTED
        shouldShowRationale -> PermissionUiState.DENIED_CAN_ASK_AGAIN
        else -> PermissionUiState.DENIED_PERMANENTLY
    }

    /** State when the screen is (re)opened; [requestedBefore] distinguishes "never asked" from "refused permanently". */
    fun current(granted: Boolean, required: Boolean, requestedBefore: Boolean, shouldShowRationale: Boolean): PermissionUiState = when {
        !required -> PermissionUiState.NOT_REQUIRED
        granted -> PermissionUiState.GRANTED
        shouldShowRationale -> PermissionUiState.DENIED_CAN_ASK_AGAIN
        requestedBefore -> PermissionUiState.DENIED_PERMANENTLY
        else -> PermissionUiState.NOT_ASKED
    }
}
