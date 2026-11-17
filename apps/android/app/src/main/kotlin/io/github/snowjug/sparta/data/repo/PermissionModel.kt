package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.permissions.PermissionStates
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.platform.PermissionChecker

/**
 * Turns "granted?" plus what the app remembers about asking into the states the UI needs
 * (never asked / can ask again / permanently refused). The system prompt itself is launched by the screen,
 * and only after the screen has explained why the permission is wanted.
 */
class PermissionModel(
    private val checker: PermissionChecker,
    private val settings: SettingsRepository,
) {
    /** [shouldShowRationale] comes from the Activity (ActivityCompat.shouldShowRequestPermissionRationale). */
    suspend fun stateOf(permission: AppPermission, shouldShowRationale: Boolean): PermissionUiState {
        val s = settings.current()
        return PermissionStates.current(
            granted = checker.isGranted(permission),
            required = checker.isRequired(permission),
            requestedBefore = when (permission) {
                AppPermission.CONTACTS -> s.contactsPermissionAsked
                AppPermission.NOTIFICATIONS -> s.notificationsPermissionAsked
            },
            shouldShowRationale = shouldShowRationale,
        )
    }

    /** Records that the notification prompt was shown and interprets its result. */
    suspend fun onNotificationsResult(granted: Boolean, shouldShowRationale: Boolean): PermissionUiState {
        settings.update { it.copy(notificationsPermissionAsked = true) }
        return PermissionStates.afterRequest(granted, shouldShowRationale)
    }

    /**
     * Result of the contacts prompt the owner started by switching "saved contacts are known callers" on.
     * The opt-in only sticks when the permission was actually granted.
     */
    suspend fun onContactsPromptResult(granted: Boolean, shouldShowRationale: Boolean): PermissionUiState {
        settings.update { it.copy(contactsPermissionAsked = true, useContactsAsKnown = granted) }
        return PermissionStates.afterRequest(granted, shouldShowRationale)
    }

    suspend fun setContactsOptIn(enabled: Boolean) {
        settings.update { it.copy(useContactsAsKnown = enabled && checker.isGranted(AppPermission.CONTACTS)) }
    }

    fun isGranted(permission: AppPermission): Boolean = checker.isGranted(permission)
}
