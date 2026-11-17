package io.github.snowjug.sparta.ui.status

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.forwarding.ForwardingCodes
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.platform.AndroidPermissionChecker
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.ui.ScreeningText
import io.github.snowjug.sparta.ui.components.CheckRow
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.ScreenTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaLogo
import io.github.snowjug.sparta.ui.components.StatusPill
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.politeLiveRegion
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class ProtectionActions(
    val onEnableScreening: () -> Unit = {},
    val onOpenDefaultApps: () -> Unit = {},
    val onRefresh: () -> Unit = {},
    val onOpenForwardingHelper: () -> Unit = {},
    val onConfirmForwarding: (Boolean) -> Unit = {},
    val onReviewCalls: () -> Unit = {},
    val onAllowNotifications: () -> Unit = {},
    val onOpenNotificationSettings: () -> Unit = {},
)

@Composable
fun ProtectionScreen(
    onReviewCalls: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ProtectionViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var showForwarding by rememberSaveable { mutableStateOf(false) }

    val roleLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        viewModel.onRoleResult(result.resultCode == android.app.Activity.RESULT_OK)
    }
    val notificationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val rationale = activity != null && AndroidPermissionChecker.manifestName(AppPermission.NOTIFICATIONS)?.let {
            androidx.core.app.ActivityCompat.shouldShowRequestPermissionRationale(activity, it)
        } == true
        viewModel.onNotificationPermissionResult(granted, rationale)
    }

    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { viewModel.onResume() }
    }

    ProtectionContent(
        state = state,
        modifier = modifier,
        actions = ProtectionActions(
            onEnableScreening = { viewModel.roleRequestIntent()?.let(roleLauncher::launch) ?: openDefaultApps(context) },
            onOpenDefaultApps = { openDefaultApps(context) },
            onRefresh = viewModel::refresh,
            onOpenForwardingHelper = { showForwarding = true },
            onConfirmForwarding = viewModel::confirmForwarding,
            onReviewCalls = onReviewCalls,
            onAllowNotifications = {
                AndroidPermissionChecker.manifestName(AppPermission.NOTIFICATIONS)?.let(notificationLauncher::launch)
            },
            onOpenNotificationSettings = { openNotificationSettings(context) },
        ),
    )

    if (showForwarding) {
        ForwardingDialog(
            number = state.forwardingNumber,
            onDismiss = { showForwarding = false },
            onOpenDialer = { code ->
                viewModel.forwardingHelperOpened()
                openDialer(context, code)
            },
        )
    }
}

@Composable
fun ProtectionContent(
    state: ProtectionUiState,
    modifier: Modifier = Modifier,
    actions: ProtectionActions = ProtectionActions(),
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().testTag("protection_screen"),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        item {
            Column(modifier = Modifier.widthIn(max = 720.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                ScreenTitle(stringResource(R.string.status_title), subtitle = stringResource(R.string.status_subtitle))
                RoleCard(state, actions)
                if (state.notifications == PermissionUiState.NOT_ASKED || state.notifications == PermissionUiState.DENIED_CAN_ASK_AGAIN ||
                    state.notifications == PermissionUiState.DENIED_PERMANENTLY
                ) {
                    NotificationsCard(state.notifications, actions)
                }
                if (state.attentionCount > 0) AttentionCard(state.attentionCount, actions)
                BackendCard(state, actions)
                ForwardingCard(state, actions)
                LastDecisionCard(state)
                PolicyCard(state)
                LimitsCard()
            }
        }
    }
}

