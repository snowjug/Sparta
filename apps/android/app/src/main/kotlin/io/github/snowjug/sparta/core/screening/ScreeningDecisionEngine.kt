package io.github.snowjug.sparta.core.screening

/**
 * Pure, deterministic local decision. Rule order (first match wins):
 *
 * 1. Outgoing calls are always allowed.
 * 2. Blocked numbers are rejected (blocked beats trusted, contacts and verification).
 * 3. Failed caller-ID verification (STIR/SHAKEN): strict rejects, balanced silences, relaxed treats the caller as unknown.
 * 4. Known callers (trusted list, or saved contacts when the owner opted in) are allowed when the policy says so.
 * 5. Everyone else follows the unknown-caller behavior. Strict never lets a hidden/unparseable number ring.
 *
 * "Screen" on a plain phone means: silence the ringer and tell the owner. It is not an AI conversation.
 */
class ScreeningDecisionEngine {

    fun decide(facts: ScreeningFacts, policy: ScreeningPolicy): ScreeningDecision {
        if (facts.direction == CallDirection.OUTGOING) {
            return ScreeningDecision(ScreeningAction.ALLOW, ScreeningReason.OUTGOING_CALL)
        }
        if (facts.blocked) {
            return ScreeningDecision(ScreeningAction.REJECT, ScreeningReason.BLOCKED_NUMBER, notifyOwner = true)
        }

        var known = facts.trusted || (policy.treatContactsAsKnown && facts.contact == ContactMatch.FOUND)
        if (facts.verification == CallerVerification.FAILED) {
            when (policy.strictness) {
                Strictness.STRICT -> return ScreeningDecision(
                    ScreeningAction.REJECT,
                    ScreeningReason.VERIFICATION_FAILED_REJECTED,
                    notifyOwner = true,
                )
                Strictness.BALANCED -> return ScreeningDecision(
                    ScreeningAction.SILENCE,
                    ScreeningReason.VERIFICATION_FAILED_SILENCED,
                    notifyOwner = true,
                )
                // A spoofed "trusted" number is the classic attack: relaxed still drops the trust.
                Strictness.RELAXED -> known = false
            }
        }

        val knownReason = if (facts.trusted) ScreeningReason.TRUSTED_NUMBER else ScreeningReason.SAVED_CONTACT
        if (known && policy.trustedContactBehavior == TrustedContactBehavior.ALLOW_DIRECTLY) {
            return ScreeningDecision(ScreeningAction.ALLOW, knownReason)
        }
        return applyUnknownBehavior(facts, policy, known, knownReason)
    }

    private fun applyUnknownBehavior(
        facts: ScreeningFacts,
        policy: ScreeningPolicy,
        known: Boolean,
        knownReason: ScreeningReason,
    ): ScreeningDecision {
        val strictHidden = policy.strictness == Strictness.STRICT && !facts.numberPresent
        val behavior = if (policy.unknownCallerBehavior == UnknownCallerBehavior.ALLOW && strictHidden) {
            UnknownCallerBehavior.SCREEN
        } else {
            policy.unknownCallerBehavior
        }
        return when (behavior) {
            UnknownCallerBehavior.ALLOW -> ScreeningDecision(
                ScreeningAction.ALLOW,
                if (known) knownReason else ScreeningReason.UNKNOWN_ALLOWED,
            )
            UnknownCallerBehavior.SILENCE -> ScreeningDecision(
                ScreeningAction.SILENCE,
                if (known) ScreeningReason.KNOWN_SCREENED_ANYWAY else ScreeningReason.UNKNOWN_SILENCED,
            )
            UnknownCallerBehavior.SCREEN -> ScreeningDecision(
                ScreeningAction.SILENCE,
                when {
                    !facts.numberPresent -> ScreeningReason.HIDDEN_NUMBER_SCREENED
                    known -> ScreeningReason.KNOWN_SCREENED_ANYWAY
                    else -> ScreeningReason.UNKNOWN_SCREENED
                },
                notifyOwner = true,
            )
        }
    }
}
