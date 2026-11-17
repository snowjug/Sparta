package io.github.snowjug.sparta.core.notify

/** Owner-configured quiet hours ("HH:MM"), local time, possibly wrapping midnight (22:00 -> 07:00). */
object QuietHours {
    fun parseMinutes(hhmm: String?): Int? {
        if (hhmm == null) return null
        val parts = hhmm.split(':')
        if (parts.size != 2) return null
        val hour = parts[0].toIntOrNull() ?: return null
        val minute = parts[1].toIntOrNull() ?: return null
        if (hour !in 0..23 || minute !in 0..59) return null
        return hour * 60 + minute
    }

    /** False when either bound is missing or invalid, and when start equals end (an empty window). */
    fun isQuiet(minuteOfDay: Int, start: String?, end: String?): Boolean {
        val from = parseMinutes(start) ?: return false
        val to = parseMinutes(end) ?: return false
        return when {
            from == to -> false
            from < to -> minuteOfDay in from until to
            else -> minuteOfDay >= from || minuteOfDay < to
        }
    }

    /** "HH:MM" moved by [deltaMinutes], wrapping around midnight. An invalid input is treated as 00:00. */
    fun shift(hhmm: String?, deltaMinutes: Int): String {
        val day = 24 * 60
        val minutes = (((parseMinutes(hhmm) ?: 0) + deltaMinutes) % day + day) % day
        return "%02d:%02d".format(minutes / 60, minutes % 60)
    }
}

/** Everything a notification may say about an escalation. Content lines appear only if the owner allows it. */
data class EscalationNotice(
    val callId: String,
    val callerDisplay: String,
    val purpose: String?,
    val importantLines: List<String>,
    val highRisk: Boolean,
)

object EscalationNoticePolicy {
    const val MAX_AGE_MS = 24L * 60 * 60 * 1000

    /** Only calls that still need the owner and are recent enough to matter produce a notification. */
    fun isFresh(startedAtMs: Long?, nowMs: Long): Boolean = startedAtMs != null && nowMs - startedAtMs in 0..MAX_AGE_MS
}
