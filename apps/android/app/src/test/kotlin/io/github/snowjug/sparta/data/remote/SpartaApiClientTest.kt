package io.github.snowjug.sparta.data.remote

import io.github.snowjug.sparta.data.remote.dto.BlockRequestDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.FeedbackRequestDto
import io.github.snowjug.sparta.data.remote.dto.ScreeningEventRequestDto
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.Fixtures
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpartaApiClientTest {

    private val harnesses = mutableListOf<ApiHarness>()

    private fun harness(
        tokens: AuthTokenProvider = NoAuthTokenProvider,
        basePath: String = "/",
        configure: okhttp3.OkHttpClient.Builder.() -> Unit = {},
    ) = ApiHarness(tokens, basePath, configure = configure).also { harnesses += it }

    @After
    fun tearDown() {
        harnesses.forEach { it.close() }
    }

    private fun <T> ApiResult<T>.success(): T {
        assertTrue("expected success but was $this", this is ApiResult.Success)
        return (this as ApiResult.Success).value
    }

    private fun <T> ApiResult<T>.failure(): ApiError {
        assertTrue("expected failure but was $this", this is ApiResult.Failure)
        return (this as ApiResult.Failure).error
    }

    // ---- success paths ----

    @Test
    fun `system status success hits the documented path with correlation headers`() = runBlocking {
        val h = harness()
        h.enqueueJson(Fixtures.text("system_status.json"))
        val status = safeApiCall { h.api.systemStatus() }.success()
        assertEquals("0.1.0", status.version)

        val request = h.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v1/system/status", request.path)
        assertEquals("application/json", request.getHeader("Accept"))
        assertEquals("SpartaAndroidTest/1.0", request.getHeader("User-Agent"))
        assertNotNull(request.getHeader("X-Request-ID"))
        assertNull("dev backends need no credentials", request.getHeader("Authorization"))
    }

    @Test
    fun `a base url with a path prefix is honoured`() = runBlocking {
        val h = harness(basePath = "/sparta/")
        h.enqueueJson(Fixtures.text("system_status.json"))
        safeApiCall { h.api.systemStatus() }.success()
        assertEquals("/sparta/api/v1/system/status", h.takeRequest().path)
    }

    @Test
    fun `call list sends only the filters that are set`() = runBlocking {
        val h = harness()
        h.enqueueJson(Fixtures.text("call_page.json"))
        val page = safeApiCall {
            h.api.calls(query = "bank", riskLevel = "high", category = "telemarketing", language = "hi-IN", attention = true, limit = 50, cursor = "c1")
        }.success()
        assertEquals(2, page.items.size)

        val url = h.takeRequest().requestUrl!!
        assertEquals("/api/v1/calls", url.encodedPath)
        assertEquals("bank", url.queryParameter("q"))
        assertEquals("high", url.queryParameter("risk_level"))
        assertEquals("telemarketing", url.queryParameter("category"))
        assertEquals("hi-IN", url.queryParameter("language"))
        assertEquals("true", url.queryParameter("attention"))
        assertEquals("50", url.queryParameter("limit"))
        assertEquals("c1", url.queryParameter("cursor"))
        assertNull(url.queryParameter("status"))
    }

    @Test
    fun `unset filters are omitted entirely`() = runBlocking {
        val h = harness()
        h.enqueueJson(Fixtures.text("call_page.json"))
        safeApiCall { h.api.calls() }.success()
        assertEquals("/api/v1/calls", h.takeRequest().path)
    }

    @Test
    fun `bearer token is attached only when a provider supplies one`() = runBlocking {
        val h = harness(tokens = AuthTokenProvider { "test-token" })
        h.enqueueJson(Fixtures.text("system_status.json"))
        safeApiCall { h.api.systemStatus() }.success()
        assertEquals("Bearer test-token", h.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `delete endpoints accept 204 with no body`() = runBlocking {
        val h = harness()
        h.enqueueEmpty(204)
        h.enqueueEmpty(204)
        safeApiCall { h.api.deleteAllCalls() }.success()
        safeApiCall { h.api.deleteCallContent("c1") }.success()
        assertEquals("DELETE /api/v1/calls", h.takeRequest().let { "${it.method} ${it.path}" })
        assertEquals("DELETE /api/v1/calls/c1/content", h.takeRequest().let { "${it.method} ${it.path}" })
    }

    // ---- request bodies ----

    @Test
    fun `feedback and block bodies carry exactly the documented fields`() = runBlocking {
        val h = harness()
        h.enqueueJson("""{"id":"fb1","call_id":"c1","kind":"was_spam","note":null,"created_at":"2026-11-17T10:00:00Z"}""")
        h.enqueueJson("""{"id":"b1","number_display":"+91 98•••• ••21"}""")
        safeApiCall { h.api.feedback("c1", FeedbackRequestDto(FeedbackKind.WAS_SPAM)) }.success()
        safeApiCall { h.api.blockCaller("c1", "key-1", BlockRequestDto()) }.success()

        val feedback = h.takeRequest()
        assertEquals("/api/v1/calls/c1/feedback", feedback.path)
        assertEquals("""{"kind":"was_spam"}""", feedback.body.readUtf8())
        val block = h.takeRequest()
        assertEquals("/api/v1/calls/c1/block", block.path)
        assertEquals("key-1", block.getHeader("Idempotency-Key"))
        assertEquals("{}", block.body.readUtf8())
    }

    @Test
    fun `owner actions post an empty object and an idempotency key`() = runBlocking {
        val h = harness()
        h.enqueueJson(
            """{"action":{"id":"a1","call_id":"c1","action":"takeover","simulated":true},"call":{"id":"c1"},"capabilities":{"can_take_over":true}}""",
        )
        val result = safeApiCall { h.api.takeover("c1", "idem-9") }.success()
        assertTrue(result.action.simulated)
        val request = h.takeRequest()
        assertEquals("/api/v1/calls/c1/takeover", request.path)
        assertEquals("idem-9", request.getHeader("Idempotency-Key"))
        assertEquals("{}", request.body.readUtf8())
    }

    @Test
    fun `screening event upload sends a fingerprint and masked display and never a raw number`() = runBlocking {
        val h = harness()
        h.enqueueJson(
            """{"id":"call_2","provider":"android_screening","mode":"screening_only","simulated":false,"status":"ended","state":"COMPLETED","started_at":"2026-11-17T10:00:00Z","caller_display":"+91 98•••• ••21"}""",
        )
        val body = ScreeningEventRequestDto(
            clientEventId = "7d3f0a52-0000-4000-8000-000000000001",
            numberFingerprint = "02104505014ef8e921b8225bdb991179325c1a15a591448f08f012125a98a8be",
            numberDisplay = "+91 98•••• ••21",
            decision = "silence",
            reason = "unknown_screened",
            verificationStatus = "not_verified",
            direction = "incoming",
            occurredAt = "2026-11-17T10:00:00Z",
        )
        safeApiCall { h.api.postScreeningEvent(body.clientEventId, body) }.success()

        val request = h.takeRequest()
        assertEquals("/api/v1/screening/events", request.path)
        assertEquals(body.clientEventId, request.getHeader("Idempotency-Key"))
        val sent = SpartaJson.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals(
            setOf("client_event_id", "number_fingerprint", "number_display", "decision", "reason", "verification_status", "direction", "occurred_at"),
            sent.keys,
        )
        assertEquals("silence", sent.getValue("decision").jsonPrimitive.content)
        assertFalse(sent.keys.any { it.contains("number") && it !in setOf("number_fingerprint", "number_display") })
    }

    @Test
    fun `preferences round trip unknown fields untouched`() = runBlocking {
        val h = harness()
        val document = """{"strictness":"balanced","retention":{"transcript_retention_days":7},"future_field":{"a":1}}"""
        h.enqueueJson(document)
        h.enqueueJson(document)
        val loaded: JsonObject = safeApiCall { h.api.preferences() }.success()
        safeApiCall { h.api.putPreferences(loaded) }.success()
        h.takeRequest()
        val put = SpartaJson.parseToJsonElement(h.takeRequest().body.readUtf8()).jsonObject
        assertEquals(loaded, put)
        assertTrue(put.containsKey("future_field"))
    }

    // ---- error handling ----

    @Test
    fun `unsupported by provider is parsed from the error envelope`() = runBlocking {
        val h = harness()
        h.enqueueJson(Fixtures.text("error_unsupported.json"), 409, "X-Request-ID" to "req-1")
        val error = safeApiCall { h.api.takeover("c1") }.failure()
        assertEquals(ApiErrorKind.UNSUPPORTED_BY_PROVIDER, error.kind)
        assertEquals(409, error.httpStatus)
        assertEquals("unsupported_by_provider", error.code)
        assertEquals("The simulator provider cannot transfer a real call.", error.message)
        assertEquals("trace-409", error.traceId)
        assertFalse(error.isTransient)
    }

    @Test
    fun `validation errors expose field details`() = runBlocking {
        val h = harness()
        h.enqueueJson(Fixtures.text("error_validation.json"), 422)
        val error = safeApiCall { h.api.putPreferences(buildJsonObject { put("strictness", JsonPrimitive("loud")) }) }.failure()
        assertEquals(ApiErrorKind.VALIDATION, error.kind)
        assertEquals("strictness", error.details.single().field)
        assertEquals("trace-422", error.traceId)
    }

    @Test
    fun `4xx statuses map to kinds even when the body is not json`() = runBlocking {
        val h = harness()
        for (status in listOf(401, 403, 404, 413, 415)) h.enqueueJson("<html>nope</html>", status)
        val kinds = (1..5).map { safeApiCall { h.api.me() }.failure().kind }
        assertEquals(
            listOf(ApiErrorKind.UNAUTHORIZED, ApiErrorKind.FORBIDDEN, ApiErrorKind.NOT_FOUND, ApiErrorKind.PAYLOAD_TOO_LARGE, ApiErrorKind.VALIDATION),
            kinds,
        )
    }

    @Test
    fun `unauthorized explains that sign in is not available`() = runBlocking {
        val h = harness()
        h.enqueueJson("{}", 401)
        val error = safeApiCall { h.api.me() }.failure()
        assertTrue(error.message.contains("Sign-in is not available"))
    }

    @Test
    fun `rate limit carries retry after and is transient`() = runBlocking {
        val h = harness()
        h.enqueueJson("""{"error":{"code":"rate_limited","message":"Slow down","trace_id":"t"}}""", 429, "Retry-After" to "17")
        val error = safeApiCall { h.api.me() }.failure()
        assertEquals(ApiErrorKind.RATE_LIMITED, error.kind)
        assertEquals(17L, error.retryAfterSeconds)
        assertTrue(error.isTransient)
    }

    @Test
    fun `server errors are transient and provider unavailable is recognised`() = runBlocking {
        val h = harness()
        h.enqueueJson("boom", 500)
        h.enqueueJson("""{"error":{"code":"provider_unavailable","message":"Speech provider is down","trace_id":"t"}}""", 503)
        h.enqueueJson("boom", 502)
        val kinds = (1..3).map { safeApiCall { h.api.me() }.failure() }
        assertEquals(ApiErrorKind.SERVER, kinds[0].kind)
        assertEquals(ApiErrorKind.PROVIDER_UNAVAILABLE, kinds[1].kind)
        assertEquals("Speech provider is down", kinds[1].message)
        assertEquals(ApiErrorKind.SERVER, kinds[2].kind)
        assertTrue(kinds.all { it.isTransient })
    }

    @Test
    fun `a read timeout becomes a timeout error`() = runBlocking {
        val h = harness { readTimeout(300, TimeUnit.MILLISECONDS) }
        h.server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val error = safeApiCall { h.api.me() }.failure()
        assertEquals(ApiErrorKind.TIMEOUT, error.kind)
        assertTrue(error.isTransient)
    }

    @Test
    fun `an unreachable backend becomes an offline error`() = runBlocking {
        val h = harness()
        h.server.shutdown()
        val error = safeApiCall { h.api.me() }.failure()
        assertEquals(ApiErrorKind.OFFLINE, error.kind)
        assertTrue(error.isTransient)
    }

    @Test
    fun `an unreadable success body becomes a malformed error`() = runBlocking {
        val h = harness()
        h.enqueueJson("this is not json")
        val error = safeApiCall { h.api.systemStatus() }.failure()
        assertEquals(ApiErrorKind.MALFORMED, error.kind)
    }

    @Test
    fun `redirects are never followed`() = runBlocking {
        val h = harness()
        h.server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "http://127.0.0.1:1/elsewhere"))
        val error = safeApiCall { h.api.me() }.failure()
        assertEquals(302, error.httpStatus)
        assertEquals(1, h.server.requestCount)
    }

    @Test
    fun `without a configured backend nothing is sent`() = runBlocking {
        val client = NetworkFactory.createClient(BaseUrlProvider { null })
        val api = NetworkFactory.createApi(client)
        val error = safeApiCall { api.me() }.failure()
        assertEquals(ApiErrorKind.NOT_CONFIGURED, error.kind)
    }

    @Test
    fun `error kinds follow the documented codes`() {
        assertEquals(ApiErrorKind.UNSUPPORTED_BY_PROVIDER, ApiErrors.kindFor(409, "unsupported_by_provider"))
        assertEquals(ApiErrorKind.CONFLICT, ApiErrors.kindFor(409, "conflict"))
        assertEquals(ApiErrorKind.VALIDATION, ApiErrors.kindFor(422, "stt_unavailable"))
        assertEquals(ApiErrorKind.SERVER, ApiErrors.kindFor(500, "internal_error"))
        assertEquals(ApiErrorKind.UNKNOWN, ApiErrors.kindFor(418, null))
    }
}
