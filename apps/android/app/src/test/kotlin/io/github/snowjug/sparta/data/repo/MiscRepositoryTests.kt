package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.net.BackendUrlPolicy
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.prefs.DataStoreSettingsRepository
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.BaseUrlProvider
import io.github.snowjug.sparta.data.remote.NetworkFactory
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.FakeSettingsRepository
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.InMemoryPreferencesDataStore
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class RecentCallsTest {

    private fun call(id: String, at: String, display: String = "+91 70•••• ••09") = CallListItemDto(id = id, startedAt = at, callerDisplay = display)

    private fun event(id: String, at: Long, backendCallId: String? = null, display: String = "+91 98•••• ••21", reason: String = "unknown_screened") = ScreeningEventEntity(
        clientEventId = id,
        numberFingerprint = "fp",
        numberDisplay = display,
        decision = "silence",
        reason = reason,
        verificationStatus = null,
        direction = "incoming",
        occurredAtMs = at,
        decisionLatencyMs = 5,
        deadlineMissed = false,
        uploadState = if (backendCallId == null) UploadState.PENDING else UploadState.UPLOADED,
        backendCallId = backendCallId,
    )

    private val t10 = 1_794_909_600_000L // 2026-11-17T10:00:00Z

    @Test
    fun `backend calls and local events are merged newest first`() {
        val merged = RecentCalls.merge(
            calls = listOf(call("c1", "2026-11-17T09:00:00Z")),
            events = listOf(event("e1", t10), event("e0", t10 - 4 * 3_600_000L)),
            filter = CallFilter(),
        )
        assertEquals(listOf("event:e1", "call:c1", "event:e0"), merged.map { it.key })
    }

    @Test
    fun `an uploaded event is hidden once its backend call is in the list`() {
        val merged = RecentCalls.merge(
            calls = listOf(call("c9", "2026-11-17T10:00:00Z")),
            events = listOf(event("e1", t10, backendCallId = "c9")),
            filter = CallFilter(),
        )
        assertEquals(listOf("call:c9"), merged.map { it.key })
    }

    @Test
    fun `an uploaded event stays visible while its backend call is not cached yet`() {
        val merged = RecentCalls.merge(emptyList(), listOf(event("e1", t10, backendCallId = "c9")), CallFilter())
        assertEquals(listOf("event:e1"), merged.map { it.key })
    }

    @Test
    fun `classification filters hide local events because they carry no analysis`() {
        val events = listOf(event("e1", t10))
        assertEquals(emptyList<String>(), RecentCalls.merge(emptyList(), events, CallFilter(language = "hi-IN")).map { it.key })
        assertEquals(emptyList<String>(), RecentCalls.merge(emptyList(), events, CallFilter(attentionOnly = true)).map { it.key })
    }

    @Test
    fun `text search matches the masked number and the reason`() {
        val events = listOf(event("e1", t10, display = "+91 98•••• ••21", reason = "blocked_number"), event("e2", t10 - 1, display = "+1 41•••• ••71"))
        assertEquals(listOf("event:e1"), RecentCalls.merge(emptyList(), events, CallFilter(query = "blocked")).map { it.key })
        assertEquals(listOf("event:e2"), RecentCalls.merge(emptyList(), events, CallFilter(query = "+1 41")).map { it.key })
    }

    @Test
    fun `filter helpers`() {
        assertTrue(CallFilter().isUnfiltered)
        assertTrue(CallFilter(query = "  ").isUnfiltered)
        assertFalse(CallFilter(query = "x").isUnfiltered)
        assertFalse(CallFilter(query = "x").hasClassificationFilters)
        assertTrue(CallFilter(risk = io.github.snowjug.sparta.data.remote.dto.RiskLevel.HIGH).hasClassificationFilters)
    }
}

class SettingsRepositoryTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val scopes = mutableListOf<CoroutineScope>()

    @After
    fun tearDown() = scopes.forEach { it.cancel() }

    private fun repo() = DataStoreSettingsRepository(InMemoryPreferencesDataStore())

    private fun fileRepo(file: File): DataStoreSettingsRepository {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO).also { scopes += it }
        return DataStoreSettingsRepository(PreferenceDataStoreFactory.create(scope = scope, produceFile = { file }))
    }

    @Test
    fun `defaults before anything is saved`() = runBlocking {
        val s = repo().current()
        assertEquals("", s.backendUrl)
        assertFalse(s.onboardingCompleted)
        assertNull(s.fingerprintSalt)
        assertEquals(0L, s.deadlineMissCount)
        assertTrue(s.notifyEscalations)
        assertTrue(s.backgroundSyncEnabled)
        assertFalse(s.contactsPermissionAsked)
    }

    @Test
    fun `values survive reopening the preferences file`() = runBlocking {
        val file = File(folder.root, "roundtrip.preferences_pb")
        fileRepo(file).update {
            it.copy(
                backendUrl = "https://api.example.invalid/",
                onboardingCompleted = true,
                strictness = Strictness.STRICT,
                useContactsAsKnown = true,
                fingerprintSalt = "c2FsdA==",
                forwardingNumber = "+918012345678",
                pendingPreferencesPatchJson = """{"strictness":"strict"}""",
            )
        }
        // Cancelling is asynchronous. Wait until the first DataStore has really released the file, or the second one fails
        // with "multiple DataStores active for the same file" (seen on a loaded CI runner).
        scopes.forEach { it.coroutineContext[Job]?.cancelAndJoin() }
        scopes.clear()

        val reopened = fileRepo(file).current()
        assertEquals("https://api.example.invalid/", reopened.backendUrl)
        assertTrue(reopened.onboardingCompleted)
        assertEquals(Strictness.STRICT, reopened.strictness)
        assertTrue(reopened.useContactsAsKnown)
        assertEquals("c2FsdA==", reopened.fingerprintSalt)
        assertEquals("+918012345678", reopened.forwardingNumber)
        assertTrue(reopened.preferencesDirty)
    }

    @Test
    fun `every field maps both ways`() = runBlocking {
        val repo = repo()
        val written = io.github.snowjug.sparta.data.prefs.AppSettings(
            backendUrl = "https://x.invalid/",
            onboardingCompleted = true,
            unknownCallerBehavior = io.github.snowjug.sparta.core.screening.UnknownCallerBehavior.SILENCE,
            trustedContactBehavior = io.github.snowjug.sparta.core.screening.TrustedContactBehavior.SCREEN_ANYWAY,
            strictness = Strictness.RELAXED,
            useContactsAsKnown = true,
            fingerprintSalt = "salt",
            forwardingNumber = "+1",
            forwardingHelperOpenedAtMs = 5,
            forwardingConfirmedByOwner = true,
            roleRequestDeclined = true,
            contactsPermissionAsked = true,
            notificationsPermissionAsked = true,
            backgroundSyncEnabled = false,
            themeMode = io.github.snowjug.sparta.data.prefs.ThemeMode.LIGHT,
            motionPreference = io.github.snowjug.sparta.core.motion.MotionPreference.REDUCE,
            notifyEscalations = false,
            notifyScreening = false,
            deadlineMissCount = 9,
            lastSyncAtMs = 11,
            lastSyncError = "OFFLINE",
            cachedPreferencesJson = "{}",
            pendingPreferencesPatchJson = "{\"a\":1}",
            cachedStatusJson = "{}",
            cachedStatusAtMs = 12,
        )
        repo.update { written }
        assertEquals(written, repo.current())
    }

    @Test
    fun `clearing a nullable value removes it`() = runBlocking {
        val repo = repo()
        repo.update { it.copy(fingerprintSalt = "x", forwardingNumber = "+1") }
        repo.update { it.copy(fingerprintSalt = null, forwardingNumber = null) }
        assertNull(repo.current().fingerprintSalt)
        assertNull(repo.current().forwardingNumber)
    }

    @Test
    fun `deadline misses increment atomically`() = runBlocking {
        val repo = repo()
        repeat(3) { repo.incrementDeadlineMisses() }
        assertEquals(3L, repo.current().deadlineMissCount)
    }

    @Test
    fun `clear all resets to defaults`() = runBlocking {
        val repo = repo()
        repo.update { it.copy(onboardingCompleted = true, backendUrl = "https://x.invalid/") }
        repo.clearAll()
        assertEquals("", repo.current().backendUrl)
        assertFalse(repo.current().onboardingCompleted)
    }
}

