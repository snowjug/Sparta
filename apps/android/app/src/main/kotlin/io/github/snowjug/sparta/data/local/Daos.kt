package io.github.snowjug.sparta.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface ScreeningEventDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(event: ScreeningEventEntity): Long

    @Query("SELECT * FROM screening_events ORDER BY occurredAtMs DESC LIMIT :limit")
    fun observeRecent(limit: Int): Flow<List<ScreeningEventEntity>>

    @Query("SELECT * FROM screening_events ORDER BY occurredAtMs DESC LIMIT 1")
    fun observeLatest(): Flow<ScreeningEventEntity?>

    @Query("SELECT * FROM screening_events WHERE clientEventId = :id")
    suspend fun get(id: String): ScreeningEventEntity?

    @Query("SELECT * FROM screening_events WHERE clientEventId = :id")
    fun observe(id: String): Flow<ScreeningEventEntity?>

    @Query("DELETE FROM screening_events WHERE clientEventId = :id")
    suspend fun delete(id: String)

    @Query("SELECT * FROM screening_events WHERE uploadState = 'PENDING' ORDER BY occurredAtMs ASC LIMIT :limit")
    suspend fun pending(limit: Int): List<ScreeningEventEntity>

    @Query(
        "UPDATE screening_events SET uploadState = 'UPLOADED', backendCallId = :callId, lastUploadError = NULL, " +
            "uploadAttempts = uploadAttempts + 1 WHERE clientEventId = :id",
    )
    suspend fun markUploaded(id: String, callId: String?)

    @Query("UPDATE screening_events SET uploadAttempts = uploadAttempts + 1, lastUploadError = :error WHERE clientEventId = :id")
    suspend fun recordFailedAttempt(id: String, error: String?)

    @Query("UPDATE screening_events SET uploadState = :state, lastUploadError = :error WHERE clientEventId = :id")
    suspend fun setUploadState(id: String, state: String, error: String?)

    @Query("SELECT COUNT(*) FROM screening_events WHERE uploadState = 'PENDING'")
    fun observePendingCount(): Flow<Int>

    @Query("DELETE FROM screening_events")
    suspend fun deleteAll()

    @Query("DELETE FROM screening_events WHERE occurredAtMs < :cutoffMs")
    suspend fun deleteOlderThan(cutoffMs: Long): Int
}

@Dao
abstract class ListEntryDao {
    @Query("SELECT EXISTS(SELECT 1 FROM list_entries WHERE kind = 'blocked' AND fingerprint = :fingerprint)")
    abstract suspend fun isBlocked(fingerprint: String): Boolean

    @Query("SELECT EXISTS(SELECT 1 FROM list_entries WHERE kind = 'trusted' AND fingerprint = :fingerprint)")
    abstract suspend fun isTrusted(fingerprint: String): Boolean

    @Query("SELECT * FROM list_entries WHERE kind = :kind ORDER BY createdAtMs DESC")
    abstract fun observe(kind: String): Flow<List<ListEntryEntity>>

    @Query("SELECT * FROM list_entries WHERE kind = :kind AND fingerprint = :fingerprint")
    abstract suspend fun get(kind: String, fingerprint: String): ListEntryEntity?

    @Upsert
    abstract suspend fun upsert(entry: ListEntryEntity)

    @Upsert
    abstract suspend fun upsertAll(entries: List<ListEntryEntity>)

    @Query("DELETE FROM list_entries WHERE kind = :kind AND fingerprint = :fingerprint")
    abstract suspend fun delete(kind: String, fingerprint: String)

    @Query("DELETE FROM list_entries WHERE kind = :kind AND source = 'backend'")
    abstract suspend fun deleteBackendEntries(kind: String)

    @Query("DELETE FROM list_entries")
    abstract suspend fun deleteAll()

    /**
     * Swaps the backend-sourced entries of one list atomically so a call arriving mid-sync can never observe a
     * half-empty block list. Device-only entries survive the swap.
     */
    @Transaction
    open suspend fun replaceBackendEntries(kind: String, entries: List<ListEntryEntity>) {
        deleteBackendEntries(kind)
        upsertAll(entries)
    }
}

@Dao
interface CachedCallDao {
    @Upsert
    suspend fun upsertAll(calls: List<CachedCallEntity>)

    @Query("SELECT * FROM cached_calls WHERE id = :id")
    suspend fun get(id: String): CachedCallEntity?

    @Query(
        "SELECT * FROM cached_calls WHERE " +
            "(:risk IS NULL OR riskLevel = :risk) AND " +
            "(:category IS NULL OR category = :category) AND " +
            "(:languageTag IS NULL OR languagesCsv LIKE '%' || :languageTag || '%') AND " +
            "(:query IS NULL OR searchText LIKE '%' || :query || '%') AND " +
            "(:attentionOnly = 0 OR ownerAttention = 1) " +
            "ORDER BY startedAtMs DESC LIMIT :limit",
    )
    fun observeFiltered(
        risk: String?,
        category: String?,
        languageTag: String?,
        query: String?,
        attentionOnly: Boolean,
        limit: Int,
    ): Flow<List<CachedCallEntity>>

    @Query("SELECT COUNT(*) FROM cached_calls WHERE ownerAttention = 1")
    fun observeAttentionCount(): Flow<Int>

    @Query("DELETE FROM cached_calls WHERE startedAtMs >= :sinceMs AND id NOT IN (:keepIds)")
    suspend fun deleteMissingSince(sinceMs: Long, keepIds: List<String>): Int

    @Query("DELETE FROM cached_calls WHERE id = :id")
    suspend fun delete(id: String)

    @Query("DELETE FROM cached_calls")
    suspend fun deleteAll()

    @Query("DELETE FROM cached_calls WHERE cachedAtMs < :cutoffMs")
    suspend fun deleteOlderThan(cutoffMs: Long): Int
}

@Dao
interface NotifiedItemDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(item: NotifiedItemEntity): Long

    @Query("SELECT EXISTS(SELECT 1 FROM notified_items WHERE `key` = :key)")
    suspend fun contains(key: String): Boolean

    @Query("DELETE FROM notified_items WHERE atMs < :cutoffMs")
    suspend fun deleteOlderThan(cutoffMs: Long): Int

    @Query("DELETE FROM notified_items")
    suspend fun deleteAll()
}
