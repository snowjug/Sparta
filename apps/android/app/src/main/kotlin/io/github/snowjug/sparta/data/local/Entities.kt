package io.github.snowjug.sparta.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/** Upload lifecycle of a locally recorded screening event. */
object UploadState {
    const val PENDING = "PENDING"
    const val UPLOADED = "UPLOADED"

    /** Never uploaded by design: the number could not be fingerprinted (no salt yet, or a private number). */
    const val LOCAL_ONLY = "LOCAL_ONLY"

    /** The backend permanently refused the event (validation error). */
    const val FAILED = "FAILED"
}

/**
 * One native screening decision. Holds a masked display and a keyed fingerprint, never the raw number, and no
 * call content (the platform gives a screening app none).
 */
@Entity(
    tableName = "screening_events",
    indices = [Index("occurredAtMs"), Index("uploadState")],
)
data class ScreeningEventEntity(
    @PrimaryKey val clientEventId: String,
    val numberFingerprint: String?,
    val numberDisplay: String,
    val decision: String,
    val reason: String,
    val verificationStatus: String?,
    val direction: String?,
    val occurredAtMs: Long,
    val decisionLatencyMs: Long,
    val deadlineMissed: Boolean,
    val uploadState: String,
    val uploadAttempts: Int = 0,
    val lastUploadError: String? = null,
    val backendCallId: String? = null,
)

object ListKind {
    const val BLOCKED = "blocked"
    const val TRUSTED = "trusted"
}

object ListSource {
    const val BACKEND = "backend"
    const val DEVICE = "device"
}

/** Local blocked/trusted fingerprints: the offline cache the screening fast path reads. */
@Entity(
    tableName = "list_entries",
    primaryKeys = ["kind", "fingerprint"],
    indices = [Index("kind")],
)
data class ListEntryEntity(
    val kind: String,
    val fingerprint: String,
    val backendId: String?,
    val numberDisplay: String,
    val label: String?,
    val source: String,
    val createdAtMs: Long,
)

/** Cached backend call list item; [payload] is the serialized CallListItemDto, other columns serve offline filters. */
@Entity(tableName = "cached_calls", indices = [Index("startedAtMs")])
data class CachedCallEntity(
    @PrimaryKey val id: String,
    val startedAtMs: Long,
    val payload: String,
    val riskLevel: String,
    val category: String,
    /** ",en-IN,hi-IN," so a LIKE on ",hi-IN," never matches a prefix of another tag. */
    val languagesCsv: String,
    val searchText: String,
    val ownerAttention: Boolean,
    val cachedAtMs: Long,
)

/** Remembers which escalations already produced a notification so periodic sync never repeats itself. */
@Entity(tableName = "notified_items")
data class NotifiedItemEntity(
    @PrimaryKey val key: String,
    val atMs: Long,
)
