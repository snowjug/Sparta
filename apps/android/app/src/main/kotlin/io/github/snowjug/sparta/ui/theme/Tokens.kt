package io.github.snowjug.sparta.ui.theme

import kotlin.math.pow

/**
 * Sparta design tokens (shared with the web app). Pure values so contrast can be unit tested.
 * Usage rules: green only for verified/low risk, amber for caution, risk red ONLY for confirmed high risk,
 * crimson (restrained) for destructive actions, bronze accent for primary actions and focus.
 */
data class SpartaPalette(
    val background: Long,
    val surface: Long,
    val surface2: Long,
    val outline: Long,
    val text: Long,
    val textSecondary: Long,
    val accent: Long,
    val onAccent: Long,
    val crimson: Long,
    val safe: Long,
    val caution: Long,
    val risk: Long,
)

object SpartaTokens {
    val Dark = SpartaPalette(
        background = 0xFF0E0F12,
        surface = 0xFF16181D,
        surface2 = 0xFF1E2128,
        outline = 0xFF2A2E37,
        text = 0xFFF2EFEA,
        textSecondary = 0xFFA8A39A,
        accent = 0xFFC8A15A,
        onAccent = 0xFF0E0F12,
        crimson = 0xFFB3342F,
        safe = 0xFF3FB27F,
        caution = 0xFFE0A93B,
        risk = 0xFFE5484D,
    )

    val Light = SpartaPalette(
        background = 0xFFF7F4EE,
        surface = 0xFFFFFFFF,
        surface2 = 0xFFEFEAE0,
        outline = 0xFFD8D1C3,
        text = 0xFF1A1A1A,
        textSecondary = 0xFF5E5A52,
        accent = 0xFF8A6A2B,
        onAccent = 0xFFFFFFFF,
        crimson = 0xFF9E2B27,
        safe = 0xFF1B7F55,
        caution = 0xFF8F6200,
        risk = 0xFFC62A30,
    )
}

/** WCAG 2.x contrast ratio between two opaque ARGB colours. */
object Contrast {
    fun ratio(first: Long, second: Long): Double {
        val a = luminance(first)
        val b = luminance(second)
        val lighter = maxOf(a, b)
        val darker = minOf(a, b)
        return (lighter + 0.05) / (darker + 0.05)
    }

    private fun luminance(argb: Long): Double {
        fun channel(shift: Int): Double {
            val value = ((argb shr shift) and 0xFF) / 255.0
            return if (value <= 0.03928) value / 12.92 else ((value + 0.055) / 1.055).pow(2.4)
        }
        return 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0)
    }
}
