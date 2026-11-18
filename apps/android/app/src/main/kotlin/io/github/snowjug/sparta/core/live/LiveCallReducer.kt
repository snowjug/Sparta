package io.github.snowjug.sparta.core.live

import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.CallSummaryDto
import io.github.snowjug.sparta.data.remote.dto.CallTurnDto
import io.github.snowjug.sparta.data.remote.dto.EscalationDto
import io.github.snowjug.sparta.data.remote.dto.LiveEventDto
import io.github.snowjug.sparta.data.remote.dto.OwnerActionDto
import io.github.snowjug.sparta.data.remote.dto.RiskAssessmentDto
import io.github.snowjug.sparta.data.remote.dto.Speaker
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/** What the visualisation and status line show. Each value comes from a real backend event, never from a timer. */
enum class VoicePhase {
    CONNECTING,

    /** Sparta is on the call and waiting for / hearing the caller. */
    LISTENING,
    ASSISTANT_SPEAKING,

    /** The caller barged in and the assistant stopped talking. */
    INTERRUPTED,
    OWNER_TAKEOVER,
    ENDED,
}

data class PartialTranscript(val speaker: Speaker, val text: String, val language: String?)

data class SpeakingInfo(val turnId: String, val text: String, val locale: String, val estDurationMs: Long)

data class LanguageChange(val from: String?, val to: String?, val profile: String?, val confidence: Double?)

data class ProviderNote(val provider: String, val stage: String, val message: String, val degraded: Boolean)

data class EndedInfo(val reason: String?, val state: CallState, val durationMs: Long?)

data class LiveCallState(
    val callId: String,
    val phase: VoicePhase = VoicePhase.CONNECTING,
    val callState: CallState = CallState.UNKNOWN,
    val call: CallDetailDto? = null,
    val transcript: List<CallTurnDto> = emptyList(),
    val partial: PartialTranscript? = null,
    val risk: RiskAssessmentDto? = null,
    val escalation: EscalationDto? = null,
    val languageChanges: List<LanguageChange> = emptyList(),
    val ownerActions: List<OwnerActionDto> = emptyList(),
    val summary: CallSummaryDto? = null,
    val providerNotes: List<ProviderNote> = emptyList(),
    val speaking: SpeakingInfo? = null,
    val ended: EndedInfo? = null,
    val lastSeq: Long = 0,
    /** From the envelope: true when the backend says this call (or its provider) is simulated. */
    val simulated: Boolean? = null,
) {
    val isEnded: Boolean get() = phase == VoicePhase.ENDED
}

/**
 * Folds backend live events (docs/API_CONTRACT.md, "Live events") into [LiveCallState]. Pure and total: an event it
 * cannot decode is ignored rather than crashing the call screen, and replayed events (seq already seen) change nothing.
 */
class LiveCallReducer(private val json: Json) {

    fun initial(callId: String) = LiveCallState(callId = callId)

    fun reduce(state: LiveCallState, event: LiveEventDto): LiveCallState {
        if (event.type == "ping") return state
        if (event.callId.isNotEmpty() && state.callId.isNotEmpty() && event.callId != state.callId) return state
        val isSnapshot = event.type == "call.snapshot"
        if (!isSnapshot && event.seq in 1..state.lastSeq) return state

        val next = try {
            apply(state, event)
        } catch (_: SerializationException) {
            state
        } catch (_: IllegalArgumentException) {
            state
        }
        return next.copy(
            lastSeq = maxOf(next.lastSeq, event.seq),
            simulated = if (event.type == "ping") next.simulated else event.simulated,
        )
    }

