package io.github.snowjug.sparta.ui.detail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ListKind
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.ListEntry
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.ui.common.UiMessage
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

data class ScreeningEventUiState(
    val eventId: String = "",
    val loading: Boolean = true,
    val event: ScreeningEventEntity? = null,
    val blockedEntry: ListEntry? = null,
    val trustedEntry: ListEntry? = null,
    val busy: Boolean = false,
    val message: UiMessage? = null,
    val deleted: Boolean = false,
    val nowMs: Long = 0,
) {
    /** Lists are keyed by the keyed fingerprint; without the backend's key there is nothing safe to key a number by. */
    val canUseLists: Boolean get() = event?.numberFingerprint != null
    val notFound: Boolean get() = !loading && event == null
}

private data class Local(val busy: Boolean = false, val message: UiMessage? = null, val deleted: Boolean = false)

/** One decision made natively on this phone, with block / trust / delete. Only masked numbers and fingerprints are involved. */
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class ScreeningEventViewModel @Inject constructor(
    private val screening: ScreeningRepository,
    private val calls: CallsRepository,
    private val clock: WallClock,
) : ViewModel() {

    private val id = MutableStateFlow<String?>(null)
    private val local = MutableStateFlow(Local())

    val state: StateFlow<ScreeningEventUiState> = id.filterNotNull().flatMapLatest { eventId ->
        combine(
            screening.observeEvent(eventId),
            screening.observeBlocked(),
            screening.observeTrusted(),
            local,
        ) { event, blocked, trusted, l ->
            val fingerprint = event?.numberFingerprint
            ScreeningEventUiState(
                eventId = eventId,
                loading = false,
                event = event,
                blockedEntry = fingerprint?.let { fp -> blocked.firstOrNull { it.fingerprint == fp } },
                trustedEntry = fingerprint?.let { fp -> trusted.firstOrNull { it.fingerprint == fp } },
                busy = l.busy,
                message = l.message,
                deleted = l.deleted,
                nowMs = clock.nowMs(),
            )
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ScreeningEventUiState())

    fun load(eventId: String) {
        if (id.value != eventId) {
            local.value = Local()
            id.value = eventId
        }
    }

    fun dismissMessage() = local.update { it.copy(message = null) }

    fun block() = addToList(ListKind.BLOCKED, R.string.event_msg_blocked) { calls.block(it) }

    fun trust() = addToList(ListKind.TRUSTED, R.string.event_msg_trusted) { calls.trust(it) }

    /** Adds the number on this phone at once (it is effective for the very next call) and tells the backend when it knows the call. */
    private fun <T> addToList(kind: String, doneMessage: Int, tellBackend: suspend (String) -> ApiResult<T>) {
        val current = state.value
        val event = current.event ?: return
        val fingerprint = event.numberFingerprint
        if (fingerprint == null || local.value.busy) return
        local.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            screening.addDeviceEntry(kind, fingerprint, event.numberDisplay)
            val backendCallId = event.backendCallId
            val message = if (backendCallId == null) {
                UiMessage.Text(doneMessage)
            } else {
                when (val result = tellBackend(backendCallId)) {
                    is ApiResult.Success -> UiMessage.Text(R.string.event_msg_backend_noted)
                    is ApiResult.Failure -> UiMessage.Text(R.string.event_msg_backend_failed, listOf(result.error.message))
                }
            }
            local.update { it.copy(busy = false, message = message) }
        }
    }

    fun unblock() = remove(state.value.blockedEntry, R.string.event_msg_unblocked)

    fun untrust() = remove(state.value.trustedEntry, R.string.event_msg_untrusted)

    private fun remove(entry: ListEntry?, doneMessage: Int) {
        if (entry == null || local.value.busy) return
        local.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            val message = when (val result = screening.removeEntry(entry)) {
                is ApiResult.Success -> UiMessage.Text(doneMessage)
                is ApiResult.Failure -> UiMessage.Failure(result.error)
            }
            local.update { it.copy(busy = false, message = message) }
        }
    }

    fun delete() {
        val eventId = id.value ?: return
        viewModelScope.launch {
            screening.deleteEvent(eventId)
            local.update { it.copy(deleted = true) }
        }
    }
}
