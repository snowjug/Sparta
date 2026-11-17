package io.github.snowjug.sparta.screening

import io.github.snowjug.sparta.core.number.NumberMasker
import io.github.snowjug.sparta.core.screening.RespondOnce
import io.github.snowjug.sparta.core.screening.ScreenedNumber
import io.github.snowjug.sparta.core.screening.ScreeningCoordinator
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningOutcome
import io.github.snowjug.sparta.core.screening.ScreeningReason
import io.github.snowjug.sparta.core.screening.ScreeningRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** What the fast path needs. Production wires it through Hilt; tests supply fakes. */
interface ScreeningRuntime {
    val coordinator: ScreeningCoordinator

    /** Outlives the service: persisting the decision must survive the system unbinding it right after we respond. */
    val appScope: CoroutineScope

    fun nowMs(): Long

    suspend fun resolve(handle: String?): ScreenedNumber

    suspend fun record(request: ScreeningRequest, number: ScreenedNumber, outcome: ScreeningOutcome, occurredAtMs: Long)
}

/** Runs [action] after [delayMs] on a thread the screening work cannot block. The returned function cancels it. */
fun interface WatchdogScheduler {
    fun schedule(delayMs: Long, action: Runnable): () -> Unit
}

/**
 * The service's whole decision flow, free of Android types so it can be tested without a real call.
 *
 * Guarantees, whatever goes wrong (dependency construction, the database, contacts, a cancelled scope):
 *  - the platform gets exactly one response, and it is ALLOW unless a real local decision arrived in time;
 *  - the watchdog answers after [watchdogMs] even if the coordinator never does (it is armed before anything else);
 *  - nothing is thrown out of [handle].
 */
class ScreeningCallHandler(
    private val runtime: () -> ScreeningRuntime,
    private val watchdogs: WatchdogScheduler,
    private val elapsedRealtime: () -> Long,
    private val watchdogMs: Long = WATCHDOG_MS,
) {
    fun handle(request: ScreeningRequest, responder: RespondOnce<ScreeningDecision>) {
        val startedAt = elapsedRealtime()
        val cancelWatchdog = watchdogs.schedule(watchdogMs) {
            responder.respond(ScreeningDecision.safeDefault(ScreeningReason.DEADLINE_EXCEEDED))
        }
        try {
            val rt = runtime()
            val occurredAtMs = rt.nowMs()
            rt.appScope.launch {
                val outcome = try {
                    rt.coordinator.screen(request, responder)
                } catch (cancelled: CancellationException) {
                    // The watchdog stays armed and answers for us.
                    throw cancelled
                } catch (_: Throwable) {
                    responder.respond(ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR))
                    cancelWatchdog()
                    return@launch
                }
                cancelWatchdog()
                record(rt, request, truthful(outcome, responder, startedAt), occurredAtMs)
            }
        } catch (_: Throwable) {
            responder.respond(ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR))
            cancelWatchdog()
        }
    }

    /** Record what the platform really received: the watchdog may have answered before the coordinator did. */
    private fun truthful(outcome: ScreeningOutcome, responder: RespondOnce<ScreeningDecision>, startedAt: Long): ScreeningOutcome {
        val actual = responder.respondedWith ?: return outcome
        if (actual == outcome.decision) return outcome
        return outcome.copy(
            decision = actual,
            latencyMs = elapsedRealtime() - startedAt,
            deadlineMissed = actual.reason == ScreeningReason.DEADLINE_EXCEEDED || outcome.deadlineMissed,
            responseDelivered = true,
        )
    }

    private suspend fun record(rt: ScreeningRuntime, request: ScreeningRequest, outcome: ScreeningOutcome, occurredAtMs: Long) {
        try {
            val number = try {
                rt.resolve(request.handle)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                ScreenedNumber(null, null, NumberMasker.maskNumber(request.handle))
            }
            rt.record(request, number, outcome, occurredAtMs)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            // The call has already been answered correctly; failing to log it must never surface.
        }
    }

    companion object {
        /** Well under the platform's five seconds, and above the coordinator's own 1.5 s budget. */
        const val WATCHDOG_MS = 2_500L
    }
}
