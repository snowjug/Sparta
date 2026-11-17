package io.github.snowjug.sparta.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.ui.common.UiMessage

/** Shows a one-off result: a short note for success, the backend's own explanation (and trace id) for a failure. */
@Composable
fun MessageBanner(message: UiMessage?, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    when (message) {
        null -> Unit
        is UiMessage.Text -> Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            InfoBanner(text = stringResource(message.res, *message.args.toTypedArray()), tone = Tone.INFO, testTag = "message_banner")
            QuietButton(stringResource(R.string.common_dismiss), onDismiss, testTag = "message_dismiss")
        }
        is UiMessage.Failure -> Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            ErrorBlock(message = message.error.message, traceId = message.error.traceId, testTag = "message_error")
            QuietButton(stringResource(R.string.common_dismiss), onDismiss, testTag = "message_dismiss")
        }
    }
}

/** Title row for screens opened from a list (call detail, live call, event). The back button is a 48dp target. */
@Composable
fun SpartaTopBar(title: String, onBack: (() -> Unit)?, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) {
            IconButton(onClick = onBack, modifier = Modifier.testTag("top_bar_back")) {
                Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = stringResource(R.string.common_back))
            }
        }
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(start = if (onBack == null) 12.dp else 4.dp).asHeading().testTag("top_bar_title"),
        )
    }
}
