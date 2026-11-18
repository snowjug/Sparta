package io.github.snowjug.sparta.core.screening

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreeningDecisionEngineTest {

    private val engine = ScreeningDecisionEngine()

    private fun facts(
        direction: CallDirection = CallDirection.INCOMING,
        numberPresent: Boolean = true,
        blocked: Boolean = false,
        trusted: Boolean = false,
        contact: ContactMatch = ContactMatch.NOT_FOUND,
        verification: CallerVerification = CallerVerification.NOT_VERIFIED,
    ) = ScreeningFacts(direction, numberPresent, blocked, trusted, contact, verification)

    private fun policy(
        unknown: UnknownCallerBehavior = UnknownCallerBehavior.SCREEN,
        trusted: TrustedContactBehavior = TrustedContactBehavior.ALLOW_DIRECTLY,
        strictness: Strictness = Strictness.BALANCED,
        contacts: Boolean = false,
    ) = ScreeningPolicy(unknown, trusted, strictness, contacts)

    private fun assertDecision(
        expectedAction: ScreeningAction,
        expectedReason: ScreeningReason,
        actual: ScreeningDecision,
        notify: Boolean? = null,
    ) {
        assertEquals(expectedAction, actual.action)
        assertEquals(expectedReason, actual.reason)
        if (notify != null) assertEquals(notify, actual.notifyOwner)
    }

    // ---- outgoing ----

    @Test
    fun `outgoing calls are always allowed even if the number is blocked`() {
        val decision = engine.decide(facts(direction = CallDirection.OUTGOING, blocked = true), policy(strictness = Strictness.STRICT))
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.OUTGOING_CALL, decision, notify = false)
    }

    // ---- blocked ----

    @Test
    fun `blocked numbers are rejected under every strictness and unknown behavior`() {
        for (strictness in Strictness.entries) {
            for (unknown in UnknownCallerBehavior.entries) {
                val decision = engine.decide(facts(blocked = true), policy(unknown = unknown, strictness = strictness))
                assertDecision(ScreeningAction.REJECT, ScreeningReason.BLOCKED_NUMBER, decision, notify = true)
            }
        }
    }

    @Test
    fun `blocked beats trusted contact and passed verification`() {
        val decision = engine.decide(
            facts(blocked = true, trusted = true, contact = ContactMatch.FOUND, verification = CallerVerification.PASSED),
            policy(contacts = true),
        )
        assertDecision(ScreeningAction.REJECT, ScreeningReason.BLOCKED_NUMBER, decision)
    }

    @Test
    fun `blocked beats failed verification handling`() {
        val decision = engine.decide(facts(blocked = true, verification = CallerVerification.FAILED), policy(strictness = Strictness.BALANCED))
        assertDecision(ScreeningAction.REJECT, ScreeningReason.BLOCKED_NUMBER, decision)
    }

    // ---- trusted / contacts ----

    @Test
    fun `trusted number is allowed directly by default`() {
        val decision = engine.decide(facts(trusted = true), policy())
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.TRUSTED_NUMBER, decision, notify = false)
    }

    @Test
    fun `trusted number with screen anyway follows the unknown behavior`() {
        val screenAnyway = TrustedContactBehavior.SCREEN_ANYWAY
        assertDecision(
            ScreeningAction.SILENCE,
            ScreeningReason.KNOWN_SCREENED_ANYWAY,
            engine.decide(facts(trusted = true), policy(trusted = screenAnyway, unknown = UnknownCallerBehavior.SCREEN)),
            notify = true,
        )
        assertDecision(
            ScreeningAction.SILENCE,
            ScreeningReason.KNOWN_SCREENED_ANYWAY,
            engine.decide(facts(trusted = true), policy(trusted = screenAnyway, unknown = UnknownCallerBehavior.SILENCE)),
            notify = false,
        )
        assertDecision(
            ScreeningAction.ALLOW,
            ScreeningReason.TRUSTED_NUMBER,
            engine.decide(facts(trusted = true), policy(trusted = screenAnyway, unknown = UnknownCallerBehavior.ALLOW)),
        )
    }

    @Test
    fun `saved contact is allowed only when the owner opted in`() {
        val found = facts(contact = ContactMatch.FOUND)
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.SAVED_CONTACT, engine.decide(found, policy(contacts = true)))
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, engine.decide(found, policy(contacts = false)))
    }

    @Test
    fun `contacts permission denied is never treated as a known contact`() {
        val decision = engine.decide(facts(contact = ContactMatch.UNAVAILABLE), policy(contacts = true))
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, decision)
    }

    @Test
    fun `saved contact with screen anyway follows the unknown behavior`() {
        val decision = engine.decide(
            facts(contact = ContactMatch.FOUND),
            policy(contacts = true, trusted = TrustedContactBehavior.SCREEN_ANYWAY, unknown = UnknownCallerBehavior.ALLOW),
        )
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.SAVED_CONTACT, decision)
    }

    // ---- STIR/SHAKEN ----

    @Test
    fun `failed verification is rejected when strict even for trusted numbers`() {
        val decision = engine.decide(
            facts(trusted = true, verification = CallerVerification.FAILED),
            policy(strictness = Strictness.STRICT),
        )
        assertDecision(ScreeningAction.REJECT, ScreeningReason.VERIFICATION_FAILED_REJECTED, decision, notify = true)
    }

    @Test
    fun `failed verification is silenced when balanced even for trusted numbers`() {
        val trusted = engine.decide(facts(trusted = true, verification = CallerVerification.FAILED), policy(strictness = Strictness.BALANCED))
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.VERIFICATION_FAILED_SILENCED, trusted, notify = true)
        val stranger = engine.decide(
            facts(verification = CallerVerification.FAILED),
            policy(unknown = UnknownCallerBehavior.ALLOW, strictness = Strictness.BALANCED),
        )
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.VERIFICATION_FAILED_SILENCED, stranger)
    }

    @Test
    fun `failed verification under relaxed drops the trust and follows unknown behavior`() {
        val trusted = engine.decide(
            facts(trusted = true, verification = CallerVerification.FAILED),
            policy(strictness = Strictness.RELAXED, unknown = UnknownCallerBehavior.SCREEN),
        )
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, trusted)
        val allowAll = engine.decide(
            facts(verification = CallerVerification.FAILED),
            policy(strictness = Strictness.RELAXED, unknown = UnknownCallerBehavior.ALLOW),
        )
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.UNKNOWN_ALLOWED, allowAll)
    }

    @Test
    fun `passed and unverified calls do not change the unknown behavior`() {
        for (verification in listOf(CallerVerification.PASSED, CallerVerification.NOT_VERIFIED, CallerVerification.UNKNOWN)) {
            val decision = engine.decide(facts(verification = verification), policy(unknown = UnknownCallerBehavior.ALLOW))
            assertDecision(ScreeningAction.ALLOW, ScreeningReason.UNKNOWN_ALLOWED, decision)
        }
    }

    // ---- unknown callers ----

    @Test
    fun `unknown caller screen silences the ringer and notifies`() {
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, engine.decide(facts(), policy(unknown = UnknownCallerBehavior.SCREEN)), notify = true)
    }

    @Test
    fun `unknown caller silence is silent about it`() {
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SILENCED, engine.decide(facts(), policy(unknown = UnknownCallerBehavior.SILENCE)), notify = false)
    }

    @Test
    fun `unknown caller allow lets the call ring`() {
        assertDecision(ScreeningAction.ALLOW, ScreeningReason.UNKNOWN_ALLOWED, engine.decide(facts(), policy(unknown = UnknownCallerBehavior.ALLOW)), notify = false)
    }

    // ---- hidden / anonymous ----

    @Test
    fun `strict never lets a hidden number ring`() {
        val decision = engine.decide(facts(numberPresent = false), policy(unknown = UnknownCallerBehavior.ALLOW, strictness = Strictness.STRICT))
        assertDecision(ScreeningAction.SILENCE, ScreeningReason.HIDDEN_NUMBER_SCREENED, decision, notify = true)
    }

    @Test
    fun `hidden number under balanced or relaxed follows the owner setting`() {
        for (strictness in listOf(Strictness.BALANCED, Strictness.RELAXED)) {
            val decision = engine.decide(facts(numberPresent = false), policy(unknown = UnknownCallerBehavior.ALLOW, strictness = strictness))
            assertDecision(ScreeningAction.ALLOW, ScreeningReason.UNKNOWN_ALLOWED, decision)
        }
    }

    @Test
    fun `strict hidden number keeps silence or screen as configured`() {
        assertDecision(
            ScreeningAction.SILENCE,
            ScreeningReason.UNKNOWN_SILENCED,
            engine.decide(facts(numberPresent = false), policy(unknown = UnknownCallerBehavior.SILENCE, strictness = Strictness.STRICT)),
        )
        assertDecision(
            ScreeningAction.SILENCE,
            ScreeningReason.HIDDEN_NUMBER_SCREENED,
            engine.decide(facts(numberPresent = false), policy(unknown = UnknownCallerBehavior.SCREEN, strictness = Strictness.STRICT)),
            notify = true,
        )
    }

    // ---- invariants ----

    @Test
    fun `the engine never answers or records and only returns the three platform actions`() {
        val everything = Strictness.entries.flatMap { s ->
            UnknownCallerBehavior.entries.flatMap { u ->
                TrustedContactBehavior.entries.flatMap { t ->
                    CallerVerification.entries.map { v ->
                        engine.decide(facts(trusted = true, verification = v), policy(unknown = u, trusted = t, strictness = s))
                    }
                }
            }
        }
        assertTrue(everything.all { it.action in ScreeningAction.entries })
        assertFalse(everything.any { it.reason == ScreeningReason.DEADLINE_EXCEEDED || it.reason == ScreeningReason.INTERNAL_ERROR })
    }

    @Test
    fun `safe default is allow with no notification`() {
        val decision = ScreeningDecision.safeDefault(ScreeningReason.DEADLINE_EXCEEDED)
        assertEquals(ScreeningAction.ALLOW, decision.action)
        assertFalse(decision.notifyOwner)
    }

    @Test
    fun `wire parsing falls back to safe defaults`() {
        assertEquals(UnknownCallerBehavior.SCREEN, UnknownCallerBehavior.fromWire("garbage"))
        assertEquals(TrustedContactBehavior.ALLOW_DIRECTLY, TrustedContactBehavior.fromWire(null))
        assertEquals(Strictness.BALANCED, Strictness.fromWire("unexpected"))
        assertEquals(Strictness.STRICT, Strictness.fromWire("strict"))
    }
}
