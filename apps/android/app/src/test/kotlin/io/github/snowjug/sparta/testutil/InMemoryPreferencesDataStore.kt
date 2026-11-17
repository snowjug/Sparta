package io.github.snowjug.sparta.testutil

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Platform independent stand-in for the file backed DataStore. (The real one replaces its file by renaming a temp
 * file over it, which fails on Windows hosts when it is exercised from JVM unit tests; on Android it is fine.)
 */
class InMemoryPreferencesDataStore : DataStore<Preferences> {
    private val state = MutableStateFlow(emptyPreferences())
    private val lock = Mutex()

    override val data: Flow<Preferences> = state

    override suspend fun updateData(transform: suspend (t: Preferences) -> Preferences): Preferences = lock.withLock {
        val next = transform(state.value)
        state.value = next
        next
    }
}
