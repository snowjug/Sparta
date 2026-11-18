package io.github.snowjug.sparta.ui.privacy

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.data.prefs.ThemeMode
import io.github.snowjug.sparta.data.repo.ListEntry
import io.github.snowjug.sparta.platform.AndroidPermissionChecker
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.ui.components.ChoiceGroup
import io.github.snowjug.sparta.ui.components.DestructiveButton
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.ScreenTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SwitchRow
import io.github.snowjug.sparta.ui.components.TimeStepperRow
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.onboarding.ConnectionUi
import io.github.snowjug.sparta.ui.theme.SpartaTheme

enum class PrivacyConfirm { DELETE_ALL, DELETE_LOCAL, DISCONNECT }

data class PrivacyActions(
    val onUnknownBehavior: (UnknownCallerBehavior) -> Unit = {},
    val onTrustedBehavior: (TrustedContactBehavior) -> Unit = {},
    val onStrictness: (Strictness) -> Unit = {},
    val onContactsToggle: (Boolean) -> Unit = {},
    val onOpenAppSettings: () -> Unit = {},
    val onRemoveEntry: (ListEntry) -> Unit = {},
    val onNotifyEscalations: (Boolean) -> Unit = {},
    val onNotifyScreening: (Boolean) -> Unit = {},
    val onNotifyHighRisk: (Boolean) -> Unit = {},
    val onIncludeLines: (Boolean) -> Unit = {},
    val onQuietHours: (Boolean) -> Unit = {},
    val onQuietStart: (Int) -> Unit = {},
    val onQuietEnd: (Int) -> Unit = {},
    val onAllowNotifications: () -> Unit = {},
    val onOpenNotificationSettings: () -> Unit = {},
    val onStoreTranscripts: (Boolean) -> Unit = {},
    val onRetentionDays: (Int) -> Unit = {},
    val onStoreFullNumber: (Boolean) -> Unit = {},
    val onDeleteAll: () -> Unit = {},
    val onDeleteLocal: () -> Unit = {},
    val onTheme: (ThemeMode) -> Unit = {},
    val onMotion: (MotionPreference) -> Unit = {},
    val onBackgroundSync: (Boolean) -> Unit = {},
    val onUrlChange: (String) -> Unit = {},
    val onTestConnection: () -> Unit = {},
    val onUseBackend: () -> Unit = {},
    val onDisconnect: () -> Unit = {},
    val onDismissMessage: () -> Unit = {},
)

private fun Activity?.shouldShowRationale(permission: AppPermission): Boolean {
    val name = AndroidPermissionChecker.manifestName(permission) ?: return false
    return this != null && ActivityCompat.shouldShowRequestPermissionRationale(this, name)
}

@Composable
fun PrivacyScreen(
    modifier: Modifier = Modifier,
    viewModel: PrivacyViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val lifecycleOwner = LocalLifecycleOwner.current

    val notificationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.onNotificationsResult(granted, activity.shouldShowRationale(AppPermission.NOTIFICATIONS))
    }
    val contactsLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.onContactsResult(granted, activity.shouldShowRationale(AppPermission.CONTACTS))
    }
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            viewModel.onResume(
                notificationsRationale = activity.shouldShowRationale(AppPermission.NOTIFICATIONS),
                contactsRationale = activity.shouldShowRationale(AppPermission.CONTACTS),
            )
        }
    }

    PrivacyContent(
        state = state,
        modifier = modifier,
        actions = PrivacyActions(
            onUnknownBehavior = viewModel::setUnknownBehavior,
            onTrustedBehavior = viewModel::setTrustedBehavior,
            onStrictness = viewModel::setStrictness,
            onContactsToggle = { on ->
                if (!on) {
                    viewModel.disableContacts()
                } else if (!viewModel.enableContactsIfGranted()) {
                    // The explanation is already on screen above the switch; only now does the system prompt appear.
                    AndroidPermissionChecker.manifestName(AppPermission.CONTACTS)?.let(contactsLauncher::launch)
                }
            },
            onOpenAppSettings = {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(intent) }
            },
            onRemoveEntry = viewModel::removeEntry,
            onNotifyEscalations = viewModel::setNotifyEscalations,
            onNotifyScreening = viewModel::setNotifyScreening,
            onNotifyHighRisk = viewModel::setNotifyHighRisk,
            onIncludeLines = viewModel::setIncludeLines,
            onQuietHours = viewModel::setQuietHours,
            onQuietStart = viewModel::shiftQuietStart,
            onQuietEnd = viewModel::shiftQuietEnd,
            onAllowNotifications = { AndroidPermissionChecker.manifestName(AppPermission.NOTIFICATIONS)?.let(notificationLauncher::launch) },
            onOpenNotificationSettings = {
                val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(intent) }
            },
            onStoreTranscripts = viewModel::setStoreTranscripts,
            onRetentionDays = viewModel::setTranscriptRetentionDays,
            onStoreFullNumber = viewModel::setStoreFullNumber,
            onDeleteAll = viewModel::deleteAllCallData,
            onDeleteLocal = viewModel::deleteLocalHistory,
            onTheme = viewModel::setTheme,
            onMotion = viewModel::setMotion,
            onBackgroundSync = viewModel::setBackgroundSync,
            onUrlChange = viewModel::onUrlChange,
            onTestConnection = viewModel::testConnection,
            onUseBackend = viewModel::useBackend,
            onDisconnect = viewModel::disconnect,
            onDismissMessage = viewModel::dismissMessage,
        ),
    )
}

