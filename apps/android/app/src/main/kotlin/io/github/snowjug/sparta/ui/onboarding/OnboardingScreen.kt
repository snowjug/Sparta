package io.github.snowjug.sparta.ui.onboarding

import android.app.Activity
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import io.github.snowjug.sparta.BuildConfig
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.platform.AndroidPermissionChecker
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaLogo
import io.github.snowjug.sparta.ui.components.SwitchRow
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.asHeading
import io.github.snowjug.sparta.ui.privacy.ConnectionResult
import io.github.snowjug.sparta.ui.status.ForwardingDialog
import io.github.snowjug.sparta.ui.status.openDialer
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class OnboardingActions(
    val onUrlChange: (String) -> Unit = {},
    val onTestConnection: () -> Unit = {},
    val onUseBackend: () -> Unit = {},
    val onNext: () -> Unit = {},
    val onBack: () -> Unit = {},
    val onChooseRole: () -> Unit = {},
    val onAllowNotifications: () -> Unit = {},
    val onOpenNotificationSettings: () -> Unit = {},
    val onContactsToggle: (Boolean) -> Unit = {},
    val onOpenAppSettings: () -> Unit = {},
    val onOpenForwarding: () -> Unit = {},
    val onFinish: () -> Unit = {},
)

private fun Activity?.shouldShowRationale(permission: AppPermission): Boolean {
    val name = AndroidPermissionChecker.manifestName(permission) ?: return false
    return this != null && ActivityCompat.shouldShowRequestPermissionRationale(this, name)
}

@Composable
fun OnboardingScreen(
    onFinished: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: OnboardingViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var showForwarding by rememberSaveable { mutableStateOf(false) }

    val roleLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        viewModel.onRoleResult(result.resultCode == Activity.RESULT_OK)
    }
    val notificationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.onNotificationsResult(granted, activity.shouldShowRationale(AppPermission.NOTIFICATIONS))
    }
    val contactsLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.onContactsResult(granted, activity.shouldShowRationale(AppPermission.CONTACTS))
    }
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            viewModel.refreshPermissions(
                notificationsRationale = activity.shouldShowRationale(AppPermission.NOTIFICATIONS),
                contactsRationale = activity.shouldShowRationale(AppPermission.CONTACTS),
            )
        }
    }
    LaunchedEffect(state.finished) { if (state.finished) onFinished() }

    OnboardingContent(
        state = state,
        isDebugBuild = BuildConfig.DEBUG,
        modifier = modifier,
        actions = OnboardingActions(
            onUrlChange = viewModel::onUrlChange,
            onTestConnection = viewModel::testConnection,
            onUseBackend = viewModel::useBackend,
            onNext = viewModel::next,
            onBack = viewModel::back,
            onChooseRole = { viewModel.roleRequestIntent()?.let(roleLauncher::launch) },
            onAllowNotifications = { AndroidPermissionChecker.manifestName(AppPermission.NOTIFICATIONS)?.let(notificationLauncher::launch) },
            onOpenNotificationSettings = {
                val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(intent) }
            },
            onContactsToggle = { on ->
                if (!on) {
                    viewModel.disableContactsOption()
                } else {
                    // The explanation is on screen right above the switch; only now does the system prompt appear.
                    AndroidPermissionChecker.manifestName(AppPermission.CONTACTS)?.let(contactsLauncher::launch)
                }
            },
            onOpenAppSettings = {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(intent) }
            },
            onOpenForwarding = { showForwarding = true },
            onFinish = viewModel::finish,
        ),
    )

    if (showForwarding) {
        ForwardingDialog(
            number = state.forwardingNumber,
            onDismiss = { showForwarding = false },
            onOpenDialer = { code -> openDialer(context, code) },
        )
    }
}

@Composable
fun OnboardingContent(
    state: OnboardingUiState,
    actions: OnboardingActions,
    modifier: Modifier = Modifier,
    isDebugBuild: Boolean = false,
) {
    Surface(modifier = modifier.fillMaxSize().testTag("onboarding_screen"), color = MaterialTheme.colorScheme.background) {
        Column(modifier = Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
            Column(
                modifier = Modifier
                    .weight(1f)
                    .widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                StepHeader(state.step)
                when (state.step) {
                    OnboardingStep.WELCOME -> WelcomeStep()
                    OnboardingStep.BACKEND -> BackendStep(state, actions, isDebugBuild)
                    OnboardingStep.ROLE -> RoleStep(state, actions)
                    OnboardingStep.PERMISSIONS -> PermissionsStep(state, actions)
                    OnboardingStep.FORWARDING -> ForwardingStep(state, actions)
                }
            }
            BottomBar(state, actions)
        }
    }
}

