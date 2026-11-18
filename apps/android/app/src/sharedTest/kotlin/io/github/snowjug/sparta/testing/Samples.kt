package io.github.snowjug.sparta.testing

import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.remote.dto.CallCapabilitiesDto
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.CallTurnDto
import io.github.snowjug.sparta.data.remote.dto.CallerClaimDto
import io.github.snowjug.sparta.data.remote.dto.EscalationDto
import io.github.snowjug.sparta.data.remote.dto.EscalationStatus
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RecommendedAction
import io.github.snowjug.sparta.data.remote.dto.RiskAssessmentDto
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.RiskSignalDto
import io.github.snowjug.sparta.data.remote.dto.SignalKind
import io.github.snowjug.sparta.data.remote.dto.SignalSeverity
import io.github.snowjug.sparta.data.remote.dto.Speaker
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.remote.dto.TelephonyStatusDto

/** Plain builders for UI tests. They compile for both the JVM (Robolectric) and the instrumented test APK. */
object Samples {
    const val MASKED = "+91 98\u2022\u2022\u2022\u2022 \u2022\u202221"

    /** 10:30 UTC on the day the sample calls started. */
    val NOW: Long = requireNotNull(Timestamps.parseMs("2026-11-17T10:30:00Z"))

    fun callItem(
        id: String = "call_1",
        display: String = MASKED,
        risk: RiskLevel = RiskLevel.LOW,
        category: CallCategory = CallCategory.LEGITIMATE_DELIVERY,
        provider: ProviderKind = ProviderKind.SIMULATOR,
        mode: CallMode = CallMode.CONVERSATIONAL,
        simulated: Boolean = true,
        status: CallStatus = CallStatus.ENDED,
        attention: Boolean = false,
        claimName: String? = "Ravi",
        organization: String? = "Swift Courier",
        purpose: String? = "Parcel delivery",
        summary: String? = "A courier asked to confirm a delivery address.",
        blocked: Boolean = false,
        trusted: Boolean = false,
        startedAt: String = "2026-11-17T10:00:00Z",
        hasContent: Boolean = true,
        languages: List<String> = listOf("en-IN", "hi-IN"),
        score: Double = 0.12,
        confidence: Double = 0.81,
    ) = CallListItemDto(
        id = id,
        provider = provider,
        mode = mode,
        simulated = simulated,
        status = status,
        state = if (status == CallStatus.ACTIVE) CallState.ESCALATE else CallState.COMPLETED,
        startedAt = startedAt,
        durationMs = if (status == CallStatus.ACTIVE) null else 74_000,
        callerDisplay = display,
        callerClaim = CallerClaimDto(claimName, organization, null),
        purpose = purpose,
        category = category,
        riskLevel = risk,
        riskScore = score,
        confidence = confidence,
        languages = languages,
        summaryText = summary,
        ownerAttentionRequired = attention,
        blocked = blocked,
        trusted = trusted,
        hasContent = hasContent,
    )

    fun turn(
        id: String,
        seq: Int,
        speaker: Speaker,
        text: String,
        language: String? = "en-IN",
        translation: String? = null,
    ) = CallTurnDto(id = id, callId = "call_1", seq = seq, speaker = speaker, text = text, language = language, translation = translation)

    fun signal(
        code: String = "OTP_REQUEST",
        kind: SignalKind = SignalKind.RISK,
        severity: SignalSeverity = SignalSeverity.HIGH,
        description: String = "Asked for a one-time password",
        excerpt: String? = "share the OTP",
    ) = RiskSignalDto(code = code, kind = kind, severity = severity, description = description, evidenceExcerpt = excerpt)

    fun riskAssessment(
        level: RiskLevel = RiskLevel.LOW,
        signals: List<RiskSignalDto> = emptyList(),
        action: RecommendedAction = RecommendedAction.ESCALATE_TO_OWNER,
        reasons: List<String> = emptyList(),
    ) = RiskAssessmentDto(
        callId = "call_1",
        riskLevel = level,
        riskScore = if (level == RiskLevel.HIGH) 0.93 else 0.12,
        confidence = 0.81,
        signals = signals,
        recommendedAction = action,
        reasons = reasons,
    )

