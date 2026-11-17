package io.github.snowjug.sparta.screening

import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.telecom.Call
import android.telecom.CallScreeningService
import android.telecom.PhoneAccount
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import io.github.snowjug.sparta.core.screening.CallDirection
import io.github.snowjug.sparta.core.screening.CallerVerification
import io.github.snowjug.sparta.core.screening.LocalFactsGatherer
import io.github.snowjug.sparta.core.screening.PlatformCodes
import io.github.snowjug.sparta.core.screening.RespondOnce
import io.github.snowjug.sparta.core.screening.ScreenedNumber
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningCoordinator
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningOutcome
import io.github.snowjug.sparta.core.screening.ScreeningReason
import io.github.snowjug.sparta.core.screening.ScreeningRequest
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.repo.ScreeningRecorder
import io.github.snowjug.sparta.di.ApplicationScope
import kotlinx.coroutines.CoroutineScope

/** Everything the service needs, fetched lazily so any failure while building it is caught and fails open. */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface ScreeningEntryPoint {
    fun coordinator(): ScreeningCoordinator

    fun gatherer(): LocalFactsGatherer

    fun recorder(): ScreeningRecorder

    @ApplicationScope
    fun appScope(): CoroutineScope

    fun wallClock(): WallClock
}

/** Hilt-backed [ScreeningRuntime]. Each dependency is resolved when first used, never at construction. */
private class HiltScreeningRuntime(private val entry: ScreeningEntryPoint) : ScreeningRuntime {
    override val coordinator: ScreeningCoordinator get() = entry.coordinator()
    override val appScope: CoroutineScope get() = entry.appScope()

    override fun nowMs(): Long = entry.wallClock().nowMs()

    override suspend fun resolve(handle: String?): ScreenedNumber = entry.gatherer().resolve(handle)

    override suspend fun record(request: ScreeningRequest, number: ScreenedNumber, outcome: ScreeningOutcome, occurredAtMs: Long) {
        entry.recorder().record(request, number, outcome, occurredAtMs)
    }
}

/** Posts the watchdog on the main looper: it must not depend on the executors the screening work runs on. */
private class HandlerWatchdogScheduler(private val handler: Handler) : WatchdogScheduler {
    override fun schedule(delayMs: Long, action: Runnable): () -> Unit {
        handler.postDelayed(action, delayMs)
        return { handler.removeCallbacks(action) }
    }
}

object ScreeningResponses {
    /**
     * ALLOW is the platform default. SILENCE needs Android 10+; on older versions it cannot be honoured, so the call
     * is allowed. REJECT disallows and rejects the call and skips the system's missed-call notification (Sparta posts
     * its own). The call-log entry is deliberately left to the system (skipCallLog stays false), so a rejected call
     * remains visible in the phone's call history.
     */
    fun toCallResponse(decision: ScreeningDecision): CallScreeningService.CallResponse {
        val builder = CallScreeningService.CallResponse.Builder()
        when (decision.action) {
            ScreeningAction.ALLOW -> Unit
            ScreeningAction.SILENCE -> if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) builder.setSilenceCall(true)
            ScreeningAction.REJECT -> builder.setDisallowCall(true).setRejectCall(true).setSkipNotification(true)
        }
        return builder.build()
    }
}

/**
 * Native call screening: allow, silence or reject an incoming call and nothing else. A screening service cannot answer
 * the call or touch its audio, so there is no AI conversation here; live AI audio only exists when a call reaches the
 * backend's telephony number (carrier forwarding).
 *
 * Hard rules (see [ScreeningCallHandler] and ScreeningCoordinator): local data only, ~1.5 s internal deadline, a 2.5 s
 * watchdog, ALLOW as the safe default, exactly one response per call, and nothing is allowed to throw out of
 * [onScreenCall].
 */
class SpartaCallScreeningService : CallScreeningService() {

    private val handler: ScreeningCallHandler by lazy(LazyThreadSafetyMode.NONE) {
        ScreeningCallHandler(
            runtime = { HiltScreeningRuntime(EntryPointAccessors.fromApplication(applicationContext, ScreeningEntryPoint::class.java)) },
            watchdogs = HandlerWatchdogScheduler(Handler(Looper.getMainLooper())),
            elapsedRealtime = SystemClock::elapsedRealtime,
        )
    }

    override fun onScreenCall(callDetails: Call.Details) {
        val responder = RespondOnce<ScreeningDecision> { decision ->
            respondToCall(callDetails, ScreeningResponses.toCallResponse(decision))
        }
        try {
            handler.handle(requestFrom(callDetails), responder)
        } catch (_: Throwable) {
            responder.respond(ScreeningDecision.safeDefault(ScreeningReason.INTERNAL_ERROR))
        }
    }

    private fun requestFrom(details: Call.Details): ScreeningRequest {
        val handle = details.handle?.takeIf { it.scheme == PhoneAccount.SCHEME_TEL }?.schemeSpecificPart
        val direction = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            PlatformCodes.direction(details.callDirection)
        } else {
            CallDirection.UNKNOWN
        }
        val verification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            PlatformCodes.verification(details.callerNumberVerificationStatus)
        } else {
            CallerVerification.UNKNOWN
        }
        return ScreeningRequest(handle, direction, verification)
    }
}
