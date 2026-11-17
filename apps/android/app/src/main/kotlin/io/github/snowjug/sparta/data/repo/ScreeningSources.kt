package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.number.NumberFingerprinter
import io.github.snowjug.sparta.core.screening.FingerprinterSource
import io.github.snowjug.sparta.core.screening.ScreeningLists
import io.github.snowjug.sparta.data.local.ListEntryDao
import io.github.snowjug.sparta.data.prefs.SettingsRepository

/** The fast path's blocked/trusted lookups: local Room only, never the network. */
class RoomScreeningLists(private val dao: ListEntryDao) : ScreeningLists {
    override suspend fun isBlocked(fingerprint: String): Boolean = dao.isBlocked(fingerprint)

    override suspend fun isTrusted(fingerprint: String): Boolean = dao.isTrusted(fingerprint)
}

/** Builds the HMAC fingerprinter from the stored salt, caching it until the salt changes. */
class SettingsFingerprinterSource(private val settings: SettingsRepository) : FingerprinterSource {
    @Volatile
    private var cached: Pair<String, NumberFingerprinter>? = null

    override suspend fun current(): NumberFingerprinter? {
        val salt = settings.current().fingerprintSalt?.takeIf { it.isNotBlank() } ?: return null
        cached?.takeIf { it.first == salt }?.let { return it.second }
        val fingerprinter = try {
            NumberFingerprinter(salt)
        } catch (_: IllegalArgumentException) {
            return null
        }
        cached = salt to fingerprinter
        return fingerprinter
    }
}