    fun capabilities(
        takeOver: Boolean = false,
        cont: Boolean = false,
        end: Boolean = false,
        block: Boolean = true,
        simulated: Boolean = true,
        twoWay: Boolean = false,
        takeoverNote: String? = null,
        audioNote: String? = null,
    ) = CallCapabilitiesDto(
        canTakeOver = takeOver,
        canContinue = cont,
        canEnd = end,
        canBlock = block,
        simulated = simulated,
        twoWayAudio = twoWay,
        takeoverNote = takeoverNote,
        audioNote = audioNote,
    )

    fun escalation(lines: List<String> = listOf("Parcel ke liye address confirm karna hai")) = EscalationDto(
        id = "esc_1",
        callId = "call_1",
        reason = "A legitimate delivery call needs you",
        status = EscalationStatus.REQUESTED,
        importantLines = lines,
    )

    fun callDetail(
        item: CallListItemDto = callItem(),
        turns: List<CallTurnDto> = listOf(
            turn("turn_1", 1, Speaker.ASSISTANT, "Hello, I am an AI assistant answering for the owner. Who is calling?"),
            turn("turn_2", 2, Speaker.CALLER, "Haan, main Swift Courier se bol raha hoon", "hi-IN", "Yes, I am calling from Swift Courier"),
        ),
        risk: RiskAssessmentDto? = riskAssessment(item.riskLevel),
        capabilities: CallCapabilitiesDto = capabilities(),
        escalations: List<EscalationDto> = emptyList(),
        traceId: String = "trace-123",
    ) = CallDetailDto(
        id = item.id,
        provider = item.provider,
        mode = item.mode,
        simulated = item.simulated,
        status = item.status,
        state = item.state,
        startedAt = item.startedAt,
        durationMs = item.durationMs,
        callerDisplay = item.callerDisplay,
        callerClaim = item.callerClaim,
        purpose = item.purpose,
        category = item.category,
        riskLevel = item.riskLevel,
        riskScore = item.riskScore,
        confidence = item.confidence,
        languages = item.languages,
        summaryText = item.summaryText,
        ownerAttentionRequired = item.ownerAttentionRequired,
        blocked = item.blocked,
        trusted = item.trusted,
        hasContent = item.hasContent,
        turns = if (item.mode == CallMode.SCREENING_ONLY) emptyList() else turns,
        risk = risk,
        escalations = escalations,
        capabilities = capabilities,
        traceId = traceId,
    )

    fun event(
        id: String = "evt_1",
        decision: String = "silence",
        reason: String = "unknown_screened",
        display: String = MASKED,
        fingerprint: String? = "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12",
        occurredAtMs: Long = NOW - 5 * 60_000,
        latencyMs: Long = 18,
        missed: Boolean = false,
        verification: String? = "not_verified",
        direction: String? = "incoming",
        uploadState: String = UploadState.PENDING,
        backendCallId: String? = null,
    ) = ScreeningEventEntity(
        clientEventId = id,
        numberFingerprint = fingerprint,
        numberDisplay = display,
        decision = decision,
        reason = reason,
        verificationStatus = verification,
        direction = direction,
        occurredAtMs = occurredAtMs,
        decisionLatencyMs = latencyMs,
        deadlineMissed = missed,
        uploadState = uploadState,
        backendCallId = backendCallId,
    )

    fun status(
        simulated: Boolean = true,
        liveCalls: Boolean = false,
        provider: String = "simulator",
        devBanner: Boolean = true,
        forwardingNumber: String? = null,
        note: String = "The simulator does not receive real phone calls.",
    ) = SystemStatusDto(
        version = "0.1.0",
        env = "development",
        authMode = if (devBanner) "dev" else "oidc",
        devBanner = devBanner,
        telephony = TelephonyStatusDto(provider, simulated, liveCalls, forwardingNumber, note),
        policyVersion = "default-v1",
        languagePackVersion = "lp-1",
    )
}
