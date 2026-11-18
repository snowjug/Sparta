package io.github.snowjug.sparta.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.core.ui.WidthClass

/** The width class of the window the app is in (split-screen and foldables included), not of the whole display. */
@Composable
fun currentWidthClass(): WidthClass {
    val widthPx = LocalWindowInfo.current.containerSize.width
    val density = LocalDensity.current.density
    return AdaptiveLayout.widthClass((widthPx / density).toInt())
}
