package io.github.snowjug.sparta.ui.diagnostics

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.BackgroundSync
import io.github.snowjug.sparta.data.repo.ConnectionTestResult
import io.github.snowjug.sparta.data.repo.DecisionStats
import io.github.snowjug.sparta.data.repo.DecisionStatsCalculator
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.data.repo.SyncReport
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.platform.DeviceInfoProvider
import io.github.snowjug.sparta.platform.RoleController
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface DiagConnection {
    data object Idle : DiagConnection

    data object Testing : DiagConnection

    data class Reachable(val roundTripMs: Long, val version: String) : DiagConnection

    data class Failed(val error: ApiError) : DiagConnection

    data class Invalid(val problem: BackendUrlProblem) : DiagConnection
}

data class DiagnosticsUiState(
    val device: DeviceInfo? = null,
    val role: RoleState = RoleState(RoleStatus.NOT_GRANTED),
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val contacts: PermissionUiState = PermissionUiState.NOT_ASKED,
    val settings: AppSettings = AppSettings(),
    val status: SystemStatusDto? = null,
    val statusFetchedAtMs: Long? = null,
    val connection: DiagConnection = DiagConnection.Idle,
    val syncing: Boolean = false,
    val syncReport: SyncReport? = null,
    val stats: DecisionStats = DecisionStats(),
    val recent: List<ScreeningEventEntity> = emptyList(),
    val pendingUploads: Int = 0,
    val nowMs: Long = 0,
    val reportText: String = "",
)

private data class DiagLocal(
    val role: RoleState = RoleState(RoleStatus.NOT_GRANTED),
    val notifications: PermissionUiState = PermissionUiState.NOT_ASKED,
    val contacts: PermissionUiState = PermissionUiState.NOT_ASKED,
    val connection: DiagConnection = DiagConnection.Idle,
    val syncing: Boolean = false,
    val syncReport: SyncReport? = null,
)

@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val system: SystemRepository,
    private val screening: ScreeningRepository,
    private val connector: BackendConnector,
    private val sync: BackgroundSync,
    private val roles: RoleController,
    private val permissions: PermissionModel,
    private val devices: DeviceInfoProvider,
    private val clock: WallClock,
) : ViewModel() {

    private val local = MutableStateFlow(DiagLocal(role = roles.currentState(requestDeclined = false)))

    val state: StateFlow<DiagnosticsUiState> = combine(
        settings.settings,
        system.cachedStatus,
        screening.observeEvents(STATS_WINDOW),
        screening.observePendingUploads(),
        local,
    ) { s, cached, events, pending, l ->
        val stats = DecisionStatsCalculator.of(events)
        val now = clock.nowMs()
        val device = devices.get()
        DiagnosticsUiState(
            device = device,
            role = l.role,
            notifications = l.notifications,
            contacts = l.contacts,
            settings = s,
            status = cached?.status,
            statusFetchedAtMs = cached?.fetchedAtMs,
            connection = l.connection,
            syncing = l.syncing,
            syncReport = l.syncReport,
            stats = stats,
            recent = events.take(RECENT_SHOWN),
            pendingUploads = pending,
            nowMs = now,
            reportText = DiagnosticReport.build(
                DiagnosticInput(
                    generatedAtMs = now,
                    device = device,
                    role = l.role,
                    notifications = l.notifications,
                    contacts = l.contacts,
                    settings = s,
                    backendReachable = when (l.connection) {
                        is DiagConnection.Reachable -> true
                        is DiagConnection.Failed -> false
                        else -> null
                    },
                    status = cached?.status,
                    stats = stats,
                    pendingUploads = pending,
                ),
            ),
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DiagnosticsUiState(device = devices.get()))

    /** Re-reads the role and the permissions: the OS can change them while the app is in the background. */
    fun onResume(notificationsRationale: Boolean = false, contactsRationale: Boolean = false) {
        viewModelScope.launch {
            val declined = settings.current().roleRequestDeclined
            val notifications = permissions.stateOf(AppPermission.NOTIFICATIONS, notificationsRationale)
            val contacts = permissions.stateOf(AppPermission.CONTACTS, contactsRationale)
            local.update { it.copy(role = roles.currentState(declined), notifications = notifications, contacts = contacts) }
        }
    }

    fun runConnectionTest() {
        local.update { it.copy(connection = DiagConnection.Testing) }
        viewModelScope.launch {
            val url = settings.current().backendUrl
            if (url.isBlank()) {
                local.update { it.copy(connection = DiagConnection.Idle) }
                return@launch
            }
            val result = when (val test = connector.test(url)) {
                is ConnectionTestResult.Reachable -> DiagConnection.Reachable(test.roundTripMs, test.status.version)
                is ConnectionTestResult.Unreachable -> DiagConnection.Failed(test.error)
                is ConnectionTestResult.InvalidUrl -> DiagConnection.Invalid(test.problem)
            }
            local.update { it.copy(connection = result) }
        }
    }

    /** One pass of exactly what the periodic worker does. */
    fun syncNow() {
        if (local.value.syncing) return
        local.update { it.copy(syncing = true) }
        viewModelScope.launch {
            val report = try {
                sync.run()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
            local.update { it.copy(syncing = false, syncReport = report) }
        }
    }

    private companion object {
        const val STATS_WINDOW = 200
        const val RECENT_SHOWN = 5
    }
}