@Composable
private fun RoleCard(state: ProtectionUiState, actions: ProtectionActions) {
    val role = state.role
    SpartaCard(modifier = Modifier.testTag("role_card").politeLiveRegion()) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            SpartaLogo(size = 56.dp, decorative = true)
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                when (role.status) {
                    RoleStatus.GRANTED -> {
                        Text(stringResource(R.string.status_role_granted_title), style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("role_headline"))
                        StatusPill(stringResource(R.string.status_role_granted_title), Tone.SAFE, icon = Icons.Rounded.CheckCircle, testTag = "role_state_granted")
                    }
                    RoleStatus.NOT_GRANTED -> {
                        Text(stringResource(R.string.status_role_not_granted_title), style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("role_headline"))
                        StatusPill(stringResource(R.string.status_role_not_granted_title), Tone.CAUTION, icon = Icons.Rounded.Warning, testTag = "role_state_not_granted")
                    }
                    RoleStatus.UNSUPPORTED_API -> {
                        Text(stringResource(R.string.status_role_unsupported_title), style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("role_headline"))
                        StatusPill(stringResource(R.string.status_role_unsupported_title), Tone.NEUTRAL, icon = Icons.Rounded.Block, testTag = "role_state_unsupported")
                    }
                    RoleStatus.ROLE_UNAVAILABLE -> {
                        Text(stringResource(R.string.status_role_unavailable_title), style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("role_headline"))
                        StatusPill(stringResource(R.string.status_role_unavailable_title), Tone.NEUTRAL, icon = Icons.Rounded.Block, testTag = "role_state_unavailable")
                    }
                }
            }
        }
        when (role.status) {
            RoleStatus.GRANTED -> Text(stringResource(R.string.status_role_granted_body), style = MaterialTheme.typography.bodyMedium)
            RoleStatus.NOT_GRANTED -> {
                Text(stringResource(R.string.status_role_not_granted_body), style = MaterialTheme.typography.bodyMedium)
                if (role.requestDeclined) {
                    InfoBanner(stringResource(R.string.status_role_declined_body), Tone.CAUTION, testTag = "role_declined_note")
                }
                PrimaryButton(
                    text = stringResource(if (role.requestDeclined) R.string.status_try_again_role else R.string.status_enable_screening),
                    onClick = actions.onEnableScreening,
                    icon = Icons.Rounded.Shield,
                    testTag = "enable_screening",
                )
                if (role.requestDeclined) {
                    SecondaryButton(stringResource(R.string.status_open_default_apps), actions.onOpenDefaultApps, testTag = "open_default_apps")
                }
            }
            RoleStatus.UNSUPPORTED_API -> Text(
                stringResource(
                    R.string.status_role_unsupported_body,
                    state.device?.androidRelease.orEmpty().ifEmpty { "?" },
                    state.device?.apiLevel ?: 0,
                ),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("unsupported_explanation"),
            )
            RoleStatus.ROLE_UNAVAILABLE -> {
                Text(stringResource(R.string.status_role_unavailable_body), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("unavailable_explanation"))
                SecondaryButton(stringResource(R.string.status_open_default_apps), actions.onOpenDefaultApps, testTag = "open_default_apps")
            }
        }
    }
}

@Composable
private fun NotificationsCard(state: PermissionUiState, actions: ProtectionActions) {
    SpartaCard(modifier = Modifier.testTag("notifications_card")) {
        Text(stringResource(R.string.status_notifications_off_title), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.status_notifications_off_body), style = MaterialTheme.typography.bodyMedium)
        if (state == PermissionUiState.DENIED_PERMANENTLY) {
            SecondaryButton(stringResource(R.string.status_notifications_settings), actions.onOpenNotificationSettings, testTag = "notification_settings")
        } else {
            PrimaryButton(stringResource(R.string.status_notifications_allow), actions.onAllowNotifications, testTag = "allow_notifications")
        }
    }
}

@Composable
private fun AttentionCard(count: Int, actions: ProtectionActions) {
    SpartaCard(modifier = Modifier.testTag("attention_card").politeLiveRegion()) {
        SectionTitle(stringResource(R.string.status_attention_title))
        Text(pluralStringResource(R.plurals.status_attention_count, count, count), style = MaterialTheme.typography.bodyLarge)
        PrimaryButton(stringResource(R.string.status_attention_open), actions.onReviewCalls, testTag = "review_calls")
    }
}

