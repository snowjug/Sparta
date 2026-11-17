package io.github.snowjug.sparta.ui.incoming

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.EscalationStatus
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.components.CallFlags
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.ErrorBlock
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.LoadingBlock
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.ProviderBadges
import io.github.snowjug.sparta.ui.components.RiskMeter
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SignalRow
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaTopBar
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.callerDisplayText
import io.github.snowjug.sparta.ui.detail.CallDetailActions
import io.github.snowjug.sparta.ui.detail.CallDetailUiState
import io.github.snowjug.sparta.ui.detail.CallDetailViewModel
import io.github.snowjug.sparta.ui.theme.SpartaTheme

/**
 * The screen a "call needs you" notification opens. It is decision-first: who is calling (masked), why Sparta stopped,
 * the evidence, and only the controls that are honest for this call's provider.
 */
@Composable
fun IncomingRoute(
    callId: String,
    onBack: () -> Unit,
    onOpenDetails: (String) -> Unit,
    onOpenLive: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: CallDetailViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(callId) { viewModel.load(callId) }
    IncomingContent(
        state = state,
        modifier = modifier,
        actions = CallDetailActions(
            onBack = onBack,
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
            onOpenLive = onOpenLive,
            onDismissMessage = viewModel::dismissMessage,
        ),
        onOpenDetails = onOpenDetails,
    )
}

@Composable
fun IncomingContent(
    state: CallDetailUiState,
    actions: CallDetailActions,
    onOpenDetails: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().testTag("incoming_screen")) {
        SpartaTopBar(stringResource(R.string.incoming_title), actions.onBack)
        val call = state.call
        val item = call?.toListItem() ?: state.cached
        when {
            item == null && state.loading -> LoadingBlock()
            item == null && state.notFound -> EmptyState(
                title = stringResource(R.string.detail_not_found_title),
                body = stringResource(R.string.detail_not_found_body),
                testTag = "incoming_not_found",
            )
            item == null -> ErrorBlock(
                message = state.error?.message ?: stringResource(R.string.api_error_offline),
                traceId = state.error?.traceId,
                onRetry = actions.onRefresh,
                modifier = Modifier.padding(16.dp),
                testTag = "incoming_error",
            )
            else -> IncomingBody(state, item, call, actions, onOpenDetails)
        }
    }
}

private fun needsOwner(item: CallListItemDto, call: CallDetailDto?): Boolean =
    item.status == CallStatus.ACTIVE &&
        (item.ownerAttentionRequired || call?.escalations?.any { it.status == EscalationStatus.REQUESTED } == true)

@Composable
private fun IncomingBody(
    state: CallDetailUiState,
    item: CallListItemDto,
    call: CallDetailDto?,
    actions: CallDetailActions,
    onOpenDetails: (String) -> Unit,
) {
    val needsOwner = needsOwner(item, call)
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
                    InfoBanner(stringResource(R.string.detail_offline_cached, state.error.message), Tone.CAUTION, testTag = "incoming_cached_note")
                }
                Headline(item, needsOwner)
                CallerCard(item)
                if (call != null) AudioHonestyBanner(call)
                EvidenceCard(item, call)
                if (call != null) {
                    SpartaCard(modifier = Modifier.testTag("incoming_controls")) {
                        SectionTitle(stringResource(R.string.detail_section_actions))
                        OwnerControlsPanel(
                            controls = state.controls,
                            busy = state.busy,
                            blocked = state.blocked,
                            trusted = state.trusted,
                            onAction = actions.onControl,
                        )
                    }
                }
                if (item.status == CallStatus.ACTIVE && item.mode != CallMode.SCREENING_ONLY) {
                    PrimaryButton(
                        text = stringResource(R.string.detail_open_live),
                        onClick = { actions.onOpenLive(item.id) },
                        icon = Icons.Rounded.GraphicEq,
                        modifier = Modifier.fillMaxWidth(),
                        testTag = "incoming_open_live",
                    )
                }
                SecondaryButton(
                    text = stringResource(R.string.incoming_open_details),
                    onClick = { onOpenDetails(item.id) },
                    icon = Icons.Rounded.Info,
                    modifier = Modifier.fillMaxWidth(),
                    testTag = "incoming_open_details",
                )
            }
        }
    }
}

@Composable
private fun Headline(item: CallListItemDto, needsOwner: Boolean) {
    val (title, body, tone) = when {
        needsOwner -> Triple(R.string.incoming_needs_you_headline, R.string.incoming_needs_you_body, Tone.CAUTION)
        item.status == CallStatus.ACTIVE -> Triple(R.string.incoming_active_headline, R.string.incoming_no_attention, Tone.INFO)
        else -> Triple(R.string.incoming_ended_headline, R.string.incoming_no_attention, Tone.INFO)
    }
    InfoBanner(
        title = stringResource(title),
        text = stringResource(body),
        tone = tone,
        testTag = if (needsOwner) "incoming_needs_you" else "incoming_no_attention",
    )
}

@Composable
private fun CallerCard(item: CallListItemDto) {
    SpartaCard(modifier = Modifier.testTag("incoming_caller")) {
        SectionTitle(stringResource(R.string.incoming_caller_section))
        Text(callerDisplayText(item.callerDisplay), style = MaterialTheme.typography.headlineSmall)
        val claim = listOfNotNull(item.callerClaim.name, item.callerClaim.organization).joinToString(", ")
        if (claim.isBlank()) {
            Text(stringResource(R.string.incoming_unknown_claim), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        } else {
            Text(stringResource(R.string.incoming_claim, claim), style = MaterialTheme.typography.bodyLarge)
        }
        item.purpose?.takeIf { it.isNotBlank() }?.let { Text(stringResource(R.string.incoming_purpose, it), style = MaterialTheme.typography.bodyMedium) }
        CallFlags(item)
        ProviderBadges(item.provider, item.simulated, item.mode)
    }
}

@Composable
private fun EvidenceCard(item: CallListItemDto, call: CallDetailDto?) {
    if (item.mode == CallMode.SCREENING_ONLY) return
    val risk = call?.risk
    val lines = call?.escalations?.lastOrNull()?.importantLines.orEmpty()
    SpartaCard(modifier = Modifier.testTag("incoming_evidence")) {
        SectionTitle(stringResource(R.string.incoming_why_title))
        if (item.riskLevel == RiskLevel.UNKNOWN) {
            Text(stringResource(R.string.risk_unknown), style = MaterialTheme.typography.bodyLarge)
        } else {
            RiskMeter(item.riskScore, item.confidence, item.riskLevel)
        }
        if (risk != null) {
            Text(stringResource(R.string.incoming_advice, stringResource(Labels.advice(risk.recommendedAction))), style = MaterialTheme.typography.bodyMedium)
            risk.signals.take(MAX_SIGNALS).forEach { SignalRow(it) }
        }
        if (lines.isNotEmpty()) {
            Text(stringResource(R.string.incoming_lines_title), style = MaterialTheme.typography.titleSmall)
            lines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("incoming_line")) }
        }
    }
}

private const val MAX_SIGNALS = 4
