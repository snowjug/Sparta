package io.github.snowjug.sparta.ui.privacy

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.notify.QuietHours
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.prefs.ThemeMode
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.SafetyPolicyDto
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.ConnectionTestResult
import io.github.snowjug.sparta.data.repo.ListEntry
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.repo.PreferencesPatch
import io.github.snowjug.sparta.data.repo.PreferencesRepository
import io.github.snowjug.sparta.data.repo.SaveResult
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.data.repo.UserPreferences
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.onboarding.ConnectionUi
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PrivacyUiState(
    val settings: AppSettings = AppSettings(),
    val prefs: UserPreferences? = null,
    val blocked: List<ListEntry> = emptyList(),
    val trusted: List<ListEntry> = emptyList(),
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val contacts: PermissionUiState = PermissionUiState.NOT_ASKED,
    val policy: SafetyPolicyDto? = null,
    val urlInput: String = "",
    val connection: ConnectionUi = ConnectionUi.Idle,
    val deleting: Boolean = false,
    val message: UiMessage? = null,
) {
    val backendConfigured: Boolean get() = settings.backendConfigured
    val quietHoursOn: Boolean get() = prefs?.quietHoursStart != null && prefs.quietHoursEnd != null
}

private data class PrivacyLocal(
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val contacts: PermissionUiState = PermissionUiState.NOT_ASKED,
    val policy: SafetyPolicyDto? = null,
    val urlInput: String = "",
    val connection: ConnectionUi = ConnectionUi.Idle,
    val deleting: Boolean = false,
    val message: UiMessage? = null,
)

