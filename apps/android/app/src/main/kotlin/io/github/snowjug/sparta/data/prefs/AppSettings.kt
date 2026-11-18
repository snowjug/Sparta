package io.github.snowjug.sparta.data.prefs

import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.screening.ScreeningPolicy
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior

enum class ThemeMode(val wire: String) {
    DARK("dark"),
    LIGHT("light"),
    SYSTEM("system"),
    ;

    companion object {
        fun fromWire(value: String?): ThemeMode = entries.firstOrNull { it.wire == value } ?: DARK
    }
}

/**
 * Everything the app persists in DataStore. Nothing here is a credential: there are no tokens, and no raw numbers.
 * The fingerprint salt is a per-owner HMAC key kept in app-private storage (backup is disabled).
 */
data class AppSettings(
    val backendUrl: String = "",
    val onboardingCompleted: Boolean = false,
    val unknownCallerBehavior: UnknownCallerBehavior = UnknownCallerBehavior.SCREEN,
    val trustedContactBehavior: TrustedContactBehavior = TrustedContactBehavior.ALLOW_DIRECTLY,
    val strictness: Strictness = Strictness.BALANCED,
    val useContactsAsKnown: Boolean = false,
    val fingerprintSalt: String? = null,
    val forwardingNumber: String? = null,
    val forwardingHelperOpenedAtMs: Long? = null,
    val forwardingConfirmedByOwner: Boolean = false,
    val roleRequestDeclined: Boolean = false,
    val contactsPermissionAsked: Boolean = false,
    val notificationsPermissionAsked: Boolean = false,
    val backgroundSyncEnabled: Boolean = true,
    val themeMode: ThemeMode = ThemeMode.DARK,
    val motionPreference: MotionPreference = MotionPreference.FOLLOW_SYSTEM,
    val notifyEscalations: Boolean = true,
    val notifyScreening: Boolean = true,
    val deadlineMissCount: Long = 0,
    val lastSyncAtMs: Long? = null,
    val lastSyncError: String? = null,
    /** Last `GET /preferences` document (offline copy of the backend's preferences). */
    val cachedPreferencesJson: String? = null,
    /**
     * Local preference edits (dotted-path -> value, as a JSON object) the backend has not accepted yet. They are
     * re-applied on top of the freshest backend document when pushed, so concurrent edits elsewhere are not clobbered.
     */
    val pendingPreferencesPatchJson: String? = null,
    val cachedStatusJson: String? = null,
    val cachedStatusAtMs: Long? = null,
) {
    val preferencesDirty: Boolean get() = pendingPreferencesPatchJson != null

    val policy: ScreeningPolicy
        get() = ScreeningPolicy(
            unknownCallerBehavior = unknownCallerBehavior,
            trustedContactBehavior = trustedContactBehavior,
            strictness = strictness,
            treatContactsAsKnown = useContactsAsKnown,
        )

    val backendConfigured: Boolean get() = backendUrl.isNotBlank()
}
