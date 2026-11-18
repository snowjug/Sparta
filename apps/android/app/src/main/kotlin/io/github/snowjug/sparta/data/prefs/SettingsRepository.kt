package io.github.snowjug.sparta.data.prefs

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

interface SettingsRepository {
    val settings: Flow<AppSettings>

    suspend fun current(): AppSettings = settings.first()

    /** Atomic read-modify-write. */
    suspend fun update(transform: (AppSettings) -> AppSettings)

    suspend fun incrementDeadlineMisses()

    suspend fun clearAll()
}

class DataStoreSettingsRepository(private val store: DataStore<Preferences>) : SettingsRepository {

    override val settings: Flow<AppSettings> = store.data
        .catch { error -> if (error is IOException) emit(androidx.datastore.preferences.core.emptyPreferences()) else throw error }
        .map { it.toSettings() }

    override suspend fun update(transform: (AppSettings) -> AppSettings) {
        store.edit { prefs -> prefs.write(transform(prefs.toSettings())) }
    }

    override suspend fun incrementDeadlineMisses() {
        store.edit { prefs -> prefs[Keys.DEADLINE_MISSES] = (prefs[Keys.DEADLINE_MISSES] ?: 0L) + 1L }
    }

    override suspend fun clearAll() {
        store.edit { it.clear() }
    }

    private object Keys {
        val BACKEND_URL = stringPreferencesKey("backend_url")
        val ONBOARDING = booleanPreferencesKey("onboarding_completed")
        val UNKNOWN_BEHAVIOR = stringPreferencesKey("unknown_caller_behavior")
        val TRUSTED_BEHAVIOR = stringPreferencesKey("trusted_contact_behavior")
        val STRICTNESS = stringPreferencesKey("strictness")
        val CONTACTS_KNOWN = booleanPreferencesKey("use_contacts_as_known")
        val SALT = stringPreferencesKey("fingerprint_salt")
        val FORWARDING_NUMBER = stringPreferencesKey("forwarding_number")
        val FORWARDING_OPENED = longPreferencesKey("forwarding_helper_opened_at")
        val FORWARDING_CONFIRMED = booleanPreferencesKey("forwarding_confirmed")
        val ROLE_DECLINED = booleanPreferencesKey("role_request_declined")
        val CONTACTS_ASKED = booleanPreferencesKey("contacts_permission_asked")
        val NOTIFICATIONS_ASKED = booleanPreferencesKey("notifications_permission_asked")
        val BACKGROUND_SYNC = booleanPreferencesKey("background_sync_enabled")
        val THEME = stringPreferencesKey("theme_mode")
        val MOTION = stringPreferencesKey("motion_preference")
        val NOTIFY_ESCALATIONS = booleanPreferencesKey("notify_escalations")
        val NOTIFY_SCREENING = booleanPreferencesKey("notify_screening")
        val DEADLINE_MISSES = longPreferencesKey("deadline_miss_count")
        val LAST_SYNC = longPreferencesKey("last_sync_at")
        val LAST_SYNC_ERROR = stringPreferencesKey("last_sync_error")
        val PREFS_JSON = stringPreferencesKey("cached_preferences_json")
        val PREFS_PATCH = stringPreferencesKey("pending_preferences_patch_json")
        val STATUS_JSON = stringPreferencesKey("cached_status_json")
        val STATUS_AT = longPreferencesKey("cached_status_at")
    }

