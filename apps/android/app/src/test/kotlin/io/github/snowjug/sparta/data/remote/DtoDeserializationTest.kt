package io.github.snowjug.sparta.data.remote

import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallPageDto
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.EscalationStatus
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.OwnerActionType
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RecommendedAction
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.ScreeningConfigDto
import io.github.snowjug.sparta.data.remote.dto.ScreeningListsDto
import io.github.snowjug.sparta.data.remote.dto.SignalKind
import io.github.snowjug.sparta.data.remote.dto.SignalSeverity
import io.github.snowjug.sparta.data.remote.dto.Speaker
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.remote.dto.TurnSource
import io.github.snowjug.sparta.testutil.Fixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Decodes JSON written the way the FastAPI/pydantic backend serialises models.py (see src/test/resources/fixtures). */
class DtoDeserializationTest {

    private fun detail(): CallDetailDto = SpartaJson.decodeFromString(CallDetailDto.serializer(), Fixtures.text("call_detail.json"))

    @Test
    fun `call detail decodes every documented section`() {
        val call = detail()
        assertEquals("call_01HZX", call.id)
        assertEquals(ProviderKind.SIMULATOR, call.provider)
        assertEquals(CallMode.CONVERSATIONAL, call.mode)
        assertTrue(call.simulated)
        assertEquals(CallStatus.ACTIVE, call.status)
        assertEquals(CallState.ESCALATE, call.state)
        assertEquals("+91 98•••• ••21", call.callerDisplay)
        assertEquals("Swift Courier", call.callerClaim.organization)
        assertEquals(CallCategory.LEGITIMATE_DELIVERY, call.category)
        assertEquals(RiskLevel.LOW, call.riskLevel)
        assertEquals(0.81, call.confidence, 0.0)
        assertEquals(listOf("en-IN", "hi-IN"), call.languages)
        assertEquals("hinglish", call.languageProfile)
        assertTrue(call.ownerAttentionRequired)
        assertEquals("trace-abc123", call.traceId)
        assertEquals(653.5, call.metrics.getValue("p50_total_ms"), 0.0)
    }

    @Test
    fun `turns carry translation language segments and latency`() {
        val turns = detail().turns
        assertEquals(2, turns.size)
        assertEquals(Speaker.ASSISTANT, turns[0].speaker)
        assertEquals(TurnSource.ASSISTANT, turns[0].source)
        assertEquals(CallState.DISCLOSURE, turns[0].stateAfter)
        assertEquals("en-IN-NeerjaNeural", turns[0].speech?.voiceId)
        val caller = turns[1]
        assertEquals(Speaker.CALLER, caller.speaker)
        assertEquals(TurnSource.PROVIDER_STT, caller.source)
        assertNotNull(caller.translation)
        assertEquals("hinglish", caller.languageProfile)
        assertEquals(2, caller.segments.size)
        assertEquals("hinglish", caller.segments[0].variant)
        assertNull(caller.segments[1].variant)
        assertEquals(listOf("stt_ms"), caller.latency?.simulatedStages)
        assertEquals(653.5, caller.latency?.totalMs ?: 0.0, 0.0)
        assertTrue(caller.isFinal)
    }

    @Test
    fun `risk assessment keeps evidence signals and unknown enum values fall back`() {
        val risk = requireNotNull(detail().risk)
        assertEquals(RecommendedAction.ESCALATE_TO_OWNER, risk.recommendedAction)
        assertEquals(listOf(RecommendedAction.HUMAN_REVIEW), risk.additionalActions)
        assertTrue(risk.requiresOwnerAttention)
        assertEquals(3, risk.signals.size)
        val legit = risk.signals[0]
        assertEquals("LEGIT_DELIVERY_COORDINATION", legit.code)
        assertEquals(SignalKind.LEGITIMATE, legit.kind)
        assertEquals(SignalSeverity.INFO, legit.severity)
        assertEquals("parcel ke liye address confirm", legit.evidenceExcerpt)
        assertEquals(listOf("turn_2"), legit.evidenceTurnIds)
        val newer = risk.signals[2]
        assertEquals("SOME_NEW_SIGNAL_CODE", newer.code)
        assertEquals(SignalKind.RISK, newer.kind)
        assertEquals(SignalSeverity.UNKNOWN, newer.severity)
    }

    @Test
    fun `escalations owner actions feedback timeline and versions decode`() {
        val call = detail()
        assertEquals(EscalationStatus.REQUESTED, call.escalations.single().status)
        assertEquals(listOf("Parcel ke liye address confirm karna hai"), call.escalations.single().importantLines)
        assertEquals(OwnerActionType.UNKNOWN, call.ownerActions.single().action)
        assertEquals(FeedbackKind.CORRECT_CLASSIFICATION, call.feedback.single().kind)
        assertEquals(listOf("state", "escalation"), call.timeline.map { it.kind })
        assertEquals("simulator", call.providerEvents.single().provider)
        assertEquals("default-v1", call.versions.policyVersion)
        assertNull(call.summary)
    }

