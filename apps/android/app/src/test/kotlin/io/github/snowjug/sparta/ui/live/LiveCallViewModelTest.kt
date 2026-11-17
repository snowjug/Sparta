package io.github.snowjug.sparta.ui.live

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.live.LiveCallReducer
import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.LiveEventDto
import io.github.snowjug.sparta.data.remote.ws.LiveCloseCodes
import io.github.snowjug.sparta.data.remote.ws.LiveEventSource
import io.github.snowjug.sparta.data.remote.ws.LiveSocketEvent
import io.github.snowjug.sparta.data.repo.LiveCallSession
import io.github.snowjug.sparta.data.repo.LiveConnection
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.Unavailable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.serialization.json.JsonObject
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
class LiveCallViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private class FakeSocket : LiveEventSource {
        val events = MutableSharedFlow<LiveSocketEvent>(replay = 64, extraBufferCapacity = 64)
        var subscribedTo: String? = "unset"

        override fun events(callId: String?): Flow<LiveSocketEvent> {
            subscribedTo = callId
            return events
        }
    }

    private lateinit var h: VmHarness
    private lateinit var socket: FakeSocket
    private lateinit var vm: LiveCallViewModel
    private val detailJson get() = Fixtures.text("call_detail.json")

    @Before
    fun setUp() {
        h = VmHarness()
        socket = FakeSocket()
        vm = LiveCallViewModel(LiveCallSession(socket, LiveCallReducer(SpartaJson)), h.calls)
    }

    @After
    fun tearDown() = h.close()

    private fun event(type: String, seq: Long, data: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(), simulated: Boolean = true) =
        LiveSocketEvent.Message(LiveEventDto(type = type, callId = "call_01HZX", seq = seq, simulated = simulated, data = JsonObject(data)))

    private fun snapshot(seq: Long = 1) = event("call.snapshot", seq, mapOf("call" to SpartaJson.parseToJsonElement(detailJson)))

    private fun bind() {
        h.api.enqueueJson(detailJson)
        vm.bind("call_01HZX")
    }

    @Test
    fun `the socket is opened for the one call and its snapshot supplies the controls`() {
        bind()
        socket.events.tryEmit(LiveSocketEvent.Open)
        socket.events.tryEmit(snapshot())

        val state = vm.state.await { it.connection == LiveConnection.CONNECTED && it.live.call != null }

        assertEquals("call_01HZX", socket.subscribedTo)
        assertEquals("call_01HZX", state.call?.id)
        val ids = state.liveControls.map { it.id }.toSet()
        assertEquals(setOf(ControlId.TAKE_OVER, ControlId.CONTINUE, ControlId.END), ids)
        assertTrue(state.liveControls.all { it.enabled })
    }

    @Test
    fun `the rest copy of the call is used until the socket delivers a snapshot`() {
        bind()
        val state = vm.state.await { it.restCall != null }
        assertNull(state.live.call)
        assertEquals("call_01HZX", state.call?.id)
        assertTrue("the controls are honest even before the socket says anything", state.liveControls.any { it.enabled })
    }

    @Test
    fun `when the socket says the call ended the controls are unavailable although the snapshot still said active`() {
        bind()
        socket.events.tryEmit(snapshot())
        socket.events.tryEmit(
            event("call.ended", 5, mapOf("reason" to kotlinx.serialization.json.JsonPrimitive("owner_ended"), "state" to kotlinx.serialization.json.JsonPrimitive("COMPLETED"), "duration_ms" to kotlinx.serialization.json.JsonPrimitive(41000))),
        )

        val state = vm.state.await { it.live.phase == VoicePhase.ENDED }

        assertEquals(CallStatus.ENDED, state.call?.status)
        assertEquals(setOf(Unavailable.CALL_ENDED), state.liveControls.mapNotNull { it.unavailable }.toSet())
    }

    @Test
    fun `a reconnecting socket is shown as such`() {
        bind()
        socket.events.tryEmit(LiveSocketEvent.Open)
        socket.events.tryEmit(LiveSocketEvent.Reconnecting(1, 1000))
        assertEquals(LiveConnection.RECONNECTING, vm.state.await { it.connection == LiveConnection.RECONNECTING }.connection)
    }

    @Test
    fun `an unknown call closes with 4404 and is reported as not found`() {
        h.api.enqueueJson("""{"error":{"code":"not_found","message":"Call not found","trace_id":"t"}}""", code = 404)
        vm.bind("call_01HZX")
        socket.events.tryEmit(LiveSocketEvent.Closed(LiveCloseCodes.CALL_NOT_FOUND, "not found", fatal = true))
        assertTrue(vm.state.await { it.notFound }.notFound)
    }

    @Test
    fun `taking over sends one request and reports a simulation`() {
        bind()
        vm.state.await { it.restCall != null }
        h.api.takeRequest()
        h.api.enqueueJson(
            """{"action":{"id":"a1","call_id":"call_01HZX","action":"takeover","created_at":"2026-11-17T10:00:20Z","simulated":true,"result":"ok"},"call":{"id":"call_01HZX","provider":"simulator","simulated":true,"status":"active","state":"OWNER_TAKEOVER","started_at":"2026-11-17T10:00:00Z","caller_display":"x"},"capabilities":{}}""",
        )

        vm.takeOver()
        val state = vm.state.await { it.busy == null && it.message != null }

        val request = h.api.takeRequest()
        assertEquals("/api/v1/calls/call_01HZX/takeover", request.path)
        assertEquals(R.string.detail_msg_simulated_action, (state.message as UiMessage.Text).res)
    }

    @Test
    fun `a refused action shows the reason and re enables the controls`() {
        bind()
        vm.state.await { it.restCall != null }
        h.api.enqueueJson("""{"error":{"code":"unsupported_by_provider","message":"This provider cannot end calls.","trace_id":"t"}}""", code = 409)

        vm.endCall()
        val state = vm.state.await { it.busy == null && it.message != null }

        assertTrue(state.message is UiMessage.Failure)
        assertFalse(state.liveControls.isEmpty())
    }

    @Test
    fun `binding the same call twice keeps one subscription`() {
        bind()
        vm.state.await { it.restCall != null }
        val before = h.api.server.requestCount
        vm.bind("call_01HZX")
        assertEquals(before, h.api.server.requestCount)
        assertNotNull(vm.state.value.restCall)
    }
}
