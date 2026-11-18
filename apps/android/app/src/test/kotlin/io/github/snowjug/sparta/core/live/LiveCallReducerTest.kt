package io.github.snowjug.sparta.core.live

import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.LiveEventDto
import io.github.snowjug.sparta.data.remote.dto.Speaker
import io.github.snowjug.sparta.testutil.Fixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveCallReducerTest {

    private val reducer = LiveCallReducer(SpartaJson)

    private fun ev(type: String, seq: Long, data: String = "{}", callId: String = "call_01HZX", simulated: Boolean = true): LiveEventDto =
        SpartaJson.decodeFromString(
            LiveEventDto.serializer(),
            """{"type":"$type","call_id":"$callId","seq":$seq,"ts":"2026-11-17T10:00:00Z","simulated":$simulated,"data":$data}""",
        )

    private fun fold(vararg events: LiveEventDto, start: LiveCallState = reducer.initial("call_01HZX")): LiveCallState =
        events.fold(start) { state, event -> reducer.reduce(state, event) }

    private val snapshot get() = ev("call.snapshot", 0, """{"call": ${Fixtures.text("call_detail.json")}}""")

    private fun turn(id: String, seq: Int, speaker: String, text: String) =
        """{"turn":{"id":"$id","call_id":"call_01HZX","seq":$seq,"speaker":"$speaker","text":"$text","is_final":true}}"""

    @Test
    fun `a snapshot syncs a late joiner with transcript risk escalation and listening phase`() {
        val state = fold(snapshot)
        assertEquals(VoicePhase.LISTENING, state.phase)
        assertEquals(CallState.ESCALATE, state.callState)
        assertEquals(2, state.transcript.size)
        assertNotNull(state.risk)
        assertEquals("esc_1", state.escalation?.id)
        assertEquals("call_01HZX", state.call?.id)
        assertFalse(state.isEnded)
    }

    @Test
    fun `a snapshot of an ended call shows ended`() {
        val ended = Fixtures.text("call_detail.json").replace("\"status\": \"active\"", "\"status\": \"ended\"")
        val state = fold(ev("call.snapshot", 0, """{"call": $ended}"""))
        assertEquals(VoicePhase.ENDED, state.phase)
        assertTrue(state.isEnded)
    }

    @Test
    fun `phases follow the real assistant speaking finished and interrupted events`() {
        var state = fold(ev("call.connected", 1, """{"state":"DISCLOSURE"}"""))
        assertEquals(VoicePhase.LISTENING, state.phase)

        state = reducer.reduce(state, ev("assistant.speaking", 2, """{"turn_id":"turn_3","text":"Please state your purpose","locale":"en-IN","voice_id":"v","est_duration_ms":2400}"""))
        assertEquals(VoicePhase.ASSISTANT_SPEAKING, state.phase)
        assertEquals("turn_3", state.speaking?.turnId)
        assertEquals(2400L, state.speaking?.estDurationMs)

        state = reducer.reduce(state, ev("assistant.interrupted", 3, """{"turn_id":"turn_3","spoken_fraction":0.4,"interruption_ms":180}"""))
        assertEquals(VoicePhase.INTERRUPTED, state.phase)
        assertNull(state.speaking)

        state = reducer.reduce(state, ev("call.listening", 4))
        assertEquals(VoicePhase.LISTENING, state.phase)

        state = reducer.reduce(state, ev("assistant.speaking", 5, """{"turn_id":"turn_4","text":"Thanks","locale":"en-IN","voice_id":"v","est_duration_ms":900}"""))
        state = reducer.reduce(state, ev("assistant.finished", 6, """{"turn_id":"turn_4"}"""))
        assertEquals(VoicePhase.LISTENING, state.phase)
    }

    @Test
    fun `finished without speaking does not change the phase`() {
        val state = fold(ev("call.listening", 1), ev("assistant.finished", 2, """{"turn_id":"x"}"""))
        assertEquals(VoicePhase.LISTENING, state.phase)
    }

    @Test
    fun `partial transcripts are replaced by the final turn`() {
        var state = fold(ev("transcript.partial", 1, """{"speaker":"caller","text":"I am calling fro","language":"en-IN"}"""))
        assertEquals("I am calling fro", state.partial?.text)
        assertEquals(Speaker.CALLER, state.partial?.speaker)

        state = reducer.reduce(state, ev("transcript.final", 2, turn("turn_2", 2, "caller", "I am calling from the bank")))
        assertNull(state.partial)
        assertEquals(listOf("turn_2"), state.transcript.map { it.id })
    }

    @Test
    fun `a repeated final turn updates in place and the transcript stays ordered`() {
        val state = fold(
            ev("transcript.final", 2, turn("turn_2", 2, "caller", "second")),
            ev("transcript.final", 1, turn("turn_1", 1, "assistant", "first")),
        )
        // seq 1 arrives after seq 2: the older envelope is dropped as a replay, order is by turn seq.
        assertEquals(listOf("turn_2"), state.transcript.map { it.id })

        val updated = reducer.reduce(state, ev("transcript.final", 3, turn("turn_2", 2, "caller", "second (corrected)")))
        assertEquals(1, updated.transcript.size)
        assertEquals("second (corrected)", updated.transcript.single().text)
    }

    @Test
    fun `language changes risk updates and escalations accumulate`() {
        val riskObj = """{"call_id":"call_01HZX","risk_level":"high","risk_score":0.9,"confidence":0.8,"category":"possible_financial_impersonation"}"""
        val state = fold(
            ev("language.changed", 1, """{"from":"en-IN","to":"hi-IN","profile":"hinglish","confidence":0.77}"""),
            ev("risk.updated", 2, """{"risk":$riskObj}"""),
            ev(
                "escalation.requested",
                3,
                """{"escalation":{"id":"esc_9","call_id":"call_01HZX","reason":"needs owner","status":"requested","important_lines":["line"]},"risk":$riskObj}""",
            ),
        )
        assertEquals(1, state.languageChanges.size)
        assertEquals("hi-IN", state.languageChanges.single().to)
        assertEquals(0.77, state.languageChanges.single().confidence ?: 0.0, 0.0)
        assertEquals("high", state.risk?.riskLevel?.wire)
        assertEquals("esc_9", state.escalation?.id)
    }

    @Test
    fun `owner takeover stops the assistant and listening events do not override it`() {
        val state = fold(
            ev("assistant.speaking", 1, """{"turn_id":"t","text":"x","locale":"en-IN","voice_id":"v","est_duration_ms":1}"""),
            ev("owner.takeover", 2, """{"action":{"id":"a1","call_id":"call_01HZX","action":"takeover","simulated":true},"simulated":true}"""),
            ev("call.listening", 3),
        )
        assertEquals(VoicePhase.OWNER_TAKEOVER, state.phase)
        assertNull(state.speaking)
        assertEquals(1, state.ownerActions.size)
    }

    @Test
    fun `an ended call stays ended`() {
        val state = fold(
            ev("call.ended", 1, """{"reason":"caller_hung_up","state":"COMPLETED","duration_ms":45000}"""),
            ev("assistant.speaking", 2, """{"turn_id":"t","text":"x","locale":"en-IN","voice_id":"v","est_duration_ms":1}"""),
            ev("call.listening", 3),
        )
        assertEquals(VoicePhase.ENDED, state.phase)
        assertEquals("caller_hung_up", state.ended?.reason)
        assertEquals(45_000L, state.ended?.durationMs)
        assertEquals(CallState.COMPLETED, state.callState)
        assertNull(state.speaking)
    }

    @Test
    fun `summary and provider errors are kept and provider notes are bounded`() {
        var state = fold(ev("summary.created", 1, """{"summary":{"call_id":"call_01HZX","text":"Delivery call","risk_level":"low"}}"""))
        assertEquals("Delivery call", state.summary?.text)
        for (i in 2..9) {
            state = reducer.reduce(state, ev("provider.error", i.toLong(), """{"provider":"azure","stage":"stt","message":"m$i","degraded":true}"""))
        }
        assertEquals(5, state.providerNotes.size)
        assertEquals("m9", state.providerNotes.last().message)
        assertTrue(state.providerNotes.last().degraded)
    }

    @Test
    fun `replayed or older sequence numbers are ignored`() {
        val first = reducer.reduce(reducer.initial("call_01HZX"), ev("language.changed", 5, """{"from":"a","to":"b"}"""))
        val replay = reducer.reduce(first, ev("language.changed", 5, """{"from":"a","to":"b"}"""))
        val older = reducer.reduce(first, ev("language.changed", 3, """{"from":"x","to":"y"}"""))
        assertEquals(1, replay.languageChanges.size)
        assertSame(first, older)
        assertEquals(5L, replay.lastSeq)
    }

    @Test
    fun `pings unknown types malformed data and other calls are ignored without crashing`() {
        val start = reducer.initial("call_01HZX")
        assertSame(start, reducer.reduce(start, ev("ping", 0)))
        assertEquals(start.phase, reducer.reduce(start, ev("future.event", 1, """{"x":1}""")).phase)
        assertTrue(reducer.reduce(start, ev("transcript.final", 2, """{"turn":{"id":123}}""")).transcript.isEmpty())
        assertSame(start, reducer.reduce(start, ev("call.ended", 3, "{}", callId = "someone_else")))
    }

    @Test
    fun `simulated flag comes from the envelope`() {
        assertEquals(true, fold(ev("call.listening", 1, simulated = true)).simulated)
        assertEquals(false, fold(ev("call.listening", 1, simulated = false)).simulated)
    }
}
