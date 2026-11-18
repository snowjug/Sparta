package io.github.snowjug.sparta.core.screening

import io.github.snowjug.sparta.core.number.NormalizedNumber
import io.github.snowjug.sparta.core.number.NumberFingerprinter
import io.github.snowjug.sparta.core.number.NumberNormalizer
import io.github.snowjug.sparta.core.number.masked
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

/** Local blocked/trusted fingerprint lists (Room). Never touches the network. */
interface ScreeningLists {
    suspend fun isBlocked(fingerprint: String): Boolean

    suspend fun isTrusted(fingerprint: String): Boolean
}

/** Contacts lookup; implementations return UNAVAILABLE when READ_CONTACTS is not granted or the lookup fails. */
fun interface ContactsLookup {
    suspend fun match(e164: String): ContactMatch
}

/** Supplies the per-owner HMAC key; null until `GET /screening/config` has succeeded once. */
fun interface FingerprinterSource {
    suspend fun current(): NumberFingerprinter?
}

/** The number as far as the device knows it: masked for display, fingerprinted for matching, never raw. */
data class ScreenedNumber(
    val normalized: NormalizedNumber?,
    val fingerprint: String?,
    val display: String,
)

class LocalFactsGatherer(
    private val lists: ScreeningLists,
    private val contacts: ContactsLookup,
    private val fingerprinters: FingerprinterSource,
    /** False unless the owner opted in to "saved contacts are known callers": contacts are not even read otherwise. */
    private val contactsEnabled: suspend () -> Boolean = { true },
) {
    fun identify(handle: String?): NormalizedNumber? = NumberNormalizer.normalize(handle)

    suspend fun fingerprintOf(number: NormalizedNumber?): String? =
        if (number == null) null else fingerprinters.current()?.fingerprint(number)

    suspend fun resolve(handle: String?): ScreenedNumber {
        val normalized = identify(handle)
        return ScreenedNumber(normalized, fingerprintOf(normalized), normalized.masked())
    }

    suspend fun gather(request: ScreeningRequest): ScreeningFacts = coroutineScope {
        val normalized = identify(request.handle)
        val fingerprint = fingerprintOf(normalized)
        val blocked = async { fingerprint != null && lists.isBlocked(fingerprint) }
        val trusted = async { fingerprint != null && lists.isTrusted(fingerprint) }
        val contact = async {
            when {
                normalized == null -> ContactMatch.NOT_FOUND
                !contactsEnabled() -> ContactMatch.UNAVAILABLE
                else -> contacts.match(normalized.e164)
            }
        }
        ScreeningFacts(
            direction = request.direction,
            numberPresent = normalized != null,
            blocked = blocked.await(),
            trusted = trusted.await(),
            contact = contact.await(),
            verification = request.verification,
        )
    }
}
