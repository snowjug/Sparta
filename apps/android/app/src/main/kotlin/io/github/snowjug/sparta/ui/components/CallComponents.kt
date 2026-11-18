package io.github.snowjug.sparta.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.NotificationImportant
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.CallTurnDto
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.RiskSignalDto
import io.github.snowjug.sparta.data.remote.dto.SignalKind
import io.github.snowjug.sparta.data.remote.dto.SignalSeverity
import io.github.snowjug.sparta.data.remote.dto.Speaker
import io.github.snowjug.sparta.ui.Ago
import io.github.snowjug.sparta.ui.Formatters
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.ScreeningText
import io.github.snowjug.sparta.ui.theme.SpartaTheme

@Composable
fun RiskBadge(level: RiskLevel, modifier: Modifier = Modifier, testTag: String = "risk_badge") {
    StatusPill(
        label = stringResource(Labels.risk(level)),
        tone = Labels.riskTone(level),
        modifier = modifier,
        icon = Labels.riskIcon(level),
        testTag = testTag,
    )
}

/** What handled the call, and whether it is a simulation. Both are always visible: nothing simulated looks real. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProviderBadges(
    provider: ProviderKind,
    simulated: Boolean,
    mode: CallMode,
    modifier: Modifier = Modifier,
) {
    FlowRow(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val onDevice = mode == CallMode.SCREENING_ONLY || provider == ProviderKind.ANDROID_SCREENING
        StatusPill(
            label = stringResource(if (onDevice) R.string.provider_android_screening else Labels.provider(provider)),
            tone = Tone.NEUTRAL,
            testTag = "provider_badge",
        )
        if (simulated && !onDevice) StatusPill(stringResource(R.string.badge_simulated), Tone.INFO, testTag = "simulated_badge")
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CallFlags(item: CallListItemDto, modifier: Modifier = Modifier) {
    FlowRow(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        RiskBadge(item.riskLevel)
        if (item.ownerAttentionRequired && item.status != CallStatus.FAILED) {
            StatusPill(stringResource(R.string.badge_needs_you), Tone.CAUTION, icon = Icons.Rounded.NotificationImportant, testTag = "attention_badge")
        }
        if (item.blocked) StatusPill(stringResource(R.string.badge_blocked), Tone.DESTRUCTIVE, icon = Icons.Rounded.Block, testTag = "blocked_badge")
        if (item.trusted) StatusPill(stringResource(R.string.badge_trusted), Tone.SAFE, icon = Icons.Rounded.CheckCircle, testTag = "trusted_badge")
    }
}

@Composable
fun callerDisplayText(display: String): String = display.ifBlank { stringResource(R.string.caller_private) }

/** One call in a list. The whole row is a single accessible button whose description summarises it. */
@Composable
fun CallRow(
    item: CallListItemDto,
    nowMs: Long,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
) {
    val display = callerDisplayText(item.callerDisplay)
    val startedAtMs = remember(item.startedAt) { Timestamps.parseMs(item.startedAt) }
    val ago = agoText(nowMs, startedAtMs)
    val risk = stringResource(Labels.risk(item.riskLevel))
    val claim = listOfNotNull(item.callerClaim.name, item.callerClaim.organization).joinToString(", ")
    val subtitle = claim.ifBlank { item.purpose.orEmpty() }.ifBlank { stringResource(Labels.category(item.category)) }
    val description = stringResource(R.string.call_row_description, display, risk, ago, subtitle)
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag("call_row_${item.id}")
            .clickable(role = Role.Button, onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = description },
        shape = MaterialTheme.shapes.medium,
        color = if (selected) SpartaTheme.extras.surface2 else MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, if (selected) SpartaTheme.extras.accent else MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.heightIn(min = MinTouchTarget).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text(display, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(ago, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            item.summaryText?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            CallFlags(item)
            ProviderBadges(item.provider, item.simulated, item.mode)
        }
    }
}

/** A decision made natively on this phone. It has no transcript and no analysis, and the row says so. */
@Composable
fun LocalEventRow(
    event: ScreeningEventEntity,
    nowMs: Long,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val display = callerDisplayText(event.numberDisplay)
    val ago = agoText(nowMs, event.occurredAtMs)
    val action = stringResource(ScreeningText.action(event.decision))
    val reason = stringResource(ScreeningText.reasonLabel(event.reason))
    val description = stringResource(R.string.event_row_description, display, action, reason, ago)
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .testTag("event_row_${event.clientEventId}")
            .clickable(role = Role.Button, onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = description },
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.heightIn(min = MinTouchTarget).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text(display, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(ago, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
            Text("$action: $reason", style = MaterialTheme.typography.bodyMedium)
            StatusPill(stringResource(R.string.provider_android_screening), Tone.NEUTRAL, testTag = "provider_badge")
        }
    }
}

/** Relative time without Android types so the rule is unit tested. */
@Composable
fun agoText(nowMs: Long, thenMs: Long?): String = when (val ago = Formatters.ago(nowMs, thenMs)) {
    Ago.Unknown -> stringResource(R.string.common_unknown)
    Ago.JustNow -> stringResource(R.string.time_just_now)
    is Ago.Minutes -> stringResource(R.string.time_minutes_ago, ago.value)
    is Ago.Hours -> stringResource(R.string.time_hours_ago, ago.value)
    is Ago.Days -> stringResource(R.string.time_days_ago, ago.value)
}

