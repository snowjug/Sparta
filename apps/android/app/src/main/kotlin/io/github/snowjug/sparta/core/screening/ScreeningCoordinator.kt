package io.github.snowjug.sparta.core.screening

import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withTimeoutOrNull

fun interface MonotonicClock {
    fun nowMs(): Long
}

/** What the platform tells us about a call; everything else is looked up locally. */
data class ScreeningRequest(
    val handle: String?,
    val direction: CallDirection,
    val verification: CallerVerification,
)

data class ScreeningOutcome(
    val decision: ScreeningDecision,
    val latencyMs: Long,
    val deadlineMissed: Boolean,
    val responseDelivered: Boolean,
    val errorType: String? = null,
)

enum class RespondResult { DELIVERED, DUPLICATE, FAILED }

/** Guarantees that the platform callback is invoked at most once, whichever path wins the race. */
class RespondOnce<T>(private val send: (T) -> Unit) {
    private val responded = AtomicBoolean(false)

    @Volatile
    private var first: T? = null

    val hasResponded: Boolean get() = responded.get()

    /** The value the platform was (or was attempted to be) given; null until the first response. */
    val respondedWith: T? get() = first

    fun respond(value: T): RespondResult {
        if (!responded.compareAndSet(false, true)) return RespondResult.DUPLICATE
        first = value
        return try {
            send(value)
            RespondResult.DELIVERED
        } catch (_: Throwable) {
            RespondResult.FAILED
        }
    }
}

/**
 * Runs the local-only fast path under an internal deadline and responds exactly once.
 *
 * The work runs in [scope] (which must use a SupervisorJob) so that a blocking database or contacts read that
 * ignores cancellation can never delay the response: after [deadlineMs] the safe default (ALLOW) is delivered and the
 * abandoned work is cancelled. Nothing escapes [screen] except cancellation of the calling coroutine.
 */
class ScreeningCoordinator(
    private val scope: CoroutineScope,
    private val workDispatcher: CoroutineDispatcher,
    private val clock: MonotonicClock,
    private val engine: ScreeningDecisionEngine,
    private val loadPolicy: suspend () -> ScreeningPolicy,
    private val gatherFacts: suspend (ScreeningRequest) -> ScreeningFacts,
    private val deadlineMs: Long = DEFAULT_DEADLINE_MS,
) {
    private sealed interface Work {
        data class Decided(val decision: ScreeningDecision) : Work
        data class Failed(val error: Throwable) : Work
    }

    suspend fun screen(request: ScreeningRequest, responder: RespondOnce<ScreeningDecision>): ScreeningOutcome {
        val startedAt = clock.nowMs()
        val work: Deferred<Work> = scope.async(workDispatcher) {
            try {
                val facts = gatherFacts(request)
                Work.Decided(engine.decide(facts, loadPolicy()))
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                Work.Failed(error)
            }
        }

        var missed = false
        var errorType: String? = null
        val decision = try {
            when (val result = withTimeoutOrNull(deadlineMs) { work.await() }) {
                is Work.Decided -> result.decision
                is Work.Failed -> {
                    errorType = result.error::class.java.simpleName
                    ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR)
                }
                null -> {
                    missed = true
                    work.cancel()
                    ScreeningDecision.safeDefault(ScreeningReason.DEADLINE_EXCEEDED)
                }
            }
        } catch (cancelled: CancellationException) {
            work.cancel()
            val fallback = ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR)
            if (currentCoroutineContext().isActive) {
                // The work was cancelled underneath us (its scope is gone), not the caller.
                errorType = "WorkCancelled"
                fallback
            } else {
                responder.respond(fallback)
                throw cancelled
            }
        }

        val result = responder.respond(decision)
        return ScreeningOutcome(
            decision = decision,
            latencyMs = clock.nowMs() - startedAt,
            deadlineMissed = missed,
            responseDelivered = result == RespondResult.DELIVERED,
            errorType = errorType,
        )
    }

    companion object {
        /** Internal budget; the platform allows five seconds, process start-up included. */
        const val DEFAULT_DEADLINE_MS = 1500L
    }
}
