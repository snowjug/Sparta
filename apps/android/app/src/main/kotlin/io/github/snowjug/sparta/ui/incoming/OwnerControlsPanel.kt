package io.github.snowjug.sparta.ui.incoming

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CallEnd
import androidx.compose.material.icons.automirrored.rounded.PhoneForwarded
import androidx.compose.material.icons.rounded.Replay
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.ui.components.DestructiveButton
import io.github.snowjug.sparta.ui.components.DisabledReason
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.theme.SpartaTheme

private val LIVE_CONTROLS = listOf(ControlId.TAKE_OVER, ControlId.CONTINUE, ControlId.END)

private fun Unavailable.textRes(): Int = when (this) {
    Unavailable.NOT_LOADED -> R.string.unavail_not_loaded
    Unavailable.CALL_ENDED -> R.string.unavail_call_ended
    Unavailable.SCREENING_ONLY -> R.string.unavail_screening_only
    Unavailable.PROVIDER_CANNOT -> R.string.unavail_provider_cannot
    Unavailable.ALREADY_TAKEN_OVER -> R.string.unavail_already_taken_over
}

/**
 * The owner's controls for one call. Which of them are enabled comes only from [OwnerControls.evaluate], i.e. from the
 * backend's `capabilities`; every disabled control says why instead of silently doing nothing, and a control that only
 * simulates its effect is labelled as a simulation.
 */
@Composable
fun OwnerControlsPanel(
    controls: List<ControlState>,
    busy: ControlId?,
    blocked: Boolean,
    trusted: Boolean,
    onAction: (ControlId) -> Unit,
    modifier: Modifier = Modifier,
) {
    val byId = controls.associateBy { it.id }
    val live = LIVE_CONTROLS.mapNotNull { byId[it] }
    val inactive = setOf(Unavailable.CALL_ENDED, Unavailable.SCREENING_ONLY, Unavailable.NOT_LOADED)
    val noLiveControls = live.isNotEmpty() && live.all { it.unavailable in inactive }

    Column(modifier = modifier.fillMaxWidth().testTag("owner_controls"), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (noLiveControls) {
            DisabledReason(
                text = stringResource(live.first().unavailable!!.textRes()),
                testTag = "control_live_unavailable",
            )
        } else {
            live.forEach { control ->
                LiveControl(control, busy, onAction)
            }
        }

        val block = byId[ControlId.BLOCK]
        if (block != null) {
            SecondaryButton(
                text = stringResource(
                    when {
                        busy == ControlId.BLOCK -> R.string.owner_ctl_working
                        blocked -> R.string.owner_ctl_blocked
                        else -> R.string.owner_ctl_block
                    },
                ),
                onClick = { onAction(ControlId.BLOCK) },
                enabled = block.enabled && busy == null && !blocked,
                icon = Icons.Rounded.Block,
                modifier = Modifier.fillMaxWidth(),
                testTag = "control_block",
            )
            if (!block.enabled) {
                DisabledReason(stringResource(R.string.unavail_block), testTag = "control_block_reason")
            }
        }
        val trust = byId[ControlId.TRUST]
        if (trust != null) {
            SecondaryButton(
                text = stringResource(
                    when {
                        busy == ControlId.TRUST -> R.string.owner_ctl_working
                        trusted -> R.string.owner_ctl_trusted
                        else -> R.string.owner_ctl_trust
                    },
                ),
                onClick = { onAction(ControlId.TRUST) },
                enabled = trust.enabled && busy == null && !trusted,
                icon = Icons.Rounded.VerifiedUser,
                modifier = Modifier.fillMaxWidth(),
                testTag = "control_trust",
            )
        }
    }
}

@Composable
private fun LiveControl(control: ControlState, busy: ControlId?, onAction: (ControlId) -> Unit) {
    val working = busy == control.id
    val base = when (control.id) {
        ControlId.TAKE_OVER -> R.string.owner_ctl_take_over
        ControlId.CONTINUE -> R.string.owner_ctl_continue
        ControlId.END -> R.string.owner_ctl_end
        else -> R.string.owner_ctl_working
    }
    val label = when {
        working -> stringResource(R.string.owner_ctl_working)
        control.simulated -> stringResource(R.string.owner_ctl_simulated_suffix, stringResource(base))
        else -> stringResource(base)
    }
    val enabled = control.enabled && busy == null
    val tag = when (control.id) {
        ControlId.TAKE_OVER -> "control_take_over"
        ControlId.CONTINUE -> "control_continue"
        else -> "control_end"
    }
    val modifier = Modifier.fillMaxWidth()
    when (control.id) {
        ControlId.TAKE_OVER -> PrimaryButton(label, { onAction(control.id) }, modifier, enabled, Icons.AutoMirrored.Rounded.PhoneForwarded, tag)
        ControlId.CONTINUE -> SecondaryButton(label, { onAction(control.id) }, modifier, enabled, Icons.Rounded.Replay, tag)
        else -> DestructiveButton(label, { onAction(control.id) }, modifier, enabled, Icons.Rounded.CallEnd, tag)
    }
    if (!control.enabled) {
        control.unavailable?.let { DisabledReason(stringResource(it.textRes()), testTag = "${tag}_reason") }
    }
    control.note?.takeIf { it.isNotBlank() }?.let {
        Text(
            stringResource(R.string.backend_says, it),
            style = MaterialTheme.typography.bodySmall,
            color = SpartaTheme.extras.textSecondary,
            modifier = Modifier.testTag("${tag}_note"),
        )
    }
}

/** What this call may honestly claim about audio, from the backend's capabilities and nothing else. */
@Composable
fun AudioHonestyBanner(call: CallDetailDto?, modifier: Modifier = Modifier) {
    if (call == null) return
    val (text, tone) = when (AudioHonesty.claim(call)) {
        AudioClaim.TWO_WAY_AUDIO -> R.string.audio_two_way to Tone.SAFE
        AudioClaim.SIMULATED -> R.string.audio_simulated to Tone.INFO
        AudioClaim.NO_AUDIO -> (if (call.mode == CallMode.SCREENING_ONLY) R.string.audio_screening_only else R.string.audio_none) to Tone.INFO
    }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        InfoBanner(text = stringResource(text), tone = tone, title = stringResource(R.string.audio_title), testTag = "audio_honesty")
        call.capabilities.audioNote?.takeIf { it.isNotBlank() }?.let {
            Text(
                stringResource(R.string.backend_says, it),
                style = MaterialTheme.typography.bodySmall,
                color = SpartaTheme.extras.textSecondary,
                modifier = Modifier.testTag("audio_note"),
            )
        }
    }
}
