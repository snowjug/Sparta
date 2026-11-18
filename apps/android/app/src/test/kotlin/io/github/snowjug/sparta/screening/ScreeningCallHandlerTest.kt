package io.github.snowjug.sparta.screening

import io.github.snowjug.sparta.core.screening.CallDirection
import io.github.snowjug.sparta.core.screening.CallerVerification
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.core.screening.RespondOnce
import io.github.snowjug.sparta.core.screening.ScreenedNumber
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningCoordinator
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningDecisionEngine
import io.github.snowjug.sparta.core.screening.ScreeningFacts
import io.github.snowjug.sparta.core.screening.ScreeningOutcome
import io.github.snowjug.sparta.core.screening.ScreeningPolicy
import io.github.snowjug.sparta.core.screening.ScreeningReason
import io.github.snowjug.sparta.core.screening.ScreeningRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The platform gives a screening service about five seconds. These tests pin the guarantees the handler makes
 * whatever fails: one response, ALLOW unless a real decision arrived in time, nothing thrown, and the watchdog armed
 * before anything else can go wrong.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ScreeningCallHandlerTest {

    private class FakeWatchdog : WatchdogScheduler {
        class Scheduled(val delayMs: Long, val action: Runnable) {
            var cancelled = false
        }

        val scheduled = mutableListOf<Scheduled>()

        override fun schedule(delayMs: Long, action: Runnable): () -> Unit {
            val entry = Scheduled(delayMs, action)
            scheduled += entry
            return { entry.cancelled = true }
        }

        /** What the main looper would do when the delay elapses. */
        fun fire() = scheduled.filterNot { it.cancelled }.forEach { it.action.run() }
    }

    private class Recorded(val outcome: ScreeningOutcome, val number: ScreenedNumber, val occurredAtMs: Long)

    private class FakeRuntime(
        private val coordinatorProvider: () -> ScreeningCoordinator,
        override val appScope: CoroutineScope,
        private val failRecording: Boolean = false,
        private val failResolving: Boolean = false,
    ) : ScreeningRuntime {
        val records = mutableListOf<Recorded>()
        override val coordinator: ScreeningCoordinator get() = coordinatorProvider()

        override fun nowMs(): Long = 1_000L

        override suspend fun resolve(handle: String?): ScreenedNumber {
            if (failResolving) error("contacts database unavailable")
            return ScreenedNumber(null, "fingerprint", "+91 98\u2022\u2022\u2022\u2022 \u2022\u202221")
        }

        override suspend fun record(request: ScreeningRequest, number: ScreenedNumber, outcome: ScreeningOutcome, occurredAtMs: Long) {
            if (failRecording) error("disk full")
            records += Recorded(outcome, number, occurredAtMs)
        }
    }

    private val request = ScreeningRequest("tel:+919876543221", CallDirection.INCOMING, CallerVerification.NOT_VERIFIED)
    private val unknownFacts = ScreeningFacts(CallDirection.INCOMING, numberPresent = true)

    private fun TestScope.coordinator(
        scope: CoroutineScope,
        gather: suspend (ScreeningRequest) -> ScreeningFacts = { unknownFacts },
    ) = ScreeningCoordinator(
        scope = scope,
        workDispatcher = StandardTestDispatcher(testScheduler),
        clock = MonotonicClock { testScheduler.currentTime },
        engine = ScreeningDecisionEngine(),
        loadPolicy = { ScreeningPolicy() },
        gatherFacts = gather,
        deadlineMs = 1_500,
    )

    private fun TestScope.appScope() = CoroutineScope(SupervisorJob() + StandardTestDispatcher(testScheduler))

    private class Sink {
        val responses = mutableListOf<ScreeningDecision>()
        val responder = RespondOnce<ScreeningDecision> { responses += it }
    }

    private fun handlerFor(runtime: () -> ScreeningRuntime, watchdog: FakeWatchdog, testScheduler: kotlinx.coroutines.test.TestCoroutineScheduler) =
        ScreeningCallHandler(runtime, watchdog, elapsedRealtime = { testScheduler.currentTime })

    @Test
    fun `a fast local decision is delivered once and recorded as delivered`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ coordinator(scope) }, scope)
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ runtime }, watchdog, testScheduler).handle(request, sink.responder)
        assertEquals("the watchdog is armed before any work starts", listOf(ScreeningCallHandler.WATCHDOG_MS), watchdog.scheduled.map { it.delayMs })
        advanceUntilIdle()

        assertEquals(listOf(ScreeningAction.SILENCE), sink.responses.map { it.action })
        assertEquals(ScreeningReason.UNKNOWN_SCREENED, sink.responses.single().reason)
        assertTrue("the decision made the watchdog unnecessary", watchdog.scheduled.single().cancelled)
        val record = runtime.records.single()
        assertEquals(ScreeningAction.SILENCE, record.outcome.decision.action)
        assertFalse(record.outcome.deadlineMissed)
        assertEquals(1_000L, record.occurredAtMs)
    }

    @Test
    fun `work that never finishes is answered with allow at the internal deadline and the watchdog stands down`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ coordinator(scope) { awaitCancellation() } }, scope)
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ runtime }, watchdog, testScheduler).handle(request, sink.responder)
        advanceTimeBy(1_499)
        runCurrent()
        assertTrue("still inside the budget: no response yet", sink.responses.isEmpty())
        advanceTimeBy(2)
        runCurrent()

        assertEquals(listOf(ScreeningAction.ALLOW), sink.responses.map { it.action })
        assertEquals(ScreeningReason.DEADLINE_EXCEEDED, sink.responses.single().reason)
        assertTrue(watchdog.scheduled.single().cancelled)
        assertTrue(runtime.records.single().outcome.deadlineMissed)
    }

    @Test
    fun `when even the coordinator never runs the watchdog answers allow and a late decision cannot answer again`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ coordinator(scope) }, scope)
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ runtime }, watchdog, testScheduler).handle(request, sink.responder)
        // The dispatcher is never advanced: the coordinator has not started. The 2.5 s watchdog fires.
        watchdog.fire()
        assertEquals(listOf(ScreeningAction.ALLOW), sink.responses.map { it.action })
        assertEquals(ScreeningReason.DEADLINE_EXCEEDED, sink.responses.single().reason)

        // Later the real decision (silence) finally arrives. The platform was already answered: nothing more is sent.
        advanceUntilIdle()
        assertEquals("exactly one response per call", 1, sink.responses.size)
        val record = runtime.records.single()
        assertEquals("history records what the platform actually received", ScreeningAction.ALLOW, record.outcome.decision.action)
        assertTrue(record.outcome.deadlineMissed)
    }

    @Test
    fun `a failure while building the dependencies fails open without throwing`() = runTest {
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ error("Hilt component not ready") }, watchdog, testScheduler).handle(request, sink.responder)

        assertEquals(listOf(ScreeningAction.ALLOW), sink.responses.map { it.action })
        assertEquals(ScreeningReason.INTERNAL_ERROR, sink.responses.single().reason)
        assertEquals("the watchdog was armed even though the runtime could not be built", 1, watchdog.scheduled.size)
        assertTrue(watchdog.scheduled.single().cancelled)
    }

    @Test
    fun `a failure while resolving the coordinator inside the work fails open`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ error("database cannot be opened") }, scope)
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ runtime }, watchdog, testScheduler).handle(request, sink.responder)
        advanceUntilIdle()

        assertEquals(listOf(ScreeningAction.ALLOW), sink.responses.map { it.action })
        assertEquals(ScreeningReason.INTERNAL_ERROR, sink.responses.single().reason)
        assertTrue(watchdog.scheduled.single().cancelled)
    }

    @Test
    fun `an unreadable facts source is an error decision of allow not a crash`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ coordinator(scope) { error("room migration failed") } }, scope)
        val sink = Sink()

        handlerFor({ runtime }, FakeWatchdog(), testScheduler).handle(request, sink.responder)
        advanceUntilIdle()

        assertEquals(ScreeningAction.ALLOW, sink.responses.single().action)
        assertEquals(ScreeningReason.INTERNAL_ERROR, sink.responses.single().reason)
    }

    @Test
    fun `a scope that is already cancelled leaves the watchdog to answer`() = runTest {
        val scope = appScope()
        scope.cancel()
        val runtime = FakeRuntime({ coordinator(scope) }, scope)
        val watchdog = FakeWatchdog()
        val sink = Sink()

        handlerFor({ runtime }, watchdog, testScheduler).handle(request, sink.responder)
        advanceUntilIdle()
        assertTrue(sink.responses.isEmpty())
        assertFalse("the watchdog must stay armed", watchdog.scheduled.single().cancelled)

        watchdog.fire()
        assertEquals(ScreeningAction.ALLOW, sink.responses.single().action)
    }

    @Test
    fun `recording problems after the response never surface`() = runTest {
        val scope = appScope()
        val failing = FakeRuntime({ coordinator(scope) }, scope, failRecording = true)
        val sink = Sink()

        handlerFor({ failing }, FakeWatchdog(), testScheduler).handle(request, sink.responder)
        advanceUntilIdle() // an uncaught exception would fail this test

        assertEquals(1, sink.responses.size)
        assertTrue(failing.records.isEmpty())
    }

    @Test
    fun `when the number cannot be resolved the event is still recorded with a masked display`() = runTest {
        val scope = appScope()
        val runtime = FakeRuntime({ coordinator(scope) }, scope, failResolving = true)

        handlerFor({ runtime }, FakeWatchdog(), testScheduler).handle(request, Sink().responder)
        advanceUntilIdle()

        val record = runtime.records.single()
        assertFalse("the raw number must never reach storage", record.number.display.contains("9876543221"))
        assertEquals(null, record.number.fingerprint)
    }

    @Test
    fun `the internal budget is shorter than the watchdog which is shorter than the platform limit`() {
        assertTrue(ScreeningCoordinator.DEFAULT_DEADLINE_MS < ScreeningCallHandler.WATCHDOG_MS)
        assertTrue(ScreeningCallHandler.WATCHDOG_MS < 5_000)
    }
}