@Composable
private fun StepHeader(step: OnboardingStep) {
    val label = stringResource(R.string.onb_step_of, step.number, OnboardingStep.count)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.labelLarge,
            color = SpartaTheme.extras.textSecondary,
            modifier = Modifier.testTag("onboarding_step_label"),
        )
        LinearProgressIndicator(
            progress = { step.number.toFloat() / OnboardingStep.count },
            modifier = Modifier.fillMaxWidth().semantics { contentDescription = label }.testTag("onboarding_progress"),
            color = SpartaTheme.extras.accent,
            trackColor = SpartaTheme.extras.surface2,
        )
    }
}

@Composable
private fun WelcomeStep() {
    Column(modifier = Modifier.testTag("onboarding_step_welcome"), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            SpartaLogo(size = 64.dp)
            Column {
                Text(stringResource(R.string.app_name), style = MaterialTheme.typography.displayLarge, modifier = Modifier.asHeading())
            }
        }
        Text(stringResource(R.string.onb_welcome_title), style = MaterialTheme.typography.headlineSmall)
        Text(stringResource(R.string.onb_welcome_body), style = MaterialTheme.typography.bodyLarge)
        SpartaCard {
            SectionTitle(stringResource(R.string.onb_disclosure_title))
            Text(stringResource(R.string.onb_disclosure_body), style = MaterialTheme.typography.bodyMedium)
        }
        InfoBanner(stringResource(R.string.onb_welcome_limits), Tone.INFO, testTag = "onboarding_limits")
    }
}