    private fun Preferences.toSettings(): AppSettings = AppSettings(
        backendUrl = this[Keys.BACKEND_URL].orEmpty(),
        onboardingCompleted = this[Keys.ONBOARDING] ?: false,
        unknownCallerBehavior = UnknownCallerBehavior.fromWire(this[Keys.UNKNOWN_BEHAVIOR]),
        trustedContactBehavior = TrustedContactBehavior.fromWire(this[Keys.TRUSTED_BEHAVIOR]),
        strictness = Strictness.fromWire(this[Keys.STRICTNESS]),
        useContactsAsKnown = this[Keys.CONTACTS_KNOWN] ?: false,
        fingerprintSalt = this[Keys.SALT],
        forwardingNumber = this[Keys.FORWARDING_NUMBER],
        forwardingHelperOpenedAtMs = this[Keys.FORWARDING_OPENED],
        forwardingConfirmedByOwner = this[Keys.FORWARDING_CONFIRMED] ?: false,
        roleRequestDeclined = this[Keys.ROLE_DECLINED] ?: false,
        contactsPermissionAsked = this[Keys.CONTACTS_ASKED] ?: false,
        notificationsPermissionAsked = this[Keys.NOTIFICATIONS_ASKED] ?: false,
        backgroundSyncEnabled = this[Keys.BACKGROUND_SYNC] ?: true,
        themeMode = ThemeMode.fromWire(this[Keys.THEME]),
        motionPreference = MotionPreference.fromWire(this[Keys.MOTION]),
        notifyEscalations = this[Keys.NOTIFY_ESCALATIONS] ?: true,
        notifyScreening = this[Keys.NOTIFY_SCREENING] ?: true,
        deadlineMissCount = this[Keys.DEADLINE_MISSES] ?: 0L,
        lastSyncAtMs = this[Keys.LAST_SYNC],
        lastSyncError = this[Keys.LAST_SYNC_ERROR],
        cachedPreferencesJson = this[Keys.PREFS_JSON],
        pendingPreferencesPatchJson = this[Keys.PREFS_PATCH],
        cachedStatusJson = this[Keys.STATUS_JSON],
        cachedStatusAtMs = this[Keys.STATUS_AT],
    )

    private fun androidx.datastore.preferences.core.MutablePreferences.write(s: AppSettings) {
        this[Keys.BACKEND_URL] = s.backendUrl
        this[Keys.ONBOARDING] = s.onboardingCompleted
        this[Keys.UNKNOWN_BEHAVIOR] = s.unknownCallerBehavior.wire
        this[Keys.TRUSTED_BEHAVIOR] = s.trustedContactBehavior.wire
        this[Keys.STRICTNESS] = s.strictness.wire
        this[Keys.CONTACTS_KNOWN] = s.useContactsAsKnown
        setOrRemove(Keys.SALT, s.fingerprintSalt)
        setOrRemove(Keys.FORWARDING_NUMBER, s.forwardingNumber)
        setOrRemove(Keys.FORWARDING_OPENED, s.forwardingHelperOpenedAtMs)
        this[Keys.FORWARDING_CONFIRMED] = s.forwardingConfirmedByOwner
        this[Keys.ROLE_DECLINED] = s.roleRequestDeclined
        this[Keys.CONTACTS_ASKED] = s.contactsPermissionAsked
        this[Keys.NOTIFICATIONS_ASKED] = s.notificationsPermissionAsked
        this[Keys.BACKGROUND_SYNC] = s.backgroundSyncEnabled
        this[Keys.THEME] = s.themeMode.wire
        this[Keys.MOTION] = s.motionPreference.wire
        this[Keys.NOTIFY_ESCALATIONS] = s.notifyEscalations
        this[Keys.NOTIFY_SCREENING] = s.notifyScreening
        this[Keys.DEADLINE_MISSES] = s.deadlineMissCount
        setOrRemove(Keys.LAST_SYNC, s.lastSyncAtMs)
        setOrRemove(Keys.LAST_SYNC_ERROR, s.lastSyncError)
        setOrRemove(Keys.PREFS_JSON, s.cachedPreferencesJson)
        setOrRemove(Keys.PREFS_PATCH, s.pendingPreferencesPatchJson)
        setOrRemove(Keys.STATUS_JSON, s.cachedStatusJson)
        setOrRemove(Keys.STATUS_AT, s.cachedStatusAtMs)
    }

    private fun <T> androidx.datastore.preferences.core.MutablePreferences.setOrRemove(
        key: Preferences.Key<T>,
        value: T?,
    ) {
        if (value == null) remove(key) else this[key] = value
    }
}
