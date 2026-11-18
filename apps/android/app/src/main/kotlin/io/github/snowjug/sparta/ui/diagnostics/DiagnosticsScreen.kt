package io.github.snowjug.sparta.ui.diagnostics

import android.content.Intent
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.platform.AndroidPermissionChecker
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.ui.ScreeningText
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.ScreenTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.agoText
import io.github.snowjug.sparta.ui.privacy.urlProblemRes
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class DiagnosticsActions(
    val onRefresh: () -> Unit = {},
    val onTestConnection: () -> Unit = {},
    val onSyncNow: () -> Unit = {},
    val onShareReport: (String) -> Unit = {},
)

@Composable
fun DiagnosticsScreen(
    modifier: Modifier = Modifier,
    viewModel: DiagnosticsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val shareSubject = stringResource(R.string.diag_share_subject)
    val shareChooser = stringResource(R.string.diag_share_chooser)
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            fun rationale(permission: AppPermission): Boolean {
                val name = AndroidPermissionChecker.manifestName(permission) ?: return false
                return activity != null && ActivityCompat.shouldShowRequestPermissionRationale(activity, name)
            }
            viewModel.onResume(rationale(AppPermission.NOTIFICATIONS), rationale(AppPermission.CONTACTS))
        }
    }
    DiagnosticsContent(
        state = state,
        modifier = modifier,
        actions = DiagnosticsActions(
            onRefresh = { viewModel.onResume() },
            onTestConnection = viewModel::runConnectionTest,
            onSyncNow = viewModel::syncNow,
            onShareReport = { text ->
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
                    .putExtra(Intent.EXTRA_SUBJECT, shareSubject)
                val chooser = Intent.createChooser(send, shareChooser).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(chooser) }
            },
        ),
    )
}

@Composable
fun DiagnosticsContent(
    state: DiagnosticsUiState,
    actions: DiagnosticsActions,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().testTag("diagnostics_screen"),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        item(key = "content") {
            Column(
                modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                ScreenTitle(stringResource(R.string.diag_title), subtitle = stringResource(R.string.diag_subtitle))
                PhoneCard(state)
                ScreeningCard(state)
                PermissionsCard(state)
                BackendCard(state, actions)
                SyncCard(state, actions)
                ReportCard(state, actions)
            }
        }
    }
}

@Composable
private fun PhoneCard(state: DiagnosticsUiState) {
    val d = state.device
    SpartaCard(modifier = Modifier.testTag("diag_phone")) {
        SectionTitle(stringResource(R.string.diag_phone_title))
        if (d != null) {
            KeyValueRow(stringResource(R.string.diag_app), "${d.appVersionName} (${d.appVersionCode})", testTag = "diag_app_version")
            KeyValueRow(stringResource(R.string.diag_build), stringResource(if (d.debugBuild) R.string.diag_build_debug else R.string.diag_build_release), testTag = "diag_build_type")
            KeyValueRow(stringResource(R.string.diag_android), "${d.androidRelease} (API ${d.apiLevel})", testTag = "diag_android")
            KeyValueRow(stringResource(R.string.diag_device), "${d.manufacturer} ${d.model}".trim())
            d.securityPatch?.let { KeyValueRow(stringResource(R.string.diag_patch), it) }
            InfoBanner(
                stringResource(if (d.debugBuild) R.string.diag_network_debug else R.string.diag_network_release),
                if (d.debugBuild) Tone.CAUTION else Tone.INFO,
                testTag = "diag_network_note",
            )
        }
    }
}

