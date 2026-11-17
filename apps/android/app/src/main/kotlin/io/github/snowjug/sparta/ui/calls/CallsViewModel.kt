package io.github.snowjug.sparta.ui.calls

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.repo.CallFilter
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.RecentCalls
import io.github.snowjug.sparta.data.repo.RecentItem
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import javax.inject.Inject
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CallsUiState(
    val filter: CallFilter = CallFilter(),
    val items: List<RecentItem> = emptyList(),
    val nowMs: Long = 0,
    val backendConfigured: Boolean = false,
    /** True until the first refresh attempt for the current filter has finished (or there is nothing to refresh). */
    val initialLoading: Boolean = true,
    val refreshing: Boolean = false,
    val loadingMore: Boolean = false,
    val hasMore: Boolean = false,
    val error: ApiError? = null,
    /** Two-pane layouts keep the open call here so rotation and process death do not lose the selection. */
    val selectedCallId: String? = null,
) {
    val isEmpty: Boolean get() = items.isEmpty()
    val filtersActive: Boolean get() = !filter.isUnfiltered
}

private data class NetState(
    val loadedOnce: Boolean = false,
    val refreshing: Boolean = false,
    val loadingMore: Boolean = false,
    val nextCursor: String? = null,
    val error: ApiError? = null,
)

/**
 * Recent calls = analysed backend calls (offline-first from the Room cache) merged with the decisions this phone
 * made natively. Typing in the search box waits a moment before it asks the backend, so it never fires a request per
 * keystroke.
 */
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class CallsViewModel @Inject constructor(
    private val calls: CallsRepository,
    private val screening: ScreeningRepository,
    private val settings: SettingsRepository,
    private val clock: WallClock,
) : ViewModel() {

    private val filter = MutableStateFlow(CallFilter())
    private val net = MutableStateFlow(NetState())
    private val selected = MutableStateFlow<String?>(null)

    private val items: Flow<List<RecentItem>> = filter.flatMapLatest { f ->
        combine(calls.observe(f), screening.observeEvents(EVENT_LIMIT)) { backend, local -> RecentCalls.merge(backend, local, f) }
    }

    val state: StateFlow<CallsUiState> = combine(filter, items, net, settings.settings, selected) { f, list, n, s, sel ->
        CallsUiState(
            filter = f,
            items = list,
            nowMs = clock.nowMs(),
            backendConfigured = s.backendConfigured,
            initialLoading = s.backendConfigured && !n.loadedOnce,
            refreshing = n.refreshing,
            loadingMore = n.loadingMore,
            hasMore = n.nextCursor != null,
            error = n.error,
            selectedCallId = sel,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), CallsUiState())

    init {
        viewModelScope.launch {
            filter.collectLatest { f ->
                delay(SEARCH_DEBOUNCE_MS)
                load(f, cursor = null)
            }
        }
    }

    fun setQuery(query: String) = filter.update { it.copy(query = query) }

    fun setRisk(risk: RiskLevel?) = filter.update { it.copy(risk = risk) }

    fun setCategory(category: CallCategory?) = filter.update { it.copy(category = category) }

    fun setLanguage(tag: String?) = filter.update { it.copy(language = tag) }

    fun setAttentionOnly(only: Boolean) = filter.update { it.copy(attentionOnly = only) }

    fun clearFilters() = filter.update { CallFilter() }

    fun select(callId: String?) {
        selected.value = callId
    }

    fun refresh() {
        viewModelScope.launch { load(filter.value, cursor = null) }
    }

    fun loadMore() {
        val cursor = net.value.nextCursor ?: return
        if (net.value.loadingMore) return
        viewModelScope.launch { load(filter.value, cursor) }
    }

    private suspend fun load(f: CallFilter, cursor: String?) {
        if (!settings.current().backendConfigured) {
            net.update { NetState(loadedOnce = true) }
            return
        }
        net.update {
            it.copy(
                refreshing = cursor == null,
                loadingMore = cursor != null,
                nextCursor = if (cursor == null) null else it.nextCursor,
                error = null,
            )
        }
        when (val result = calls.refresh(f, cursor)) {
            is ApiResult.Success -> net.update {
                it.copy(loadedOnce = true, refreshing = false, loadingMore = false, nextCursor = result.value.nextCursor, error = null)
            }
            is ApiResult.Failure -> net.update {
                it.copy(loadedOnce = true, refreshing = false, loadingMore = false, error = result.error)
            }
        }
    }

    companion object {
        const val SEARCH_DEBOUNCE_MS = 250L
        const val EVENT_LIMIT = 200
    }
}
