package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.CachedCallDao
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.dto.BlockRequestDto
import io.github.snowjug.sparta.data.remote.dto.BlockedCallerDto
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.FeedbackRecordDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackRequestDto
import io.github.snowjug.sparta.data.remote.dto.OwnerActionResultDto
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.TrustRequestDto
import io.github.snowjug.sparta.data.remote.dto.TrustedCallerDto
import io.github.snowjug.sparta.data.remote.map
import io.github.snowjug.sparta.data.remote.safeApiCall
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

data class CallFilter(
    val query: String = "",
    val risk: RiskLevel? = null,
    val category: CallCategory? = null,
    /** BCP-47 tag such as "hi-IN". */
    val language: String? = null,
    val attentionOnly: Boolean = false,
) {
    val normalizedQuery: String? get() = query.trim().lowercase().ifEmpty { null }

    /** Risk, category, language and attention only describe analysed backend calls (not on-device screening events). */
    val hasClassificationFilters: Boolean get() = risk != null || category != null || language != null || attentionOnly

    val isUnfiltered: Boolean get() = normalizedQuery == null && !hasClassificationFilters
}

data class CallPage(val items: List<CallListItemDto>, val nextCursor: String?)

class CallsRepository(
    private val api: SpartaApi,
    private val cache: CachedCallDao,
    private val json: Json,
    private val clock: WallClock,
    private val ids: IdGenerator,
) {
    /** Offline-first: always served from the local cache (which `refresh` keeps current). */
    fun observe(filter: CallFilter, limit: Int = 200): Flow<List<CallListItemDto>> =
        cache.observeFiltered(
            risk = filter.risk?.wire,
            category = filter.category?.wire,
            languageTag = filter.language?.let { ",$it," },
            query = filter.normalizedQuery,
            attentionOnly = filter.attentionOnly,
            limit = limit,
        ).map { rows -> rows.mapNotNull { CallCache.fromEntity(it, json) } }

    suspend fun refresh(filter: CallFilter, cursor: String? = null): ApiResult<CallPage> {
        val result = safeApiCall(json) {
            api.calls(
                query = filter.normalizedQuery,
                riskLevel = filter.risk?.wire,
                category = filter.category?.wire,
                language = filter.language,
                attention = if (filter.attentionOnly) true else null,
                limit = PAGE_SIZE,
                cursor = cursor,
            )
        }
        if (result is ApiResult.Success) {
            val now = clock.nowMs()
            val page = result.value
            cache.upsertAll(page.items.map { CallCache.toEntity(it, json, now) })
            if (cursor == null && filter.isUnfiltered) pruneMissing(page.items, page.nextCursor)
        }
        return result.map { CallPage(it.items, it.nextCursor) }
    }

    suspend fun cached(id: String): CallListItemDto? = cache.get(id)?.let { CallCache.fromEntity(it, json) }

    suspend fun detail(id: String): ApiResult<CallDetailDto> {
        val result = safeApiCall(json) { api.call(id) }
        if (result is ApiResult.Success) remember(result.value.toListItem())
        return result
    }

    suspend fun takeOver(id: String): ApiResult<OwnerActionResultDto> = ownerAction { api.takeover(id, ids.newId()) }

    suspend fun continueCall(id: String): ApiResult<OwnerActionResultDto> = ownerAction { api.continueCall(id, ids.newId()) }

    suspend fun endCall(id: String): ApiResult<OwnerActionResultDto> = ownerAction { api.endCall(id, ids.newId()) }

    suspend fun block(id: String, reason: String? = null): ApiResult<BlockedCallerDto> =
        safeApiCall(json) { api.blockCaller(id, ids.newId(), BlockRequestDto(reason)) }.also { markFlag(id, it) { c -> c.copy(blocked = true, trusted = false) } }

    suspend fun trust(id: String, label: String? = null): ApiResult<TrustedCallerDto> =
        safeApiCall(json) { api.trustCaller(id, ids.newId(), TrustRequestDto(label)) }.also { markFlag(id, it) { c -> c.copy(trusted = true, blocked = false) } }

    suspend fun feedback(id: String, kind: FeedbackKind, note: String? = null): ApiResult<FeedbackRecordDto> =
        safeApiCall(json) { api.feedback(id, FeedbackRequestDto(kind, note?.trim()?.ifEmpty { null })) }

    suspend fun deleteContent(id: String): ApiResult<Unit> =
        safeApiCall(json) { api.deleteCallContent(id) }.also { if (it is ApiResult.Success) cache.delete(id) }

    suspend fun deleteCall(id: String): ApiResult<Unit> =
        safeApiCall(json) { api.deleteCall(id) }.also { if (it is ApiResult.Success) cache.delete(id) }

    suspend fun deleteAll(): ApiResult<Unit> =
        safeApiCall(json) { api.deleteAllCalls() }.also { if (it is ApiResult.Success) cache.deleteAll() }

    suspend fun clearCache() = cache.deleteAll()

    private suspend fun ownerAction(block: suspend () -> OwnerActionResultDto): ApiResult<OwnerActionResultDto> {
        val result = safeApiCall(json) { block() }
        if (result is ApiResult.Success) remember(result.value.call)
        return result
    }

    private suspend fun remember(item: CallListItemDto) {
        cache.upsertAll(listOf(CallCache.toEntity(item, json, clock.nowMs())))
    }

    private suspend fun <T> markFlag(id: String, result: ApiResult<T>, change: (CallListItemDto) -> CallListItemDto) {
        if (result !is ApiResult.Success) return
        cached(id)?.let { remember(change(it)) }
    }

    /** After an unfiltered first page, cached calls inside the fetched time window that the backend no longer lists were deleted there. */
    private suspend fun pruneMissing(items: List<CallListItemDto>, nextCursor: String?) {
        val since = if (nextCursor == null) {
            0L
        } else {
            items.mapNotNull { Timestamps.parseMs(it.startedAt) }.minOrNull() ?: return
        }
        cache.deleteMissingSince(since, items.map { it.id })
    }

    companion object {
        const val PAGE_SIZE = 50
    }
}
