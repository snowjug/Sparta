package io.github.snowjug.sparta.ui.theme

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContrastTest {

    private val white = 0xFFFFFFFF

    private fun assertAa(label: String, foreground: Long, background: Long, minimum: Double = 4.5) {
        val ratio = Contrast.ratio(foreground, background)
        assertTrue("$label contrast $ratio is below $minimum", ratio >= minimum)
    }

    private fun check(name: String, p: SpartaPalette) {
        assertAa("$name text/background", p.text, p.background)
        assertAa("$name text/surface", p.text, p.surface)
        assertAa("$name text/surface2", p.text, p.surface2)
        assertAa("$name secondary/background", p.textSecondary, p.background)
        assertAa("$name secondary/surface", p.textSecondary, p.surface)
        assertAa("$name secondary/surface2", p.textSecondary, p.surface2)
        assertAa("$name onAccent/accent", p.onAccent, p.accent)
        assertAa("$name accent/background (focus, links)", p.accent, p.background)
        assertAa("$name accent/surface", p.accent, p.surface)
        assertAa("$name safe/surface", p.safe, p.surface)
        assertAa("$name caution/surface", p.caution, p.surface)
        assertAa("$name risk/surface", p.risk, p.surface)
        assertAa("$name white on destructive", white, p.crimson)
    }

    @Test
    fun `dark palette meets WCAG AA for every text and control pair`() = check("dark", SpartaTokens.Dark)

    @Test
    fun `light palette meets WCAG AA for every text and control pair`() = check("light", SpartaTokens.Light)

    @Test
    fun `contrast formula reproduces the WCAG extremes`() {
        assertEquals(21.0, Contrast.ratio(0xFF000000, 0xFFFFFFFF), 0.01)
        assertEquals(1.0, Contrast.ratio(0xFF808080, 0xFF808080), 0.0001)
    }

    @Test
    fun `brand tokens are the shared design values`() {
        assertEquals(0xFF0E0F12, SpartaTokens.Dark.background)
        assertEquals(0xFF16181D, SpartaTokens.Dark.surface)
        assertEquals(0xFF1E2128, SpartaTokens.Dark.surface2)
        assertEquals(0xFF2A2E37, SpartaTokens.Dark.outline)
        assertEquals(0xFFF2EFEA, SpartaTokens.Dark.text)
        assertEquals(0xFFA8A39A, SpartaTokens.Dark.textSecondary)
        assertEquals(0xFFC8A15A, SpartaTokens.Dark.accent)
        assertEquals(0xFFB3342F, SpartaTokens.Dark.crimson)
        assertEquals(0xFF3FB27F, SpartaTokens.Dark.safe)
        assertEquals(0xFFE0A93B, SpartaTokens.Dark.caution)
        assertEquals(0xFFE5484D, SpartaTokens.Dark.risk)
        assertEquals(0xFFF7F4EE, SpartaTokens.Light.background)
        assertEquals(0xFFFFFFFF, SpartaTokens.Light.surface)
        assertEquals(0xFF1A1A1A, SpartaTokens.Light.text)
        assertEquals(0xFF8A6A2B, SpartaTokens.Light.accent)
    }
}