@HiltViewModel
class PrivacyViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val preferences: PreferencesRepository,
    private val screening: ScreeningRepository,
    private val calls: CallsRepository,
    private val system: SystemRepository,
    private val permissions: PermissionModel,
    private val connector: BackendConnector,
) : ViewModel() {

    private val local = MutableStateFlow(PrivacyLocal())

    val state: StateFlow<PrivacyUiState> = combine(
        settings.settings,
        preferences.preferences,
        screening.observeBlocked(),
        screening.observeTrusted(),
        local,
    ) { s, prefs, blocked, trusted, l ->
        PrivacyUiState(
            settings = s,
            prefs = prefs,
            blocked = blocked,
            trusted = trusted,
            notifications = l.notifications,
            contacts = l.contacts,
            policy = l.policy,
            urlInput = l.urlInput.ifEmpty { s.backendUrl },
            connection = l.connection,
            deleting = l.deleting,
            message = l.message,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PrivacyUiState())

    /** Re-reads what the OS can change behind our back and refreshes backend-owned data. */
    fun onResume(notificationsRationale: Boolean = false, contactsRationale: Boolean = false) {
        viewModelScope.launch {
            val notifications = permissions.stateOf(AppPermission.NOTIFICATIONS, notificationsRationale)
            val contacts = permissions.stateOf(AppPermission.CONTACTS, contactsRationale)
            local.update { it.copy(notifications = notifications, contacts = contacts) }
            if (settings.current().backendConfigured) {
                preferences.refresh()
                (system.safetyPolicy() as? ApiResult.Success)?.let { r -> local.update { it.copy(policy = r.value) } }
            }
        }
    }

    fun dismissMessage() = local.update { it.copy(message = null) }

    // ---- screening behaviour (effective on this phone at once, synced when the backend is reachable) ----

    fun setUnknownBehavior(value: UnknownCallerBehavior) = save(PreferencesPatch().unknownCallerBehavior(value))

    fun setTrustedBehavior(value: TrustedContactBehavior) = save(PreferencesPatch().trustedContactBehavior(value))

    fun setStrictness(value: Strictness) = save(PreferencesPatch().strictness(value))

    // ---- notifications ----

    fun setNotifyEscalations(value: Boolean) {
        viewModelScope.launch { settings.update { it.copy(notifyEscalations = value) } }
    }

    fun setNotifyScreening(value: Boolean) {
        viewModelScope.launch { settings.update { it.copy(notifyScreening = value) } }
    }

    fun setNotifyHighRisk(value: Boolean) = save(PreferencesPatch().notifyOnHighRisk(value))

    fun setIncludeLines(value: Boolean) = save(PreferencesPatch().includeTranscriptLines(value))

    fun setQuietHours(on: Boolean) =
        save(if (on) PreferencesPatch().quietHours(DEFAULT_QUIET_START, DEFAULT_QUIET_END) else PreferencesPatch().quietHours(null, null))

    fun shiftQuietStart(deltaMinutes: Int) {
        viewModelScope.launch {
            val prefs = preferences.preferences.first() ?: return@launch
            val end = prefs.quietHoursEnd ?: DEFAULT_QUIET_END
            apply(PreferencesPatch().quietHours(QuietHours.shift(prefs.quietHoursStart, deltaMinutes), end))
        }
    }

    fun shiftQuietEnd(deltaMinutes: Int) {
        viewModelScope.launch {
            val prefs = preferences.preferences.first() ?: return@launch
            val start = prefs.quietHoursStart ?: DEFAULT_QUIET_START
            apply(PreferencesPatch().quietHours(start, QuietHours.shift(prefs.quietHoursEnd, deltaMinutes)))
        }
    }

    fun onNotificationsResult(granted: Boolean, shouldShowRationale: Boolean) {
        viewModelScope.launch {
            val result = permissions.onNotificationsResult(granted, shouldShowRationale)
            local.update { it.copy(notifications = result) }
        }
    }

    // ---- contacts ----

    /** Switching off needs no prompt. Switching on while the permission is already granted needs none either. */
    fun disableContacts() {
        viewModelScope.launch { permissions.setContactsOptIn(false) }
    }

    fun enableContactsIfGranted(): Boolean {
        if (!permissions.isGranted(AppPermission.CONTACTS)) return false
        viewModelScope.launch { permissions.setContactsOptIn(true) }
        return true
    }

    fun onContactsResult(granted: Boolean, shouldShowRationale: Boolean) {
        viewModelScope.launch {
            val result = permissions.onContactsPromptResult(granted, shouldShowRationale)
            local.update { it.copy(contacts = result) }
        }
    }

    // ---- data and retention ----

    fun setStoreTranscripts(value: Boolean) = save(PreferencesPatch().storeTranscripts(value))

    fun setTranscriptRetentionDays(days: Int) = save(PreferencesPatch().transcriptRetentionDays(days))

    fun setStoreFullNumber(value: Boolean) = save(PreferencesPatch().storeFullCallerNumber(value))

    fun removeEntry(entry: ListEntry) {
        viewModelScope.launch {
            val message = when (val result = screening.removeEntry(entry)) {
                is ApiResult.Success -> UiMessage.Text(R.string.privacy_entry_removed)
                is ApiResult.Failure -> UiMessage.Failure(result.error)
            }
            local.update { it.copy(message = message) }
        }
    }

    /** Backend content first (it is the part that can fail); the phone's own history is cleared only on success. */
    fun deleteAllCallData() {
        if (local.value.deleting) return
        local.update { it.copy(deleting = true, message = null) }
        viewModelScope.launch {
            val backend = if (settings.current().backendConfigured) calls.deleteAll() else ApiResult.Success(Unit)
            val message = when (backend) {
                is ApiResult.Success -> {
                    screening.clearLocalHistory()
                    calls.clearCache()
                    UiMessage.Text(R.string.privacy_deleted_all)
                }
                is ApiResult.Failure -> UiMessage.Failure(backend.error)
            }
            local.update { it.copy(deleting = false, message = message) }
        }
    }

    fun deleteLocalHistory() {
        viewModelScope.launch {
            screening.clearLocalHistory()
            local.update { it.copy(message = UiMessage.Text(R.string.privacy_deleted_local)) }
        }
    }

    // ---- appearance and battery ----

    fun setTheme(mode: ThemeMode) {
        viewModelScope.launch { settings.update { it.copy(themeMode = mode) } }
    }

    fun setMotion(pref: MotionPreference) {
        viewModelScope.launch { settings.update { it.copy(motionPreference = pref) } }
    }

    fun setBackgroundSync(value: Boolean) {
        viewModelScope.launch { settings.update { it.copy(backgroundSyncEnabled = value) } }
    }

    // ---- backend ----

    fun onUrlChange(value: String) = local.update { it.copy(urlInput = value, connection = ConnectionUi.Idle) }

    fun testConnection() {
        local.update { it.copy(connection = ConnectionUi.Testing) }
        viewModelScope.launch {
            // What was typed, or the saved address when the owner has not edited the field.
            val input = local.value.urlInput.ifBlank { settings.current().backendUrl }
            val result = when (val test = connector.test(input)) {
                is ConnectionTestResult.Reachable -> ConnectionUi.Success(
                    url = test.url,
                    version = test.status.version,
                    provider = test.status.telephony.provider,
                    simulated = test.status.telephony.simulated,
                    devBanner = test.status.devBanner,
                    forwardingNumber = test.status.telephony.forwardingNumber,
                )
                is ConnectionTestResult.Unreachable -> ConnectionUi.Failure(test.error)
                is ConnectionTestResult.InvalidUrl -> ConnectionUi.InvalidUrl(test.problem)
            }
            local.update { it.copy(connection = result) }
        }
    }

    fun useBackend() {
        val success = local.value.connection as? ConnectionUi.Success ?: return
        viewModelScope.launch {
            val sync = connector.connect(success.url)
            val message = if (sync is ApiResult.Failure) UiMessage.Failure(sync.error) else UiMessage.Text(R.string.privacy_backend_saved)
            local.update { it.copy(urlInput = "", connection = ConnectionUi.Idle, message = message) }
            onResume()
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            connector.disconnect()
            calls.clearCache()
            local.update { it.copy(urlInput = "", connection = ConnectionUi.Idle, policy = null, message = UiMessage.Text(R.string.privacy_backend_disconnected)) }
        }
    }

    private fun save(patch: PreferencesPatch) {
        viewModelScope.launch { apply(patch) }
    }

    private suspend fun apply(patch: PreferencesPatch) {
        val message = when (val result = preferences.save(patch)) {
            SaveResult.Synced -> UiMessage.Text(R.string.privacy_saved)
            is SaveResult.SavedOnDevice ->
                if (result.error.kind == ApiErrorKind.NOT_CONFIGURED) {
                    UiMessage.Text(R.string.privacy_saved_local)
                } else {
                    UiMessage.Text(R.string.common_saved_on_phone, listOf(result.error.message))
                }
        }
        local.update { it.copy(message = message) }
    }

    private companion object {
        const val DEFAULT_QUIET_START = "22:00"
        const val DEFAULT_QUIET_END = "07:00"
    }
}
