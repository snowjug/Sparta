package io.github.snowjug.sparta.core.number

import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class InvalidFingerprintSaltException(message: String) : IllegalArgumentException(message)

/**
 * Privacy-preserving caller identity: hex HMAC-SHA256 over the E.164 number (including the leading "+"),
 * keyed with the base64-decoded `fingerprint_salt` served by `GET /screening/config`.
 */
class NumberFingerprinter(saltBase64: String) {
    private val key: ByteArray = decodeSalt(saltBase64)

    fun fingerprint(number: NormalizedNumber): String = fingerprint(number.e164)

    fun fingerprint(e164: String): String {
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(SecretKeySpec(key, ALGORITHM))
        return mac.doFinal(e164.toByteArray(Charsets.UTF_8)).toHex()
    }

    companion object {
        private const val ALGORITHM = "HmacSHA256"

        private fun decodeSalt(saltBase64: String): ByteArray {
            val text = saltBase64.trim()
            val decoded = try {
                Base64.getDecoder().decode(text)
            } catch (_: IllegalArgumentException) {
                try {
                    Base64.getUrlDecoder().decode(text)
                } catch (_: IllegalArgumentException) {
                    throw InvalidFingerprintSaltException("fingerprint_salt is not valid base64")
                }
            }
            if (decoded.isEmpty()) throw InvalidFingerprintSaltException("fingerprint_salt is empty")
            return decoded
        }

        private fun ByteArray.toHex(): String {
            val out = StringBuilder(size * 2)
            for (b in this) {
                out.append(HEX[(b.toInt() shr 4) and 0xF]).append(HEX[b.toInt() and 0xF])
            }
            return out.toString()
        }

        private val HEX = "0123456789abcdef".toCharArray()
    }
}
