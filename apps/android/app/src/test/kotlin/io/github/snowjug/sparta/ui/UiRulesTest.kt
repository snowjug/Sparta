package io.github.snowjug.sparta.ui

import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.core.nav.DeepLink
import io.github.snowjug.sparta.core.nav.DeepLinks
import io.github.snowjug.sparta.core.nav.Routes
import io.github.snowjug.sparta.core.notify.QuietHours
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.ui.components.VoiceVisualizerSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveLayoutTest {
    @Test
    fun `window width classes follow the material breakpoints`() {
        assertEquals(WidthClass.COMPACT, AdaptiveLayout.widthClass(320))
        assertEquals(WidthClass.COMPACT, AdaptiveLayout.widthClass(599))
        assertEquals(WidthClass.MEDIUM, AdaptiveLayout.widthClass(600))
        assertEquals(WidthClass.MEDIUM, AdaptiveLayout.widthClass(839))
        assertEquals(WidthClass.EXPANDED, AdaptiveLayout.widthClass(840))
        assertEquals(WidthClass.EXPANDED, AdaptiveLayout.widthClass(1280))
    }

    @Test
    fun `phones get a bottom bar and wider windows a rail and only expanded windows get two panes`() {
        assertFalse(AdaptiveLayout.usesNavigationRail(WidthClass.COMPACT))
        assertTrue(AdaptiveLayout.usesNavigationRail(WidthClass.MEDIUM))
        assertTrue(AdaptiveLayout.usesNavigationRail(WidthClass.EXPANDED))
        assertFalse(AdaptiveLayout.usesTwoPane(WidthClass.MEDIUM))
        assertTrue(AdaptiveLayout.usesTwoPane(WidthClass.EXPANDED))
    }
}

class RoutesTest {
    @Test
    fun `every deep link maps to a route and back through the real parser`() {
        assertEquals("incoming/call_1", Routes.forLink(DeepLinks.parse(DeepLinks.incoming("call_1"))!!))
        assertEquals("call/call_1", Routes.forLink(DeepLinks.parse(DeepLinks.detail("call_1"))!!))
        assertEquals("live/call_1", Routes.forLink(DeepLinks.parse(DeepLinks.live("call_1"))!!))
        assertEquals("event/evt-9", Routes.forLink(DeepLinks.parse(DeepLinks.screeningEvent("evt-9"))!!))
        assertEquals("event/e1", Routes.forLink(DeepLink.ScreeningEvent("e1")))
    }

    @Test
    fun `ids that are not path safe are percent encoded so they cannot change the route`() {
        assertEquals("call/a%2Fb%3Fc", Routes.call("a/b?c"))
        assertEquals("call/caf%C3%A9", Routes.call("caf\u00e9"))
        assertEquals("call/call_77-x.y~z", Routes.call("call_77-x.y~z"))
    }

    @Test
    fun `only the five tabs show the bottom bar`() {
        assertEquals(listOf("status", "calls", "studio", "privacy", "diagnostics"), Routes.topLevel)
        assertTrue(Routes.isTopLevel(Routes.CALLS))
        assertFalse(Routes.isTopLevel(Routes.CALL_PATTERN))
        assertFalse(Routes.isTopLevel(Routes.ONBOARDING))
        assertFalse(Routes.isTopLevel(null))
    }
}

class QuietHoursShiftTest {
    @Test
    fun `shifting moves by half hours and wraps around midnight both ways`() {
        assertEquals("22:30", QuietHours.shift("22:00", 30))
        assertEquals("21:30", QuietHours.shift("22:00", -30))
        assertEquals("00:00", QuietHours.shift("23:30", 30))
        assertEquals("23:30", QuietHours.shift("00:00", -30))
        assertEquals("07:00", QuietHours.shift("07:00", 24 * 60))
    }

    @Test
    fun `an invalid time is treated as midnight instead of crashing`() {
        assertEquals("00:30", QuietHours.shift(null, 30))
        assertEquals("00:30", QuietHours.shift("25:99", 30))
    }

