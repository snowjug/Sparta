package io.github.snowjug.sparta.core.time

import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.UUID

fun interface WallClock {
    fun nowMs(): Long

    companion object {
        val System = WallClock { java.lang.System.currentTimeMillis() }
    }
}

fun interface IdGenerator {
    fun newId(): String

    companion object {
        val Random = IdGenerator { UUID.randomUUID().toString() }
    }
}

/** Local time of day in minutes since midnight (used for quiet hours). */
fun interface MinuteOfDayProvider {
    fun minuteOfDay(): Int
}

object Timestamps {
    /** Parses the backend's ISO-8601 UTC timestamps ("Z" or numeric offsets, with or without fractions). */
    fun parseMs(text: String?): Long? {
        if (text.isNullOrBlank()) return null
        return try {
            Instant.parse(text).toEpochMilli()
        } catch (_: DateTimeParseException) {
            try {
                OffsetDateTime.parse(text).toInstant().toEpochMilli()
            } catch (_: DateTimeParseException) {
                null
            }
        }
    }

    /** ISO-8601 UTC with a trailing "Z"; the same input always yields the same string (idempotent uploads). */
    fun formatIsoUtc(epochMs: Long): String = DateTimeFormatter.ISO_INSTANT.format(Instant.ofEpochMilli(epochMs))
}
