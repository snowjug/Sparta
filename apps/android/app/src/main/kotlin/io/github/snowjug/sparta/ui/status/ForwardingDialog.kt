package io.github.snowjug.sparta.ui.status

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.forwarding.ForwardingCodes
import io.github.snowjug.sparta.core.forwarding.ForwardingMode
import io.github.snowjug.sparta.ui.components.ChoiceGroup
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.theme.SpartaTheme

/**
 * Pre-fills the dialer with a conditional call-forwarding code for the backend's forwarding number. The code is shown
 * in full before anything opens, the number is validated (digits only), and the owner presses call.
 */
@Composable
fun ForwardingDialog(
    number: String?,
    onDismiss: () -> Unit,
    onOpenDialer: (String) -> Unit,
) {
    var mode by rememberSaveable { mutableStateOf(ForwardingMode.NO_ANSWER) }
    val code = ForwardingCodes.activation(mode, number)

    AlertDialog(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag("forwarding_dialog"),
        title = { Text(stringResource(R.string.forwarding_title)) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(stringResource(R.string.forwarding_intro), style = MaterialTheme.typography.bodyMedium)
                if (code == null) {
                    InfoBanner(stringResource(R.string.forwarding_no_number), Tone.CAUTION, testTag = "forwarding_no_number")
                } else {
                    Text(stringResource(R.string.forwarding_number_label, number.orEmpty()), style = MaterialTheme.typography.bodyMedium)
                    Text(stringResource(R.string.forwarding_mode_label), style = MaterialTheme.typography.titleSmall)
                    ChoiceGroup(
                        options = listOf(
                            ForwardingMode.NO_ANSWER to stringResource(R.string.forwarding_mode_no_answer),
                            ForwardingMode.BUSY to stringResource(R.string.forwarding_mode_busy),
                            ForwardingMode.UNREACHABLE to stringResource(R.string.forwarding_mode_unreachable),
                        ),
                        selected = mode,
                        onSelect = { mode = it },
                        testTagPrefix = "forwarding_mode",
                    )
                    Text(stringResource(R.string.forwarding_code_label), style = MaterialTheme.typography.titleSmall)
                    Text(
                        code,
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.fillMaxWidth().testTag("forwarding_code").padding(vertical = 4.dp),
                        color = SpartaTheme.extras.accent,
                    )
                    Text(
                        stringResource(R.string.forwarding_cancel_code, ForwardingCodes.deactivation(mode), ForwardingCodes.CANCEL_ALL),
                        style = MaterialTheme.typography.bodySmall,
                        color = SpartaTheme.extras.textSecondary,
                    )
                }
                Text(stringResource(R.string.forwarding_caveats), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
        },
        confirmButton = {
            PrimaryButton(
                text = stringResource(R.string.forwarding_open_dialer),
                onClick = { code?.let(onOpenDialer) },
                enabled = code != null,
                testTag = "forwarding_open_dialer",
            )
        },
        dismissButton = { QuietButton(stringResource(R.string.forwarding_close), onDismiss, testTag = "forwarding_close") },
    )
}