@Composable
fun PrivacyContent(
    state: PrivacyUiState,
    actions: PrivacyActions,
    modifier: Modifier = Modifier,
) {
    var confirm by rememberSaveable { mutableStateOf<PrivacyConfirm?>(null) }
    LazyColumn(
        modifier = modifier.fillMaxSize().testTag("privacy_screen"),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        item(key = "content") {
            Column(
                modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                ScreenTitle(stringResource(R.string.privacy_title), subtitle = stringResource(R.string.privacy_subtitle))
                MessageBanner(state.message, actions.onDismissMessage)
                ScreeningCard(state, actions)
                ContactsCard(state, actions)
                ListsCard(state, actions)
                NotificationsCard(state, actions)
                DataCard(state, actions) { confirm = it }
                AppearanceCard(state, actions)
                BackendCard(state, actions) { confirm = PrivacyConfirm.DISCONNECT }
                SafetyCard(state)
                PermissionsCard()
            }
        }
    }

    confirm?.let { kind ->
        val (title, body, onConfirm) = when (kind) {
            PrivacyConfirm.DELETE_ALL -> Triple(R.string.privacy_delete_all_title, R.string.privacy_delete_all_body, actions.onDeleteAll)
            PrivacyConfirm.DELETE_LOCAL -> Triple(R.string.privacy_delete_local_title, R.string.privacy_delete_local_body, actions.onDeleteLocal)
            PrivacyConfirm.DISCONNECT -> Triple(R.string.privacy_disconnect_title, R.string.privacy_disconnect_body, actions.onDisconnect)
        }
        AlertDialog(
            onDismissRequest = { confirm = null },
            modifier = Modifier.testTag("privacy_confirm_dialog"),
            title = { Text(stringResource(title)) },
            text = { Text(stringResource(body)) },
            confirmButton = {
                DestructiveButton(
                    text = stringResource(R.string.common_confirm),
                    onClick = {
                        confirm = null
                        onConfirm()
                    },
                    testTag = "privacy_confirm",
                )
            },
            dismissButton = { QuietButton(stringResource(R.string.common_cancel), { confirm = null }, testTag = "privacy_confirm_cancel") },
        )
    }
}

