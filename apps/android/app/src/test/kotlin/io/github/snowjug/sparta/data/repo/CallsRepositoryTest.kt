package io.github.snowjug.sparta.data.repo

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.SpartaDatabase
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.inMemoryDatabase
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CallsRepositoryTest {

    private lateinit var db: SpartaDatabase
    private lateinit var harness: ApiHarness
    private lateinit var repo: CallsRepository
    private var counter = 0

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        harness = ApiHarness()
        repo = CallsRepository(
            api = harness.api,
            cache = db.cachedCalls(),
            json = SpartaJson,
            clock = WallClock { 1_794_909_600_000L },
            ids = IdGenerator { "idem-${++counter}" },
        )
    }

    @After
    fun tearDown() {
        harness.close()
        db.close()
    }

    private fun ids(filter: CallFilter = CallFilter()) = runBlocking { repo.observe(filter).first().map { it.id } }

    @Test
    fun `refresh writes the backend page through to the offline cache`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        val result = repo.refresh(CallFilter())

        assertTrue(result is ApiResult.Success)
        assertEquals("cursor-2", (result as ApiResult.Success).value.nextCursor)
        assertEquals(listOf("call_2", "call_1"), ids())
    }

    @Test
    fun `when the backend is unreachable the cached calls are still served and the error is reported`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.server.shutdown()

        val result = repo.refresh(CallFilter())

        assertTrue(result is ApiResult.Failure)
        assertEquals(ApiErrorKind.OFFLINE, (result as ApiResult.Failure).error.kind)
        assertEquals(listOf("call_2", "call_1"), ids())
    }

    @Test
    fun `offline search and filters work on the cache`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.server.shutdown()

        assertEquals(listOf("call_1"), ids(CallFilter(risk = RiskLevel.HIGH)))
        assertEquals(listOf("call_1"), ids(CallFilter(category = CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION)))
        assertEquals(listOf("call_1"), ids(CallFilter(language = "kn-IN")))
        assertEquals(listOf("call_1"), ids(CallFilter(query = "  OTP ")))
        assertEquals(listOf("call_2"), ids(CallFilter(query = "98")))
        assertEquals(emptyList<String>(), ids(CallFilter(query = "nonexistent words")))
    }

    @Test
    fun `filters are sent to the backend`() = runBlocking {
        harness.enqueueJson("""{"items":[],"next_cursor":null}""")
        repo.refresh(CallFilter(query = "Bank", risk = RiskLevel.HIGH, language = "hi-IN", attentionOnly = true), cursor = "c7")
        val url = harness.takeRequest().requestUrl!!
        assertEquals("bank", url.queryParameter("q"))
        assertEquals("high", url.queryParameter("risk_level"))
        assertEquals("hi-IN", url.queryParameter("language"))
        assertEquals("true", url.queryParameter("attention"))
        assertEquals("c7", url.queryParameter("cursor"))
        assertEquals("50", url.queryParameter("limit"))
    }

    @Test
    fun `an unfiltered refresh removes cached calls the backend no longer lists`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json").replace("\"cursor-2\"", "null"))
        repo.refresh(CallFilter())
        assertEquals(2, ids().size)

        harness.enqueueJson("""{"items":[{"id":"call_2","started_at":"2026-11-17T09:00:00Z"}],"next_cursor":null}""")
        repo.refresh(CallFilter())

        assertEquals(listOf("call_2"), ids())
    }

    @Test
    fun `a filtered refresh never prunes the cache`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.enqueueJson("""{"items":[],"next_cursor":null}""")
        repo.refresh(CallFilter(risk = RiskLevel.HIGH))
        assertEquals(2, ids().size)
    }

    @Test
    fun `detail refreshes the cached list item`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_detail.json"))
        val result = repo.detail("call_01HZX")
        assertTrue(result is ApiResult.Success)
        assertEquals(listOf("call_01HZX"), ids())
        assertTrue(repo.cached("call_01HZX")?.ownerAttentionRequired == true)
    }

    @Test
    fun `owner action returns the honest provider error and does not touch the cache`() = runBlocking {
        harness.enqueueJson(Fixtures.text("error_unsupported.json"), 409)
        val result = repo.takeOver("c1")
        val error = (result as ApiResult.Failure).error
        assertEquals(ApiErrorKind.UNSUPPORTED_BY_PROVIDER, error.kind)
        assertEquals("The simulator provider cannot transfer a real call.", error.message)
        assertEquals(emptyList<String>(), ids())
    }

    @Test
    fun `a successful owner action updates the cached call and sends an idempotency key`() = runBlocking {
        harness.enqueueJson(
            """{"action":{"id":"a1","call_id":"c1","action":"end","simulated":true},"call":{"id":"c1","status":"ended","state":"COMPLETED","started_at":"2026-11-17T10:00:00Z"},"capabilities":{}}""",
        )
        val result = repo.endCall("c1")
        assertTrue(result is ApiResult.Success)
        assertEquals("idem-1", harness.takeRequest().getHeader("Idempotency-Key"))
        assertEquals(listOf("c1"), ids())
    }

    @Test
    fun `block marks the cached call as blocked`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.enqueueJson("""{"id":"blk","number_display":"+91 98•••• ••21"}""")

        val result = repo.block("call_2", "spam")

        assertTrue(result is ApiResult.Success)
        harness.takeRequest()
        val body = harness.takeRequest().body.readUtf8()
        assertEquals("""{"reason":"spam"}""", body)
        assertTrue(repo.cached("call_2")?.blocked == true)
        assertFalse(repo.cached("call_2")?.trusted == true)
    }

    @Test
    fun `a failed block leaves the cache alone`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.enqueueJson("{}", 500)
        repo.block("call_2")
        assertFalse(repo.cached("call_2")?.blocked == true)
    }

    @Test
    fun `feedback is sent with the documented kind`() = runBlocking {
        harness.enqueueJson("""{"id":"fb","call_id":"c1","kind":"wrong_language","note":"was Hindi"}""")
        val result = repo.feedback("c1", FeedbackKind.WRONG_LANGUAGE, "  was Hindi ")
        assertEquals(FeedbackKind.WRONG_LANGUAGE, (result as ApiResult.Success).value.kind)
        assertEquals("""{"kind":"wrong_language","note":"was Hindi"}""", harness.takeRequest().body.readUtf8())
    }

    @Test
    fun `delete content and delete call drop the cached row only after the backend agrees`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())

        harness.enqueueJson("{}", 500)
        assertTrue(repo.deleteContent("call_1") is ApiResult.Failure)
        assertNotNull(repo.cached("call_1"))

        harness.enqueueEmpty(204)
        assertTrue(repo.deleteContent("call_1") is ApiResult.Success)
        assertNull(repo.cached("call_1"))

        harness.enqueueEmpty(204)
        assertTrue(repo.deleteCall("call_2") is ApiResult.Success)
        assertEquals(emptyList<String>(), ids())
    }

    @Test
    fun `delete all clears the cache on success`() = runBlocking {
        harness.enqueueJson(Fixtures.text("call_page.json"))
        repo.refresh(CallFilter())
        harness.enqueueEmpty(204)
        assertTrue(repo.deleteAll() is ApiResult.Success)
        assertEquals(emptyList<String>(), ids())
    }

    @Test
    fun `unreadable cached payloads are skipped instead of crashing the list`() = runBlocking {
        db.cachedCalls().upsertAll(
            listOf(io.github.snowjug.sparta.data.local.CachedCallEntity("bad", 1, "not json", "low", "unknown", ",", "", false, 1)),
        )
        assertEquals(emptyList<String>(), ids())
    }
}
