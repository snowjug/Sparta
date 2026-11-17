package io.github.snowjug.sparta.core.number

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The backend's `caller_display` algorithm, re-implemented independently in Python to produce these vectors:
 * national < 6 digits -> "•" * max(len - 1, 1) + last digit; otherwise
 * head = first 2, tail = last 2, mid = "•" * (len - 4), split = max(len(mid) - 2, 1),
 * display = "+cc " + head + mid[:split] + " " + mid[split:] + tail.
 */
class NumberMaskerTest {

    @Test
    fun `lead supplied example for an indian mobile number`() {
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("+919876543221"))
    }

    @Test
    fun `ten digit national numbers show two head digits four then two bullets and two tail digits`() {
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("+919812345621"))
        assertEquals("+1 41•••• ••71", NumberMasker.maskNumber("+14155552671"))
        assertEquals("+44 20•••• ••50", NumberMasker.maskNumber("+442071838750"))
        assertEquals("+7 91•••• ••67", NumberMasker.maskNumber("+79161234567"))
    }

    @Test
    fun `other national lengths follow the same split rule`() {
        assertEquals("+353 85••• ••78", NumberMasker.maskNumber("+353851234578"))
        assertEquals("+86 13••••• ••00", NumberMasker.maskNumber("+8613800138000"))
        assertEquals("+91 76•••••• ••76", NumberMasker.maskNumber("+91765432109876"))
        assertEquals("+91 76• •32", NumberMasker.maskNumber("+91765432"))
    }

    @Test
    fun `fewer than six national digits show only the last digit`() {
        assertEquals("+91 ••••5", NumberMasker.maskNumber("+9112345"))
        assertEquals("+353 •••4", NumberMasker.maskNumber("+3531234"))
    }

    @Test
    fun `raw handles are normalized before masking`() {
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("tel:+919876543221"))
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("9876543221"))
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("09876543221"))
        assertEquals("+91 98•••• ••21", NumberMasker.maskNumber("00 91 98765 43221"))
    }

    @Test
    fun `missing private or unusable handles render as private number`() {
        assertEquals("Private number", NumberMasker.maskNumber(null))
        assertEquals("Private number", NumberMasker.maskNumber(""))
        assertEquals("Private number", NumberMasker.maskNumber("abc"))
        assertEquals("Private number", NumberMasker.maskNumber("+123456"))
        assertEquals("Private number", NumberMasker.maskNumber("+1234567890123456"))
        assertEquals("Private number", (null as NormalizedNumber?).masked())
    }

    @Test
    fun `masked extension matches the string api`() {
        assertEquals("+91 98•••• ••21", NumberNormalizer.normalize("+919876543221").masked())
    }

    @Test
    fun `mask never contains the middle digits`() {
        val display = NumberMasker.maskNumber("+919876543221")
        assertFalse(display.contains("7654"))
        assertFalse(display.contains("765"))
        assertFalse(display.contains("9876543221"))
    }

    @Test
    fun `country code lengths`() {
        assertEquals(1, CountryCodes.lengthOf("14155552671"))
        assertEquals(2, CountryCodes.lengthOf("919812345621"))
        assertEquals(3, CountryCodes.lengthOf("353851234578"))
        assertEquals(3, CountryCodes.lengthOf("97150123456"))
        assertEquals(2, CountryCodes.lengthOf("8613800138000"))
        assertEquals(3, CountryCodes.lengthOf("85212345678"))
    }
}
