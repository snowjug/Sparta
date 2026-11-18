package io.github.snowjug.sparta.ui.detail

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.repo.CallCache
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.incoming.ControlId
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CallDetailViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private lateinit var h: VmHarness
    private lateinit var vm: CallDetailViewModel

    private val detailJson get() = Fixtures.text("call_detail.json")

    private val listItemJson =
        """{"id":"call_01HZX","provider":"simulator","simulated":true,"status":"active","state":"OWNER_TAKEOVER","started_at":"2026-11-17T10:00:00Z","caller_display":"+91 98\u2022\u2022\u2022\u2022 \u2022\u202221"}"""

    private fun actionJson(type: String, simulated: Boolean = true) =
        """{"action":{"id":"act_9","call_id":"call_01HZX","action":"$type","created_at":"2026-11-17T10:00:20Z","simulated":$simulated,"result":"ok"},"call":$listItemJson,"capabilities":{"can_end":true}}"""

    @Before
    fun setUp() {
        h = VmHarness()
        vm = CallDetailViewModel(h.calls, h.screening, h.clock)
    }

    @After
    fun tearDown() = h.close()

    private fun loadAndWait() {
        h.api.enqueueJson(detailJson)
        vm.load("call_01HZX")
        vm.state.await { !it.loading }
        h.api.takeRequest() // the detail GET
    }

    @Test
    fun `loading fetches the call and exposes its controls`() {
        h.api.enqueueJson(detailJson)
        vm.load("call_01HZX")
        val state = vm.state.await { !it.loading }

        assertEquals("/api/v1/calls/call_01HZX", h.api.takeRequest().path)
        assertEquals("call_01HZX", state.call?.id)
        assertNull(state.error)
        assertTrue("an escalated simulated call: the unknown action in the fixture is tolerated", state.controls.isNotEmpty())
    }

    @Test
    fun `the cached list row is available while the detail loads`() {
        val cached = SpartaJson.decodeFromString(CallListItemDto.serializer(), listItemJson)
        runBlocking { h.db.cachedCalls().upsertAll(listOf(CallCache.toEntity(cached, SpartaJson, 1L))) }
        h.api.enqueueJson(detailJson)
        vm.load("call_01HZX")
        val state = vm.state.await { !it.loading }
        assertNotNull(state.cached)
        assertEquals("call_01HZX", state.cached?.id)
    }

    @Test
    fun `loading the same call again does not fetch twice`() {
        loadAndWait()
        vm.load("call_01HZX")
        assertEquals("only the first load hit the network", 1, h.api.server.requestCount)
    }

    @Test
    fun `an unknown call is reported as not found`() {
        h.api.enqueueJson("""{"error":{"code":"not_found","message":"Call not found","trace_id":"t-9"}}""", code = 404)
        vm.load("nope")
        val state = vm.state.await { !it.loading }
        assertTrue(state.notFound)
        assertEquals(ApiErrorKind.NOT_FOUND, state.error?.kind)
        assertEquals("t-9", state.error?.traceId)
    }

    @Test
    fun `taking over sends one idempotent request then refreshes and says it was a simulation`() {
        loadAndWait()
        h.api.enqueueJson(actionJson("takeover"))
        h.api.enqueueJson(detailJson)

        vm.takeOver()
        val state = vm.state.await { it.busy == null && it.message != null }

        val action = h.api.takeRequest()
        assertEquals("/api/v1/calls/call_01HZX/takeover", action.path)
        assertEquals("id-1", action.getHeader("Idempotency-Key"))
        assertEquals((state.message as UiMessage.Text).res, R.string.detail_msg_simulated_action)
        assertEquals("/api/v1/calls/call_01HZX", h.api.takeRequest().path)
    }

    @Test
    fun `an unsupported action shows the backend reason and changes nothing else`() {
        loadAndWait()
        h.api.enqueueJson("""{"error":{"code":"unsupported_by_provider","message":"This provider cannot take over.","trace_id":"t-1"}}""", code = 409)

        vm.takeOver()
        val state = vm.state.await { it.busy == null && it.message != null }

        val failure = state.message as UiMessage.Failure
        assertEquals(ApiErrorKind.UNSUPPORTED_BY_PROVIDER, failure.error.kind)
        assertEquals("This provider cannot take over.", failure.error.message)
        assertEquals(2, h.api.server.requestCount)
    }

    @Test
    fun `a second action while one runs is ignored`() {
        loadAndWait()
        h.api.enqueueJson(actionJson("end"))
        h.api.enqueueJson(detailJson)
        vm.endCall()
        vm.endCall()
        vm.state.await { it.busy == null && it.message != null }
        assertEquals("/api/v1/calls/call_01HZX/end", h.api.takeRequest().path)
        assertEquals("the refresh after the action", "/api/v1/calls/call_01HZX", h.api.takeRequest().path)
        Thread.sleep(300) // a duplicate press would have produced a second POST by now
        // 1 GET (load) + 1 POST + 1 GET (refresh): the second press sent nothing
        assertEquals(3, h.api.server.requestCount)
    }

    @Test
    fun `blocking records it then pulls the new fingerprint into the phone before refreshing`() {
        loadAndWait()
        h.api.enqueueJson("""{"id":"blk_1","number_display":"+91 98\u2022\u2022\u2022\u2022 \u2022\u202221"}""")
        h.api.enqueueJson(Fixtures.text("screening_config.json"))
        h.api.enqueueJson(Fixtures.text("screening_lists.json"))
        h.api.enqueueJson(detailJson)

        vm.block()
        val state = vm.state.await { it.busy == null && it.message != null }

        assertEquals("/api/v1/calls/call_01HZX/block", h.api.takeRequest().path)
        assertEquals("/api/v1/screening/config", h.api.takeRequest().path)
        assertEquals("/api/v1/screening/lists", h.api.takeRequest().path)
        assertEquals(R.string.detail_msg_blocked, (state.message as UiMessage.Text).res)
    }

    @Test
    fun `a failed block is reported and the lists are not touched`() {
        loadAndWait()
        h.api.enqueueJson("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t-2"}}""", code = 500)
        vm.block()
        val state = vm.state.await { it.busy == null && it.message != null }
        assertTrue(state.message is UiMessage.Failure)
        assertEquals(2, h.api.server.requestCount)
    }

    @Test
    fun `feedback is sent once per kind`() {
        loadAndWait()
        h.api.enqueueJson("""{"id":"fb_1","call_id":"call_01HZX","kind":"was_spam","created_at":"2026-11-17T10:00:30Z"}""")

        vm.sendFeedback(FeedbackKind.WAS_SPAM)
        val state = vm.state.await { FeedbackKind.WAS_SPAM in it.feedbackSent }
        vm.sendFeedback(FeedbackKind.WAS_SPAM)

        val request = h.api.takeRequest()
        assertEquals("/api/v1/calls/call_01HZX/feedback", request.path)
        val body = SpartaJson.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals("was_spam", body.getValue("kind").jsonPrimitive.content)
        assertEquals(R.string.detail_msg_feedback_saved, (state.message as UiMessage.Text).res)
        assertEquals("the repeat press sent nothing", 2, h.api.server.requestCount)
    }

    @Test
    fun `deleting the content keeps the call and reloads it`() {
        loadAndWait()
        h.api.enqueueEmpty(204)
        h.api.enqueueJson(detailJson)
        vm.delete(DeleteKind.CONTENT)
        val state = vm.state.await { it.deleting == null && it.message != null }
        assertEquals("/api/v1/calls/call_01HZX/content", h.api.takeRequest().path)
        assertFalse(state.deleted)
    }

    @Test
    fun `deleting the call marks the screen finished and clears the cache`() {
        loadAndWait()
        h.api.enqueueEmpty(204)
        vm.delete(DeleteKind.CALL)
        val state = vm.state.await { it.deleted }
        assertEquals("DELETE", h.api.takeRequest().method)
        assertTrue(state.deleted)
        assertNull(runBlocking { h.calls.cached("call_01HZX") })
    }

    @Test
    fun `toggling translations and dismissing messages only change local state`() {
        loadAndWait()
        vm.toggleTranslations()
        assertTrue(vm.state.value.showTranslations)
        vm.dismissMessage()
        assertNull(vm.state.value.message)
        assertEquals(1, h.api.server.requestCount)
    }

    @Test
    fun `controls are only those the call allows`() {
        loadAndWait()
        val ids = vm.state.value.controls.map { it.id }
        assertTrue(ControlId.BLOCK in ids && ControlId.TRUST in ids)
    }
}
