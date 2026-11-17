package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.ListEntryDao
import io.github.snowjug.sparta.data.local.ListEntryEntity
import io.github.snowjug.sparta.data.local.ListKind
import io.github.snowjug.sparta.data.local.ListSource
import io.github.snowjug.sparta.data.local.ScreeningEventDao
import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.dto.ScreeningListEntryDto
import io.github.snowjug.sparta.data.remote.safeApiCall
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

/** A blocked or trusted caller as shown in settings. Only a masked display is ever kept, never the raw number. */
data class ListEntry(
    val kind: String,
    val fingerprint: String,
    val backendId: String?,
    val display: String,
    val label: String?,
    val createdAtMs: Long,
) {
    /** Entries created on this phone are not known to the backend (a number cannot be sent by default). */
    val deviceOnly: Boolean get() = backendId == null
}

class ScreeningRepository(
    private val events: ScreeningEventDao,
    private val lists: ListEntryDao,
    private val api: SpartaApi,
    private val settings: SettingsRepository,
    private val clock: WallClock,
    private val json: Json,
) {
    fun observeEvents(limit: Int = 100): Flow<List<ScreeningEventEntity>> = events.observeRecent(limit)

    fun observeLatestEvent(): Flow<ScreeningEventEntity?> = events.observeLatest()

    fun observeEvent(id: String): Flow<ScreeningEventEntity?> = events.observe(id)

    suspend fun deleteEvent(id: String) = events.delete(id)

    fun observePendingUploads(): Flow<Int> = events.observePendingCount()

    fun observeBlocked(): Flow<List<ListEntry>> = lists.observe(ListKind.BLOCKED).map { rows -> rows.map { it.toDomain() } }

    fun observeTrusted(): Flow<List<ListEntry>> = lists.observe(ListKind.TRUSTED).map { rows -> rows.map { it.toDomain() } }

    suspend fun pendingEventIds(limit: Int = 50): List<String> = events.pending(limit).map { it.clientEventId }

    /**
     * Pulls `GET /screening/config` (fingerprint key, forwarding number, policy) and `GET /screening/lists` into
     * local storage so the fast path keeps working offline. The backend policy is adopted only when the owner has
     * no unsent local edits.
     */
    suspend fun syncConfigAndLists(): ApiResult<Unit> {
        val config = when (val result = safeApiCall(json) { api.screeningConfig() }) {
            is ApiResult.Success -> result.value
            is ApiResult.Failure -> {
                settings.update { it.copy(lastSyncError = result.error.kind.name) }
                return result
            }
        }
        settings.update { s ->
            val adopt = !s.preferencesDirty
            s.copy(
                fingerprintSalt = config.fingerprintSalt.ifBlank { null } ?: s.fingerprintSalt,
                forwardingNumber = config.forwardingNumber?.ifBlank { null },
                unknownCallerBehavior = if (adopt) UnknownCallerBehavior.fromWire(config.unknownCallerBehavior) else s.unknownCallerBehavior,
                trustedContactBehavior = if (adopt) TrustedContactBehavior.fromWire(config.trustedContactBehavior) else s.trustedContactBehavior,
                strictness = if (adopt) Strictness.fromWire(config.strictness) else s.strictness,
            )
        }

        val listsResult = safeApiCall(json) { api.screeningLists() }
        return when (listsResult) {
            is ApiResult.Success -> {
                val now = clock.nowMs()
                lists.replaceBackendEntries(ListKind.BLOCKED, listsResult.value.blocked.map { it.toEntity(ListKind.BLOCKED, now) })
                lists.replaceBackendEntries(ListKind.TRUSTED, listsResult.value.trusted.map { it.toEntity(ListKind.TRUSTED, now) })
                settings.update { it.copy(lastSyncAtMs = now, lastSyncError = null) }
                ApiResult.Success(Unit)
            }
            is ApiResult.Failure -> {
                settings.update { it.copy(lastSyncError = listsResult.error.kind.name) }
                listsResult
            }
        }
    }

    /** Adds a device-only entry (works offline; effective for the very next call). Blocked and trusted are mutually exclusive here. */
    suspend fun addDeviceEntry(kind: String, fingerprint: String, display: String, label: String? = null) {
        val other = if (kind == ListKind.BLOCKED) ListKind.TRUSTED else ListKind.BLOCKED
        lists.get(other, fingerprint)?.takeIf { it.source == ListSource.DEVICE }?.let { lists.delete(other, fingerprint) }
        lists.upsert(
            ListEntryEntity(
                kind = kind,
                fingerprint = fingerprint,
                backendId = null,
                numberDisplay = display,
                label = label?.trim()?.ifEmpty { null },
                source = ListSource.DEVICE,
                createdAtMs = clock.nowMs(),
            ),
        )
    }

    /** Backend entries need the backend to confirm removal (otherwise the next sync would bring them back). */
    suspend fun removeEntry(entry: ListEntry): ApiResult<Unit> {
        val backendId = entry.backendId
        if (backendId == null) {
            lists.delete(entry.kind, entry.fingerprint)
            return ApiResult.Success(Unit)
        }
        val result = safeApiCall(json) {
            if (entry.kind == ListKind.BLOCKED) api.removeBlockedCaller(backendId) else api.removeTrustedCaller(backendId)
        }
        if (result is ApiResult.Success) lists.delete(entry.kind, entry.fingerprint)
        return result
    }

    /** Local-only history and lists (used by "delete all call content"). */
    suspend fun clearLocalHistory() {
        events.deleteAll()
    }

    suspend fun clearLocalLists() {
        lists.deleteAll()
    }

    suspend fun pruneEventsOlderThan(cutoffMs: Long): Int = events.deleteOlderThan(cutoffMs)

    private fun ListEntryEntity.toDomain() = ListEntry(kind, fingerprint, backendId, numberDisplay, label, createdAtMs)

    private fun ScreeningListEntryDto.toEntity(kind: String, nowMs: Long) = ListEntryEntity(
        kind = kind,
        fingerprint = fingerprint,
        backendId = id.ifBlank { null },
        numberDisplay = numberDisplay,
        label = label,
        source = ListSource.BACKEND,
        createdAtMs = nowMs,
    )
}
