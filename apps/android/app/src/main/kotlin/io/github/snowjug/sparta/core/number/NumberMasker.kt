package io.github.snowjug.sparta.core.number

/**
 * Masked rendering of a caller number, identical to the backend's `caller_display` so that device-created and
 * server-created display strings look the same, e.g. "+91 98•••• ••21". The raw number is never persisted or
 * uploaded by default.
 *
 * Given E.164 "+{cc}{national}": with fewer than 6 national digits show "•" for all but the last digit (at least one)
 * and then the last digit; otherwise show the first two digits, a bullet run, a space, two more bullets' worth of
 * the run and the last two digits (the run is national.length - 4 bullets, split after max(run - 2, 1)).
 */
object NumberMasker {
    const val PRIVATE_NUMBER = "Private number"
    private const val BULLET = "\u2022"

    /** Accepts an E.164 string or any raw handle; anything unusable renders as "Private number". */
    fun maskNumber(number: String?): String {
        val e164 = NumberNormalizer.normalize(number)?.e164 ?: return PRIVATE_NUMBER
        val digits = e164.removePrefix("+")
        val ccLength = CountryCodes.lengthOf(digits)
        val cc = digits.take(ccLength)
        val national = digits.drop(ccLength)
        return "+$cc ${maskNational(national)}"
    }

    private fun maskNational(national: String): String {
        if (national.length < 6) {
            return BULLET.repeat(maxOf(national.length - 1, 1)) + national.takeLast(1)
        }
        val head = national.take(2)
        val tail = national.takeLast(2)
        val middle = BULLET.repeat(national.length - 4)
        val split = maxOf(middle.length - 2, 1)
        return head + middle.take(split) + " " + middle.drop(split) + tail
    }
}

fun NormalizedNumber?.masked(): String = NumberMasker.maskNumber(this?.e164)

/** Length of the ITU-T E.164 country calling code at the start of a digit string (no libphonenumber needed). */
object CountryCodes {
    private val TWO_DIGIT_PREFIXES: Map<Char, Set<Char>> = mapOf(
        '2' to setOf('0', '7'),
        '3' to setOf('0', '1', '2', '3', '4', '6', '9'),
        '4' to setOf('0', '1', '3', '4', '5', '6', '7', '8', '9'),
        '5' to setOf('1', '2', '3', '4', '5', '6', '7', '8'),
        '6' to setOf('0', '1', '2', '3', '4', '5', '6'),
        '8' to setOf('1', '2', '4', '6'),
        '9' to setOf('0', '1', '2', '3', '4', '5', '8'),
    )

    fun lengthOf(digits: String): Int {
        val first = digits.firstOrNull() ?: return 0
        if (first == '1' || first == '7') return 1
        val second = digits.getOrNull(1) ?: return 1
        return if (second in TWO_DIGIT_PREFIXES[first].orEmpty()) 2 else 3
    }
}
