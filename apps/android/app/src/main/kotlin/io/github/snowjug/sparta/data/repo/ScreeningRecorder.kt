package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.screening.ScreenedNumber
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningOutcome
import io.github.snowjug.sparta.core.screening.ScreeningReason
import io.github.snowjug.sparta.core.screening.ScreeningRequest
import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.local.ScreeningEventDao
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.dto.ScreeningEventRequestDto
import io.github.snowjug.sparta.data.remote.safeApiCall
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.Json

/** Schedules the idempotent WorkManager upload (implemented with WorkManager; faked in tests). */
interface UploadScheduler {
    fun enqueueUpload(eventId: String)
}

/** Posts the low-key "Screening" notification (implemented with NotificationManager; faked in tests). */
interface ScreeningNotifier {
    fun notifyScreened(eventId: String, decision: ScreeningDecision, numberDisplay: String)
}

/**
 * Persists a finished screening decision and schedules its upload. Runs after the platform response has been sent,
 * so none of this can delay a call. Outgoing calls are never recorded.
 */
class ScreeningRecorder(
    private val events: ScreeningEventDao,
    private val settings: SettingsRepository,
    private val scheduler: UploadScheduler,
    private val notifier: ScreeningNotifier,
    private val ids: IdGenerator,
) {
    /** Returns the new event id, or null when nothing was recorded. */
    suspend fun record(
        request: ScreeningRequest,
        number: ScreenedNumber,
        outcome: ScreeningOutcome,
        occurredAtMs: Long,
    ): String? {
        if (outcome.decision.reason == ScreeningReason.OUTGOING_CALL) return null

        val id = ids.newId()
        val state = if (number.fingerprint == null) UploadState.LOCAL_ONLY else UploadState.PENDING
        events.insert(
            ScreeningEventEntity(
                clientEventId = id,
                numberFingerprint = number.fingerprint,
                numberDisplay = number.display,
                decision = outcome.decision.action.wire,
                reason = outcome.decision.reason.wire,
                verificationStatus = request.verification.wire,
                direction = request.direction.wire,
                occurredAtMs = occurredAtMs,
                decisionLatencyMs = outcome.latencyMs,
                deadlineMissed = outcome.deadlineMissed,
                uploadState = state,
            ),
        )
        sideEffect { if (outcome.deadlineMissed) settings.incrementDeadlineMisses() }
        if (state == UploadState.PENDING) sideEffect { scheduler.enqueueUpload(id) }
        if (outcome.decision.notifyOwner) {
            sideEffect {
                if (settings.current().notifyScreening) notifier.notifyScreened(id, outcome.decision, number.display)
            }
        }
        return id
    }

    private suspend fun sideEffect(block: suspend () -> Unit) {
        try {
            block()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // Persistence of the event itself already succeeded; a failed side effect must not undo or crash it.
        }
    }
}

sealed interface UploadOutcome {
    data class Uploaded(val backendCallId: String?) : UploadOutcome

    /** Nothing to do: unknown id, already uploaded, or intentionally local only. */
    data object NothingToDo : UploadOutcome

    /** Transient failure: try again with backoff. */
    data class Retry(val error: ApiError) : UploadOutcome

    /** Cannot succeed now (no backend configured, or sign-in required): leave pending for the next sync. */
    data class Deferred(val error: ApiError) : UploadOutcome

    /** The backend permanently refused the event. */
    data class Rejected(val error: ApiError) : UploadOutcome
}

/**
 * Idempotent upload of one screening event to `POST /screening/events`. The `client_event_id` (also sent as the
 * Idempotency-Key) makes a retry after a lost response safe: the backend replays the first result.
 */
class ScreeningUploader(
    private val events: ScreeningEventDao,
    private val api: SpartaApi,
    private val json: Json,
) {
    suspend fun upload(eventId: String): UploadOutcome {
        val event = events.get(eventId) ?: return UploadOutcome.NothingToDo
        if (event.uploadState != UploadState.PENDING) return UploadOutcome.NothingToDo
        val fingerprint = event.numberFingerprint
        if (fingerprint == null) {
            events.setUploadState(eventId, UploadState.LOCAL_ONLY, "no_fingerprint")
            return UploadOutcome.NothingToDo
        }

        val request = ScreeningEventRequestDto(
            clientEventId = event.clientEventId,
            numberFingerprint = fingerprint,
            numberDisplay = event.numberDisplay,
            decision = event.decision,
            reason = event.reason,
            verificationStatus = event.verificationStatus,
            // The backend only accepts incoming|outgoing (an "unknown" direction would be rejected as a validation error).
            direction = event.direction?.takeIf { it == "incoming" || it == "outgoing" },
            occurredAt = Timestamps.formatIsoUtc(event.occurredAtMs),
        )
        return when (val result = safeApiCall(json) { api.postScreeningEvent(event.clientEventId, request) }) {
            is ApiResult.Success -> {
                events.markUploaded(eventId, result.value.id)
                UploadOutcome.Uploaded(result.value.id)
            }
            is ApiResult.Failure -> classify(eventId, result.error)
        }
    }

    private suspend fun classify(eventId: String, error: ApiError): UploadOutcome = when (error.kind) {
        ApiErrorKind.OFFLINE,
        ApiErrorKind.TIMEOUT,
        ApiErrorKind.RATE_LIMITED,
        ApiErrorKind.SERVER,
        ApiErrorKind.PROVIDER_UNAVAILABLE,
        // A 2xx whose body could not be read may still have been stored: the idempotent retry settles it.
        ApiErrorKind.MALFORMED,
        -> {
            events.recordFailedAttempt(eventId, error.kind.name)
            UploadOutcome.Retry(error)
        }
        ApiErrorKind.NOT_CONFIGURED,
        ApiErrorKind.UNAUTHORIZED,
        ApiErrorKind.FORBIDDEN,
        -> {
            events.recordFailedAttempt(eventId, error.kind.name)
            UploadOutcome.Deferred(error)
        }
        else -> {
            events.setUploadState(eventId, UploadState.FAILED, error.kind.name)
            UploadOutcome.Rejected(error)
        }
    }
}