    @Test
    fun `capabilities are authoritative and honest`() {
        val capabilities = detail().capabilities
        assertTrue(capabilities.canTakeOver)
        assertTrue(capabilities.simulated)
        assertFalse(capabilities.twoWayAudio)
        assertEquals("Simulated takeover: no phone call is transferred.", capabilities.takeoverNote)
        assertEquals("The simulator has no real audio path.", capabilities.audioNote)
    }

    @Test
    fun `missing fields default to the least capable honest values`() {
        val minimal = SpartaJson.decodeFromString(CallDetailDto.serializer(), """{"id": "x"}""")
        assertEquals("x", minimal.id)
        assertTrue(minimal.simulated)
        assertFalse(minimal.capabilities.canTakeOver)
        assertFalse(minimal.capabilities.canContinue)
        assertFalse(minimal.capabilities.canEnd)
        assertFalse(minimal.capabilities.twoWayAudio)
        assertEquals(RiskLevel.UNKNOWN, minimal.riskLevel)
        assertEquals(CallState.UNKNOWN, minimal.state)
        assertTrue(minimal.turns.isEmpty())
    }

    @Test
    fun `null for a non nullable field with a default uses the default`() {
        val call = SpartaJson.decodeFromString(
            CallDetailDto.serializer(),
            """{"id": "x", "languages": null, "caller_display": null, "risk_score": null}""",
        )
        assertEquals(emptyList<String>(), call.languages)
        assertEquals("", call.callerDisplay)
        assertEquals(0.0, call.riskScore, 0.0)
    }

    @Test
    fun `call page carries items and the opaque cursor`() {
        val page = SpartaJson.decodeFromString(CallPageDto.serializer(), Fixtures.text("call_page.json"))
        assertEquals(2, page.items.size)
        assertEquals("cursor-2", page.nextCursor)
        val screening = page.items[0]
        assertEquals(ProviderKind.ANDROID_SCREENING, screening.provider)
        assertEquals(CallMode.SCREENING_ONLY, screening.mode)
        assertFalse(screening.hasContent)
        assertEquals("silence", screening.actionTaken)
        val spam = page.items[1]
        assertEquals(CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION, spam.category)
        assertEquals(RiskLevel.HIGH, spam.riskLevel)
        assertTrue(spam.blocked)
    }

    @Test
    fun `system status decodes telephony honesty fields and ignores new top level fields`() {
        val status = SpartaJson.decodeFromString(SystemStatusDto.serializer(), Fixtures.text("system_status.json"))
        assertEquals("0.1.0", status.version)
        assertTrue(status.devBanner)
        assertEquals("dev", status.authMode)
        assertEquals("simulator", status.telephony.provider)
        assertTrue(status.telephony.simulated)
        assertFalse(status.telephony.liveCallsSupported)
        assertNull(status.telephony.forwardingNumber)
        assertEquals("Simulator only: no phone number is attached.", status.telephony.note)
        assertTrue(status.features.translation)
        assertFalse(status.features.rawAudioStorage)
        assertEquals(listOf("supported", "supported", "supported", "planned"), status.languages.map { it.status })
        assertEquals("हिन्दी", status.languages[1].nativeName)
        assertEquals(900, status.limits.maxCallDurationS)
    }

    @Test
    fun `an empty status never claims live calls or real telephony`() {
        val status = SpartaJson.decodeFromString(SystemStatusDto.serializer(), "{}")
        assertTrue(status.telephony.simulated)
        assertFalse(status.telephony.liveCallsSupported)
    }

    @Test
    fun `screening config and lists decode`() {
        val config = SpartaJson.decodeFromString(ScreeningConfigDto.serializer(), Fixtures.text("screening_config.json"))
        assertEquals("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", config.fingerprintSalt)
        assertEquals("silence", config.unknownCallerBehavior)
        assertEquals("screen_anyway", config.trustedContactBehavior)
        assertEquals("strict", config.strictness)
        assertEquals("+918012345678", config.forwardingNumber)
        assertFalse(config.liveCallsSupported)

        val lists = SpartaJson.decodeFromString(ScreeningListsDto.serializer(), Fixtures.text("screening_lists.json"))
        assertEquals("blk_1", lists.blocked.single().id)
        assertEquals("+91 98•••• ••21", lists.blocked.single().numberDisplay)
        assertEquals("Dr. Rao", lists.trusted.single().label)
        assertEquals(64, lists.trusted.single().fingerprint.length)
    }

    @Test
    fun `timestamps parse with Z fractions and numeric offsets`() {
        val base = 1_794_909_600_000L // 2026-11-17T10:00:00Z
        assertEquals(base, Timestamps.parseMs("2026-11-17T10:00:00Z"))
        assertEquals(base + 123, Timestamps.parseMs("2026-11-17T10:00:00.123Z"))
        assertEquals(base, Timestamps.parseMs("2026-11-17T10:00:00+00:00"))
        assertEquals(base, Timestamps.parseMs("2026-11-17T15:30:00+05:30"))
        assertNull(Timestamps.parseMs("yesterday"))
        assertNull(Timestamps.parseMs(null))
        assertEquals("2026-11-17T10:00:00Z", Timestamps.formatIsoUtc(base))
    }
}
