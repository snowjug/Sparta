package io.github.snowjug.sparta.ui.incoming

import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus

enum class ControlId { TAKE_OVER, CONTINUE, END, BLOCK, TRUST }

enum class Unavailable {
    /** The call has not loaded yet. */
    NOT_LOADED,

    /** The call is over, so live controls no longer apply. */
    CALL_ENDED,

    /** Native on-device screening: the platform gives the app no way to join or steer a call. */
    SCREENING_ONLY,

    /** The telephony provider (see `CallDetail.capabilities`) cannot do this. The provider's own note is shown. */
    PROVIDER_CANNOT,

    ALREADY_TAKEN_OVER,
}

data class ControlState(
    val id: ControlId,
    val enabled: Boolean,
    val unavailable: Unavailable? = null,
    /** The backend's own explanation (`takeover_note`), shown next to a disabled or simulated control. */
    val note: String? = null,
    /** True when the action only simulates what its label says (simulator provider). */
    val simulated: Boolean = false,
)

/**
 * Which owner controls are honest right now. `CallDetail.capabilities` is authoritative: a control is only enabled
 * if the backend says the provider can do it AND the call is still live. Disabled controls carry the reason.
 */
object OwnerControls {
    fun evaluate(call: CallDetailDto?): List<ControlState> {
        if (call == null) {
            return ControlId.entries.map { ControlState(it, enabled = false, unavailable = Unavailable.NOT_LOADED) }
        }
        val caps = call.capabilities
        val live = call.status == CallStatus.ACTIVE
        val screeningOnly = call.mode == CallMode.SCREENING_ONLY

        fun live(id: ControlId, supported: Boolean, extra: Unavailable? = null): ControlState = when {
            screeningOnly -> ControlState(id, false, Unavailable.SCREENING_ONLY)
            !live -> ControlState(id, false, Unavailable.CALL_ENDED)
            extra != null -> ControlState(id, false, extra, note = caps.takeoverNote)
            !supported -> ControlState(id, false, Unavailable.PROVIDER_CANNOT, note = caps.takeoverNote)
            else -> ControlState(id, true, note = caps.takeoverNote.takeIf { caps.simulated }, simulated = caps.simulated)
        }

        return listOf(
            live(ControlId.TAKE_OVER, caps.canTakeOver, extra = Unavailable.ALREADY_TAKEN_OVER.takeIf { call.state == CallState.OWNER_TAKEOVER }),
            live(ControlId.CONTINUE, caps.canContinue),
            live(ControlId.END, caps.canEnd),
            ControlState(ControlId.BLOCK, enabled = caps.canBlock, unavailable = if (caps.canBlock) null else Unavailable.PROVIDER_CANNOT),
            // Trusting only edits the owner's own list, so it never depends on the telephony provider.
            ControlState(ControlId.TRUST, enabled = true),
        )
    }
}

/** What the call page may claim about audio: only what the backend reports for this call. */
enum class AudioClaim { TWO_WAY_AUDIO, SIMULATED, NO_AUDIO }

object AudioHonesty {
    fun claim(call: CallDetailDto): AudioClaim = when {
        call.capabilities.twoWayAudio && !call.capabilities.simulated && call.mode != CallMode.SCREENING_ONLY -> AudioClaim.TWO_WAY_AUDIO
        call.capabilities.simulated || call.simulated -> AudioClaim.SIMULATED
        else -> AudioClaim.NO_AUDIO
    }
}
