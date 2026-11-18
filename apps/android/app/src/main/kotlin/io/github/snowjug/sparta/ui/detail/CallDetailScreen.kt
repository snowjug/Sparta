package io.github.snowjug.sparta.ui.detail

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
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
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.ui.Formatters
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.components.CallFlags
import io.github.snowjug.sparta.ui.components.DestructiveButton
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.ErrorBlock
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.LoadingBlock
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.ProviderBadges
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.RiskMeter
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SignalRow
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaTopBar
import io.github.snowjug.sparta.ui.components.SwitchRow
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.TranscriptTurn
import io.github.snowjug.sparta.ui.components.agoText
import io.github.snowjug.sparta.ui.components.callerDisplayText
import io.github.snowjug.sparta.ui.incoming.AudioHonestyBanner
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.OwnerControlsPanel
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class CallDetailActions(
    val onBack: (() -> Unit)? = null,
    val onRefresh: () -> Unit = {},
    val onControl: (ControlId) -> Unit = {},
    val onFeedback: (FeedbackKind) -> Unit = {},
    val onToggleTranslations: () -> Unit = {},
    val onDelete: (DeleteKind) -> Unit = {},
    val onOpenLive: (String) -> Unit = {},
    val onDismissMessage: () -> Unit = {},
)

private val FEEDBACK_KINDS = listOf(
    FeedbackKind.CORRECT_CLASSIFICATION,
    FeedbackKind.WAS_SPAM,
    FeedbackKind.WAS_LEGITIMATE,
    FeedbackKind.WRONG_LANGUAGE,
    FeedbackKind.POOR_TRANSCRIPTION,
    FeedbackKind.WRONG_SUMMARY,
)

/** Stateful entry point. [embedded] is true inside the second pane of an expanded layout (no back button). */
@Composable
fun CallDetailRoute(
    callId: String,
    onBack: (() -> Unit)?,
    onOpenLive: (String) -> Unit,
    modifier: Modifier = Modifier,
    embedded: Boolean = false,
    viewModel: CallDetailViewModel = hiltViewModel(key = if (embedded) "pane" else null),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(callId) { viewModel.load(callId) }
    LaunchedEffect(state.deleted) { if (state.deleted) onBack?.invoke() }
    CallDetailContent(
        state = state,
        modifier = modifier,
        actions = CallDetailActions(
            onBack = if (embedded) null else onBack,
            onRefresh = viewModel::refresh,
            onControl = { control ->
                when (control) {
                    ControlId.TAKE_OVER -> viewModel.takeOver()
                    ControlId.CONTINUE -> viewModel.continueCall()
                    ControlId.END -> viewModel.endCall()
                    ControlId.BLOCK -> viewModel.block()
                    ControlId.TRUST -> viewModel.trust()
                }
            },
            onFeedback = viewModel::sendFeedback,
            onToggleTranslations = viewModel::toggleTranslations,
            onDelete = viewModel::delete,
            onOpenLive = onOpenLive,
            onDismissMessage = viewModel::dismissMessage,
        ),
    )
}

@Composable
fun CallDetailContent(
    state: CallDetailUiState,
    actions: CallDetailActions,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().testTag("call_detail_screen")) {
        SpartaTopBar(stringResource(R.string.detail_title), actions.onBack)
        val call = state.call
        val item = call?.toListItem() ?: state.cached
        when {
            item == null && state.loading -> LoadingBlock()
            item == null && state.notFound -> EmptyState(
                title = stringResource(R.string.detail_not_found_title),
                body = stringResource(R.string.detail_not_found_body),
                testTag = "detail_not_found",
            )
            item == null -> ErrorBlock(
                message = state.error?.message ?: stringResource(R.string.api_error_offline),
                traceId = state.error?.traceId,
                onRetry = actions.onRefresh,
                modifier = Modifier.padding(16.dp),
                testTag = "detail_error",
            )
            else -> DetailList(state, item, call, actions)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DetailList(state: CallDetailUiState, item: CallListItemDto, call: CallDetailDto?, actions: CallDetailActions) {
    var confirm by rememberSaveable { mutableStateOf<DeleteKind?>(null) }
    val screeningOnly = item.mode == CallMode.SCREENING_ONLY

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
                if (state.error != null) {
                    InfoBanner(stringResource(R.string.detail_offline_cached, state.error.message), Tone.CAUTION, testTag = "detail_cached_note")
                }
                HeaderCard(item, state.nowMs)
                if (call != null) AudioHonestyBanner(call)
                SummaryCard(item)
                if (!screeningOnly) RiskCard(item, call)
                if (call != null) {
                    ActionsCard(state, call, item, actions)
                    if (!screeningOnly) FeedbackCard(state, actions)
                }
                TranscriptCard(state, item, call, actions)
                if (call != null && call.timeline.isNotEmpty()) TimelineCard(call)
                if (call != null) DataCard(item, call) { confirm = it }
                if (call != null) TechnicalCard(call)
            }
        }
    }

    confirm?.let { kind ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            modifier = Modifier.testTag("delete_dialog"),
            title = { Text(stringResource(if (kind == DeleteKind.CALL) R.string.detail_delete_call_title else R.string.detail_delete_content_title)) },
            text = { Text(stringResource(if (kind == DeleteKind.CALL) R.string.detail_delete_call_body else R.string.detail_delete_content_body)) },
            confirmButton = {
                DestructiveButton(
                    text = stringResource(R.string.common_delete),
                    onClick = {
                        confirm = null
                        actions.onDelete(kind)
                    },
                    testTag = "delete_confirm",
                )
            },
            dismissButton = { QuietButton(stringResource(R.string.common_cancel), { confirm = null }, testTag = "delete_cancel") },
        )
    }
}