@Composable
fun severityLabel(severity: SignalSeverity): String = stringResource(
    when (severity) {
        SignalSeverity.INFO -> R.string.severity_info
        SignalSeverity.LOW -> R.string.severity_low
        SignalSeverity.MEDIUM -> R.string.severity_medium
        SignalSeverity.HIGH -> R.string.severity_high
        SignalSeverity.CRITICAL -> R.string.severity_critical
        SignalSeverity.UNKNOWN -> R.string.severity_unknown
    },
)

/**
 * One piece of evidence behind a classification. The backend's own description is shown (it is already written for
 * people); the stable code is only a fallback. Reassuring signals never use the risk colour.
 */
@Composable
fun SignalRow(signal: RiskSignalDto, modifier: Modifier = Modifier) {
    val reassuring = signal.kind == SignalKind.LEGITIMATE
    val tone = when {
        reassuring -> Tone.SAFE
        signal.severity == SignalSeverity.CRITICAL || signal.severity == SignalSeverity.HIGH -> Tone.CAUTION
        else -> Tone.NEUTRAL
    }
    val title = signal.description.ifBlank { Labels.humanizeCode(signal.code) }
    val kindLabel = stringResource(if (reassuring) R.string.signal_reassuring else R.string.signal_warning)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .testTag("signal_${signal.code}")
            .semantics(mergeDescendants = true) {},
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            StatusPill("$kindLabel · ${severityLabel(signal.severity)}", tone)
        }
        Text(title, style = MaterialTheme.typography.bodyMedium)
        signal.evidenceExcerpt?.takeIf { it.isNotBlank() }?.let {
            Text(
                stringResource(R.string.signal_excerpt, it),
                style = MaterialTheme.typography.bodySmall,
                fontStyle = FontStyle.Italic,
                color = SpartaTheme.extras.textSecondary,
            )
        }
    }
}

/** A score is shown with its confidence, never as a bare certainty. */
@Composable
fun RiskMeter(riskScore: Double, confidence: Double, level: RiskLevel, modifier: Modifier = Modifier) {
    val toneColor = Labels.riskTone(level).color()
    val scorePercent = Formatters.percent(riskScore)
    val confidencePercent = Formatters.percent(confidence)
    val description = stringResource(R.string.risk_meter_description, stringResource(Labels.risk(level)), scorePercent, confidencePercent)
    Column(
        modifier = modifier.fillMaxWidth().testTag("risk_meter").semantics(mergeDescendants = true) { contentDescription = description },
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.score_value, scorePercent), style = MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.confidence_value, confidencePercent), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        }
        LinearProgressIndicator(
            progress = { riskScore.coerceIn(0.0, 1.0).toFloat() },
            modifier = Modifier.fillMaxWidth().heightIn(min = 8.dp),
            color = toneColor,
            trackColor = SpartaTheme.extras.surface2,
        )
    }
}

@Composable
fun speakerLabel(speaker: Speaker): String = stringResource(
    when (speaker) {
        Speaker.CALLER -> R.string.speaker_caller
        Speaker.ASSISTANT -> R.string.speaker_assistant
        Speaker.OWNER -> R.string.speaker_owner
        Speaker.SYSTEM -> R.string.speaker_system
        Speaker.UNKNOWN -> R.string.speaker_unknown
    },
)

/** One transcript line. The assistant is always labelled as an AI assistant; translations are opt-in per call. */
@Composable
fun TranscriptTurn(turn: CallTurnDto, showTranslation: Boolean, modifier: Modifier = Modifier) {
    val assistant = turn.speaker == Speaker.ASSISTANT
    val label = speakerLabel(turn.speaker)
    Surface(
        modifier = modifier.fillMaxWidth().testTag("turn_${turn.id}").semantics(mergeDescendants = true) {},
        shape = MaterialTheme.shapes.medium,
        color = if (assistant) SpartaTheme.extras.surface2 else MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, if (assistant) SpartaTheme.extras.accent else MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(label, style = MaterialTheme.typography.labelLarge, color = if (assistant) SpartaTheme.extras.accent else SpartaTheme.extras.textSecondary)
                turn.language?.takeIf { it.isNotBlank() }?.let {
                    Text(Labels.languageName(it), style = MaterialTheme.typography.labelSmall, color = SpartaTheme.extras.textSecondary)
                }
                if (turn.interrupted) Text(stringResource(R.string.turn_interrupted), style = MaterialTheme.typography.labelSmall, color = SpartaTheme.extras.caution)
            }
            Text(turn.text, style = MaterialTheme.typography.bodyLarge)
            if (showTranslation) {
                turn.translation?.takeIf { it.isNotBlank() && it != turn.text }?.let {
                    Text(
                        stringResource(R.string.transcript_translation, it),
                        style = MaterialTheme.typography.bodySmall,
                        fontStyle = FontStyle.Italic,
                        color = SpartaTheme.extras.textSecondary,
                    )
                }
            }
        }
    }
}

@Composable
fun IconText(
    icon: ImageVector,
    text: String,
    modifier: Modifier = Modifier,
    tint: Color = SpartaTheme.extras.textSecondary,
) {
    Row(modifier = modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(20.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}
