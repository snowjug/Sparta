package io.github.snowjug.sparta.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Error
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.ui.theme.SpartaTheme

/** Every touch target is at least 48dp tall. */
val MinTouchTarget: Dp = 48.dp

/** Announces changes to screen readers (state banners, connection status, results). */
fun Modifier.politeLiveRegion(): Modifier = semantics { liveRegion = LiveRegionMode.Polite }

fun Modifier.asHeading(): Modifier = semantics { heading() }

@Composable
fun SpartaLogo(modifier: Modifier = Modifier, size: Dp = 56.dp, decorative: Boolean = false) {
    val description = stringResource(R.string.common_logo_description)
    Image(
        painter = painterResource(R.drawable.ic_sparta_mark),
        contentDescription = if (decorative) null else description,
        modifier = modifier.size(size),
    )
}

@Composable
fun ScreenTitle(text: String, modifier: Modifier = Modifier, subtitle: String? = null) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(text = text, style = MaterialTheme.typography.headlineMedium, modifier = Modifier.asHeading())
        if (subtitle != null) {
            Text(text = subtitle, style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleMedium,
        color = SpartaTheme.extras.accent,
        modifier = modifier.asHeading(),
    )
}

@Composable
fun SpartaCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
    }
}

@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    testTag: String? = null,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = MinTouchTarget).tagged(testTag),
        colors = ButtonDefaults.buttonColors(
            containerColor = SpartaTheme.extras.accent,
            contentColor = SpartaTheme.extras.onAccent,
        ),
    ) { ButtonContent(text, icon) }
}

@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    testTag: String? = null,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = MinTouchTarget).tagged(testTag),
        border = BorderStroke(1.dp, if (enabled) SpartaTheme.extras.accent else MaterialTheme.colorScheme.outlineVariant),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = SpartaTheme.extras.accent),
    ) { ButtonContent(text, icon) }
}

/** Destructive actions use the restrained crimson, never the risk red (which is reserved for confirmed high risk). */
@Composable
fun DestructiveButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    testTag: String? = null,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = MinTouchTarget).tagged(testTag),
        colors = ButtonDefaults.buttonColors(containerColor = SpartaTheme.extras.crimson, contentColor = Color.White),
    ) { ButtonContent(text, icon) }
}

@Composable
fun QuietButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    testTag: String? = null,
) {
    TextButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = MinTouchTarget).tagged(testTag),
        colors = ButtonDefaults.textButtonColors(contentColor = SpartaTheme.extras.accent),
    ) { Text(text) }
}

@Composable
private fun ButtonContent(text: String, icon: ImageVector?) {
    if (icon != null) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
    }
    Text(text, textAlign = TextAlign.Center)
}

private fun Modifier.tagged(tag: String?): Modifier = if (tag == null) this else testTag(tag)

/** Why a control is disabled. Unavailable controls always say so instead of silently doing nothing. */
@Composable
fun DisabledReason(text: String, modifier: Modifier = Modifier, testTag: String? = null) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = SpartaTheme.extras.textSecondary,
        modifier = modifier.tagged(testTag),
    )
}

enum class Tone { NEUTRAL, SAFE, CAUTION, RISK, INFO, DESTRUCTIVE }

@Composable
fun Tone.color(): Color = when (this) {
    Tone.NEUTRAL -> SpartaTheme.extras.textSecondary
    Tone.SAFE -> SpartaTheme.extras.safe
    Tone.CAUTION -> SpartaTheme.extras.caution
    Tone.RISK -> SpartaTheme.extras.risk
    Tone.INFO -> SpartaTheme.extras.accent
    Tone.DESTRUCTIVE -> SpartaTheme.extras.crimson
}

/** A status label that never relies on colour alone: icon and text carry the meaning too. */
@Composable
fun StatusPill(
    label: String,
    tone: Tone,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    testTag: String? = null,
) {
    val color = tone.color()
    Surface(
        modifier = modifier.tagged(testTag),
        shape = MaterialTheme.shapes.small,
        color = SpartaTheme.extras.surface2,
        border = BorderStroke(1.dp, color),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (icon != null) Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurface)
        }
    }
}

