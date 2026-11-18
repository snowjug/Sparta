package io.github.snowjug.sparta.core.number

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class NumberNormalizerTest {

    private fun e164(raw: String?) = NumberNormalizer.normalize(raw)?.e164

    // Expected values below were produced by an independent Python implementation of the backend rules.

    @Test
    fun `strips spaces dashes and parentheses and keeps the plus`() {
        assertEquals("+919876543221", e164("+91 98765-43221"))
        assertEquals("+919876543221", e164("(+91) 98765 43221"))
        assertEquals("+14155552671", e164("+1 (415) 555-2671"))
    }

    @Test
    fun `tel prefix is optional and case insensitive and parameters are dropped`() {
        assertEquals("+919876543221", e164("tel:+919876543221"))
        assertEquals("+14155552671", e164("TEL:+14155552671"))
        assertEquals("+919876543221", e164("tel:+919876543221;phone-context=example.invalid"))
        assertEquals("+919876543221", e164("tel:%2B91%2098765%2043221"))
    }

    @Test
    fun `double zero international prefix becomes plus`() {
        assertEquals("+919876543221", e164("00919876543221"))
        assertEquals("+919876543221", e164("0091 98765 43221"))
    }

    @Test
    fun `ten digits without a plus are assumed to be indian`() {
        assertEquals("+919876543221", e164("9876543221"))
        assertEquals("+919876543221", e164("98765 43221"))
    }

    @Test
    fun `eleven digits starting with zero drop the trunk zero and assume india`() {
        assertEquals("+919876543221", e164("09876543221"))
        assertEquals("+919876543221", e164("0 98765 43221"))
    }

    @Test
    fun `a leading plus is kept as typed with no india assumption`() {
        assertEquals("+9876543221", e164("+9876543221"))
    }

    @Test
    fun `other digit counts without a plus are kept and prefixed with plus`() {
        assertEquals("+919876543221", e164("919876543221"))
        assertEquals("+1234567", e164("1234567"))
        assertEquals("+123456789012345", e164("123456789012345"))
    }

    @Test
    fun `seven to fifteen digits are accepted and everything else is unusable`() {
        assertEquals("+1234567", e164("+1234567"))
        assertNull(e164("123456"))
        assertNull(e164("+123456"))
        assertNull(e164("+1234567890123456"))
        assertNull(e164("1234567890123456"))
    }

    @Test
    fun `private or non dialable input is unusable`() {
        assertNull(e164(null))
        assertNull(e164(""))
        assertNull(e164("   "))
        assertNull(e164("tel:"))
        assertNull(e164("+"))
        assertNull(e164("*123#"))
        assertNull(e164("abc"))
        assertNull(e164("sip:alice@example.invalid"))
    }

    @Test
    fun `digits accessor drops the plus`() {
        assertEquals("919876543221", NumberNormalizer.normalize("+919876543221")?.digits)
    }
}
