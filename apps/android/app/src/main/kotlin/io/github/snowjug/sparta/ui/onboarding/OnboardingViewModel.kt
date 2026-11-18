package io.github.snowjug.sparta.ui.onboarding

import android.content.Intent
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.BuildConfig
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.ConnectionTestResult
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.repo.PreferencesPatch
import io.github.snowjug.sparta.data.repo.PreferencesRepository
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.platform.DeviceInfoProvider
import io.github.snowjug.sparta.platform.RoleController
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class OnboardingStep {
    WELCOME,
    BACKEND,
    ROLE,
    PERMISSIONS,
    FORWARDING,
    ;

    val number: Int get() = ordinal + 1

    companion object {
        val count: Int get() = entries.size
    }
}

sealed interface ConnectionUi {
    data object Idle : ConnectionUi

    data object Testing : ConnectionUi

    data class Success(
        val url: String,
        val version: String,
        val provider: String,
        val simulated: Boolean,
        val devBanner: Boolean,
        val forwardingNumber: String?,
    ) : ConnectionUi

    data class Failure(val error: ApiError) : ConnectionUi

    data class InvalidUrl(val problem: BackendUrlProblem) : ConnectionUi
}

data class OnboardingUiState(
    val step: OnboardingStep = OnboardingStep.WELCOME,
    val urlInput: String = "",
    val connection: ConnectionUi = ConnectionUi.Idle,
    val backendSaved: Boolean = false,
    val role: RoleState = RoleState(RoleStatus.NOT_GRANTED),
    val device: DeviceInfo? = null,
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val contacts: PermissionUiState = PermissionUiState.NOT_ASKED,
    val useContactsAsKnown: Boolean = false,
    val forwardingNumber: String? = null,
    val finishing: Boolean = false,
    val finished: Boolean = false,
) {
    val canGoBack: Boolean get() = step != OnboardingStep.WELCOME
    val isLastStep: Boolean get() = step == OnboardingStep.FORWARDING
}

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val connector: BackendConnector,
    private val roles: RoleController,
    private val permissions: PermissionModel,
    private val preferences: PreferencesRepository,
    devices: DeviceInfoProvider,
) : ViewModel() {

    private val _state = MutableStateFlow(
        OnboardingUiState(
            urlInput = BuildConfig.DEFAULT_BACKEND_URL,
            role = roles.currentState(requestDeclined = false),
            device = devices.get(),
        ),
    )
    val state: StateFlow<OnboardingUiState> = _state.asStateFlow()

    fun onUrlChange(value: String) = _state.update { it.copy(urlInput = value, connection = ConnectionUi.Idle, backendSaved = false) }

    fun testConnection() {
        val input = _state.value.urlInput
        _state.update { it.copy(connection = ConnectionUi.Testing, backendSaved = false) }
        viewModelScope.launch {
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
            _state.update { it.copy(connection = result) }
        }
    }

    /** Saves the tested address and pulls the screening key, lists and policy. */
    fun useBackend() {
        val success = _state.value.connection as? ConnectionUi.Success ?: return
        viewModelScope.launch {
            val sync = connector.connect(success.url)
            val forwarding = settings.current().forwardingNumber ?: success.forwardingNumber
            _state.update {
                it.copy(
                    backendSaved = true,
                    forwardingNumber = forwarding,
                    // A failed first sync is not fatal (the address is saved); the status screen shows the reason later.
                    connection = if (sync is ApiResult.Failure) ConnectionUi.Failure(sync.error) else it.connection,
                )
            }
        }
    }

    fun next() = _state.update { s ->
        val nextStep = OnboardingStep.entries.getOrNull(s.step.ordinal + 1) ?: s.step
        s.copy(step = nextStep)
    }

    fun back() = _state.update { s ->
        val previous = OnboardingStep.entries.getOrNull(s.step.ordinal - 1) ?: s.step
        s.copy(step = previous)
    }

    fun roleRequestIntent(): Intent? = roles.createRequestIntent()

    fun onRoleResult(granted: Boolean) {
        viewModelScope.launch {
            settings.update { it.copy(roleRequestDeclined = !granted) }
            _state.update { it.copy(role = roles.currentState(requestDeclined = !granted)) }
        }
    }

    fun refreshPermissions(notificationsRationale: Boolean = false, contactsRationale: Boolean = false) {
        viewModelScope.launch {
            val s = settings.current()
            val notifications = permissions.stateOf(AppPermission.NOTIFICATIONS, notificationsRationale)
            val contacts = permissions.stateOf(AppPermission.CONTACTS, contactsRationale)
            _state.update {
                it.copy(
                    notifications = notifications,
                    contacts = contacts,
                    useContactsAsKnown = s.useContactsAsKnown && permissions.isGranted(AppPermission.CONTACTS),
                    role = roles.currentState(s.roleRequestDeclined),
                    forwardingNumber = it.forwardingNumber ?: s.forwardingNumber,
                )
            }
        }
    }

    fun onNotificationsResult(granted: Boolean, shouldShowRationale: Boolean) {
        viewModelScope.launch {
            val result = permissions.onNotificationsResult(granted, shouldShowRationale)
            _state.update { it.copy(notifications = result) }
        }
    }

    /** The owner switched the contacts option off: no prompt needed. */
    fun disableContactsOption() {
        viewModelScope.launch {
            permissions.setContactsOptIn(false)
            _state.update { it.copy(useContactsAsKnown = false) }
        }
    }

    /** Result of the system prompt that the owner started by switching the option on. */
    fun onContactsResult(granted: Boolean, shouldShowRationale: Boolean) {
        viewModelScope.launch {
            val result = permissions.onContactsPromptResult(granted, shouldShowRationale)
            _state.update { it.copy(contacts = result, useContactsAsKnown = granted) }
        }
    }

    fun finish() {
        if (_state.value.finishing) return
        _state.update { it.copy(finishing = true) }
        viewModelScope.launch {
            settings.update { it.copy(onboardingCompleted = true) }
            if (settings.current().backendConfigured) preferences.save(PreferencesPatch().onboardingCompleted(true))
            _state.update { it.copy(finishing = false, finished = true) }
        }
    }
}