@Composable
private fun ScreeningCard(state: DiagnosticsUiState) {
    val s = state.stats
    SpartaCard(modifier = Modifier.testTag("diag_screening")) {
        SectionTitle(stringResource(R.string.diag_screening_title))
        KeyValueRow(
            stringResource(R.string.diag_role),
            stringResource(
                when (state.role.status) {
                    RoleStatus.GRANTED -> R.string.status_role_granted_title
                    RoleStatus.NOT_GRANTED -> R.string.status_role_not_granted_title
                    RoleStatus.UNSUPPORTED_API -> R.string.status_role_unsupported_title
                    RoleStatus.ROLE_UNAVAILABLE -> R.string.status_role_unavailable_title
                },
            ),
            testTag = "diag_role",
        )
        KeyValueRow(stringResource(R.string.diag_decisions_total), s.total.toString(), testTag = "diag_total")
        KeyValueRow(stringResource(R.string.diag_allowed), s.allowed.toString())
        KeyValueRow(stringResource(R.string.diag_silenced), s.silenced.toString())
        KeyValueRow(stringResource(R.string.diag_rejected), s.rejected.toString())
        KeyValueRow(stringResource(R.string.diag_latency_avg), s.averageLatencyMs?.let { "$it ms" } ?: stringResource(R.string.common_not_available), testTag = "diag_latency_avg")
        KeyValueRow(stringResource(R.string.diag_latency_p95), s.p95LatencyMs?.let { "$it ms" } ?: stringResource(R.string.common_not_available))
        KeyValueRow(stringResource(R.string.diag_latency_max), s.maxLatencyMs?.let { "$it ms" } ?: stringResource(R.string.common_not_available))
        KeyValueRow(stringResource(R.string.diag_deadline_misses), "${s.deadlineMisses} / ${state.settings.deadlineMissCount}", testTag = "diag_deadline_misses")
        Text(stringResource(R.string.diag_deadline_note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        Text(stringResource(R.string.diag_recent_title), style = MaterialTheme.typography.titleSmall)
        if (state.recent.isEmpty()) {
            Text(stringResource(R.string.status_last_decision_none), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("diag_recent_none"))
        }
        state.recent.forEach { event ->
            Column(modifier = Modifier.fillMaxWidth().testTag("diag_recent_${event.clientEventId}")) {
                Text(
                    stringResource(R.string.status_last_decision_row, stringResource(ScreeningText.action(event.decision)), stringResource(ScreeningText.reasonLabel(event.reason))),
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "${event.numberDisplay} · ${agoText(state.nowMs, event.occurredAtMs)} · ${event.decisionLatencyMs} ms",
                    style = MaterialTheme.typography.bodySmall,
                    color = SpartaTheme.extras.textSecondary,
                )
            }
        }
    }
}

@Composable
private fun permissionText(state: PermissionUiState): String = stringResource(
    when (state) {
        PermissionUiState.NOT_ASKED -> R.string.perm_state_not_asked
        PermissionUiState.GRANTED -> R.string.perm_state_granted
        PermissionUiState.DENIED_CAN_ASK_AGAIN -> R.string.perm_state_denied
        PermissionUiState.DENIED_PERMANENTLY -> R.string.perm_state_blocked
        PermissionUiState.NOT_REQUIRED -> R.string.perm_state_not_required
    },
)

@Composable
private fun PermissionsCard(state: DiagnosticsUiState) {
    SpartaCard(modifier = Modifier.testTag("diag_permissions")) {
        SectionTitle(stringResource(R.string.diag_permissions_title))
        KeyValueRow(stringResource(R.string.perm_notifications), permissionText(state.notifications), testTag = "diag_perm_notifications")
        KeyValueRow(stringResource(R.string.perm_contacts), permissionText(state.contacts), testTag = "diag_perm_contacts")
        KeyValueRow(stringResource(R.string.diag_contacts_option), stringResource(if (state.settings.useContactsAsKnown) R.string.common_on else R.string.common_off))
    }
}

@Composable
private fun BackendCard(state: DiagnosticsUiState, actions: DiagnosticsActions) {
    val s = state.settings
    SpartaCard(modifier = Modifier.testTag("diag_backend")) {
        SectionTitle(stringResource(R.string.diag_backend_title))
        if (!s.backendConfigured) {
            Text(stringResource(R.string.status_backend_not_configured), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("diag_backend_none"))
            return@SpartaCard
        }
        val status = state.status
        if (status == null) {
            Text(stringResource(R.string.diag_backend_no_status), style = MaterialTheme.typography.bodyMedium)
        } else {
            KeyValueRow(stringResource(R.string.status_provider_row), status.telephony.provider.ifEmpty { stringResource(R.string.common_unknown) }, testTag = "diag_provider")
            KeyValueRow(
                stringResource(R.string.diag_telephony_kind),
                stringResource(if (status.telephony.simulated) R.string.common_simulated else R.string.common_not_simulated),
                testTag = "diag_simulated",
            )
            KeyValueRow(stringResource(R.string.diag_live_calls), stringResource(if (status.telephony.liveCallsSupported) R.string.common_yes else R.string.common_no), testTag = "diag_live_calls")
            KeyValueRow(stringResource(R.string.diag_backend_version), "${status.version} (${status.env})")
            KeyValueRow(stringResource(R.string.diag_auth_mode), status.authMode)
            if (status.policyVersion.isNotBlank()) KeyValueRow(stringResource(R.string.detail_row_policy), status.policyVersion)
            KeyValueRow(stringResource(R.string.diag_status_age), agoText(state.nowMs, state.statusFetchedAtMs))
        }
        SecondaryButton(
            text = stringResource(if (state.connection == DiagConnection.Testing) R.string.onb_backend_testing else R.string.diag_test_connection),
            onClick = actions.onTestConnection,
            enabled = state.connection != DiagConnection.Testing,
            icon = Icons.Rounded.Refresh,
            modifier = Modifier.fillMaxWidth(),
            testTag = "diag_test_connection",
        )
        when (val c = state.connection) {
            DiagConnection.Idle, DiagConnection.Testing -> Unit
            is DiagConnection.Reachable -> InfoBanner(stringResource(R.string.diag_connection_ok, c.roundTripMs, c.version), Tone.SAFE, testTag = "diag_connection_ok")
            is DiagConnection.Failed -> InfoBanner(c.error.message, Tone.CAUTION, testTag = "diag_connection_failed")
            is DiagConnection.Invalid -> InfoBanner(stringResource(urlProblemRes(c.problem)), Tone.CAUTION, testTag = "diag_connection_invalid")
        }
    }
}

@Composable
private fun SyncCard(state: DiagnosticsUiState, actions: DiagnosticsActions) {
    val s = state.settings
    SpartaCard(modifier = Modifier.testTag("diag_sync")) {
        SectionTitle(stringResource(R.string.diag_sync_title))
        KeyValueRow(stringResource(R.string.diag_last_sync), if (s.lastSyncAtMs == null) stringResource(R.string.diag_never) else agoText(state.nowMs, s.lastSyncAtMs), testTag = "diag_last_sync")
        KeyValueRow(stringResource(R.string.diag_last_sync_error), s.lastSyncError ?: stringResource(R.string.common_none), testTag = "diag_last_sync_error")
        KeyValueRow(stringResource(R.string.diag_pending_uploads), state.pendingUploads.toString(), testTag = "diag_pending")
        KeyValueRow(stringResource(R.string.privacy_background_sync), stringResource(if (s.backgroundSyncEnabled) R.string.common_on else R.string.common_off))
        if (s.backendConfigured) {
            SecondaryButton(
                text = stringResource(if (state.syncing) R.string.status_refreshing else R.string.diag_sync_now),
                onClick = actions.onSyncNow,
                enabled = !state.syncing,
                icon = Icons.Rounded.Refresh,
                modifier = Modifier.fillMaxWidth(),
                testTag = "diag_sync_now",
            )
            state.syncReport?.let { report ->
                val text = when {
                    report.skipped -> stringResource(R.string.diag_sync_skipped)
                    report.error != null -> stringResource(R.string.diag_sync_error, report.error.name)
                    else -> stringResource(R.string.diag_sync_ok, report.uploadsRequeued, report.notificationsPosted)
                }
                InfoBanner(text, if (report.error != null) Tone.CAUTION else Tone.INFO, testTag = "diag_sync_result")
            }
        }
    }
}

@Composable
private fun ReportCard(state: DiagnosticsUiState, actions: DiagnosticsActions) {
    SpartaCard(modifier = Modifier.testTag("diag_report")) {
        SectionTitle(stringResource(R.string.diag_report_title))
        Text(stringResource(R.string.diag_report_body), style = MaterialTheme.typography.bodyMedium)
        Text(
            state.reportText,
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.fillMaxWidth().testTag("diag_report_text"),
        )
        SecondaryButton(
            text = stringResource(R.string.diag_share),
            onClick = { actions.onShareReport(state.reportText) },
            icon = Icons.Rounded.Share,
            modifier = Modifier.fillMaxWidth(),
            testTag = "diag_share",
        )
    }
}
