package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto

/** One row of the "Recent calls" list: an analysed backend call or an on-device screening decision. */
sealed interface RecentItem {
    val key: String
    val timeMs: Long

    data class Backend(val call: CallListItemDto, override val timeMs: Long) : RecentItem {
        override val key: String get() = "call:${call.id}"
    }

    data class Local(val event: ScreeningEventEntity) : RecentItem {
        override val key: String get() = "event:${event.clientEventId}"
        override val timeMs: Long get() = event.occurredAtMs
    }
}

object RecentCalls {
    /**
     * Backend calls plus local screening events, newest first.
     * A local event is hidden once the backend copy it was uploaded as is part of [calls] (no duplicates), but kept
     * while offline or not yet uploaded. Risk/category/language/attention filters describe analysed calls only, so
     * local events (which carry no analysis) appear only when none of those filters is active.
     */
    fun merge(calls: List<CallListItemDto>, events: List<ScreeningEventEntity>, filter: CallFilter): List<RecentItem> {
        val backendIds = calls.mapTo(HashSet()) { it.id }
        val query = filter.normalizedQuery
        val local = if (filter.hasClassificationFilters) {
            emptyList()
        } else {
            events
                .filter { it.backendCallId == null || it.backendCallId !in backendIds }
                .filter { query == null || searchText(it).contains(query) }
                .map { RecentItem.Local(it) }
        }
        val backend = calls.map { RecentItem.Backend(it, Timestamps.parseMs(it.startedAt) ?: 0L) }
        return (backend + local).sortedByDescending { it.timeMs }
    }

    private fun searchText(event: ScreeningEventEntity): String =
        "${event.numberDisplay} ${event.decision} ${event.reason.replace('_', ' ')}".lowercase()
}
