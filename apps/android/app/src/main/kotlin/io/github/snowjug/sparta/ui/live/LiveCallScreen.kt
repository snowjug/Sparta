package io.github.snowjug.sparta.ui.live

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.repo.LiveConnection
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.RiskMeter
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SignalRow
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SpartaTopBar
import io.github.snowjug.sparta.ui.components.StatusPill
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.TranscriptTurn
import io.github.snowjug.sparta.ui.components.VoiceVisualizer
import io.github.snowjug.sparta.ui.components.currentWidthClass
import io.github.snowjug.sparta.ui.components.speakerLabel
import io.github.snowjug.sparta.ui.incoming.AudioHonestyBanner
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.OwnerControlsPanel
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class LiveCallActions(
    val onBack: () -> Unit = {},
    val onControl: (ControlId) -> Unit = {},
    val onOpenDetails: (String) -> Unit = {},
    val onDismissMessage: () -> Unit = {},
)

@Composable
fun LiveCallRoute(
    callId: String,
    onBack: () -> Unit,
    onOpenDetails: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: LiveCallViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(callId) { viewModel.bind(callId) }
    val widthClass = currentWidthClass()
    LiveCallContent(
        state = state,
        widthClass = widthClass,
        modifier = modifier,
        actions = LiveCallActions(
            onBack = onBack,
            onControl = { control ->
                when (control) {
                    ControlId.TAKE_OVER -> viewModel.takeOver()
                    ControlId.CONTINUE -> viewModel.continueCall()
                    ControlId.END -> viewModel.endCall()
                    else -> Unit
                }
            },
            onOpenDetails = onOpenDetails,
            onDismissMessage = viewModel::dismissMessage,
        ),
    )
}

@Composable
fun LiveCallContent(
    state: LiveCallUiState,
    widthClass: WidthClass,
    actions: LiveCallActions,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().testTag("live_screen")) {
        SpartaTopBar(stringResource(R.string.live_title), actions.onBack)
        if (state.notFound) {
            EmptyState(
                title = stringResource(R.string.live_not_found),
                body = stringResource(R.string.detail_not_found_body),
                actionLabel = stringResource(R.string.common_back),
                onAction = actions.onBack,
                testTag = "live_not_found",
            )
            return@Column
        }
        if (AdaptiveLayout.usesTwoPane(widthClass)) {
            Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Box(modifier = Modifier.weight(1f)) { LeftColumn(state, actions) }
                Box(modifier = Modifier.weight(1f)) { TranscriptColumn(state) }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item(key = "left") {
                    Column(Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        TopSections(state, actions)
                    }
                }
                item(key = "transcript_title") {
                    Column(Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth()) {
                        SectionTitle(stringResource(R.string.live_transcript_title))
                    }
                }
                transcriptItems(state)
                item(key = "bottom") {
                    Column(Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        BottomSections(state, actions)
                    }
                }
            }
        }
    }
}

@Composable
private fun LeftColumn(state: LiveCallUiState, actions: LiveCallActions) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item(key = "left") {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                TopSections(state, actions)
                BottomSections(state, actions)
            }
        }
    }
}

@Composable
private fun TranscriptColumn(state: LiveCallUiState) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item(key = "transcript_title") { SectionTitle(stringResource(R.string.live_transcript_title)) }
        transcriptItems(state)
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.transcriptItems(state: LiveCallUiState) {
    val turns = state.live.transcript
    if (turns.isEmpty() && state.live.partial == null) {
        item(key = "transcript_waiting") {
            Text(
                stringResource(R.string.live_transcript_waiting),
                style = MaterialTheme.typography.bodyMedium,
                color = SpartaTheme.extras.textSecondary,
                modifier = Modifier.testTag("live_transcript_waiting"),
            )
        }
    }
    items(turns, key = { it.id }) { turn ->
        Box(Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth()) {
            TranscriptTurn(turn, showTranslation = true)
        }
    }
    val partial = state.live.partial
    if (partial != null) {
        item(key = "partial") {
            Text(
                text = speakerLabel(partial.speaker) + ": " + stringResource(R.string.live_partial, partial.text),
                style = MaterialTheme.typography.bodyMedium,
                fontStyle = FontStyle.Italic,
                color = SpartaTheme.extras.textSecondary,
                modifier = Modifier.fillMaxWidth().testTag("live_partial").semantics { liveRegion = LiveRegionMode.Polite },
            )
        }
    }
}

