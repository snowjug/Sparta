package io.github.snowjug.sparta.testutil

import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

class FakeSettingsRepository(initial: AppSettings = AppSettings()) : SettingsRepository {
    private val state = MutableStateFlow(initial)
    override val settings: Flow<AppSettings> = state

    val value: AppSettings get() = state.value

    override suspend fun update(transform: (AppSettings) -> AppSettings) {
        state.update(transform)
    }

    override suspend fun incrementDeadlineMisses() {
        state.update { it.copy(deadlineMissCount = it.deadlineMissCount + 1) }
    }

    override suspend fun clearAll() {
        state.value = AppSettings()
    }
}
