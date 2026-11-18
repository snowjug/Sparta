package io.github.snowjug.sparta.ui.status

import android.content.Intent
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.screening.ScreeningPolicy
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.platform.DeviceInfoProvider
import io.github.snowjug.sparta.platform.RoleController
import io.github.snowjug.sparta.ui.common.UiMessage
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface BackendReachability {
    data object NotConfigured : BackendReachability

    data object Unknown : BackendReachability

    data object Checking : BackendReachability

    data class Reachable(val checkedAtMs: Long?) : BackendReachability

    data class Unreachable(val error: ApiError, val hasCachedStatus: Boolean) : BackendReachability
}

data class ProtectionUiState(
    val role: RoleState = RoleState(RoleStatus.NOT_GRANTED),
    val device: DeviceInfo? = null,
    val backendConfigured: Boolean = false,
    val backend: BackendReachability = BackendReachability.Unknown,
    val status: SystemStatusDto? = null,
    val statusFetchedAtMs: Long? = null,
    val forwardingNumber: String? = null,
    val forwardingConfirmed: Boolean = false,
    val forwardingHelperOpenedAtMs: Long? = null,
    val lastDecision: ScreeningEventEntity? = null,
    val pendingUploads: Int = 0,
    val attentionCount: Int = 0,
    val policy: ScreeningPolicy = ScreeningPolicy(),
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val refreshing: Boolean = false,
    val message: UiMessage? = null,
) {
    /** Provider honesty: unknown means simulated until the backend says otherwise. */
    val simulated: Boolean get() = status?.telephony?.simulated ?: true
    val liveCallsSupported: Boolean get() = status?.telephony?.liveCallsSupported ?: false
    val devBanner: Boolean get() = status?.devBanner ?: false
}

private data class Transient(
    val role: RoleState = RoleState(RoleStatus.NOT_GRANTED),
    val backend: BackendReachability? = null,
    val attentionCount: Int = 0,
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val refreshing: Boolean = false,
    val message: UiMessage? = null,
)

@HiltViewModel
class ProtectionViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val system: SystemRepository,
    private val screening: ScreeningRepository,
    private val roles: RoleController,
    private val devices: DeviceInfoProvider,
    private val permissions: PermissionModel,
    private val clock: WallClock,
) : ViewModel() {

    private val transient = MutableStateFlow(Transient(role = roles.currentState(requestDeclined = false)))

    val state: StateFlow<ProtectionUiState> = combine(
        settings.settings,
        system.cachedStatus,
        screening.observeLatestEvent(),
        screening.observePendingUploads(),
        transient,
    ) { s, cached, latest, pending, t ->
        val reachability = when {
            !s.backendConfigured -> BackendReachability.NotConfigured
            else -> t.backend ?: BackendReachability.Unknown
        }
        ProtectionUiState(
            role = t.role,
            device = devices.get(),
            backendConfigured = s.backendConfigured,
            backend = reachability,
            status = cached?.status,
            statusFetchedAtMs = cached?.fetchedAtMs,
            forwardingNumber = s.forwardingNumber ?: cached?.status?.telephony?.forwardingNumber,
            forwardingConfirmed = s.forwardingConfirmedByOwner,
            forwardingHelperOpenedAtMs = s.forwardingHelperOpenedAtMs,
            lastDecision = latest,
            pendingUploads = pending,
            attentionCount = t.attentionCount,
            policy = s.policy,
            notifications = t.notifications,
            refreshing = t.refreshing,
            message = t.message,
        )
    }.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        // The role is known synchronously, so the first frame never claims "screening is off" for a phone that has it on.
        ProtectionUiState(role = transient.value.role, device = devices.get()),
    )

    /** Re-reads everything the OS can change behind our back (role, permissions) and refreshes the backend. */
    fun onResume(notificationRationale: Boolean = false) {
        viewModelScope.launch {
            val declined = settings.current().roleRequestDeclined
            val notifications = permissions.stateOf(AppPermission.NOTIFICATIONS, notificationRationale)
            transient.update { it.copy(role = roles.currentState(declined), notifications = notifications) }
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            if (!settings.current().backendConfigured) {
                transient.update { it.copy(backend = BackendReachability.NotConfigured, refreshing = false) }
                return@launch
            }
            transient.update { it.copy(refreshing = true, backend = BackendReachability.Checking) }
            val status = system.refreshStatus()
            val reachability = when (status) {
                is ApiResult.Success -> BackendReachability.Reachable(clock.nowMs())
                is ApiResult.Failure -> BackendReachability.Unreachable(status.error, hasCachedStatus = settings.current().cachedStatusJson != null)
            }
            if (status is ApiResult.Success) screening.syncConfigAndLists()
            val attention = (system.home() as? ApiResult.Success)?.value?.attention?.size
            transient.update {
                it.copy(
                    refreshing = false,
                    backend = reachability,
                    attentionCount = attention ?: it.attentionCount,
                )
            }
        }
    }

    /** The system role-request intent, or null when the role cannot be requested here. */
    fun roleRequestIntent(): Intent? = roles.createRequestIntent()

    /** Called with the result of the system role dialog (RESULT_OK means Sparta was chosen). */
    fun onRoleResult(granted: Boolean) {
        viewModelScope.launch {
            settings.update { it.copy(roleRequestDeclined = !granted) }
            transient.update { it.copy(role = roles.currentState(requestDeclined = !granted)) }
        }
    }

    fun onNotificationPermissionResult(granted: Boolean, shouldShowRationale: Boolean) {
        viewModelScope.launch {
            val result = permissions.onNotificationsResult(granted, shouldShowRationale)
            transient.update { it.copy(notifications = result) }
        }
    }

    fun confirmForwarding(confirmed: Boolean) {
        viewModelScope.launch { settings.update { it.copy(forwardingConfirmedByOwner = confirmed) } }
    }

    fun forwardingHelperOpened() {
        viewModelScope.launch { settings.update { it.copy(forwardingHelperOpenedAtMs = clock.nowMs()) } }
    }

    fun dismissMessage() = transient.update { it.copy(message = null) }
}
