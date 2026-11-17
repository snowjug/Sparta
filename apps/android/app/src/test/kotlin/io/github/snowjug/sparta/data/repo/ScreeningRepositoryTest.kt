package io.github.snowjug.sparta.data.repo

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ListKind
import io.github.snowjug.sparta.data.local.SpartaDatabase
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.FakeSettingsRepository
import io.github.snowjug.sparta.testutil.Fixtures
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
class ScreeningRepositoryTest {

    private lateinit var db: SpartaDatabase
    private lateinit var harness: ApiHarness
    private lateinit var settings: FakeSettingsRepository
    private lateinit var repo: ScreeningRepository

    private val blockedFp = "02104505014ef8e921b8225bdb991179325c1a15a591448f08f012125a98a8be"
    private val trustedFp = "5d1520e8d73327bd269b10828e5c681d4dc35cb56cf4e04fc51e0370f3de742f"

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        harness = ApiHarness()
        settings = FakeSettingsRepository()
        repo = ScreeningRepository(db.screeningEvents(), db.listEntries(), harness.api, settings, WallClock { 42L }, SpartaJson)
    }

    @After
    fun tearDown() {
        harness.close()
        db.close()
    }

    @Test
    fun `sync stores the fingerprint key forwarding number policy and both lists`() = runBlocking {
        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson(Fixtures.text("screening_lists.json"))

        val result = repo.syncConfigAndLists()

        assertTrue(result is ApiResult.Success)
        val s = settings.value
        assertEquals("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", s.fingerprintSalt)
        assertEquals("+918012345678", s.forwardingNumber)
        assertEquals(UnknownCallerBehavior.SILENCE, s.unknownCallerBehavior)
        assertEquals(TrustedContactBehavior.SCREEN_ANYWAY, s.trustedContactBehavior)
        assertEquals(Strictness.STRICT, s.strictness)
        assertEquals(42L, s.lastSyncAtMs)
        assertNull(s.lastSyncError)
        assertTrue(db.listEntries().isBlocked(blockedFp))
        assertTrue(db.listEntries().isTrusted(trustedFp))
        assertEquals(listOf("+91 98•••• ••21"), repo.observeBlocked().first().map { it.display })
        assertEquals("Dr. Rao", repo.observeTrusted().first().single().label)
    }

    @Test
    fun `the local lists keep working after a failed sync because they are a cache`() = runBlocking {
        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson(Fixtures.text("screening_lists.json"))
        repo.syncConfigAndLists()
        harness.server.shutdown()

        val result = repo.syncConfigAndLists()

        assertEquals(ApiErrorKind.OFFLINE, (result as ApiResult.Failure).error.kind)
        assertEquals("OFFLINE", settings.value.lastSyncError)
        assertTrue(db.listEntries().isBlocked(blockedFp))
        assertEquals("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", settings.value.fingerprintSalt)
    }

    @Test
    fun `an empty backend list replaces the cached entries but device entries survive`() = runBlocking {
        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson(Fixtures.text("screening_lists.json"))
        repo.syncConfigAndLists()
        repo.addDeviceEntry(ListKind.BLOCKED, "device-fp", "+1 41•••• ••71")

        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson("""{"blocked":[],"trusted":[]}""")
        repo.syncConfigAndLists()

        assertFalse(db.listEntries().isBlocked(blockedFp))
        assertFalse(db.listEntries().isTrusted(trustedFp))
        assertTrue(db.listEntries().isBlocked("device-fp"))
    }

    @Test
    fun `backend policy is not adopted while local edits are pending`() = runBlocking {
        settings.update {
            it.copy(
                unknownCallerBehavior = UnknownCallerBehavior.ALLOW,
                pendingPreferencesPatchJson = """{"unknown_caller_behavior":"allow"}""",
            )
        }
        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson(Fixtures.text("screening_lists.json"))
        repo.syncConfigAndLists()
        assertEquals(UnknownCallerBehavior.ALLOW, settings.value.unknownCallerBehavior)
    }

    @Test
    fun `a blank backend key never erases the stored key`() = runBlocking {
        settings.update { it.copy(fingerprintSalt = "existing") }
        harness.enqueueJson("""{"fingerprint_salt":"","forwarding_number":""}""")
        harness.enqueueJson("""{"blocked":[],"trusted":[]}""")
        repo.syncConfigAndLists()
        assertEquals("existing", settings.value.fingerprintSalt)
        assertNull(settings.value.forwardingNumber)
    }

    @Test
    fun `config failure stops before touching the lists`() = runBlocking {
        harness.enqueueJson("{}", 500)
        val result = repo.syncConfigAndLists()
        assertTrue(result is ApiResult.Failure)
        assertEquals(1, harness.server.requestCount)
        assertEquals("SERVER", settings.value.lastSyncError)
    }

    @Test
    fun `device entries are mutually exclusive between blocked and trusted`() = runBlocking {
        repo.addDeviceEntry(ListKind.TRUSTED, "fp", "+91 98•••• ••21", "Mum")
        assertTrue(db.listEntries().isTrusted("fp"))
        repo.addDeviceEntry(ListKind.BLOCKED, "fp", "+91 98•••• ••21")
        assertTrue(db.listEntries().isBlocked("fp"))
        assertFalse(db.listEntries().isTrusted("fp"))
        assertTrue(repo.observeBlocked().first().single().deviceOnly)
    }

    @Test
    fun `removing a device entry is local and immediate`() = runBlocking {
        repo.addDeviceEntry(ListKind.BLOCKED, "fp", "+91 98•••• ••21")
        val entry = repo.observeBlocked().first().single()
        assertTrue(repo.removeEntry(entry) is ApiResult.Success)
        assertFalse(db.listEntries().isBlocked("fp"))
        assertEquals(0, harness.server.requestCount)
    }

    @Test
    fun `removing a backend entry needs the backend and keeps the entry when it fails`() = runBlocking {
        harness.enqueueJson(Fixtures.text("screening_config.json"))
        harness.enqueueJson(Fixtures.text("screening_lists.json"))
        repo.syncConfigAndLists()
        val entry = repo.observeBlocked().first().single()

        harness.enqueueJson("{}", 500)
        assertTrue(repo.removeEntry(entry) is ApiResult.Failure)
        assertTrue(db.listEntries().isBlocked(blockedFp))

        harness.enqueueEmpty(204)
        assertTrue(repo.removeEntry(entry) is ApiResult.Success)
        assertFalse(db.listEntries().isBlocked(blockedFp))
        repeat(3) { harness.takeRequest() }
        val last = harness.takeRequest()
        assertEquals("DELETE", last.method)
        assertEquals("/api/v1/blocked-callers/blk_1", last.path)
    }

    @Test
    fun `pending upload ids and history clearing`() = runBlocking {
        assertEquals(emptyList<String>(), repo.pendingEventIds())
        repo.clearLocalHistory()
        assertEquals(emptyList<String>(), repo.observeEvents().first().map { it.clientEventId })
    }

    @Test
    fun `app settings default to the safest screening behaviour`() {
        val defaults = AppSettings()
        assertEquals(UnknownCallerBehavior.SCREEN, defaults.unknownCallerBehavior)
        assertEquals(TrustedContactBehavior.ALLOW_DIRECTLY, defaults.trustedContactBehavior)
        assertEquals(Strictness.BALANCED, defaults.strictness)
        assertFalse("contacts are only read after the owner opts in", defaults.useContactsAsKnown)
        assertFalse(defaults.backendConfigured)
    }
}