@Composable
fun InfoBanner(
    text: String,
    tone: Tone,
    modifier: Modifier = Modifier,
    title: String? = null,
    testTag: String? = null,
) {
    val color = tone.color()
    val icon = when (tone) {
        Tone.SAFE -> Icons.Rounded.CheckCircle
        Tone.CAUTION -> Icons.Rounded.Warning
        Tone.RISK, Tone.DESTRUCTIVE -> Icons.Rounded.Error
        else -> Icons.Rounded.Info
    }
    Surface(
        modifier = modifier.fillMaxWidth().tagged(testTag).politeLiveRegion(),
        shape = MaterialTheme.shapes.medium,
        color = SpartaTheme.extras.surface2,
        border = BorderStroke(1.dp, color),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(22.dp))
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                if (title != null) Text(title, style = MaterialTheme.typography.titleSmall)
                Text(text, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
fun DevIdentityBanner(modifier: Modifier = Modifier) {
    InfoBanner(
        title = stringResource(R.string.common_dev_identity_title),
        text = stringResource(R.string.common_dev_identity_body),
        tone = Tone.CAUTION,
        modifier = modifier,
        testTag = "dev_identity_banner",
    )
}

/** A compact strip shown on every screen while the backend reports a development identity (no real sign-in). */
@Composable
fun DevIdentityStrip(modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier.fillMaxWidth().testTag("dev_identity_banner").politeLiveRegion(),
        color = SpartaTheme.extras.surface2,
        border = BorderStroke(1.dp, SpartaTheme.extras.caution),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(Icons.Rounded.Warning, contentDescription = null, tint = SpartaTheme.extras.caution, modifier = Modifier.size(18.dp))
            Text(stringResource(R.string.common_dev_identity_short), style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
fun LoadingBlock(modifier: Modifier = Modifier, label: String = stringResource(R.string.common_loading)) {
    Box(modifier = modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(
            color = SpartaTheme.extras.accent,
            modifier = Modifier.semantics { contentDescription = label }.testTag("loading_indicator"),
        )
    }
}

@Composable
fun EmptyState(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    testTag: String = "empty_state",
) {
    Column(
        modifier = modifier.fillMaxWidth().padding(24.dp).testTag(testTag),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        SpartaLogo(size = 48.dp, decorative = true)
        Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
        Text(body, style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary, textAlign = TextAlign.Center)
        if (actionLabel != null && onAction != null) SecondaryButton(actionLabel, onAction, testTag = "${testTag}_action")
    }
}

@Composable
fun ErrorBlock(
    message: String,
    modifier: Modifier = Modifier,
    traceId: String? = null,
    onRetry: (() -> Unit)? = null,
    testTag: String = "error_block",
) {
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = 8.dp).testTag(testTag),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        InfoBanner(text = message, tone = Tone.CAUTION)
        if (traceId != null) {
            Text(
                stringResource(R.string.common_trace_id, traceId),
                style = MaterialTheme.typography.bodySmall,
                color = SpartaTheme.extras.textSecondary,
            )
        }
        if (onRetry != null) SecondaryButton(stringResource(R.string.common_retry), onRetry, testTag = "${testTag}_retry")
    }
}

@Composable
fun SwitchRow(
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    enabled: Boolean = true,
    testTag: String? = null,
) {
    val state = stringResource(if (checked) R.string.common_on else R.string.common_off)
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = MinTouchTarget)
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onCheckedChange)
            .semantics { stateDescription = state }
            .tagged(testTag)
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            }
        }
        Switch(checked = checked, onCheckedChange = null, enabled = enabled)
    }
}

/** A mutually exclusive choice rendered as radio rows (each row is a 48dp selectable target). */
@Composable
fun <T> ChoiceGroup(
    options: List<Pair<T, String>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    descriptions: Map<T, String> = emptyMap(),
    enabled: Boolean = true,
    testTagPrefix: String = "choice",
) {
    Column(modifier = modifier.fillMaxWidth().selectableGroup()) {
        options.forEach { (value, label) ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = MinTouchTarget)
                    .selectable(selected = value == selected, enabled = enabled, role = Role.RadioButton, onClick = { onSelect(value) })
                    .testTag("${testTagPrefix}_$value")
                    .padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                RadioButton(selected = value == selected, onClick = null, enabled = enabled)
                Column {
                    Text(label, style = MaterialTheme.typography.bodyLarge)
                    descriptions[value]?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
                    }
                }
            }
        }
    }
}

@Composable
fun KeyValueRow(label: String, value: String, modifier: Modifier = Modifier, testTag: String? = null) {
    Row(
        modifier = modifier.fillMaxWidth().tagged(testTag).semantics(mergeDescendants = true) {},
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary, modifier = Modifier.weight(0.45f))
        Text(value, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.End, modifier = Modifier.weight(0.55f))
    }
}
