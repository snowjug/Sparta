package io.github.snowjug.sparta.core.screening

import io.github.snowjug.sparta.core.number.NumberFingerprinter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LocalFactsGathererTest {

    private val saltB64 = "c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx"
    private val blockedFingerprint = "02104505014ef8e921b8225bdb991179325c1a15a591448f08f012125a98a8be" // +919812345621
    private val trustedFingerprint = "5d1520e8d73327bd269b10828e5c681d4dc35cb56cf4e04fc51e0370f3de742f" // +14155552671

    private class FakeLists(val blocked: Set<String> = emptySet(), val trusted: Set<String> = emptySet()) : ScreeningLists {
        var lookups = 0
        override suspend fun isBlocked(fingerprint: String): Boolean = blocked.contains(fingerprint).also { lookups++ }
        override suspend fun isTrusted(fingerprint: String): Boolean = trusted.contains(fingerprint).also { lookups++ }
    }

    private fun gatherer(
        lists: ScreeningLists,
        contacts: ContactsLookup = ContactsLookup { ContactMatch.UNAVAILABLE },
        salt: String? = saltB64,
    ) = LocalFactsGatherer(lists, contacts, fingerprinters = FingerprinterSource { salt?.let(::NumberFingerprinter) })

    private fun request(handle: String?, verification: CallerVerification = CallerVerification.NOT_VERIFIED) =
        ScreeningRequest(handle, CallDirection.INCOMING, verification)

    @Test
    fun `blocked number from the local cache is rejected with no network involved`() = runTest {
        val lists = FakeLists(blocked = setOf(blockedFingerprint))
        val gatherer = gatherer(lists)
        val facts = gatherer.gather(request("tel:%2B91%2098123%2045621"))
        assertTrue(facts.blocked)
        assertFalse(facts.trusted)

        val decision = ScreeningDecisionEngine().decide(facts, ScreeningPolicy())
        assertEquals(ScreeningAction.REJECT, decision.action)
        assertEquals(ScreeningReason.BLOCKED_NUMBER, decision.reason)
    }

    @Test
    fun `trusted number from the local cache is allowed`() = runTest {
        val gatherer = gatherer(FakeLists(trusted = setOf(trustedFingerprint)))
        val facts = gatherer.gather(request("+1 (415) 555-2671"))
        assertTrue(facts.trusted)
        assertEquals(ScreeningAction.ALLOW, ScreeningDecisionEngine().decide(facts, ScreeningPolicy()).action)
    }

    @Test
    fun `contacts match is consulted with the normalized number only`() = runTest {
        var seen: String? = null
        val gatherer = gatherer(FakeLists(), contacts = ContactsLookup { e164 -> seen = e164; ContactMatch.FOUND })
        val facts = gatherer.gather(request("+91 98123-45621"))
        assertEquals("+919812345621", seen)
        assertEquals(ContactMatch.FOUND, facts.contact)
    }

    @Test
    fun `unparseable or missing handle is a hidden number with no list lookups`() = runTest {
        val lists = FakeLists(blocked = setOf(blockedFingerprint))
        val gatherer = gatherer(lists)
        val facts = gatherer.gather(request(null))
        assertFalse(facts.numberPresent)
        assertFalse(facts.blocked)
        assertEquals(0, lists.lookups)
        assertEquals(ContactMatch.NOT_FOUND, facts.contact)
    }

    @Test
    fun `missing salt means lists cannot match but the number is still present`() = runTest {
        val lists = FakeLists(blocked = setOf(blockedFingerprint))
        val gatherer = gatherer(lists, salt = null)
        val facts = gatherer.gather(request("+919812345621"))
        assertTrue(facts.numberPresent)
        assertFalse(facts.blocked)
        assertEquals(0, lists.lookups)
        assertNull(gatherer.resolve("+919812345621").fingerprint)
    }

    @Test
    fun `resolve returns masked display and fingerprint but never the raw number`() = runTest {
        val resolved = gatherer(FakeLists()).resolve("+919812345621")
        assertEquals("+91 98•••• ••21", resolved.display)
        assertEquals(blockedFingerprint, resolved.fingerprint)
        assertNotNull(resolved.normalized)
        assertFalse(resolved.display.contains("9812345621"))
    }

    @Test
    fun `private handle resolves to private number with no fingerprint`() = runTest {
        val resolved = gatherer(FakeLists()).resolve(null)
        assertEquals("Private number", resolved.display)
        assertNull(resolved.fingerprint)
        assertNull(resolved.normalized)
    }

    @Test
    fun `contacts are not read at all unless the owner opted in`() = runTest {
        var lookedUp = false
        val gatherer = LocalFactsGatherer(
            lists = FakeLists(),
            contacts = ContactsLookup { lookedUp = true; ContactMatch.FOUND },
            fingerprinters = FingerprinterSource { NumberFingerprinter(saltB64) },
            contactsEnabled = { false },
        )
        val facts = gatherer.gather(request("+919812345621"))
        assertFalse(lookedUp)
        assertEquals(ContactMatch.UNAVAILABLE, facts.contact)
    }

    @Test
    fun `verification status is passed through from the request`() = runTest {
        val facts = gatherer(FakeLists()).gather(request("+919812345621", CallerVerification.FAILED))
        assertEquals(CallerVerification.FAILED, facts.verification)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ScreeningCoordinatorTest {

    private class Harness(testScope: TestScope) {
        val dispatcher = StandardTestDispatcher(testScope.testScheduler)
        val scope = CoroutineScope(SupervisorJob() + dispatcher)
        val clock = MonotonicClock { testScope.testScheduler.currentTime }
        val sent = mutableListOf<ScreeningDecision>()
        val responder = RespondOnce<ScreeningDecision> { sent += it }
        val request = ScreeningRequest("+919812345621", CallDirection.INCOMING, CallerVerification.NOT_VERIFIED)
    }

    private fun coordinator(
        h: Harness,
        policy: ScreeningPolicy = ScreeningPolicy(),
        gather: suspend (ScreeningRequest) -> ScreeningFacts,
    ) = ScreeningCoordinator(
        scope = h.scope,
        workDispatcher = h.dispatcher,
        clock = h.clock,
        engine = ScreeningDecisionEngine(),
        loadPolicy = { policy },
        gatherFacts = gather,
    )

    private val unknownFacts = ScreeningFacts(CallDirection.INCOMING, numberPresent = true, contact = ContactMatch.NOT_FOUND)

    @Test
    fun `fast path responds once with the engine decision and measures latency`() = runTest {
        val h = Harness(this)
        val outcome = coordinator(h) { delay(40); unknownFacts }.screen(h.request, h.responder)

        assertEquals(ScreeningAction.SILENCE, outcome.decision.action)
        assertEquals(ScreeningReason.UNKNOWN_SCREENED, outcome.decision.reason)
        assertFalse(outcome.deadlineMissed)
        assertTrue(outcome.responseDelivered)
        assertEquals(40L, outcome.latencyMs)
        assertEquals(listOf(outcome.decision), h.sent)
    }

    @Test
    fun `a slow lookup misses the deadline and the safe default allow is delivered exactly once`() = runTest {
        val h = Harness(this)
        var finished = false
        val outcome = coordinator(h) {
            delay(4_000)
            finished = true
            unknownFacts
        }.screen(h.request, h.responder)

        assertTrue(outcome.deadlineMissed)
        assertEquals(ScreeningAction.ALLOW, outcome.decision.action)
        assertEquals(ScreeningReason.DEADLINE_EXCEEDED, outcome.decision.reason)
        assertEquals(ScreeningCoordinator.DEFAULT_DEADLINE_MS, outcome.latencyMs)
        assertEquals(1, h.sent.size)

        // The abandoned work is cancelled and can never cause a second response.
        advanceTimeBy(10_000)
        runCurrent()
        assertFalse(finished)
        assertEquals(1, h.sent.size)
    }

    @Test
    fun `work that never completes still answers at the deadline`() = runTest {
        val h = Harness(this)
        val outcome = coordinator(h) { awaitCancellation() }.screen(h.request, h.responder)
        assertTrue(outcome.deadlineMissed)
        assertEquals(1, h.sent.size)
    }

    @Test
    fun `deadline is the internal budget well below the five second platform limit`() {
        assertTrue(ScreeningCoordinator.DEFAULT_DEADLINE_MS in 1000L..2500L)
    }

    @Test
    fun `an exception in the fast path fails open and never escapes`() = runTest {
        val h = Harness(this)
        val outcome = coordinator(h) { throw IllegalStateException("database corrupted") }.screen(h.request, h.responder)

        assertEquals(ScreeningAction.ALLOW, outcome.decision.action)
        assertEquals(ScreeningReason.INTERNAL_ERROR, outcome.decision.reason)
        assertEquals("IllegalStateException", outcome.errorType)
        assertFalse(outcome.deadlineMissed)
        assertEquals(1, h.sent.size)
    }

    @Test
    fun `a policy that cannot be loaded also fails open`() = runTest {
        val h = Harness(this)
        val coordinator = ScreeningCoordinator(
            scope = h.scope,
            workDispatcher = h.dispatcher,
            clock = h.clock,
            engine = ScreeningDecisionEngine(),
            loadPolicy = { error("datastore unavailable") },
            gatherFacts = { unknownFacts },
        )
        val outcome = coordinator.screen(h.request, h.responder)
        assertEquals(ScreeningReason.INTERNAL_ERROR, outcome.decision.reason)
        assertEquals(1, h.sent.size)
    }

    @Test
    fun `a responder that throws does not cause a second response`() = runTest {
        val h = Harness(this)
        var calls = 0
        val throwing = RespondOnce<ScreeningDecision> { calls++; error("call is gone") }
        val outcome = coordinator(h) { unknownFacts }.screen(h.request, throwing)

        assertFalse(outcome.responseDelivered)
        assertEquals(1, calls)
        assertEquals(RespondResult.DUPLICATE, throwing.respond(ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR)))
        assertEquals(1, calls)
    }

    @Test
    fun `respond once ignores every later response`() {
        val delivered = mutableListOf<String>()
        val once = RespondOnce<String> { delivered += it }
        assertFalse(once.hasResponded)
        assertNull(once.respondedWith)
        assertEquals(RespondResult.DELIVERED, once.respond("first"))
        assertEquals(RespondResult.DUPLICATE, once.respond("second"))
        assertEquals(RespondResult.DUPLICATE, once.respond("third"))
        assertTrue(once.hasResponded)
        assertEquals("first", once.respondedWith)
        assertEquals(listOf("first"), delivered)
    }

    @Test
    fun `a watchdog response that wins the race is what the platform actually received`() = runTest {
        val h = Harness(this)
        // The service's independent watchdog answered first (for example the dependency graph was slow to build).
        h.responder.respond(ScreeningDecision.safeDefault(ScreeningReason.DEADLINE_EXCEEDED))
        val outcome = coordinator(h) { unknownFacts }.screen(h.request, h.responder)

        assertFalse(outcome.responseDelivered)
        assertEquals(ScreeningReason.DEADLINE_EXCEEDED, h.responder.respondedWith?.reason)
        assertEquals(1, h.sent.size)
    }

    @Test
    fun `a blocked number decided locally is rejected through the full path`() = runTest {
        val h = Harness(this)
        val gatherer = LocalFactsGatherer(
            lists = object : ScreeningLists {
                override suspend fun isBlocked(fingerprint: String) = true
                override suspend fun isTrusted(fingerprint: String) = false
            },
            contacts = ContactsLookup { ContactMatch.UNAVAILABLE },
            fingerprinters = FingerprinterSource { NumberFingerprinter("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx") },
        )
        val outcome = coordinator(h) { gatherer.gather(it) }.screen(h.request, h.responder)
        assertEquals(ScreeningAction.REJECT, outcome.decision.action)
        assertEquals(listOf(outcome.decision), h.sent)
    }
}
