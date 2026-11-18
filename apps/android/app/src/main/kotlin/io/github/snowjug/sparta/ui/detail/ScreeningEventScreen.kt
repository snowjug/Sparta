package io.github.snowjug.sparta.ui.detail

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.ui.ScreeningText
import io.github.snowjug.sparta.ui.components.DestructiveButton
import io.github.snowjug.sparta.ui.components.DisabledReason
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.LoadingBlock
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaTopBar
import io.github.snowjug.sparta.ui.components.StatusPill
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.agoText
import io.github.snowjug.sparta.ui.components.callerDisplayText
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class ScreeningEventActions(
    val onBack: () -> Unit = {},
    val onBlock: () -> Unit = {},
    val onUnblock: () -> Unit = {},
    val onTrust: () -> Unit = {},
    val onUntrust: () -> Unit = {},
    val onDelete: () -> Unit = {},
    val onDismissMessage: () -> Unit = {},
)

@Composable
fun ScreeningEventRoute(
    eventId: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ScreeningEventViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(eventId) { viewModel.load(eventId) }
    LaunchedEffect(state.deleted) { if (state.deleted) onBack() }
    ScreeningEventContent(
        state = state,
        modifier = modifier,
        actions = ScreeningEventActions(
            onBack = onBack,
            onBlock = viewModel::block,
            onUnblock = viewModel::unblock,
            onTrust = viewModel::trust,
            onUntrust = viewModel::untrust,
            onDelete = viewModel::delete,
            onDismissMessage = viewModel::dismissMessage,
        ),
    )
}

@Composable
fun ScreeningEventContent(
    state: ScreeningEventUiState,
    actions: ScreeningEventActions,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().testTag("event_screen")) {
        SpartaTopBar(stringResource(R.string.event_title), actions.onBack)
        val event = state.event
        when {
            state.loading -> LoadingBlock()
            event == null -> EmptyState(
                title = stringResource(R.string.event_not_found),
                body = stringResource(R.string.event_no_content),
                testTag = "event_not_found",
            )
            else -> EventBody(state, event, actions)
        }
    }
}

@Composable
private fun EventBody(state: ScreeningEventUiState, event: ScreeningEventEntity, actions: ScreeningEventActions) {
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        item(key = "content") {
            Column(
                modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                MessageBanner(state.message, actions.onDismissMessage)
                SpartaCard(modifier = Modifier.testTag("event_decision")) {
                    Text(callerDisplayText(event.numberDisplay), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.testTag("event_number"))
                    StatusPill(stringResource(R.string.provider_android_screening), Tone.NEUTRAL, testTag = "provider_badge")
                    KeyValueRow(stringResource(R.string.event_row_decision), stringResource(ScreeningText.action(event.decision)), testTag = "event_action")
                    KeyValueRow(stringResource(R.string.event_row_reason), stringResource(ScreeningText.reasonLabel(event.reason)), testTag = "event_reason")
                    Text(
                        stringResource(ScreeningText.reasonExplanation(event.reason)),
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.testTag("event_explanation"),
                    )
                    KeyValueRow(stringResource(R.string.event_row_time), agoText(state.nowMs, event.occurredAtMs))
                    KeyValueRow(stringResource(R.string.event_row_verification), stringResource(verificationRes(event.verificationStatus)))
                    KeyValueRow(stringResource(R.string.event_row_direction), stringResource(directionRes(event.direction)))
                    KeyValueRow(
                        stringResource(R.string.event_row_latency),
                        if (event.deadlineMissed) stringResource(R.string.event_latency_missed, event.decisionLatencyMs) else stringResource(R.string.event_latency_value, event.decisionLatencyMs),
                        testTag = "event_latency",
                    )
                    KeyValueRow(stringResource(R.string.event_row_sync), stringResource(syncRes(event.uploadState)))
                }
                InfoBanner(stringResource(R.string.event_no_content), Tone.INFO, testTag = "event_no_content")
                SpartaCard(modifier = Modifier.testTag("event_actions")) {
                    val canUse = state.canUseLists
                    if (state.blockedEntry != null) {
                        SecondaryButton(stringResource(R.string.event_unblock_number), actions.onUnblock, Modifier.fillMaxWidth(), !state.busy, Icons.Rounded.Block, "event_unblock")
                    } else {
                        SecondaryButton(stringResource(R.string.event_block_number), actions.onBlock, Modifier.fillMaxWidth(), canUse && !state.busy, Icons.Rounded.Block, "event_block")
                    }
                    if (state.trustedEntry != null) {
                        SecondaryButton(stringResource(R.string.event_untrust_number), actions.onUntrust, Modifier.fillMaxWidth(), !state.busy, Icons.Rounded.VerifiedUser, "event_untrust")
                    } else {
                        SecondaryButton(stringResource(R.string.event_trust_number), actions.onTrust, Modifier.fillMaxWidth(), canUse && !state.busy, Icons.Rounded.VerifiedUser, "event_trust")
                    }
                    if (!canUse) DisabledReason(stringResource(R.string.event_no_fingerprint), testTag = "event_no_fingerprint")
                    DestructiveButton(stringResource(R.string.event_delete), { confirmDelete = true }, Modifier.fillMaxWidth(), !state.busy, Icons.Rounded.Delete, "event_delete")
                }
            }
        }
    }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            modifier = Modifier.testTag("event_delete_dialog"),
            title = { Text(stringResource(R.string.event_delete_title)) },
            text = { Text(stringResource(R.string.event_delete_body), color = SpartaTheme.extras.textSecondary) },
            confirmButton = {
                DestructiveButton(
                    text = stringResource(R.string.common_delete),
                    onClick = {
                        confirmDelete = false
                        actions.onDelete()
                    },
                    testTag = "event_delete_confirm",
                )
            },
            dismissButton = { QuietButton(stringResource(R.string.common_cancel), { confirmDelete = false }, testTag = "event_delete_cancel") },
        )
    }
}

private fun verificationRes(wire: String?): Int = when (wire) {
    "passed" -> R.string.event_verification_passed
    "failed" -> R.string.event_verification_failed
    "not_verified" -> R.string.event_verification_not_verified
    else -> R.string.event_verification_unknown
}

private fun directionRes(wire: String?): Int = when (wire) {
    "incoming" -> R.string.event_direction_incoming
    "outgoing" -> R.string.event_direction_outgoing
    else -> R.string.event_direction_unknown
}

private fun syncRes(state: String): Int = when (state) {
    UploadState.UPLOADED -> R.string.event_sync_uploaded
    UploadState.LOCAL_ONLY -> R.string.event_sync_local
    UploadState.FAILED -> R.string.event_sync_failed
    else -> R.string.event_sync_pending
}