@Composable
private fun ConnectionBanner(state: LiveCallUiState) {
    val (text, tone) = when (state.connection) {
        LiveConnection.CONNECTING -> stringResource(R.string.live_conn_connecting) to Tone.INFO
        LiveConnection.CONNECTED -> stringResource(R.string.live_conn_connected) to Tone.SAFE
        LiveConnection.RECONNECTING -> stringResource(R.string.live_conn_reconnecting) to Tone.CAUTION
        LiveConnection.CLOSED -> stringResource(R.string.live_conn_closed) to Tone.INFO
        LiveConnection.FAILED -> stringResource(R.string.live_conn_failed, state.connectionError?.message ?: stringResource(R.string.api_error_offline)) to Tone.CAUTION
    }
    InfoBanner(text = text, tone = tone, testTag = "live_connection")
}

@Composable
private fun TopSections(state: LiveCallUiState, actions: LiveCallActions) {
    val live = state.live
    val call = state.call
    MessageBanner(state.message, actions.onDismissMessage)
    ConnectionBanner(state)
    Text(stringResource(R.string.live_intro), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
    if (live.simulated == true || call?.simulated == true) {
        StatusPill(stringResource(R.string.live_simulated_note), Tone.INFO, icon = Icons.Rounded.Info, testTag = "live_simulated")
    }
    AudioHonestyBanner(call)

    SpartaCard(modifier = Modifier.testTag("live_now")) {
        val phaseText = stringResource(phaseRes(live.phase))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
            VoiceVisualizer(
                phase = live.phase,
                description = stringResource(R.string.live_visual_description, phaseText),
                modifier = Modifier.size(180.dp),
            )
        }
        Text(
            phaseText,
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.fillMaxWidth().testTag("live_phase_text").semantics { liveRegion = LiveRegionMode.Polite },
        )
        live.speaking?.text?.takeIf { it.isNotBlank() }?.let {
            Text(stringResource(R.string.live_speaking_text, it), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("live_speaking"))
        }
        live.languageChanges.lastOrNull()?.to?.let {
            Text(stringResource(R.string.live_language_changed, Labels.languageName(it)), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
        live.providerNotes.lastOrNull()?.let {
            InfoBanner(stringResource(R.string.live_provider_issue, it.stage, it.message), Tone.CAUTION, testTag = "live_provider_issue")
        }
    }

    val escalation = live.escalation
    if (escalation != null && !live.isEnded) {
        SpartaCard(modifier = Modifier.testTag("live_escalation")) {
            SectionTitle(stringResource(R.string.live_escalation_title))
            if (escalation.reason.isNotBlank()) Text(escalation.reason, style = MaterialTheme.typography.bodyMedium)
            escalation.importantLines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
        }
    }

    val risk = live.risk
    if (risk != null && call?.mode != CallMode.SCREENING_ONLY) {
        SpartaCard(modifier = Modifier.testTag("live_risk")) {
            SectionTitle(stringResource(R.string.live_risk_title))
            RiskMeter(risk.riskScore, risk.confidence, risk.riskLevel)
            risk.signals.take(3).forEach { SignalRow(it) }
        }
    }
}

@Composable
private fun BottomSections(state: LiveCallUiState, actions: LiveCallActions) {
    val live = state.live
    val call = state.call
    if (live.isEnded) {
        SpartaCard(modifier = Modifier.testTag("live_summary")) {
            SectionTitle(stringResource(R.string.live_ended_title))
            val text = live.summary?.text?.takeIf { it.isNotBlank() } ?: call?.summaryText?.takeIf { it.isNotBlank() }
            Text(
                text ?: stringResource(R.string.live_ended_waiting_summary),
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.testTag("live_summary_text"),
            )
            SecondaryButton(
                text = stringResource(R.string.live_view_details),
                onClick = { actions.onOpenDetails(state.callId) },
                modifier = Modifier.fillMaxWidth(),
                testTag = "live_view_details",
            )
        }
    } else {
        SpartaCard(modifier = Modifier.testTag("live_controls")) {
            SectionTitle(stringResource(R.string.detail_section_actions))
            OwnerControlsPanel(
                controls = state.liveControls,
                busy = state.busy,
                blocked = false,
                trusted = false,
                onAction = actions.onControl,
            )
        }
    }
}

private fun phaseRes(phase: VoicePhase): Int = when (phase) {
    VoicePhase.CONNECTING -> R.string.live_phase_connecting
    VoicePhase.LISTENING -> R.string.live_phase_listening
    VoicePhase.ASSISTANT_SPEAKING -> R.string.live_phase_speaking
    VoicePhase.INTERRUPTED -> R.string.live_phase_interrupted
    VoicePhase.OWNER_TAKEOVER -> R.string.live_phase_takeover
    VoicePhase.ENDED -> R.string.live_phase_ended
}
