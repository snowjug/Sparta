package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.repo.DecisionStatsCalculator
import io.github.snowjug.sparta.data.repo.ListEntry
import io.github.snowjug.sparta.data.repo.SyncReport
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.detail.ScreeningEventActions
import io.github.snowjug.sparta.ui.detail.ScreeningEventContent
import io.github.snowjug.sparta.ui.detail.ScreeningEventUiState
import io.github.snowjug.sparta.ui.diagnostics.DiagConnection
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsActions
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsContent
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DiagnosticsContentTest {

    @get:Rule
    val compose = createComposeRule()

    private val phone = DeviceInfo(35, "15", "Google", "Pixel 9", "2026-10-05", "0.1.0", 7, debugBuild = true)
    private val events = listOf(
        Samples.event(id = "e1", decision = "silence", latencyMs = 20),
        Samples.event(id = "e2", decision = "reject", reason = "blocked_number", latencyMs = 40, missed = true),
    )

    private fun state(change: DiagnosticsUiState.() -> DiagnosticsUiState = { this }) = DiagnosticsUiState(
        device = phone,
        role = RoleState(RoleStatus.GRANTED),
        notifications = PermissionUiState.GRANTED,
        contacts = PermissionUiState.DENIED_PERMANENTLY,
        settings = AppSettings(backendUrl = "https://sparta.example.com/", deadlineMissCount = 3),
        status = Samples.status(),
        statusFetchedAtMs = Samples.NOW - 120_000,
        stats = DecisionStatsCalculator.of(events),
        recent = events,
        pendingUploads = 2,
        nowMs = Samples.NOW,
        reportText = "SPARTA ANDROID DIAGNOSTIC REPORT\nSanitised",
    ).change()

    private fun show(state: DiagnosticsUiState, actions: DiagnosticsActions = DiagnosticsActions()) {
        compose.setContent { SpartaTheme { DiagnosticsContent(state, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    @Test
    fun `the phone card shows version build type android and device`() {
        show(state())
        node("diag_app_version").assertTextContains("0.1.0 (7)", substring = true)
        node("diag_build_type").assertTextContains("Debug", substring = true)
        node("diag_android").assertTextContains("15 (API 35)", substring = true)
        node("diag_network_note").assertTextContains("only for localhost", substring = true)
    }

    @Test
    fun `a release build says https only`() {
        show(state { copy(device = phone.copy(debugBuild = false)) })
        node("diag_network_note").assertTextContains("only HTTPS connections are allowed", substring = true)
    }

    @Test
    fun `screening statistics and the latest decisions are shown without full numbers`() {
        show(state())
        node("diag_role").assertTextContains("Screening is on", substring = true)
        node("diag_total").assertTextContains("2", substring = true)
        node("diag_latency_avg").assertTextContains("30 ms", substring = true)
        node("diag_deadline_misses").assertTextContains("1 / 3", substring = true)
        node("diag_recent_e2").assertTextContains("Rejected", substring = true)
        node("diag_recent_e2").assertTextContains(Samples.MASKED, substring = true)
    }

    @Test
    fun `no decisions yet is said instead of showing zeros as success`() {
        show(state { copy(stats = io.github.snowjug.sparta.data.repo.DecisionStats(), recent = emptyList()) })
        node("diag_recent_none").assertExists()
        node("diag_latency_avg").assertTextContains("Not available", substring = true)
    }

    @Test
    fun `permission states are spelled out`() {
        show(state())
        node("diag_perm_notifications").assertTextContains("Allowed", substring = true)
        node("diag_perm_contacts").assertTextContains("change it in Android settings", substring = true)
    }

    @Test
    fun `the backend card labels a simulator as simulated and says whether live calls are supported`() {
        show(state())
        node("diag_provider").assertTextContains("simulator", substring = true)
        node("diag_simulated").assertTextContains("Simulated", substring = true)
        node("diag_live_calls").assertTextContains("No", substring = true)
    }

    @Test
    fun `an unconfigured backend is reported`() {
        show(state { copy(settings = AppSettings(), status = null) })
        node("diag_backend_none").assertExists()
        node("diag_test_connection").assertDoesNotExist()
        node("diag_sync_now").assertDoesNotExist()
    }

    @Test
    fun `the connection test reports success failure and invalid addresses`() {
        var tested = 0
        show(state { copy(connection = DiagConnection.Reachable(84, "0.1.0")) }, DiagnosticsActions(onTestConnection = { tested++ }))
        node("diag_test_connection").assertIsEnabled().performClick()
        assertEquals(1, tested)
        node("diag_connection_ok").assertTextContains("Reachable in 84 ms", substring = true)
    }

    @Test
    fun `a failed connection test shows the reason`() {
        show(state { copy(connection = DiagConnection.Failed(ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached."))) })
        node("diag_connection_failed").assertTextContains("could not be reached", substring = true)
    }

    @Test
    fun `a testing connection disables the button`() {
        show(state { copy(connection = DiagConnection.Testing) })
        node("diag_test_connection").assertIsNotEnabled()
    }

    @Test
    fun `an invalid saved address is explained`() {
        show(state { copy(connection = DiagConnection.Invalid(BackendUrlProblem.HTTPS_REQUIRED)) })
        node("diag_connection_invalid").assertTextContains("only connects over HTTPS", substring = true)
    }

    @Test
    fun `sync facts and the sync now action are shown`() {
        var synced = 0
        show(
            state { copy(settings = settings.copy(lastSyncAtMs = Samples.NOW - 3_600_000, lastSyncError = "OFFLINE"), syncReport = SyncReport(uploadsRequeued = 2, notificationsPosted = 1)) },
            DiagnosticsActions(onSyncNow = { synced++ }),
        )
        node("diag_last_sync").assertTextContains("1 h ago", substring = true)
        node("diag_last_sync_error").assertTextContains("OFFLINE", substring = true)
        node("diag_pending").assertTextContains("2", substring = true)
        node("diag_sync_result").assertTextContains("Uploads re-queued: 2. Notifications posted: 1.", substring = true)
        node("diag_sync_now").performClick()
        assertEquals(1, synced)
    }

    @Test
    fun `a sync that never ran says never`() {
        show(state())
        node("diag_last_sync").assertTextContains("Never", substring = true)
    }

    @Test
    fun `the report can be read and shared exactly as shown`() {
        var shared = ""
        show(state(), DiagnosticsActions(onShareReport = { shared = it }))
        node("diag_report_text").assertTextContains("SPARTA ANDROID DIAGNOSTIC REPORT", substring = true)
        node("diag_share").performClick()
        assertEquals("SPARTA ANDROID DIAGNOSTIC REPORT\nSanitised", shared)
    }
}

@RunWith(AndroidJUnit4::class)
class ScreeningEventContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun show(state: ScreeningEventUiState, actions: ScreeningEventActions = ScreeningEventActions()) {
        compose.setContent { SpartaTheme { ScreeningEventContent(state, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    private fun loaded(change: ScreeningEventUiState.() -> ScreeningEventUiState = { this }) =
        ScreeningEventUiState(eventId = "evt_1", loading = false, event = Samples.event(), nowMs = Samples.NOW).change()

    @Test
    fun `the decision the reason and the explanation are shown with a masked number`() {
        show(loaded())
        node("event_number").assertTextContains(Samples.MASKED)
        node("event_action").assertTextContains("Silenced", substring = true)
        node("event_reason").assertTextContains("Unknown caller, screened", substring = true)
        node("event_explanation").assertTextContains("Sparta does not answer calls on this phone", substring = true)
        node("provider_badge").assertTextContains("On-device screening")
    }

    @Test
    fun `it says plainly there is no transcript or analysis`() {
        show(loaded())
        node("event_no_content").assertTextContains("no audio and no words from the call", substring = true)
    }

    @Test
    fun `a missed deadline is shown as a safe default`() {
        show(loaded { copy(event = Samples.event(decision = "allow", reason = "deadline_exceeded", missed = true, latencyMs = 1500)) })
        node("event_latency").assertTextContains("took too long, the call was allowed", substring = true)
    }

    @Test
    fun `block and trust are offered and reported`() {
        var blocked = 0
        var trusted = 0
        show(loaded(), ScreeningEventActions(onBlock = { blocked++ }, onTrust = { trusted++ }))
        node("event_block").assertIsEnabled().performClick()
        node("event_trust").assertIsEnabled().performClick()
        assertEquals(1, blocked)
        assertEquals(1, trusted)
    }

    @Test
    fun `a number without a fingerprint cannot be listed and the reason is given`() {
        show(loaded { copy(event = Samples.event(fingerprint = null)) })
        node("event_block").assertIsNotEnabled()
        node("event_trust").assertIsNotEnabled()
        node("event_no_fingerprint").assertTextContains("connect a backend once", substring = true)
    }

    @Test
    fun `an already blocked number offers to unblock it`() {
        var unblocked = 0
        show(
            loaded { copy(blockedEntry = ListEntry("blocked", "fp", null, Samples.MASKED, null, 1)) },
            ScreeningEventActions(onUnblock = { unblocked++ }),
        )
        node("event_block").assertDoesNotExist()
        node("event_unblock").performClick()
        assertEquals(1, unblocked)
    }

    @Test
    fun `an already trusted number offers to remove trust`() {
        var removed = 0
        show(
            loaded { copy(trustedEntry = ListEntry("trusted", "fp", null, Samples.MASKED, null, 1)) },
            ScreeningEventActions(onUntrust = { removed++ }),
        )
        node("event_untrust").performClick()
        assertEquals(1, removed)
    }

    @Test
    fun `deleting the record asks first`() {
        var deleted = 0
        show(loaded(), ScreeningEventActions(onDelete = { deleted++ }))
        node("event_delete").performClick()
        node("event_delete_dialog").assertTextContains("removed from this phone only", substring = true)
        node("event_delete_cancel").performClick()
        assertEquals(0, deleted)
        node("event_delete").performClick()
        node("event_delete_confirm").performClick()
        assertEquals(1, deleted)
    }

    @Test
    fun `upload state is explained`() {
        show(loaded { copy(event = Samples.event(uploadState = UploadState.UPLOADED)) })
        node("event_screen").assertTextContains("Uploaded", substring = true)
    }

    @Test
    fun `a missing record is explained`() {
        show(ScreeningEventUiState(eventId = "gone", loading = false, event = null))
        node("event_not_found").assertExists()
    }

    @Test
    fun `results of actions appear`() {
        show(loaded { copy(message = UiMessage.Text(io.github.snowjug.sparta.R.string.event_msg_blocked)) })
        node("message_banner").assertTextContains("now blocked on this phone", substring = true)
    }
}
