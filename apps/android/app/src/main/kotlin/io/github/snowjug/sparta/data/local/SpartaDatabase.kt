package io.github.snowjug.sparta.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [
        ScreeningEventEntity::class,
        ListEntryEntity::class,
        CachedCallEntity::class,
        NotifiedItemEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class SpartaDatabase : RoomDatabase() {
    abstract fun screeningEvents(): ScreeningEventDao

    abstract fun listEntries(): ListEntryDao

    abstract fun cachedCalls(): CachedCallDao

    abstract fun notifiedItems(): NotifiedItemDao

    companion object {
        const val NAME = "sparta.db"
    }
}
