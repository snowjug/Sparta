package io.github.snowjug.sparta.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/** Pure description of how the visualisation behaves, so the rules are unit tested without a screen. */
object VoiceVisualizerSpec {
    private const val BARS = 36

    val barCount: Int get() = BARS

    /** Looping motion only for live phases, and never when reduced motion is on. */
    fun isAnimated(phase: VoicePhase, reducedMotion: Boolean): Boolean =
        !reducedMotion && (phase == VoicePhase.LISTENING || phase == VoicePhase.ASSISTANT_SPEAKING || phase == VoicePhase.CONNECTING)

    /** Cycle length of the looping animation for [phase], in milliseconds. */
    fun periodMillis(phase: VoicePhase): Int = when (phase) {
        VoicePhase.ASSISTANT_SPEAKING -> 1400
        VoicePhase.LISTENING -> 3200
        VoicePhase.CONNECTING -> 2200
        else -> 3000
    }

    /**
     * Bar height as a fraction (0..1) of the available length. The shape is driven by the call state only: it is an
     * illustration, NOT an audio level meter (the app has no access to call audio).
     */
    fun amplitude(phase: VoicePhase, index: Int, progress: Float, animated: Boolean): Float {
        val position = index.toFloat() / BARS
        val t = if (animated) progress else 0f
        return when (phase) {
            VoicePhase.ASSISTANT_SPEAKING -> {
                val wave = abs(sin(2 * PI * (t * 2 + position * 3))).toFloat()
                val envelope = (0.65 + 0.35 * sin(2 * PI * (t + position * 1.7))).toFloat()
                (0.30f + 0.55f * wave * envelope).coerceIn(0f, 1f)
            }
            VoicePhase.LISTENING -> (0.18f + 0.06f * sin(2 * PI * (t + position)).toFloat()).coerceIn(0f, 1f)
            VoicePhase.CONNECTING -> (0.10f + 0.05f * cos(2 * PI * (t + position * 2)).toFloat()).coerceIn(0f, 1f)
            VoicePhase.INTERRUPTED -> if (index % 2 == 0) 0.34f else 0.12f
            VoicePhase.OWNER_TAKEOVER -> 0.22f
            VoicePhase.ENDED -> 0.08f
        }
    }
}

@Composable
fun VoiceVisualizer(
    phase: VoicePhase,
    modifier: Modifier = Modifier,
    description: String,
    reducedMotion: Boolean = SpartaTheme.extras.reducedMotion,
) {
    val animated = VoiceVisualizerSpec.isAnimated(phase, reducedMotion)
    val progress: State<Float> = if (animated) {
        rememberInfiniteTransition(label = "voice").animateFloat(
            initialValue = 0f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(tween(VoiceVisualizerSpec.periodMillis(phase), easing = LinearEasing), RepeatMode.Restart),
            label = "voice-progress",
        )
    } else {
        rememberUpdatedState(0f)
    }

    val active = SpartaTheme.extras.accent
    val caution = SpartaTheme.extras.caution
    val muted = SpartaTheme.extras.textSecondary
    val color = when (phase) {
        VoicePhase.LISTENING, VoicePhase.ASSISTANT_SPEAKING -> active
        VoicePhase.INTERRUPTED -> caution
        else -> muted
    }

    Canvas(
        modifier = modifier
            .aspectRatio(1f)
            .testTag("voice_visualizer")
            .semantics {
                contentDescription = description
                liveRegion = LiveRegionMode.Polite
            },
    ) {
        val center = Offset(size.width / 2f, size.height / 2f)
        val radius = min(size.width, size.height) / 2f
        val inner = radius * 0.42f
        val maxLength = radius * 0.5f
        val stroke = (radius * 0.045f).coerceAtLeast(2f)
        val bars = VoiceVisualizerSpec.barCount
        for (i in 0 until bars) {
            val angle = (2 * PI * i / bars).toFloat()
            val length = maxLength * VoiceVisualizerSpec.amplitude(phase, i, progress.value, animated)
            val start = Offset(center.x + cos(angle) * inner, center.y + sin(angle) * inner)
            val end = Offset(center.x + cos(angle) * (inner + length), center.y + sin(angle) * (inner + length))
            drawLine(color = color, start = start, end = end, strokeWidth = stroke, cap = StrokeCap.Round)
        }
        drawCircle(color = color.copy(alpha = 0.35f), radius = inner * 0.86f, center = center, style = Stroke(width = stroke))
    }
}