@Composable
private fun BackendCard(state: ProtectionUiState, actions: ProtectionActions) {
    SpartaCard(modifier = Modifier.testTag("backend_card")) {
        SectionTitle(stringResource(R.string.status_backend_title))
        val reachability = state.backend
        when (reachability) {
            BackendReachability.NotConfigured -> InfoBanner(stringResource(R.string.status_backend_not_configured), Tone.INFO, testTag = "backend_not_configured")
            BackendReachability.Checking -> Text(stringResource(R.string.status_backend_checking), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("backend_checking"))
            BackendReachability.Unknown -> Text(stringResource(R.string.common_unknown), style = MaterialTheme.typography.bodyMedium)
            is BackendReachability.Reachable -> StatusPill(
                stringResource(R.string.status_backend_reachable, state.status?.version.orEmpty().ifEmpty { "?" }),
                Tone.SAFE,
                icon = Icons.Rounded.CheckCircle,
                testTag = "backend_reachable",
            )
            is BackendReachability.Unreachable -> InfoBanner(
                text = stringResource(
                    if (reachability.hasCachedStatus) R.string.status_backend_unreachable_cached else R.string.status_backend_unreachable,
                    reachability.error.message,
                ),
                tone = Tone.CAUTION,
                testTag = "backend_unreachable",
            )
        }
        val status = state.status
        if (state.backendConfigured && status != null) {
            val provider = status.telephony.provider.ifEmpty { stringResource(R.string.common_unknown) }
            KeyValueRow(
                stringResource(R.string.status_provider_row),
                if (state.simulated) stringResource(R.string.status_provider_simulated, provider) else stringResource(R.string.status_provider_real, provider),
                testTag = "provider_row",
            )
            if (state.simulated) {
                StatusPill(stringResource(R.string.common_simulated), Tone.INFO, testTag = "simulated_label")
            }
            if (status.telephony.note.isNotBlank()) {
                Text(stringResource(R.string.status_provider_note, status.telephony.note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
            Text(
                stringResource(if (state.liveCallsSupported) R.string.status_live_calls_yes else R.string.status_live_calls_no),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("live_calls_note"),
            )
        }
        if (state.backendConfigured) {
            SecondaryButton(
                text = stringResource(if (state.refreshing) R.string.status_refreshing else R.string.status_refresh),
                onClick = actions.onRefresh,
                enabled = !state.refreshing,
                icon = Icons.Rounded.Refresh,
                testTag = "refresh_status",
            )
        }
    }
}

@Composable
private fun ForwardingCard(state: ProtectionUiState, actions: ProtectionActions) {
    SpartaCard(modifier = Modifier.testTag("forwarding_card")) {
        SectionTitle(stringResource(R.string.status_forwarding_title))
        val number = state.forwardingNumber
        val safe = ForwardingCodes.isSafeNumber(number)
        when {
            !state.backendConfigured || number.isNullOrBlank() -> Text(stringResource(R.string.status_forwarding_not_available), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("forwarding_unavailable"))
            else -> {
                Text(stringResource(R.string.status_forwarding_available, number), style = MaterialTheme.typography.bodyMedium)
                Text(
                    stringResource(if (state.forwardingConfirmed) R.string.status_forwarding_confirmed else R.string.status_forwarding_unknown),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.testTag("forwarding_status_text"),
                )
                // Android cannot read forwarding state, so this is the owner's own note, labelled as such above.
                CheckRow(
                    title = stringResource(R.string.forwarding_confirm_label),
                    checked = state.forwardingConfirmed,
                    onCheckedChange = actions.onConfirmForwarding,
                    testTag = "forwarding_confirm",
                )
                if (safe) SecondaryButton(stringResource(R.string.status_forwarding_open_helper), actions.onOpenForwardingHelper, testTag = "open_forwarding_helper")
            }
        }
    }
}

@Composable
private fun LastDecisionCard(state: ProtectionUiState) {
    SpartaCard(modifier = Modifier.testTag("last_decision_card")) {
        SectionTitle(stringResource(R.string.status_last_decision_title))
        val event = state.lastDecision
        if (event == null) {
            Text(stringResource(R.string.status_last_decision_none), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("last_decision_none"))
        } else {
            Text(
                stringResource(R.string.status_last_decision_row, stringResource(ScreeningText.action(event.decision)), stringResource(ScreeningText.reasonLabel(event.reason))),
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.testTag("last_decision_text"),
            )
            Text(event.numberDisplay, style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
            Text(
                stringResource(R.string.status_last_decision_latency, event.decisionLatencyMs),
                style = MaterialTheme.typography.bodySmall,
                color = SpartaTheme.extras.textSecondary,
            )
        }
        if (state.pendingUploads > 0) {
            Text(pluralStringResource(R.plurals.status_pending_uploads, state.pendingUploads, state.pendingUploads), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
    }
}

@Composable
private fun PolicyCard(state: ProtectionUiState) {
    SpartaCard(modifier = Modifier.testTag("policy_card")) {
        SectionTitle(stringResource(R.string.status_policy_title))
        Text(
            stringResource(
                when (state.policy.unknownCallerBehavior) {
                    UnknownCallerBehavior.SCREEN -> R.string.status_policy_screen
                    UnknownCallerBehavior.SILENCE -> R.string.status_policy_silence
                    UnknownCallerBehavior.ALLOW -> R.string.status_policy_allow
                },
            ),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun LimitsCard() {
    SpartaCard(modifier = Modifier.testTag("limits_card")) {
        SectionTitle(stringResource(R.string.status_limits_title))
        Text(stringResource(R.string.status_can_title), style = MaterialTheme.typography.titleSmall)
        listOf(R.string.status_can_1, R.string.status_can_2, R.string.status_can_3).forEach {
            Text("• " + stringResource(it), style = MaterialTheme.typography.bodyMedium)
        }
        Text(stringResource(R.string.status_cannot_title), style = MaterialTheme.typography.titleSmall)
        listOf(R.string.status_cannot_1, R.string.status_cannot_2, R.string.status_cannot_3).forEach {
            Text("• " + stringResource(it), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private fun openDefaultApps(context: android.content.Context) {
    runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        .onFailure { runCatching { context.startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } }
}

private fun openNotificationSettings(context: android.content.Context) {
    val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}

/** Opens the dialer with [code] pre-filled. The owner reviews it and presses call: the app never dials by itself. */
internal fun openDialer(context: android.content.Context, code: String) {
    val intent = Intent(Intent.ACTION_DIAL, ("tel:" + Uri.encode(code)).toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}
