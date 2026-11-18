package io.github.snowjug.sparta.ui.live

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.live.LiveCallState
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.OwnerActionResultDto
import io.github.snowjug.sparta.data.remote.ws.LiveCloseCodes
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.LiveCallSession
import io.github.snowjug.sparta.data.repo.LiveConnection
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.ControlState
import io.github.snowjug.sparta.ui.incoming.OwnerControls
import javax.inject.Inject
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class LiveCallUiState(
    val callId: String = "",
    val connection: LiveConnection = LiveConnection.CONNECTING,
    val live: LiveCallState = LiveCallState(callId = ""),
    val connectionError: ApiError? = null,
    val closeCode: Int? = null,
    /** Fetched over REST so the controls are honest even before (or without) the socket's first snapshot. */
    val restCall: CallDetailDto? = null,
    val busy: ControlId? = null,
    val message: UiMessage? = null,
) {
    /**
     * The newest call document. Events never rewrite the socket's snapshot or the REST copy, so what the socket has
     * established since (the call ended, the owner took over) is applied here; otherwise the controls would keep
     * offering what is no longer possible.
     */
    val call: CallDetailDto?
        get() {
            val doc = live.call ?: restCall ?: return null
            val state = live.callState.takeIf { it != CallState.UNKNOWN } ?: doc.state
            val status = if (live.isEnded && doc.status == CallStatus.ACTIVE) CallStatus.ENDED else doc.status
            return if (state == doc.state && status == doc.status) doc else doc.copy(state = state, status = status)
        }

    /** Only the controls that act on a live call; blocking and trusting live on the detail screen. */
    val liveControls: List<ControlState>
        get() = OwnerControls.evaluate(call).filter { it.id == ControlId.TAKE_OVER || it.id == ControlId.CONTINUE || it.id == ControlId.END }

    val notFound: Boolean get() = closeCode == LiveCloseCodes.CALL_NOT_FOUND
}

private data class LocalLive(val restCall: CallDetailDto? = null, val busy: ControlId? = null, val message: UiMessage? = null)

/**
 * Follows one call over the backend's live socket. The socket only runs while the screen is visible (it is closed
 * five seconds after the screen stops), so nothing keeps the radio awake in the background.
 */
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class LiveCallViewModel @Inject constructor(
    private val live: LiveCallSession,
    private val calls: CallsRepository,
) : ViewModel() {

    private val callId = MutableStateFlow<String?>(null)
    private val local = MutableStateFlow(LocalLive())

    val state: StateFlow<LiveCallUiState> = callId.filterNotNull().flatMapLatest { id ->
        combine(live.run(id), local) { session, l ->
            LiveCallUiState(
                callId = id,
                connection = session.connection,
                live = session.call,
                connectionError = session.error,
                closeCode = session.closeCode,
                restCall = l.restCall,
                busy = l.busy,
                message = l.message,
            )
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), LiveCallUiState())

    fun bind(id: String) {
        if (callId.value == id) return
        local.value = LocalLive()
        callId.value = id
        viewModelScope.launch {
            val result = calls.detail(id)
            if (result is ApiResult.Success) local.update { it.copy(restCall = result.value) }
        }
    }

    fun dismissMessage() = local.update { it.copy(message = null) }

    fun takeOver() = act(ControlId.TAKE_OVER) { calls.takeOver(it) }

    fun continueCall() = act(ControlId.CONTINUE) { calls.continueCall(it) }

    fun endCall() = act(ControlId.END) { calls.endCall(it) }

    private fun act(control: ControlId, run: suspend (String) -> ApiResult<OwnerActionResultDto>) {
        val id = callId.value ?: return
        if (local.value.busy != null) return
        local.update { it.copy(busy = control, message = null) }
        viewModelScope.launch {
            val result = run(id)
            val message = when (result) {
                is ApiResult.Success -> UiMessage.Text(
                    if (result.value.action.simulated) R.string.detail_msg_simulated_action else R.string.detail_msg_action_done,
                )
                is ApiResult.Failure -> UiMessage.Failure(result.error)
            }
            local.update { l ->
                // The action's own result is the newest word on the call: keep the REST copy (the only one without a socket snapshot) in step.
                val settled = (result as? ApiResult.Success)?.let { l.restCall?.after(it.value.call) } ?: l.restCall
                l.copy(restCall = settled, busy = null, message = message)
            }
        }
    }
}

/** What an owner action's result says about the call's progress; unknown values (a newer backend) change nothing. */
private fun CallDetailDto.after(settled: CallListItemDto): CallDetailDto = copy(
    state = settled.state.takeIf { it != CallState.UNKNOWN } ?: state,
    status = settled.status.takeIf { it != CallStatus.UNKNOWN } ?: status,
)
