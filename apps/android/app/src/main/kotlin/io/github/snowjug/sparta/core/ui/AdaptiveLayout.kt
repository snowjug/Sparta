package io.github.snowjug.sparta.core.ui

/** Material window width classes (compact < 600dp, medium < 840dp, expanded otherwise). */
enum class WidthClass { COMPACT, MEDIUM, EXPANDED }

object AdaptiveLayout {
    const val MEDIUM_MIN_DP = 600
    const val EXPANDED_MIN_DP = 840

    /** Widest a single column of text should grow: long lines are hard to read and reach. */
    const val CONTENT_MAX_WIDTH_DP = 720

    /** Width of the list pane when the calls list and a call's detail are shown side by side. */
    const val LIST_PANE_WIDTH_DP = 400

    fun widthClass(widthDp: Int): WidthClass = when {
        widthDp < MEDIUM_MIN_DP -> WidthClass.COMPACT
        widthDp < EXPANDED_MIN_DP -> WidthClass.MEDIUM
        else -> WidthClass.EXPANDED
    }

    /** Phones get a bottom bar; tablets, foldables and landscape get a rail. */
    fun usesNavigationRail(width: WidthClass): Boolean = width != WidthClass.COMPACT

    /** Only expanded windows have room for list and detail at once. */
    fun usesTwoPane(width: WidthClass): Boolean = width == WidthClass.EXPANDED
}