    private fun apply(state: LiveCallState, event: LiveEventDto): LiveCallState {
        val data = event.data
        return when (event.type) {
            "call.snapshot" -> snapshot(state, data)
            "call.connected" -> state.copy(phase = if (state.isEnded) state.phase else VoicePhase.LISTENING)
            "call.listening" -> if (state.isEnded || state.phase == VoicePhase.OWNER_TAKEOVER) state else state.copy(phase = VoicePhase.LISTENING, speaking = null)
            "state.changed" -> stateChanged(state, data)
            "transcript.partial" -> state.copy(
                partial = PartialTranscript(
                    speaker = decode(Speaker.serializer(), data["speaker"]) ?: Speaker.CALLER,
                    text = data.string("text").orEmpty(),
                    language = data.string("language"),
                ),
            )
            "transcript.final" -> {
                val turn = decode(CallTurnDto.serializer(), data["turn"]) ?: return state
                state.copy(transcript = upsertTurn(state.transcript, turn), partial = null)
            }
            "language.changed" -> state.copy(
                languageChanges = state.languageChanges + LanguageChange(
                    from = data.string("from"),
                    to = data.string("to"),
                    profile = data.string("profile"),
                    confidence = (data["confidence"] as? JsonPrimitive)?.doubleOrNull,
                ),
            )
            "risk.updated" -> state.copy(risk = decode(RiskAssessmentDto.serializer(), data["risk"]) ?: state.risk)
            "assistant.speaking" -> if (state.isEnded) state else state.copy(
                phase = VoicePhase.ASSISTANT_SPEAKING,
                speaking = SpeakingInfo(
                    turnId = data.string("turn_id").orEmpty(),
                    text = data.string("text").orEmpty(),
                    locale = data.string("locale").orEmpty(),
                    estDurationMs = (data["est_duration_ms"] as? JsonPrimitive)?.longOrNull ?: 0L,
                ),
            )
            "assistant.finished" -> if (state.isEnded || state.phase != VoicePhase.ASSISTANT_SPEAKING) state else state.copy(phase = VoicePhase.LISTENING, speaking = null)
            "assistant.interrupted" -> if (state.isEnded) state else state.copy(phase = VoicePhase.INTERRUPTED, speaking = null)
            "escalation.requested" -> state.copy(
                escalation = decode(EscalationDto.serializer(), data["escalation"]) ?: state.escalation,
                risk = decode(RiskAssessmentDto.serializer(), data["risk"]) ?: state.risk,
            )
            "owner.takeover" -> {
                val action = decode(OwnerActionDto.serializer(), data["action"])
                state.copy(
                    phase = if (state.isEnded) state.phase else VoicePhase.OWNER_TAKEOVER,
                    speaking = null,
                    ownerActions = if (action != null) state.ownerActions + action else state.ownerActions,
                )
            }
            "owner.action" -> {
                val action = decode(OwnerActionDto.serializer(), data["action"]) ?: return state
                state.copy(ownerActions = state.ownerActions + action)
            }
            "call.ended" -> state.copy(
                phase = VoicePhase.ENDED,
                speaking = null,
                partial = null,
                callState = decode(CallState.serializer(), data["state"]) ?: state.callState,
                ended = EndedInfo(
                    reason = data.string("reason"),
                    state = decode(CallState.serializer(), data["state"]) ?: state.callState,
                    durationMs = (data["duration_ms"] as? JsonPrimitive)?.longOrNull,
                ),
            )
            "summary.created" -> state.copy(summary = decode(CallSummaryDto.serializer(), data["summary"]) ?: state.summary)
            "provider.error" -> state.copy(
                providerNotes = (
                    state.providerNotes + ProviderNote(
                        provider = data.string("provider").orEmpty(),
                        stage = data.string("stage").orEmpty(),
                        message = data.string("message").orEmpty(),
                        degraded = (data["degraded"] as? JsonPrimitive)?.contentOrNull == "true",
                    )
                    ).takeLast(MAX_NOTES),
            )
            else -> state
        }
    }

    private fun snapshot(state: LiveCallState, data: JsonObject): LiveCallState {
        val call = decode(CallDetailDto.serializer(), data["call"]) ?: return state
        val ended = call.status == CallStatus.ENDED || call.status == CallStatus.FAILED
        return state.copy(
            call = call,
            callState = call.state,
            phase = when {
                ended -> VoicePhase.ENDED
                call.state == CallState.OWNER_TAKEOVER -> VoicePhase.OWNER_TAKEOVER
                else -> VoicePhase.LISTENING
            },
            transcript = call.turns.filter { it.isFinal },
            risk = call.risk ?: state.risk,
            escalation = call.escalations.lastOrNull() ?: state.escalation,
            ownerActions = call.ownerActions,
            summary = call.summary,
            speaking = null,
            partial = null,
            ended = if (ended) EndedInfo(call.actionTaken, call.state, call.durationMs) else null,
        )
    }

    private fun stateChanged(state: LiveCallState, data: JsonObject): LiveCallState {
        val to = decode(CallState.serializer(), data["to"]) ?: return state
        return state.copy(
            callState = to,
            phase = when {
                state.isEnded -> state.phase
                to == CallState.OWNER_TAKEOVER -> VoicePhase.OWNER_TAKEOVER
                else -> state.phase
            },
        )
    }

    private fun upsertTurn(turns: List<CallTurnDto>, turn: CallTurnDto): List<CallTurnDto> {
        val index = turns.indexOfFirst { it.id == turn.id }
        val merged = if (index >= 0) turns.toMutableList().also { it[index] = turn } else turns + turn
        return merged.sortedBy { it.seq }
    }

    private fun <T> decode(serializer: KSerializer<T>, element: JsonElement?): T? =
        if (element == null) null else json.decodeFromJsonElement(serializer, element)

    private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull

    companion object {
        private const val MAX_NOTES = 5
    }
}
