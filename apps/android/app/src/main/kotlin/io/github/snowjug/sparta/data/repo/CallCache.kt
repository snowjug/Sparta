package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.local.CachedCallEntity
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** Maps backend list items to the offline cache and back. */
object CallCache {
    fun toEntity(item: CallListItemDto, json: Json, nowMs: Long): CachedCallEntity = CachedCallEntity(
        id = item.id,
        startedAtMs = Timestamps.parseMs(item.startedAt) ?: nowMs,
        payload = json.encodeToString(CallListItemDto.serializer(), item),
        riskLevel = item.riskLevel.wire,
        category = item.category.wire,
        languagesCsv = item.languages.joinToString(separator = ",", prefix = ",", postfix = ","),
        searchText = searchText(item),
        ownerAttention = item.ownerAttentionRequired,
        cachedAtMs = nowMs,
    )

    /** Null when the stored payload no longer matches the DTO (schema drift); callers drop such rows. */
    fun fromEntity(entity: CachedCallEntity, json: Json): CallListItemDto? = try {
        json.decodeFromString(CallListItemDto.serializer(), entity.payload)
    } catch (_: SerializationException) {
        null
    }

    fun searchText(item: CallListItemDto): String = listOfNotNull(
        item.callerDisplay,
        item.callerClaim.name,
        item.callerClaim.organization,
        item.purpose,
        item.summaryText,
        item.category.wire.replace('_', ' '),
        item.languageProfile,
        item.languages.joinToString(" "),
    ).joinToString(" ").lowercase()
}
