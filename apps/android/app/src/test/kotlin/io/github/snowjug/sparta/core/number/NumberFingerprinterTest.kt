package io.github.snowjug.sparta.core.number

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/**
 * Expected values were computed independently with Python:
 * `hmac.new(key, message.encode(), hashlib.sha256).hexdigest()` (RFC 4231 case 1 reproduced the published digest).
 */
class NumberFingerprinterTest {

    private val saltB64 = "c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx" // base64("sparta-test-fingerprint-salt-0001")

    @Test
    fun `fingerprint matches independent python vectors`() {
        val fingerprinter = NumberFingerprinter(saltB64)
        assertEquals("02104505014ef8e921b8225bdb991179325c1a15a591448f08f012125a98a8be", fingerprinter.fingerprint("+919812345621"))
        assertEquals("5d1520e8d73327bd269b10828e5c681d4dc35cb56cf4e04fc51e0370f3de742f", fingerprinter.fingerprint("+14155552671"))
        assertEquals("00ced512e50043970bcec521fc51f7f7c4b42792df24919a67c621de66954dec", fingerprinter.fingerprint("+442071838750"))
    }

    @Test
    fun `normalized formatting variants share one fingerprint`() {
        val fingerprinter = NumberFingerprinter(saltB64)
        val a = fingerprinter.fingerprint(NumberNormalizer.normalize("+91 98123-45621")!!)
        val b = fingerprinter.fingerprint(NumberNormalizer.normalize("tel:%2B919812345621")!!)
        val c = fingerprinter.fingerprint(NumberNormalizer.normalize("0091 (98123) 45621")!!)
        assertEquals("02104505014ef8e921b8225bdb991179325c1a15a591448f08f012125a98a8be", a)
        assertEquals(a, b)
        assertEquals(a, c)
    }

    @Test
    fun `lead example number and its national and prefixed formats share one fingerprint`() {
        val fingerprinter = NumberFingerprinter(saltB64)
        val expected = "407f8b7e7ed883af1ec563265e95acce13a7cbf8386ed67c0535958721dd6ed3"
        for (raw in listOf("+919876543221", "tel:+919876543221", "9876543221", "09876543221", "0091 98765 43221")) {
            assertEquals(raw, expected, fingerprinter.fingerprint(NumberNormalizer.normalize(raw)!!))
        }
    }

    @Test
    fun `different numbers and different salts give different fingerprints`() {
        val fingerprinter = NumberFingerprinter(saltB64)
        assertNotEquals(fingerprinter.fingerprint("+919812345621"), fingerprinter.fingerprint("+919812345622"))
        assertEquals("f44d9eb93ddef65ce50102aae940c3b883766812e55a7f210d9cf8bada5e94ec", fingerprinter.fingerprint("+919812345622"))
        val other = NumberFingerprinter("b3RoZXItc2FsdC1ieXRlcw==")
        assertNotEquals(fingerprinter.fingerprint("+919812345621"), other.fingerprint("+919812345621"))
    }

    @Test
    fun `hmac implementation reproduces RFC 4231 test case 1`() {
        val fingerprinter = NumberFingerprinter("CwsLCwsLCwsLCwsLCwsLCwsLCws=")
        assertEquals("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7", fingerprinter.fingerprint("Hi There"))
    }

    @Test
    fun `url safe base64 salt is accepted`() {
        val fingerprinter = NumberFingerprinter("-__-AQID")
        assertEquals("2a582dc03b199df34365c4c4aa24a8551b8d59f8292de47007013d506fe7680b", fingerprinter.fingerprint("+919812345621"))
    }

    @Test
    fun `invalid or empty salts are rejected`() {
        assertThrows(InvalidFingerprintSaltException::class.java) { NumberFingerprinter("not base64 !!") }
        assertThrows(InvalidFingerprintSaltException::class.java) { NumberFingerprinter("") }
    }
}
