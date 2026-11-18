package io.github.snowjug.sparta.ui.detail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.OwnerControls
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What is being deleted; the screen asks for confirmation first. */
enum class DeleteKind { CONTENT, CALL }

data class CallDetailUiState(
    val callId: String = "",
    val loading: Boolean = true,
    val call: CallDetailDto? = null,
    /** The list row cached from an earlier visit, shown instantly while the full detail loads. */
    val cached: CallListItemDto? = null,
    val error: ApiError? = null,
    val busy: ControlId? = null,
    val deleting: DeleteKind? = null,
    val feedbackSent: Set<FeedbackKind> = emptySet(),
    val showTranslations: Boolean = false,
    val message: UiMessage? = null,
    val deleted: Boolean = false,
    val nowMs: Long = 0,
) {
    val notFound: Boolean get() = error?.kind == ApiErrorKind.NOT_FOUND && call == null
    val controls get() = OwnerControls.evaluate(call)
    val blocked: Boolean get() = call?.blocked ?: cached?.blocked ?: false
    val trusted: Boolean get() = call?.trusted ?: cached?.trusted ?: false
}

/** Loads one call and runs the owner's actions on it. Used by the call detail and the incoming-call screens. */
@HiltViewModel
class CallDetailViewModel @Inject constructor(
    private val calls: CallsRepository,
    private val screening: ScreeningRepository,
    private val clock: WallClock,
) : ViewModel() {

    private val _state = MutableStateFlow(CallDetailUiState())
    val state: StateFlow<CallDetailUiState> = _state.asStateFlow()

    /** Idempotent for the same id, so recomposition and rotation never reload. */
    fun load(id: String, force: Boolean = false) {
        if (!force && id == _state.value.callId) return
        _state.value = CallDetailUiState(callId = id, nowMs = clock.nowMs())
        viewModelScope.launch {
            val cached = calls.cached(id)
            _state.update { it.copy(cached = cached) }
            fetch(id)
        }
    }

    fun refresh() = load(_state.value.callId, force = true)

    private suspend fun fetch(id: String) {
        when (val result = calls.detail(id)) {
            is ApiResult.Success -> _state.update {
                it.copy(
                    loading = false,
                    call = result.value,
                    error = null,
                    feedbackSent = it.feedbackSent + result.value.feedback.map { f -> f.kind },
                    nowMs = clock.nowMs(),
                )
            }
            is ApiResult.Failure -> _state.update { it.copy(loading = false, error = result.error, nowMs = clock.nowMs()) }
        }
    }

    fun toggleTranslations() = _state.update { it.copy(showTranslations = !it.showTranslations) }

    fun dismissMessage() = _state.update { it.copy(message = null) }

    fun takeOver() = ownerAction(ControlId.TAKE_OVER) { calls.takeOver(it) }

    fun continueCall() = ownerAction(ControlId.CONTINUE) { calls.continueCall(it) }

    fun endCall() = ownerAction(ControlId.END) { calls.endCall(it) }

    private fun ownerAction(
        control: ControlId,
        run: suspend (String) -> ApiResult<io.github.snowjug.sparta.data.remote.dto.OwnerActionResultDto>,
    ) {
        val id = _state.value.callId
        if (id.isEmpty() || _state.value.busy != null) return
        _state.update { it.copy(busy = control, message = null) }
        viewModelScope.launch {
            when (val result = run(id)) {
                is ApiResult.Success -> {
                    val message = if (result.value.action.simulated) R.string.detail_msg_simulated_action else R.string.detail_msg_action_done
                    _state.update { it.copy(busy = null, message = UiMessage.Text(message)) }
                    fetch(id)
                }
                is ApiResult.Failure -> _state.update { it.copy(busy = null, message = UiMessage.Failure(result.error)) }
            }
        }
    }

    fun block() {
        val id = _state.value.callId
        if (id.isEmpty() || _state.value.busy != null) return
        _state.update { it.copy(busy = ControlId.BLOCK, message = null) }
        viewModelScope.launch {
            when (val result = calls.block(id)) {
                is ApiResult.Success -> {
                    // Pull the new fingerprint into the phone's own list so the next call is already covered.
                    screening.syncConfigAndLists()
                    _state.update { it.copy(busy = null, message = UiMessage.Text(R.string.detail_msg_blocked)) }
                    fetch(id)
                }
                is ApiResult.Failure -> _state.update { it.copy(busy = null, message = UiMessage.Failure(result.error)) }
            }
        }
    }

    fun trust() {
        val id = _state.value.callId
        if (id.isEmpty() || _state.value.busy != null) return
        _state.update { it.copy(busy = ControlId.TRUST, message = null) }
        viewModelScope.launch {
            when (val result = calls.trust(id)) {
                is ApiResult.Success -> {
                    screening.syncConfigAndLists()
                    _state.update { it.copy(busy = null, message = UiMessage.Text(R.string.detail_msg_trusted)) }
                    fetch(id)
                }
                is ApiResult.Failure -> _state.update { it.copy(busy = null, message = UiMessage.Failure(result.error)) }
            }
        }
    }

    fun sendFeedback(kind: FeedbackKind) {
        val id = _state.value.callId
        if (id.isEmpty() || kind in _state.value.feedbackSent) return
        viewModelScope.launch {
            when (val result = calls.feedback(id, kind)) {
                is ApiResult.Success -> _state.update {
                    it.copy(feedbackSent = it.feedbackSent + kind, message = UiMessage.Text(R.string.detail_msg_feedback_saved))
                }
                is ApiResult.Failure -> _state.update { it.copy(message = UiMessage.Failure(result.error)) }
            }
        }
    }

    fun delete(kind: DeleteKind) {
        val id = _state.value.callId
        if (id.isEmpty() || _state.value.deleting != null) return
        _state.update { it.copy(deleting = kind, message = null) }
        viewModelScope.launch {
            val result = when (kind) {
                DeleteKind.CONTENT -> calls.deleteContent(id)
                DeleteKind.CALL -> calls.deleteCall(id)
            }
            when (result) {
                is ApiResult.Success -> when (kind) {
                    DeleteKind.CALL -> _state.update { it.copy(deleting = null, deleted = true) }
                    DeleteKind.CONTENT -> {
                        _state.update { it.copy(deleting = null, message = UiMessage.Text(R.string.detail_msg_content_deleted)) }
                        fetch(id)
                    }
                }
                is ApiResult.Failure -> _state.update { it.copy(deleting = null, message = UiMessage.Failure(result.error)) }
            }
        }
    }
}
