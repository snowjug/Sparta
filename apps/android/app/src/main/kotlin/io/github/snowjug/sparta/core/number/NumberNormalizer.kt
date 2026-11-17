package io.github.snowjug.sparta.core.number

/** A phone number in the canonical form used for fingerprints and masking: "+" followed by 7..15 digits. */
data class NormalizedNumber(val e164: String) {
    val digits: String get() = e164.removePrefix("+")
}

/**
 * Mirrors the backend normalizer so device and server fingerprints agree:
 * strip an optional "tel:" prefix, keep a leading "+", "00xxxxxxxx" becomes "+xxxxxxxx", without a "+"
 * exactly 10 digits become "+91" + digits and 11 digits starting with "0" become "+91" + digits[1:]
 * (an India-first product assumption shared with the backend), and 7..15 digits in total are accepted.
 */
object NumberNormalizer {
    private const val MIN_DIGITS = 7
    private const val MAX_DIGITS = 15
    private const val DEFAULT_COUNTRY_CODE = "91"
    private val SEPARATORS = setOf(' ', '-', '.', '/', '(', ')', '\u00A0', '\t')

    /**
     * Normalizes a tel: handle or typed number. Spaces, dashes, dots, slashes and parentheses are ignored and
     * tel: parameters (";phone-context=..") are dropped. Returns null for anything that is not a usable
     * number (letters, "*#" codes, too few or too many digits, empty), which the app treats as a private number.
     */
    fun normalize(raw: String?): NormalizedNumber? {
        if (raw == null) return null
        var text = raw.trim()
        if (text.startsWith("tel:", ignoreCase = true)) text = text.substring(4)
        text = decodePercent(text).substringBefore(';').filter { it !in SEPARATORS }

        val hasPlus = text.startsWith("+")
        var digits = if (hasPlus) text.substring(1) else text
        if (digits.isEmpty() || digits.any { !it.isAsciiDigit() }) return null

        if (!hasPlus) {
            digits = when {
                digits.startsWith("00") -> digits.substring(2)
                digits.length == 10 -> DEFAULT_COUNTRY_CODE + digits
                digits.length == 11 && digits.startsWith("0") -> DEFAULT_COUNTRY_CODE + digits.substring(1)
                else -> digits
            }
        }
        if (digits.length !in MIN_DIGITS..MAX_DIGITS) return null
        return NormalizedNumber("+$digits")
    }

    private fun Char.isAsciiDigit(): Boolean = this in '0'..'9'

    private fun decodePercent(text: String): String {
        if (!text.contains('%')) return text
        val out = StringBuilder(text.length)
        var i = 0
        while (i < text.length) {
            val c = text[i]
            val high = if (c == '%' && i + 2 < text.length) Character.digit(text[i + 1], 16) else -1
            val low = if (high >= 0) Character.digit(text[i + 2], 16) else -1
            if (high >= 0 && low >= 0) {
                out.append((high * 16 + low).toChar())
                i += 3
            } else {
                out.append(c)
                i++
            }
        }
        return out.toString()
    }
}
