package io.github.snowjug.sparta.screening

import android.net.Uri
import android.telecom.Call
import android.telecom.CallScreeningService
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.shadow.api.Shadow
import org.robolectric.shadows.ShadowCallScreeningService
import org.robolectric.util.ReflectionHelpers

/**
 * The real service class on the Robolectric platform. The application here is a plain Application (no Hilt), so the
 * dependency graph cannot be built, which is exactly the failure the service must survive.
 */
@RunWith(AndroidJUnit4::class)
class SpartaCallScreeningServiceTest {

    /** `Call.Details` has no public constructor; only the fields the service reads are filled in. */
    private fun callDetails(handle: String?, direction: Int = 0, verification: Int = 0): Call.Details {
        val unsafeClass = Class.forName("sun.misc.Unsafe")
        val unsafe = unsafeClass.getDeclaredField("theUnsafe").apply { isAccessible = true }.get(null)
        val details = unsafeClass.getMethod("allocateInstance", Class::class.java).invoke(unsafe, Call.Details::class.java) as Call.Details
        ReflectionHelpers.setField(details, "mHandle", handle?.let { Uri.parse(it) })
        ReflectionHelpers.setField(details, "mCallDirection", direction)
        ReflectionHelpers.setField(details, "mCallerNumberVerificationStatus", verification)
        return details
    }

    private fun shadowOf(service: CallScreeningService): ShadowCallScreeningService = Shadow.extract(service)

    @Test
    fun `when the dependency graph is unavailable the call is allowed and the service does not crash`() {
        val service = Robolectric.setupService(SpartaCallScreeningService::class.java)
        val details = callDetails("tel:+919876543221")

        service.onScreenCall(details)

        val input = shadowOf(service).lastRespondToCallInput
        assertTrue("the platform must always get an answer", input.isPresent)
        assertSame(details, input.get().callDetails)
        val response = input.get().callResponse
        assertFalse("a failure must never block a call", response.disallowCall)
        assertFalse(response.rejectCall)
        assertFalse("a failure must never silence a call", response.silenceCall)
    }

    @Test
    fun `a hidden number with no handle is also answered`() {
        val service = Robolectric.setupService(SpartaCallScreeningService::class.java)

        service.onScreenCall(callDetails(handle = null))

        val input = shadowOf(service).lastRespondToCallInput
        assertTrue(input.isPresent)
        assertFalse(input.get().callResponse.disallowCall)
    }
}
