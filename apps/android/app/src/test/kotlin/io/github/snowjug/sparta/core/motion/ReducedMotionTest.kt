package io.github.snowjug.sparta.core.motion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReducedMotionTest {

    @Test
    fun `system animator scale of zero means reduced motion when following the system`() {
        assertTrue(ReducedMotion.isReduced(0f, MotionPreference.FOLLOW_SYSTEM))
    }

    @Test
    fun `normal or longer animator scales keep motion when following the system`() {
        assertFalse(ReducedMotion.isReduced(1f, MotionPreference.FOLLOW_SYSTEM))
        assertFalse(ReducedMotion.isReduced(0.5f, MotionPreference.FOLLOW_SYSTEM))
        assertFalse(ReducedMotion.isReduced(2f, MotionPreference.FOLLOW_SYSTEM))
    }

    @Test
    fun `unreadable scale defaults to full motion unless the owner chose otherwise`() {
        assertFalse(ReducedMotion.isReduced(null, MotionPreference.FOLLOW_SYSTEM))
        assertTrue(ReducedMotion.isReduced(null, MotionPreference.REDUCE))
    }

    @Test
    fun `owner preference overrides the system value`() {
        assertTrue(ReducedMotion.isReduced(1f, MotionPreference.REDUCE))
        assertFalse(ReducedMotion.isReduced(0f, MotionPreference.FULL))
    }

    @Test
    fun `preference wire values round trip and unknown values follow the system`() {
        for (preference in MotionPreference.entries) {
            assertEquals(preference, MotionPreference.fromWire(preference.wire))
        }
        assertEquals(MotionPreference.FOLLOW_SYSTEM, MotionPreference.fromWire("bogus"))
        assertEquals(MotionPreference.FOLLOW_SYSTEM, MotionPreference.fromWire(null))
    }
}