@Composable
private fun ScreeningCard(state: PrivacyUiState, actions: PrivacyActions) {
    val s = state.settings
    SpartaCard(modifier = Modifier.testTag("privacy_screening")) {
        SectionTitle(stringResource(R.string.privacy_screening_title))
        Text(stringResource(R.string.privacy_screening_body), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        Text(stringResource(R.string.privacy_unknown_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = listOf(
                UnknownCallerBehavior.SCREEN to stringResource(R.string.privacy_unknown_screen),
                UnknownCallerBehavior.SILENCE to stringResource(R.string.privacy_unknown_silence),
                UnknownCallerBehavior.ALLOW to stringResource(R.string.privacy_unknown_allow),
            ),
            descriptions = mapOf(
                UnknownCallerBehavior.SCREEN to stringResource(R.string.privacy_unknown_screen_d),
                UnknownCallerBehavior.SILENCE to stringResource(R.string.privacy_unknown_silence_d),
                UnknownCallerBehavior.ALLOW to stringResource(R.string.privacy_unknown_allow_d),
            ),
            selected = s.unknownCallerBehavior,
            onSelect = actions.onUnknownBehavior,
            testTagPrefix = "unknown",
        )
        Text(stringResource(R.string.privacy_trusted_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = listOf(
                TrustedContactBehavior.ALLOW_DIRECTLY to stringResource(R.string.privacy_trusted_allow),
                TrustedContactBehavior.SCREEN_ANYWAY to stringResource(R.string.privacy_trusted_screen),
            ),
            selected = s.trustedContactBehavior,
            onSelect = actions.onTrustedBehavior,
            testTagPrefix = "trusted",
        )
        Text(stringResource(R.string.privacy_strictness_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = listOf(
                Strictness.RELAXED to stringResource(R.string.privacy_strict_relaxed),
                Strictness.BALANCED to stringResource(R.string.privacy_strict_balanced),
                Strictness.STRICT to stringResource(R.string.privacy_strict_strict),
            ),
            descriptions = mapOf(
                Strictness.RELAXED to stringResource(R.string.privacy_strict_relaxed_d),
                Strictness.BALANCED to stringResource(R.string.privacy_strict_balanced_d),
                Strictness.STRICT to stringResource(R.string.privacy_strict_strict_d),
            ),
            selected = s.strictness,
            onSelect = actions.onStrictness,
            testTagPrefix = "strictness",
        )
        if (!state.backendConfigured) {
            Text(stringResource(R.string.privacy_local_only_note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, modifier = Modifier.testTag("privacy_local_note"))
        }
    }
}

@Composable
private fun ContactsCard(state: PrivacyUiState, actions: PrivacyActions) {
    val s = state.settings
    SpartaCard(modifier = Modifier.testTag("privacy_contacts")) {
        SectionTitle(stringResource(R.string.privacy_contacts_title))
        Text(stringResource(R.string.onb_perm_contacts_why), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("contacts_rationale"))
        val blocked = state.contacts == PermissionUiState.DENIED_PERMANENTLY
        SwitchRow(
            title = stringResource(R.string.onb_perm_contacts_switch),
            checked = s.useContactsAsKnown,
            onCheckedChange = actions.onContactsToggle,
            enabled = !blocked,
            testTag = "contacts_switch",
        )
        when (state.contacts) {
            PermissionUiState.DENIED_CAN_ASK_AGAIN -> Text(stringResource(R.string.onb_perm_contacts_denied), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("contacts_denied"))
            PermissionUiState.DENIED_PERMANENTLY -> {
                Text(stringResource(R.string.onb_perm_contacts_blocked), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("contacts_blocked"))
                SecondaryButton(stringResource(R.string.common_open_settings), actions.onOpenAppSettings, testTag = "contacts_open_settings")
            }
            else -> Unit
        }
    }
}

@Composable
private fun ListsCard(state: PrivacyUiState, actions: PrivacyActions) {
    SpartaCard(modifier = Modifier.testTag("privacy_lists")) {
        SectionTitle(stringResource(R.string.privacy_lists_title))
        Text(stringResource(R.string.privacy_lists_body), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        Text(stringResource(R.string.privacy_blocked_header, state.blocked.size), style = MaterialTheme.typography.titleSmall)
        if (state.blocked.isEmpty()) Text(stringResource(R.string.common_none), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("blocked_none"))
        state.blocked.forEach { ListEntryRow(it, "blocked", actions.onRemoveEntry) }
        Text(stringResource(R.string.privacy_trusted_header, state.trusted.size), style = MaterialTheme.typography.titleSmall)
        if (state.trusted.isEmpty()) Text(stringResource(R.string.common_none), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("trusted_none"))
        state.trusted.forEach { ListEntryRow(it, "trusted", actions.onRemoveEntry) }
    }
}

@Composable
private fun ListEntryRow(entry: ListEntry, prefix: String, onRemove: (ListEntry) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().testTag("${prefix}_entry_${entry.fingerprint.take(8)}"),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(entry.display.ifBlank { stringResource(R.string.caller_private) }, style = MaterialTheme.typography.bodyLarge)
            val detail = listOfNotNull(
                entry.label,
                stringResource(if (entry.deviceOnly) R.string.privacy_entry_device else R.string.privacy_entry_backend),
            ).joinToString(" · ")
            Text(detail, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
        QuietButton(stringResource(R.string.common_remove), { onRemove(entry) }, testTag = "${prefix}_remove_${entry.fingerprint.take(8)}")
    }
}

@Composable
private fun NotificationsCard(state: PrivacyUiState, actions: PrivacyActions) {
    val s = state.settings
    val prefs = state.prefs
    SpartaCard(modifier = Modifier.testTag("privacy_notifications")) {
        SectionTitle(stringResource(R.string.privacy_notifications_title))
        when (state.notifications) {
            PermissionUiState.GRANTED, PermissionUiState.NOT_REQUIRED ->
                Text(stringResource(R.string.privacy_notifications_on), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("notifications_granted"))
            PermissionUiState.DENIED_PERMANENTLY -> {
                Text(stringResource(R.string.onb_perm_notifications_blocked), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("notifications_blocked"))
                SecondaryButton(stringResource(R.string.status_notifications_settings), actions.onOpenNotificationSettings, testTag = "notifications_open_settings")
            }
            else -> {
                Text(stringResource(R.string.onb_perm_notifications_why), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("notifications_rationale"))
                PrimaryButton(stringResource(R.string.onb_perm_notifications_allow), actions.onAllowNotifications, testTag = "notifications_allow")
            }
        }
        SwitchRow(stringResource(R.string.privacy_notify_escalations), s.notifyEscalations, actions.onNotifyEscalations, subtitle = stringResource(R.string.privacy_notify_escalations_d), testTag = "notify_escalations")
        SwitchRow(stringResource(R.string.privacy_notify_screening), s.notifyScreening, actions.onNotifyScreening, subtitle = stringResource(R.string.privacy_notify_screening_d), testTag = "notify_screening")
        if (state.backendConfigured && prefs != null) {
            SwitchRow(stringResource(R.string.privacy_notify_high_risk), prefs.notifyOnHighRisk, actions.onNotifyHighRisk, subtitle = stringResource(R.string.privacy_notify_high_risk_d), testTag = "notify_high_risk")
            SwitchRow(stringResource(R.string.privacy_include_lines), prefs.includeTranscriptLines, actions.onIncludeLines, subtitle = stringResource(R.string.privacy_include_lines_d), testTag = "include_lines")
            SwitchRow(stringResource(R.string.privacy_quiet_hours), state.quietHoursOn, actions.onQuietHours, subtitle = stringResource(R.string.privacy_quiet_hours_d), testTag = "quiet_hours")
            if (state.quietHoursOn) {
                TimeStepperRow(stringResource(R.string.privacy_quiet_from), prefs.quietHoursStart.orEmpty(), { actions.onQuietStart(-QUIET_STEP) }, { actions.onQuietStart(QUIET_STEP) }, testTag = "quiet_start")
                TimeStepperRow(stringResource(R.string.privacy_quiet_to), prefs.quietHoursEnd.orEmpty(), { actions.onQuietEnd(-QUIET_STEP) }, { actions.onQuietEnd(QUIET_STEP) }, testTag = "quiet_end")
            }
        } else {
            Text(stringResource(R.string.privacy_notifications_backend_note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
        Text(stringResource(R.string.privacy_notifications_limit), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, modifier = Modifier.testTag("notifications_limit"))
    }
}

private const val QUIET_STEP = 30

@Composable
private fun DataCard(state: PrivacyUiState, actions: PrivacyActions, onConfirm: (PrivacyConfirm) -> Unit) {
    val prefs = state.prefs
    SpartaCard(modifier = Modifier.testTag("privacy_data")) {
        SectionTitle(stringResource(R.string.privacy_data_title))
        InfoBanner(stringResource(R.string.privacy_never_record), Tone.INFO, testTag = "privacy_never_record")
        if (state.backendConfigured && prefs != null) {
            SwitchRow(stringResource(R.string.privacy_store_transcripts), prefs.storeTranscripts, actions.onStoreTranscripts, subtitle = stringResource(R.string.privacy_store_transcripts_d), testTag = "store_transcripts")
            if (prefs.storeTranscripts) {
                Text(stringResource(R.string.privacy_retention_title), style = MaterialTheme.typography.titleSmall)
                val current = prefs.transcriptRetentionDays
                // A value set elsewhere (for example 14 days on the web) is shown as it is, never rounded to a preset.
                val choices = (RETENTION_CHOICES + current).distinct().sorted()
                ChoiceGroup(
                    options = choices.map { it to pluralStringResource(R.plurals.privacy_retention_days, it, it) },
                    selected = current,
                    onSelect = actions.onRetentionDays,
                    testTagPrefix = "retention",
                )
            }
            SwitchRow(stringResource(R.string.privacy_store_number), prefs.storeFullCallerNumber, actions.onStoreFullNumber, subtitle = stringResource(R.string.privacy_store_number_d), testTag = "store_number")
        }
        SecondaryButton(
            text = stringResource(R.string.privacy_delete_local),
            onClick = { onConfirm(PrivacyConfirm.DELETE_LOCAL) },
            icon = Icons.Rounded.Delete,
            modifier = Modifier.fillMaxWidth(),
            testTag = "delete_local",
        )
        DestructiveButton(
            text = stringResource(if (state.deleting) R.string.owner_ctl_working else R.string.privacy_delete_all),
            onClick = { onConfirm(PrivacyConfirm.DELETE_ALL) },
            enabled = !state.deleting,
            icon = Icons.Rounded.Delete,
            modifier = Modifier.fillMaxWidth(),
            testTag = "delete_all",
        )
    }
}

private val RETENTION_CHOICES = listOf(1, 7, 30, 90)

@Composable
private fun AppearanceCard(state: PrivacyUiState, actions: PrivacyActions) {
    val s = state.settings
    SpartaCard(modifier = Modifier.testTag("privacy_appearance")) {
        SectionTitle(stringResource(R.string.privacy_appearance_title))
        ChoiceGroup(
            options = listOf(
                ThemeMode.DARK to stringResource(R.string.theme_dark),
                ThemeMode.LIGHT to stringResource(R.string.theme_light),
                ThemeMode.SYSTEM to stringResource(R.string.theme_system),
            ),
            selected = s.themeMode,
            onSelect = actions.onTheme,
            testTagPrefix = "theme",
        )
        Text(stringResource(R.string.privacy_motion_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = listOf(
                MotionPreference.FOLLOW_SYSTEM to stringResource(R.string.motion_system),
                MotionPreference.REDUCE to stringResource(R.string.motion_reduce),
                MotionPreference.FULL to stringResource(R.string.motion_full),
            ),
            selected = s.motionPreference,
            onSelect = actions.onMotion,
            testTagPrefix = "motion",
        )
        SwitchRow(
            title = stringResource(R.string.privacy_background_sync),
            subtitle = stringResource(R.string.privacy_background_sync_d),
            checked = s.backgroundSyncEnabled,
            onCheckedChange = actions.onBackgroundSync,
            testTag = "background_sync",
        )
    }
}

@Composable
private fun BackendCard(state: PrivacyUiState, actions: PrivacyActions, onDisconnect: () -> Unit) {
    SpartaCard(modifier = Modifier.testTag("privacy_backend")) {
        SectionTitle(stringResource(R.string.privacy_backend_title))
        if (state.backendConfigured) {
            KeyValueRow(stringResource(R.string.privacy_backend_address), state.settings.backendUrl, testTag = "backend_address")
        } else {
            Text(stringResource(R.string.status_backend_not_configured), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("backend_none"))
        }
        OutlinedTextField(
            value = state.urlInput,
            onValueChange = actions.onUrlChange,
            label = { Text(stringResource(R.string.onb_backend_url_label)) },
            placeholder = { Text(stringResource(R.string.onb_backend_url_hint)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().testTag("backend_url"),
        )
        ConnectionResult(state.connection)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            SecondaryButton(
                text = stringResource(if (state.connection == ConnectionUi.Testing) R.string.onb_backend_testing else R.string.onb_backend_test),
                onClick = actions.onTestConnection,
                enabled = state.connection != ConnectionUi.Testing && state.urlInput.isNotBlank(),
                testTag = "backend_test",
            )
            PrimaryButton(
                text = stringResource(R.string.onb_backend_use),
                onClick = actions.onUseBackend,
                enabled = state.connection is ConnectionUi.Success,
                testTag = "backend_use",
            )
        }
        if (state.backendConfigured) {
            QuietButton(stringResource(R.string.privacy_disconnect), onDisconnect, testTag = "backend_disconnect")
        }
        Text(stringResource(R.string.onb_backend_release_https), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
    }
}

@Composable
fun ConnectionResult(connection: ConnectionUi) {
    when (connection) {
        ConnectionUi.Idle, ConnectionUi.Testing -> Unit
        is ConnectionUi.Success -> Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.testTag("backend_result_success")) {
            InfoBanner(
                text = stringResource(R.string.onb_backend_connected, connection.version.ifEmpty { "?" }, connection.provider.ifEmpty { "?" }),
                tone = Tone.SAFE,
            )
            if (connection.simulated) InfoBanner(stringResource(R.string.onb_backend_connected_simulated), Tone.INFO, testTag = "backend_result_simulated")
            if (connection.devBanner) InfoBanner(stringResource(R.string.common_dev_identity_body), Tone.CAUTION, title = stringResource(R.string.common_dev_identity_title), testTag = "backend_result_dev")
        }
        is ConnectionUi.Failure -> InfoBanner(connection.error.message, Tone.CAUTION, testTag = "backend_result_failure")
        is ConnectionUi.InvalidUrl -> InfoBanner(stringResource(urlProblemRes(connection.problem)), Tone.CAUTION, testTag = "backend_result_invalid")
    }
}

fun urlProblemRes(problem: BackendUrlProblem): Int = when (problem) {
    BackendUrlProblem.EMPTY -> R.string.url_problem_empty
    BackendUrlProblem.MALFORMED -> R.string.url_problem_malformed
    BackendUrlProblem.UNSUPPORTED_SCHEME -> R.string.url_problem_scheme
    BackendUrlProblem.HTTPS_REQUIRED -> R.string.url_problem_https
    BackendUrlProblem.CREDENTIALS_NOT_ALLOWED -> R.string.url_problem_credentials
    BackendUrlProblem.QUERY_OR_FRAGMENT_NOT_ALLOWED -> R.string.url_problem_query
}

@Composable
private fun SafetyCard(state: PrivacyUiState) {
    SpartaCard(modifier = Modifier.testTag("privacy_safety")) {
        SectionTitle(stringResource(R.string.privacy_safety_title))
        Text(stringResource(R.string.privacy_safety_body), style = MaterialTheme.typography.bodyMedium)
        val policy = state.policy
        if (policy != null && policy.protectedInformation.isNotEmpty()) {
            Text(stringResource(R.string.privacy_safety_protected), style = MaterialTheme.typography.titleSmall)
            policy.protectedInformation.forEach { Text("• ${it.label}", style = MaterialTheme.typography.bodyMedium) }
            Text(stringResource(R.string.privacy_safety_policy_version, policy.version), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        } else {
            Text(stringResource(R.string.privacy_safety_needs_backend), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, modifier = Modifier.testTag("safety_needs_backend"))
        }
    }
}

@Composable
private fun PermissionsCard() {
    SpartaCard(modifier = Modifier.testTag("privacy_permissions")) {
        SectionTitle(stringResource(R.string.privacy_permissions_title))
        Text(stringResource(R.string.privacy_permissions_body), style = MaterialTheme.typography.bodyMedium)
        listOf(
            R.string.perm_role to R.string.perm_role_why,
            R.string.perm_notifications to R.string.perm_notifications_why,
            R.string.perm_contacts to R.string.perm_contacts_why,
            R.string.perm_internet to R.string.perm_internet_why,
        ).forEach { (name, why) ->
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(name), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(why), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
        }
        Text(stringResource(R.string.perm_never), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("permissions_never"))
    }
}
