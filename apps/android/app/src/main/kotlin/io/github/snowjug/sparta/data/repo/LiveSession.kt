package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.live.LiveCallReducer
import io.github.snowjug.sparta.core.live.LiveCallState
import io.github.snowjug.sparta.core.notify.EscalationNotice
import io.github.snowjug.sparta.core.number.NumberMasker
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.dto.EscalationDto
import io.github.snowjug.sparta.data.remote.dto.RiskAssessmentDto
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.ws.LiveEventSource
import io.github.snowjug.sparta.data.remote.ws.LiveSocketEvent
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.scan
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

enum class LiveConnection { CONNECTING, CONNECTED, RECONNECTING, CLOSED, FAILED }

/** The live call as seen by a screen: transport state plus the folded call state. */
data class LiveSession(
    val connection: LiveConnection,
    val call: LiveCallState,
    val error: ApiError? = null,
    val closeCode: Int? = null,
)

/** Turns the raw socket events of one call into [LiveSession] updates. */
class LiveCallSession(private val source: LiveEventSource, private val reducer: LiveCallReducer) {

    fun run(callId: String): Flow<LiveSession> =
        source.events(callId).scan(LiveSession(LiveConnection.CONNECTING, reducer.initial(callId))) { session, event ->
            when (event) {
                LiveSocketEvent.Connecting -> session.copy(connection = if (session.connection == LiveConnection.CONNECTING) LiveConnection.CONNECTING else LiveConnection.RECONNECTING)
                LiveSocketEvent.Open -> session.copy(connection = LiveConnection.CONNECTED, error = null)
                is LiveSocketEvent.Message -> session.copy(call = reducer.reduce(session.call, event.event))
                is LiveSocketEvent.Reconnecting -> session.copy(connection = LiveConnection.RECONNECTING)
                is LiveSocketEvent.Closed -> session.copy(connection = LiveConnection.CLOSED, closeCode = event.code)
                is LiveSocketEvent.Failed -> session.copy(connection = LiveConnection.FAILED, error = event.error)
            }
        }
}

/**
 * While the app is in the foreground it listens to the owner's live socket and turns `escalation.requested` into the
 * high-importance "Escalations" notification. There is no foreground service: the collection is cancelled when the UI
 * stops, and the periodic WorkManager sync covers the time the app is closed.
 */
class EscalationMonitor(
    private val source: LiveEventSource,
    private val announcer: EscalationAnnouncer,
    private val calls: CallsRepository,
    private val settings: SettingsRepository,
    private val json: Json,
) {
    suspend fun run() {
        val s = settings.current()
        if (!s.backendConfigured || !s.onboardingCompleted || !s.notifyEscalations) return
        source.events(null).collect { event ->
            if (event is LiveSocketEvent.Message && event.event.type == "escalation.requested") handle(event)
        }
    }

    private suspend fun handle(message: LiveSocketEvent.Message) {
        val data = message.event.data
        val escalation = decode(EscalationDto.serializer(), data["escalation"]) ?: return
        val risk = decode(RiskAssessmentDto.serializer(), data["risk"])
        val callId = escalation.callId.ifEmpty { message.event.callId }
        if (callId.isEmpty()) return
        val display = calls.cached(callId)?.callerDisplay?.takeIf { it.isNotBlank() } ?: NumberMasker.PRIVATE_NUMBER
        announcer.announce(
            key = "call:$callId",
            notice = EscalationNotice(
                callId = callId,
                callerDisplay = display,
                purpose = risk?.purpose,
                importantLines = escalation.importantLines.take(MAX_LINES),
                highRisk = risk?.riskLevel == RiskLevel.HIGH,
            ),
            kind = EscalationAnnouncer.Kind.ESCALATION,
        )
    }

    private fun <T> decode(serializer: kotlinx.serialization.KSerializer<T>, element: kotlinx.serialization.json.JsonElement?): T? {
        if (element == null) return null
        return try {
            json.decodeFromJsonElement(serializer, element)
        } catch (_: SerializationException) {
            null
        }
    }

    private companion object {
        const val MAX_LINES = 3
    }
}
