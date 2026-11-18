package io.github.snowjug.sparta.data.local

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.testutil.inMemoryDatabase
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RoomDaoTest {

    private lateinit var db: SpartaDatabase

    @Before
    fun setUp() {
        db = inMemoryDatabase()
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun event(id: String, at: Long, state: String = UploadState.PENDING, miss: Boolean = false) = ScreeningEventEntity(
        clientEventId = id,
        numberFingerprint = "fp-$id",
        numberDisplay = "+91 98•••• ••21",
        decision = "silence",
        reason = "unknown_screened",
        verificationStatus = "not_verified",
        direction = "incoming",
        occurredAtMs = at,
        decisionLatencyMs = 12,
        deadlineMissed = miss,
        uploadState = state,
    )

    private fun call(id: String, at: Long, risk: String = "low", category: String = "unknown", langs: String = ",en-IN,", text: String = "", attention: Boolean = false) =
        CachedCallEntity(id, at, "{}", risk, category, langs, text, attention, at)

    private fun entry(kind: String, fp: String, source: String) = ListEntryEntity(kind, fp, if (source == ListSource.BACKEND) "id-$fp" else null, "+91 98•••• ••21", null, source, 1L)

    @Test
    fun `screening events insert ignores duplicates and orders newest first`() = runBlocking {
        val dao = db.screeningEvents()
        assertTrue(dao.insert(event("a", 100)) > 0)
        assertEquals(-1L, dao.insert(event("a", 999)))
        dao.insert(event("b", 300))
        dao.insert(event("c", 200))
        assertEquals(listOf("b", "c", "a"), dao.observeRecent(10).first().map { it.clientEventId })
        assertEquals("b", dao.observeLatest().first()?.clientEventId)
        assertEquals(100L, dao.get("a")?.occurredAtMs)
    }

    @Test
    fun `upload state transitions`() = runBlocking {
        val dao = db.screeningEvents()
        dao.insert(event("a", 1))
        dao.insert(event("b", 2))
        assertEquals(listOf("a", "b"), dao.pending(10).map { it.clientEventId })
        assertEquals(2, dao.observePendingCount().first())

        dao.recordFailedAttempt("a", "OFFLINE")
        assertEquals(1, dao.get("a")?.uploadAttempts)
        assertEquals("OFFLINE", dao.get("a")?.lastUploadError)

        dao.markUploaded("a", "call_9")
        assertEquals(UploadState.UPLOADED, dao.get("a")?.uploadState)
        assertEquals("call_9", dao.get("a")?.backendCallId)
        assertNull(dao.get("a")?.lastUploadError)

        dao.setUploadState("b", UploadState.FAILED, "VALIDATION")
        assertTrue(dao.pending(10).isEmpty())
    }

    @Test
    fun `prune removes only old events`() = runBlocking {
        val dao = db.screeningEvents()
        dao.insert(event("old", 10))
        dao.insert(event("new", 1000))
        assertEquals(1, dao.deleteOlderThan(500))
        assertEquals(listOf("new"), dao.observeRecent(10).first().map { it.clientEventId })
    }

    @Test
    fun `blocked and trusted lookups are exact and independent`() = runBlocking {
        val dao = db.listEntries()
        dao.upsert(entry(ListKind.BLOCKED, "fp1", ListSource.BACKEND))
        dao.upsert(entry(ListKind.TRUSTED, "fp2", ListSource.DEVICE))
        assertTrue(dao.isBlocked("fp1"))
        assertFalse(dao.isTrusted("fp1"))
        assertTrue(dao.isTrusted("fp2"))
        assertFalse(dao.isBlocked("fp2"))
        assertFalse(dao.isBlocked("fp"))
    }

    @Test
    fun `replacing backend entries keeps device entries`() = runBlocking {
        val dao = db.listEntries()
        dao.upsert(entry(ListKind.BLOCKED, "old-backend", ListSource.BACKEND))
        dao.upsert(entry(ListKind.BLOCKED, "mine", ListSource.DEVICE))
        dao.upsert(entry(ListKind.TRUSTED, "trusted-backend", ListSource.BACKEND))

        dao.replaceBackendEntries(ListKind.BLOCKED, listOf(entry(ListKind.BLOCKED, "new-backend", ListSource.BACKEND)))

        val blocked = dao.observe(ListKind.BLOCKED).first().map { it.fingerprint }.toSet()
        assertEquals(setOf("new-backend", "mine"), blocked)
        assertTrue(dao.isTrusted("trusted-backend"))
        assertFalse(dao.isBlocked("old-backend"))
    }

    @Test
    fun `cached call filters combine risk category language query and attention`() = runBlocking {
        val dao = db.cachedCalls()
        dao.upsertAll(
            listOf(
                call("1", 100, risk = "high", category = "possible_financial_impersonation", langs = ",en-IN,kn-IN,", text = "fake bank otp"),
                call("2", 200, risk = "low", category = "legitimate_delivery", langs = ",hi-IN,", text = "swift courier parcel", attention = true),
                call("3", 300, risk = "low", category = "legitimate_delivery", langs = ",en-IN,", text = "pizza delivery"),
            ),
        )
        suspend fun ids(risk: String? = null, category: String? = null, lang: String? = null, q: String? = null, attention: Boolean = false) =
            dao.observeFiltered(risk, category, lang, q, attention, 50).first().map { it.id }

        assertEquals(listOf("3", "2", "1"), ids())
        assertEquals(listOf("1"), ids(risk = "high"))
        assertEquals(listOf("3", "2"), ids(category = "legitimate_delivery"))
        assertEquals(listOf("2"), ids(lang = ",hi-IN,"))
        assertEquals(listOf("3", "1"), ids(lang = ",en-IN,"))
        assertEquals(listOf("2"), ids(q = "COURIER"))
        assertEquals(listOf("2"), ids(attention = true))
        assertEquals(listOf("3"), ids(risk = "low", lang = ",en-IN,"))
        assertEquals(emptyList<String>(), ids(risk = "high", category = "legitimate_delivery"))
        assertEquals(1, dao.observeAttentionCount().first())
    }

    @Test
    fun `language filter does not match a prefix of another tag`() = runBlocking {
        val dao = db.cachedCalls()
        dao.upsertAll(listOf(call("1", 1, langs = ",en-IN,"), call("2", 2, langs = ",en,")))
        assertEquals(listOf("2"), dao.observeFiltered(null, null, ",en,", null, false, 10).first().map { it.id })
    }

    @Test
    fun `missing since prunes only calls the backend no longer lists`() = runBlocking {
        val dao = db.cachedCalls()
        dao.upsertAll(listOf(call("keep", 500), call("gone", 600), call("older", 100)))
        assertEquals(1, dao.deleteMissingSince(400, listOf("keep")))
        assertEquals(setOf("keep", "older"), dao.observeFiltered(null, null, null, null, false, 10).first().map { it.id }.toSet())
    }

    @Test
    fun `notified items are remembered once`() = runBlocking {
        val dao = db.notifiedItems()
        assertFalse(dao.contains("esc_1"))
        assertTrue(dao.insert(NotifiedItemEntity("esc_1", 5)) > 0)
        assertEquals(-1L, dao.insert(NotifiedItemEntity("esc_1", 6)))
        assertTrue(dao.contains("esc_1"))
    }
}