@Composable
private fun HeaderCard(item: CallListItemDto, nowMs: Long) {
    val startedAt = Timestamps.parseMs(item.startedAt)
    SpartaCard(modifier = Modifier.testTag("detail_header")) {
        Text(callerDisplayText(item.callerDisplay), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.testTag("detail_caller"))
        val claim = listOfNotNull(item.callerClaim.name, item.callerClaim.organization).joinToString(", ")
        if (claim.isNotBlank()) KeyValueRow(stringResource(R.string.detail_row_claim), claim)
        item.purpose?.takeIf { it.isNotBlank() }?.let { KeyValueRow(stringResource(R.string.detail_row_purpose), it) }
        CallFlags(item)
        ProviderBadges(item.provider, item.simulated, item.mode)
        KeyValueRow(stringResource(R.string.detail_row_status), stringResource(Labels.status(item.status)), testTag = "detail_status")
        KeyValueRow(stringResource(R.string.detail_row_started), agoText(nowMs, startedAt))
        if (item.durationMs != null) KeyValueRow(stringResource(R.string.detail_row_duration), Formatters.duration(item.durationMs))
        if (item.languages.isNotEmpty()) {
            KeyValueRow(stringResource(R.string.detail_row_languages), item.languages.joinToString(", ") { Labels.languageName(it) })
        }
    }
}

@Composable
private fun SummaryCard(item: CallListItemDto) {
    val summary = item.summaryText?.takeIf { it.isNotBlank() }
    val action = item.actionTaken?.takeIf { it.isNotBlank() }
    if (summary == null && action == null) return
    SpartaCard(modifier = Modifier.testTag("detail_summary")) {
        SectionTitle(stringResource(R.string.detail_section_summary))
        if (summary != null) Text(summary, style = MaterialTheme.typography.bodyLarge)
        if (action != null) KeyValueRow(stringResource(R.string.detail_row_action), action)
        KeyValueRow(stringResource(R.string.detail_row_category), stringResource(Labels.category(item.category)))
    }
}

