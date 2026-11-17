package io.github.snowjug.sparta.platform

import android.content.Context
import android.net.Uri
import android.provider.ContactsContract
import io.github.snowjug.sparta.core.screening.ContactMatch
import io.github.snowjug.sparta.core.screening.ContactsLookup
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext

/**
 * Asks the platform contacts provider whether the (already normalized) number belongs to a saved contact.
 * Only a yes/no leaves this class: no names, no numbers are read back. Without READ_CONTACTS the answer is
 * UNAVAILABLE, which the decision engine never treats as "not a contact".
 */
class ContentResolverContactsLookup(
    private val context: Context,
    private val permissions: PermissionChecker,
    private val io: CoroutineDispatcher,
) : ContactsLookup {

    override suspend fun match(e164: String): ContactMatch = withContext(io) {
        if (!permissions.isGranted(AppPermission.CONTACTS)) return@withContext ContactMatch.UNAVAILABLE
        try {
            val uri = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(e164))
            val cursor = context.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup._ID), null, null, null)
                ?: return@withContext ContactMatch.UNAVAILABLE
            cursor.use { if (it.moveToFirst()) ContactMatch.FOUND else ContactMatch.NOT_FOUND }
        } catch (_: SecurityException) {
            ContactMatch.UNAVAILABLE
        } catch (_: RuntimeException) {
            ContactMatch.UNAVAILABLE
        }
    }
}
