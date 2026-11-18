package io.github.snowjug.sparta.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.snowjug.sparta.data.prefs.ThemeMode
import androidx.compose.foundation.shape.RoundedCornerShape

/** Colours the Material scheme has no slot for. */
@Immutable
data class SpartaExtras(
    val surface2: Color,
    val outline: Color,
    val textSecondary: Color,
    val accent: Color,
    val onAccent: Color,
    val crimson: Color,
    /** Verified / low risk only. */
    val safe: Color,
    val caution: Color,
    /** Confirmed high risk only. */
    val risk: Color,
    val isDark: Boolean,
    /** True when the owner or the system asked for reduced motion: no looping or decorative animation. */
    val reducedMotion: Boolean,
)

val LocalSpartaExtras = staticCompositionLocalOf<SpartaExtras> { error("SpartaTheme missing") }

object SpartaTheme {
    val extras: SpartaExtras
        @Composable
        @ReadOnlyComposable
        get() = LocalSpartaExtras.current
}

private fun Long.c() = Color(this)

private fun SpartaPalette.extras(dark: Boolean, reducedMotion: Boolean) = SpartaExtras(
    surface2 = surface2.c(),
    outline = outline.c(),
    textSecondary = textSecondary.c(),
    accent = accent.c(),
    onAccent = onAccent.c(),
    crimson = crimson.c(),
    safe = safe.c(),
    caution = caution.c(),
    risk = risk.c(),
    isDark = dark,
    reducedMotion = reducedMotion,
)

private fun SpartaPalette.scheme(dark: Boolean): ColorScheme {
    val base = if (dark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = accent.c(),
        onPrimary = onAccent.c(),
        primaryContainer = surface2.c(),
        onPrimaryContainer = text.c(),
        secondary = textSecondary.c(),
        onSecondary = background.c(),
        secondaryContainer = surface2.c(),
        onSecondaryContainer = text.c(),
        tertiary = crimson.c(),
        onTertiary = Color.White,
        background = background.c(),
        onBackground = text.c(),
        surface = surface.c(),
        onSurface = text.c(),
        surfaceVariant = surface2.c(),
        onSurfaceVariant = textSecondary.c(),
        surfaceContainer = surface.c(),
        surfaceContainerHigh = surface2.c(),
        surfaceContainerHighest = surface2.c(),
        outline = textSecondary.c(),
        outlineVariant = outline.c(),
        error = risk.c(),
        onError = Color.White,
        errorContainer = surface2.c(),
        onErrorContainer = text.c(),
    )
}

/** System fonts only. Tabular numerals are applied through [SpartaTextStyles.numeric] for timers and scores. */
private val SpartaTypography = Typography(
    displayLarge = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold, fontSize = 34.sp, lineHeight = 40.sp),
    headlineLarge = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold, fontSize = 28.sp, lineHeight = 34.sp),
    headlineMedium = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold, fontSize = 24.sp, lineHeight = 30.sp),
    headlineSmall = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
    titleLarge = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
    titleMedium = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium, fontSize = 16.sp, lineHeight = 22.sp),
    titleSmall = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp),
    bodyLarge = TextStyle(fontFamily = FontFamily.Default, fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontFamily = FontFamily.Default, fontSize = 14.sp, lineHeight = 21.sp),
    bodySmall = TextStyle(fontFamily = FontFamily.Default, fontSize = 12.sp, lineHeight = 18.sp),
    labelLarge = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp),
    labelMedium = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp),
    labelSmall = TextStyle(fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium, fontSize = 11.sp, lineHeight = 16.sp),
)

object SpartaTextStyles {
    /** Tabular numerals so timers, scores and latencies do not jitter as digits change. */
    val numeric = TextStyle(fontFeatureSettings = "tnum")
}

private val SpartaShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun SpartaTheme(
    themeMode: ThemeMode = ThemeMode.DARK,
    reducedMotion: Boolean = false,
    content: @Composable () -> Unit,
) {
    val dark = when (themeMode) {
        ThemeMode.DARK -> true
        ThemeMode.LIGHT -> false
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
    }
    val palette = if (dark) SpartaTokens.Dark else SpartaTokens.Light
    CompositionLocalProvider(LocalSpartaExtras provides palette.extras(dark, reducedMotion)) {
        MaterialTheme(
            colorScheme = palette.scheme(dark),
            typography = SpartaTypography,
            shapes = SpartaShapes,
            content = content,
        )
    }
}
