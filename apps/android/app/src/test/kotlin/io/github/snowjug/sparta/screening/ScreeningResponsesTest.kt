package io.github.snowjug.sparta.screening

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningReason
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.util.ReflectionHelpers

@RunWith(AndroidJUnit4::class)
class ScreeningResponsesTest {

    private val originalSdk = Build.VERSION.SDK_INT

    @After
    fun restoreSdk() {
        ReflectionHelpers.setStaticField(Build.VERSION::class.java, "SDK_INT", originalSdk)
    }

    private fun decision(action: ScreeningAction) = ScreeningDecision(action, ScreeningReason.UNKNOWN_SCREENED)

    @Test
    fun `allow leaves every flag at the platform default`() {
        val response = ScreeningResponses.toCallResponse(decision(ScreeningAction.ALLOW))
        assertFalse(response.disallowCall)
        assertFalse(response.rejectCall)
        assertFalse(response.silenceCall)
        assertFalse(response.skipNotification)
    }

    @Test
    fun `silence only silences the ringer`() {
        val response = ScreeningResponses.toCallResponse(decision(ScreeningAction.SILENCE))
        assertTrue(response.silenceCall)
        assertFalse("silenced calls still reach the phone and the call log", response.disallowCall)
        assertFalse(response.rejectCall)
    }

    @Test
    fun `reject disallows and rejects and skips the system missed call notification`() {
        val response = ScreeningResponses.toCallResponse(decision(ScreeningAction.REJECT))
        assertTrue(response.disallowCall)
        assertTrue("reject requires disallow", response.rejectCall)
        assertTrue(response.skipNotification)
        assertFalse("the rejected call stays visible in the phone's call history", response.skipCallLog)
        assertFalse(response.silenceCall)
    }

    @Test
    fun `silence is downgraded to allow on android 9 and lower where it does not exist`() {
        ReflectionHelpers.setStaticField(Build.VERSION::class.java, "SDK_INT", 28)
        val response = ScreeningResponses.toCallResponse(decision(ScreeningAction.SILENCE))
        assertFalse(response.silenceCall)
        assertFalse(response.disallowCall)
        assertEquals(28, Build.VERSION.SDK_INT)
    }
}
