package io.github.snowjug.sparta.data.remote.ws

import io.github.snowjug.sparta.data.remote.AbsoluteUrl
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.BaseUrlProvider
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.LiveEventDto
import io.github.snowjug.sparta.data.remote.dto.LiveTicketRequestDto
import io.github.snowjug.sparta.data.remote.safeApiCall
import java.util.concurrent.TimeUnit
import kotlin.random.Random
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

sealed interface LiveSocketEvent {
    data object Connecting : LiveSocketEvent

    data object Open : LiveSocketEvent

    data class Message(val event: LiveEventDto) : LiveSocketEvent

    data class Reconnecting(val attempt: Int, val delayMs: Long) : LiveSocketEvent

    /** Terminal. [fatal] closes (4403 origin, 4404 unknown call) will not be retried. */
    data class Closed(val code: Int, val reason: String, val fatal: Boolean) : LiveSocketEvent

    /** Terminal: the socket could not be established or kept. */
    data class Failed(val error: ApiError) : LiveSocketEvent
}

/** Source of live backend events (a WebSocket in production, a fake in tests). */
interface LiveEventSource {
    /** [callId] null subscribes to all of the owner's calls. Terminal events (Closed fatal / Failed) end the flow. */
    fun events(callId: String?): Flow<LiveSocketEvent>
}

object LiveCloseCodes {
    const val NORMAL = 1000
    const val BAD_TICKET = 4401
    const val ORIGIN_NOT_ALLOWED = 4403
    const val CALL_NOT_FOUND = 4404
    const val TOO_MANY_CONNECTIONS = 4429
}

/**
 * Live events over WebSocket per docs/API_CONTRACT.md: `POST /live/ticket`, then connect with the single-use ticket.
 * The socket URL is always built from the owner-configured backend plus the documented path; the `ws_url` hint in the
 * ticket response is deliberately ignored so a ticket can only ever be presented to the configured backend.
 * Reconnects with backoff (a fresh ticket each time); no foreground service is involved.
 */
class LiveCallClient(
    private val api: SpartaApi,
    private val client: OkHttpClient,
    private val baseUrl: BaseUrlProvider,
    private val json: Json = SpartaJson,
    private val maxFailures: Int = 6,
    private val backoffMs: (attempt: Int) -> Long = ::defaultLiveBackoff,
) : LiveEventSource {
    private val socketClient: OkHttpClient = client.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    /** [callId] null subscribes to all of the owner's calls (used for escalation notifications). */
    override fun events(callId: String?): Flow<LiveSocketEvent> = channelFlow {
        var failures = 0
        while (isActive) {
            send(if (failures == 0) LiveSocketEvent.Connecting else LiveSocketEvent.Reconnecting(failures, backoffMs(failures)))

            val base = baseUrl.current()
            if (base == null) {
                send(LiveSocketEvent.Failed(ApiError(ApiErrorKind.NOT_CONFIGURED, "No backend is configured yet.")))
                return@channelFlow
            }
            val ticket = when (val result = safeApiCall(json) { api.liveTicket(LiveTicketRequestDto(callId)) }) {
                is ApiResult.Success -> result.value.ticket
                is ApiResult.Failure -> {
                    if (!result.error.isTransient || ++failures >= maxFailures) {
                        send(LiveSocketEvent.Failed(result.error))
                        return@channelFlow
                    }
                    delay(backoffMs(failures))
                    continue
                }
            }
            if (ticket.isBlank()) {
                send(LiveSocketEvent.Failed(ApiError(ApiErrorKind.MALFORMED, "The backend did not issue a live ticket.")))
                return@channelFlow
            }

            val closed = CompletableDeferred<Outcome>()
            val socket = socketClient.newWebSocket(handshake(base, callId, ticket), object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    failures = 0
                    trySend(LiveSocketEvent.Open)
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    val event = try {
                        json.decodeFromString(LiveEventDto.serializer(), text)
                    } catch (_: SerializationException) {
                        return
                    }
                    if (event.type != "ping") trySend(LiveSocketEvent.Message(event))
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code.takeIf { it in 1000..4999 && it != 1005 && it != 1006 } ?: LiveCloseCodes.NORMAL, null)
                    closed.complete(Outcome.Closed(code, reason))
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    closed.complete(Outcome.Closed(code, reason))
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    closed.complete(Outcome.Dropped)
                }
            })

            val outcome = try {
                closed.await()
            } finally {
                socket.cancel()
            }

            when (outcome) {
                is Outcome.Closed -> when (outcome.code) {
                    LiveCloseCodes.NORMAL -> {
                        send(LiveSocketEvent.Closed(outcome.code, outcome.reason, fatal = false))
                        return@channelFlow
                    }
                    LiveCloseCodes.ORIGIN_NOT_ALLOWED, LiveCloseCodes.CALL_NOT_FOUND -> {
                        send(LiveSocketEvent.Closed(outcome.code, outcome.reason, fatal = true))
                        return@channelFlow
                    }
                    else -> failures++
                }
                Outcome.Dropped -> failures++
            }
            if (failures >= maxFailures) {
                send(LiveSocketEvent.Failed(ApiError(ApiErrorKind.OFFLINE, "The live connection was lost and could not be restored.")))
                return@channelFlow
            }
            delay(backoffMs(failures))
        }
    }.flowOn(Dispatchers.IO)

    private sealed interface Outcome {
        data class Closed(val code: Int, val reason: String) : Outcome

        data object Dropped : Outcome
    }

    internal fun handshake(base: HttpUrl, callId: String?, ticket: String): Request {
        val path = if (callId == null) "api/v1/live" else "api/v1/live/$callId"
        val url = base.newBuilder().addPathSegments(path).addQueryParameter("ticket", ticket).build()
        return Request.Builder().url(url).tag(AbsoluteUrl::class.java, AbsoluteUrl).build()
    }
}

/** 1 s, 2 s, 4 s, 8 s, then 15 s, each with +/-20 % jitter. */
fun defaultLiveBackoff(attempt: Int): Long {
    val base = (1000L shl (attempt - 1).coerceIn(0, 4)).coerceAtMost(15_000L)
    val jitter = (base * 0.2).toLong()
    return base - jitter + Random.nextLong(0, 2 * jitter + 1)
}