@Composable
private fun RiskCard(item: CallListItemDto, call: CallDetailDto?) {
    SpartaCard(modifier = Modifier.testTag("detail_risk")) {
        SectionTitle(stringResource(R.string.detail_section_risk))
        if (item.riskLevel == RiskLevel.UNKNOWN) {
            Text(stringResource(R.string.risk_unknown), style = MaterialTheme.typography.bodyLarge)
        } else {
            RiskMeter(item.riskScore, item.confidence, item.riskLevel)
        }
        val risk = call?.risk
        if (risk != null) {
            Text(
                stringResource(R.string.detail_advice, stringResource(Labels.advice(risk.recommendedAction))),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("detail_advice"),
            )
            if (risk.signals.isEmpty()) {
                Text(stringResource(R.string.detail_no_signals), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
            }
            risk.signals.forEach { SignalRow(it) }
            if (risk.reasons.isNotEmpty()) {
                Text(stringResource(R.string.detail_reasons_title), style = MaterialTheme.typography.titleSmall)
                risk.reasons.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
            }
        }
    }
}

@Composable
private fun ActionsCard(state: CallDetailUiState, call: CallDetailDto, item: CallListItemDto, actions: CallDetailActions) {
    SpartaCard(modifier = Modifier.testTag("detail_actions")) {
        SectionTitle(stringResource(R.string.detail_section_actions))
        if (item.status == CallStatus.ACTIVE && item.mode != CallMode.SCREENING_ONLY) {
            PrimaryButton(
                text = stringResource(R.string.detail_open_live),
                onClick = { actions.onOpenLive(call.id) },
                icon = Icons.Rounded.GraphicEq,
                modifier = Modifier.fillMaxWidth(),
                testTag = "open_live",
            )
        }
        OwnerControlsPanel(
            controls = state.controls,
            busy = state.busy,
            blocked = state.blocked,
            trusted = state.trusted,
            onAction = actions.onControl,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FeedbackCard(state: CallDetailUiState, actions: CallDetailActions) {
    SpartaCard(modifier = Modifier.testTag("detail_feedback")) {
        SectionTitle(stringResource(R.string.detail_section_feedback))
        Text(stringResource(R.string.detail_feedback_intro), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            FEEDBACK_KINDS.forEach { kind ->
                val sent = kind in state.feedbackSent
                FilterChip(
                    selected = sent,
                    onClick = { actions.onFeedback(kind) },
                    enabled = !sent,
                    label = { Text(stringResource(Labels.feedback(kind)) + if (sent) " · " + stringResource(R.string.detail_feedback_sent) else "") },
                    leadingIcon = if (sent) {
                        { Icon(Icons.Rounded.CheckCircle, contentDescription = null) }
                    } else {
                        null
                    },
                    modifier = Modifier.testTag("feedback_${kind.wire}"),
                )
            }
        }
    }
}

@Composable
private fun TranscriptCard(state: CallDetailUiState, item: CallListItemDto, call: CallDetailDto?, actions: CallDetailActions) {
    SpartaCard(modifier = Modifier.testTag("detail_transcript")) {
        SectionTitle(stringResource(R.string.detail_section_transcript))
        val turns = call?.turns?.filter { it.isFinal }.orEmpty()
        when {
            item.mode == CallMode.SCREENING_ONLY -> Text(
                stringResource(R.string.detail_transcript_none_screening),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("transcript_none_screening"),
            )
            !item.hasContent -> Text(
                stringResource(R.string.detail_transcript_deleted),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("transcript_deleted"),
            )
            call == null -> LoadingBlock()
            turns.isEmpty() -> Text(
                stringResource(R.string.detail_transcript_empty),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.testTag("transcript_empty"),
            )
            else -> {
                if (turns.any { !it.translation.isNullOrBlank() && it.translation != it.text }) {
                    SwitchRow(
                        title = stringResource(R.string.detail_show_translations),
                        checked = state.showTranslations,
                        onCheckedChange = { actions.onToggleTranslations() },
                        testTag = "toggle_translations",
                    )
                }
                turns.forEach { TranscriptTurn(it, state.showTranslations) }
            }
        }
    }
}

@Composable
private fun TimelineCard(call: CallDetailDto) {
    SpartaCard(modifier = Modifier.testTag("detail_timeline")) {
        SectionTitle(stringResource(R.string.detail_section_timeline))
        call.timeline.take(MAX_TIMELINE).forEach { entry ->
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(entry.label, style = MaterialTheme.typography.bodyMedium)
                entry.detail?.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
                }
            }
        }
    }
}

@Composable
private fun DataCard(item: CallListItemDto, call: CallDetailDto, onConfirm: (DeleteKind) -> Unit) {
    SpartaCard(modifier = Modifier.testTag("detail_data")) {
        SectionTitle(stringResource(R.string.detail_section_data))
        if (item.hasContent && item.mode != CallMode.SCREENING_ONLY) {
            SecondaryButton(
                text = stringResource(R.string.detail_delete_content),
                onClick = { onConfirm(DeleteKind.CONTENT) },
                icon = Icons.Rounded.Delete,
                modifier = Modifier.fillMaxWidth(),
                testTag = "delete_content",
            )
        }
        DestructiveButton(
            text = stringResource(R.string.detail_delete_call),
            onClick = { onConfirm(DeleteKind.CALL) },
            icon = Icons.Rounded.Delete,
            modifier = Modifier.fillMaxWidth(),
            testTag = "delete_call",
        )
    }
}

@Composable
private fun TechnicalCard(call: CallDetailDto) {
    SpartaCard(modifier = Modifier.testTag("detail_tech")) {
        SectionTitle(stringResource(R.string.detail_section_tech))
        KeyValueRow(stringResource(R.string.detail_row_state), stringResource(Labels.state(call.state)))
        KeyValueRow(stringResource(R.string.detail_row_provider), stringResource(Labels.provider(call.provider)))
        if (call.versions.policyVersion.isNotBlank()) KeyValueRow(stringResource(R.string.detail_row_policy), call.versions.policyVersion)
        if (call.versions.languagePackVersion.isNotBlank()) {
            KeyValueRow(stringResource(R.string.detail_row_language_pack), call.versions.languagePackVersion)
        }
        if (call.traceId.isNotBlank()) KeyValueRow(stringResource(R.string.detail_row_trace), call.traceId, testTag = "detail_trace")
    }
}

private const val MAX_TIMELINE = 30