class ConnectionTesterTest {

    private val harnesses = mutableListOf<ApiHarness>()

    @After
    fun tearDown() = harnesses.forEach { it.close() }

    private fun tester(policy: BackendUrlPolicy = BackendUrlPolicy(allowLocalCleartext = true)): Pair<ApiHarness, ConnectionTester> {
        val h = ApiHarness().also { harnesses += it }
        val client = NetworkFactory.createClient(BaseUrlProvider { null })
        var now = 0L
        return h to ConnectionTester(client, SpartaJson, policy, MonotonicClock { now += 25; now })
    }

    private fun url(h: ApiHarness) = "http://${h.server.hostName}:${h.server.port}"

    @Test
    fun `a sparta backend is reachable and reports its status`() = runBlocking {
        val (h, tester) = tester()
        h.enqueueJson(Fixtures.text("system_status.json"))
        val result = tester.test(url(h)) as ConnectionTestResult.Reachable
        assertEquals("0.1.0", result.status.version)
        assertTrue(result.status.telephony.simulated)
        assertEquals(25L, result.roundTripMs)
        assertEquals("/api/v1/system/status", h.takeRequest().path)
    }

    @Test
    fun `an address that is not a sparta backend is reported as such`() = runBlocking {
        val (h, tester) = tester()
        h.enqueueJson("""{"hello":"world"}""")
        val result = tester.test(url(h)) as ConnectionTestResult.Unreachable
        assertEquals(ApiErrorKind.MALFORMED, result.error.kind)
        assertTrue(result.error.message.contains("does not look like a Sparta backend"))
    }

    @Test
    fun `http errors carry the backend message`() = runBlocking {
        val (h, tester) = tester()
        h.enqueueJson("""{"error":{"code":"unauthorized","message":"Sign in required","trace_id":"t"}}""", 401)
        val result = tester.test(url(h)) as ConnectionTestResult.Unreachable
        assertEquals(ApiErrorKind.UNAUTHORIZED, result.error.kind)
        assertEquals("Sign in required", result.error.message)
    }

    @Test
    fun `a dead address is offline`() = runBlocking {
        val (h, tester) = tester()
        val address = url(h)
        h.server.shutdown()
        val result = tester.test(address) as ConnectionTestResult.Unreachable
        assertEquals(ApiErrorKind.OFFLINE, result.error.kind)
    }

    @Test
    fun `invalid urls never hit the network`() = runBlocking {
        val (h, tester) = tester(BackendUrlPolicy(allowLocalCleartext = false))
        val result = tester.test(url(h)) as ConnectionTestResult.InvalidUrl
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, result.problem)
        assertEquals(0, h.server.requestCount)
        assertEquals(BackendUrlProblem.EMPTY, (tester.test("") as ConnectionTestResult.InvalidUrl).problem)
    }
}

class SystemRepositoryOfflineTest {

    @Test
    fun `status is cached for offline display and decoded back`() = runBlocking {
        val h = ApiHarness()
        val settings = FakeSettingsRepository()
        val repo = SystemRepository(h.api, settings, SpartaJson, WallClock { 77L })
        assertNull(repo.cachedStatus.first())

        h.enqueueJson(Fixtures.text("system_status.json"))
        assertTrue(repo.refreshStatus() is ApiResult.Success)
        h.server.shutdown()
        assertTrue(repo.refreshStatus() is ApiResult.Failure)

        val cached = repo.cachedStatus.first()
        assertNotNull(cached)
        assertEquals("0.1.0", cached!!.status.version)
        assertEquals(77L, cached.fetchedAtMs)
        assertTrue(cached.status.telephony.simulated)
        h.close()
    }
}