    @Test
    fun `a shifted window still wraps midnight correctly`() {
        val start = QuietHours.shift("22:00", 30)
        val end = QuietHours.shift("07:00", -30)
        assertTrue(QuietHours.isQuiet(23 * 60, start, end))
        assertTrue(QuietHours.isQuiet(6 * 60, start, end))
        assertFalse(QuietHours.isQuiet(12 * 60, start, end))
    }
}

class FormattersAgoTest {
    private val now = 1_000_000_000_000L

    @Test
    fun `relative time uses the largest whole unit`() {
        assertEquals(Ago.JustNow, Formatters.ago(now, now - 59_999))
        assertEquals(Ago.Minutes(1), Formatters.ago(now, now - 60_000))
        assertEquals(Ago.Minutes(59), Formatters.ago(now, now - 59 * 60_000L))
        assertEquals(Ago.Hours(1), Formatters.ago(now, now - 3_600_000))
        assertEquals(Ago.Hours(23), Formatters.ago(now, now - 23 * 3_600_000L))
        assertEquals(Ago.Days(1), Formatters.ago(now, now - 86_400_000))
        assertEquals(Ago.Days(9), Formatters.ago(now, now - 9 * 86_400_000L))
    }

    @Test
    fun `a missing time is unknown and a time in the future reads as just now`() {
        assertEquals(Ago.Unknown, Formatters.ago(now, null))
        assertEquals(Ago.JustNow, Formatters.ago(now, now + 5 * 60_000L))
    }

    @Test
    fun `durations and percentages are formatted without locale surprises`() {
        assertEquals("1:10", Formatters.duration(70_000))
        assertEquals("1:02:05", Formatters.duration(3_725_000))
        assertEquals("--:--", Formatters.duration(null))
        assertEquals(93, Formatters.percent(0.934))
        assertEquals(100, Formatters.percent(4.0))
        assertEquals(0, Formatters.percent(-1.0))
    }
}

class VoiceVisualizerSpecTest {
    @Test
    fun `nothing loops when reduced motion is on whatever the call is doing`() {
        VoicePhase.entries.forEach { phase ->
            assertFalse("$phase must not animate under reduced motion", VoiceVisualizerSpec.isAnimated(phase, reducedMotion = true))
        }
    }

    @Test
    fun `only live phases animate otherwise and ended or taken over calls are still`() {
        assertTrue(VoiceVisualizerSpec.isAnimated(VoicePhase.LISTENING, false))
        assertTrue(VoiceVisualizerSpec.isAnimated(VoicePhase.ASSISTANT_SPEAKING, false))
        assertFalse(VoiceVisualizerSpec.isAnimated(VoicePhase.ENDED, false))
        assertFalse(VoiceVisualizerSpec.isAnimated(VoicePhase.OWNER_TAKEOVER, false))
        assertFalse(VoiceVisualizerSpec.isAnimated(VoicePhase.INTERRUPTED, false))
    }

    @Test
    fun `a still frame is identical whatever the animation clock says and always inside the unit range`() {
        VoicePhase.entries.forEach { phase ->
            for (index in 0 until VoiceVisualizerSpec.barCount) {
                val still = VoiceVisualizerSpec.amplitude(phase, index, progress = 0.73f, animated = false)
                assertEquals(VoiceVisualizerSpec.amplitude(phase, index, progress = 0.1f, animated = false), still, 0f)
                assertTrue(still in 0f..1f)
                assertTrue(VoiceVisualizerSpec.amplitude(phase, index, 0.4f, animated = true) in 0f..1f)
            }
        }
    }

    @Test
    fun `speaking looks more energetic than listening`() {
        val speaking = (0 until VoiceVisualizerSpec.barCount).sumOf { VoiceVisualizerSpec.amplitude(VoicePhase.ASSISTANT_SPEAKING, it, 0.25f, true).toDouble() }
        val listening = (0 until VoiceVisualizerSpec.barCount).sumOf { VoiceVisualizerSpec.amplitude(VoicePhase.LISTENING, it, 0.25f, true).toDouble() }
        assertTrue(speaking > listening)
    }
}