@Composable
private fun BackendStep(state: OnboardingUiState, actions: OnboardingActions, isDebugBuild: Boolean) {
    Column(modifier = Modifier.testTag("onboarding_step_backend"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(R.string.onb_backend_title), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.asHeading())
        Text(stringResource(R.string.onb_backend_body), style = MaterialTheme.typography.bodyLarge)
        OutlinedTextField(
            value = state.urlInput,
            onValueChange = actions.onUrlChange,
            label = { Text(stringResource(R.string.onb_backend_url_label)) },
            placeholder = { Text(stringResource(R.string.onb_backend_url_hint)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().testTag("onboarding_backend_url"),
        )
        Text(
            stringResource(if (isDebugBuild) R.string.onb_backend_debug_hint else R.string.onb_backend_release_https),
            style = MaterialTheme.typography.bodySmall,
            color = SpartaTheme.extras.textSecondary,
            modifier = Modifier.testTag("onboarding_url_hint"),
        )
        SecondaryButton(
            text = stringResource(if (state.connection == ConnectionUi.Testing) R.string.onb_backend_testing else R.string.onb_backend_test),
            onClick = actions.onTestConnection,
            enabled = state.connection != ConnectionUi.Testing && state.urlInput.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
            testTag = "onboarding_test_connection",
        )
        ConnectionResult(state.connection)
        if (state.backendSaved) {
            InfoBanner(stringResource(R.string.onb_backend_saved), Tone.SAFE, testTag = "onboarding_backend_saved")
        } else {
            PrimaryButton(
                text = stringResource(R.string.onb_backend_use),
                onClick = actions.onUseBackend,
                enabled = state.connection is ConnectionUi.Success,
                modifier = Modifier.fillMaxWidth(),
                testTag = "onboarding_use_backend",
            )
            Text(stringResource(R.string.onb_backend_skipped_note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
    }
}

@Composable
private fun RoleStep(state: OnboardingUiState, actions: OnboardingActions) {
    Column(modifier = Modifier.testTag("onboarding_step_role"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(R.string.onb_role_title), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.asHeading())
        when (state.role.status) {
            RoleStatus.GRANTED -> InfoBanner(stringResource(R.string.onb_role_done), Tone.SAFE, testTag = "onboarding_role_done")
            RoleStatus.NOT_GRANTED -> {
                Text(stringResource(R.string.onb_role_body), style = MaterialTheme.typography.bodyLarge)
                PrimaryButton(
                    text = stringResource(R.string.onb_role_button),
                    onClick = actions.onChooseRole,
                    icon = Icons.Rounded.Shield,
                    modifier = Modifier.fillMaxWidth(),
                    testTag = "onboarding_choose_role",
                )
                if (state.role.requestDeclined) InfoBanner(stringResource(R.string.onb_role_declined), Tone.CAUTION, testTag = "onboarding_role_declined")
            }
            RoleStatus.UNSUPPORTED_API -> InfoBanner(
                title = stringResource(R.string.status_role_unsupported_title),
                text = stringResource(R.string.status_role_unsupported_body, state.device?.androidRelease.orEmpty().ifEmpty { "?" }, state.device?.apiLevel ?: 0),
                tone = Tone.INFO,
                testTag = "onboarding_role_unsupported",
            )
            RoleStatus.ROLE_UNAVAILABLE -> InfoBanner(
                title = stringResource(R.string.status_role_unavailable_title),
                text = stringResource(R.string.status_role_unavailable_body),
                tone = Tone.INFO,
                testTag = "onboarding_role_unavailable",
            )
        }
    }
}

@Composable
private fun PermissionsStep(state: OnboardingUiState, actions: OnboardingActions) {
    Column(modifier = Modifier.testTag("onboarding_step_permissions"), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.onb_perm_title), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.asHeading())
        Text(stringResource(R.string.onb_perm_body), style = MaterialTheme.typography.bodyLarge)

        SpartaCard(modifier = Modifier.testTag("onboarding_notifications_card")) {
            SectionTitle(stringResource(R.string.onb_perm_notifications_title))
            Text(stringResource(R.string.onb_perm_notifications_why), style = MaterialTheme.typography.bodyMedium)
            when (state.notifications) {
                PermissionUiState.GRANTED -> InfoBanner(stringResource(R.string.onb_perm_notifications_granted), Tone.SAFE, testTag = "onboarding_notifications_granted")
                PermissionUiState.NOT_REQUIRED -> Text(stringResource(R.string.onb_perm_notifications_not_required), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("onboarding_notifications_not_required"))
                PermissionUiState.DENIED_PERMANENTLY -> {
                    InfoBanner(stringResource(R.string.onb_perm_notifications_blocked), Tone.CAUTION, testTag = "onboarding_notifications_blocked")
                    SecondaryButton(stringResource(R.string.status_notifications_settings), actions.onOpenNotificationSettings, testTag = "onboarding_notification_settings")
                }
                PermissionUiState.DENIED_CAN_ASK_AGAIN -> {
                    InfoBanner(stringResource(R.string.onb_perm_notifications_denied), Tone.CAUTION, testTag = "onboarding_notifications_denied")
                    PrimaryButton(stringResource(R.string.onb_perm_notifications_allow), actions.onAllowNotifications, testTag = "onboarding_allow_notifications")
                }
                PermissionUiState.NOT_ASKED -> PrimaryButton(stringResource(R.string.onb_perm_notifications_allow), actions.onAllowNotifications, testTag = "onboarding_allow_notifications")
            }
        }

        SpartaCard(modifier = Modifier.testTag("onboarding_contacts_card")) {
            SectionTitle(stringResource(R.string.onb_perm_contacts_title))
            Text(stringResource(R.string.onb_perm_contacts_why), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("onboarding_contacts_rationale"))
            SwitchRow(
                title = stringResource(R.string.onb_perm_contacts_switch),
                checked = state.useContactsAsKnown,
                onCheckedChange = actions.onContactsToggle,
                enabled = state.contacts != PermissionUiState.DENIED_PERMANENTLY,
                testTag = "onboarding_contacts_switch",
            )
            when (state.contacts) {
                PermissionUiState.GRANTED -> if (state.useContactsAsKnown) {
                    Text(stringResource(R.string.onb_perm_contacts_granted), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, modifier = Modifier.testTag("onboarding_contacts_granted"))
                }
                PermissionUiState.DENIED_CAN_ASK_AGAIN -> Text(stringResource(R.string.onb_perm_contacts_denied), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("onboarding_contacts_denied"))
                PermissionUiState.DENIED_PERMANENTLY -> {
                    Text(stringResource(R.string.onb_perm_contacts_blocked), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("onboarding_contacts_blocked"))
                    SecondaryButton(stringResource(R.string.common_open_settings), actions.onOpenAppSettings, testTag = "onboarding_contacts_settings")
                }
                else -> Unit
            }
        }
    }
}

@Composable
private fun ForwardingStep(state: OnboardingUiState, actions: OnboardingActions) {
    Column(modifier = Modifier.testTag("onboarding_step_forwarding"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(R.string.onb_fwd_title), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.asHeading())
        Text(stringResource(R.string.onb_fwd_body), style = MaterialTheme.typography.bodyLarge)
        val number = state.forwardingNumber
        if (number.isNullOrBlank()) {
            InfoBanner(stringResource(R.string.onb_fwd_unavailable), Tone.INFO, testTag = "onboarding_forwarding_unavailable")
        } else {
            Text(stringResource(R.string.onb_fwd_available, number), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("onboarding_forwarding_number"))
            SecondaryButton(
                text = stringResource(R.string.onb_fwd_helper),
                onClick = actions.onOpenForwarding,
                modifier = Modifier.fillMaxWidth(),
                testTag = "onboarding_forwarding_helper",
            )
        }
        Text(stringResource(R.string.onb_done_note), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, textAlign = TextAlign.Start)
    }
}

@Composable
private fun BottomBar(state: OnboardingUiState, actions: OnboardingActions) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp).widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (state.canGoBack) {
                QuietButton(stringResource(R.string.onb_back), actions.onBack, testTag = "onboarding_back")
            } else {
                Row {}
            }
            if (state.isLastStep) {
                PrimaryButton(
                    text = stringResource(R.string.onb_finish),
                    onClick = actions.onFinish,
                    enabled = !state.finishing,
                    testTag = "onboarding_finish",
                )
            } else {
                val skip = state.step == OnboardingStep.BACKEND && !state.backendSaved
                PrimaryButton(
                    text = stringResource(if (skip) R.string.onb_skip_for_now else R.string.onb_next),
                    onClick = actions.onNext,
                    testTag = "onboarding_next",
                )
            }
        }
    }
}
