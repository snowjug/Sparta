package io.github.snowjug.sparta.core.forwarding

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ForwardingCodesTest {

    @Test
    fun `activation codes follow the gsm conditional forwarding scheme`() {
        assertEquals("**61*+918012345678#", ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "+918012345678"))
        assertEquals("**67*+918012345678#", ForwardingCodes.activation(ForwardingMode.BUSY, "+918012345678"))
        assertEquals("**62*+918012345678#", ForwardingCodes.activation(ForwardingMode.UNREACHABLE, "+918012345678"))
        assertEquals("**61*08012345678#", ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "08012345678"))
    }

    @Test
    fun `deactivation codes`() {
        assertEquals("##61#", ForwardingCodes.deactivation(ForwardingMode.NO_ANSWER))
        assertEquals("##67#", ForwardingCodes.deactivation(ForwardingMode.BUSY))
        assertEquals("##62#", ForwardingCodes.deactivation(ForwardingMode.UNREACHABLE))
        assertEquals("##002#", ForwardingCodes.CANCEL_ALL)
    }

    @Test
    fun `numbers from the backend cannot smuggle other network codes into the dialer`() {
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "+9180*#06#"))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "**21*+911234567890#"))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "+91 80 1234 5678"))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "call me"))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, ""))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, null))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "12345"))
        assertNull(ForwardingCodes.activation(ForwardingMode.NO_ANSWER, "+1234567890123456"))
    }

    @Test
    fun `safe number check`() {
        assertTrue(ForwardingCodes.isSafeNumber("+14155552671"))
        assertTrue(ForwardingCodes.isSafeNumber("4155552671"))
        assertFalse(ForwardingCodes.isSafeNumber("++4155552671"))
        assertFalse(ForwardingCodes.isSafeNumber("4155552671;1"))
    }
}
