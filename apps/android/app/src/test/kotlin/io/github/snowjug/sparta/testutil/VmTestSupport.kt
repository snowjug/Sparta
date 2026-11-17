package io.github.snowjug.sparta.testutil

import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.SpartaDatabase
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.PreferencesRepository
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.data.repo.SystemRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import org.junit.rules.TestWatcher
import org.junit.runner.Description

/**
 * ViewModels launch on Dispatchers.Main. Unconfined keeps them running eagerly and lets `delay` use real time, which is
 * what we want next to a real HTTP client talking to a MockWebServer.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherRule : TestWatcher() {
    override fun starting(description: Description) = Dispatchers.setMain(Dispatchers.Unconfined)

    override fun finished(description: Description) = Dispatchers.resetMain()
}

/** Real repositories over a real Room database (in memory) and the real Retrofit client pointed at a MockWebServer. */
class VmHarness(configured: Boolean = true, initial: (AppSettings) -> AppSettings = { it }) : AutoCloseable {
    val db: SpartaDatabase = inMemoryDatabase()
    private var backendSaved: () -> Boolean = { configured }
    val api = ApiHarness(reachable = { backendSaved() })
    val settings = FakeSettingsRepository(initial(AppSettings(backendUrl = if (configured) api.baseUrl.toString() else ""))).also { saved ->
        // Like production, requests only leave the app while an address is saved (and they follow later changes).
        backendSaved = { saved.value.backendConfigured }
    }
    val clock = WallClock { 1_794_912_000_000L }
    private var counter = 0
    val ids = IdGenerator { "id-${++counter}" }
    val calls = CallsRepository(api.api, db.cachedCalls(), SpartaJson, clock, ids)
    val screening = ScreeningRepository(db.screeningEvents(), db.listEntries(), api.api, settings, clock, SpartaJson)
    val preferences = PreferencesRepository(api.api, settings, SpartaJson)
    val system = SystemRepository(api.api, settings, SpartaJson, clock)

    override fun close() {
        api.close()
        db.close()
    }
}

/** Waits (really) for a flow to reach a state; fails the test after [timeoutMs]. */
fun <T> Flow<T>.await(timeoutMs: Long = 10_000, predicate: (T) -> Boolean): T = runBlocking { withTimeout(timeoutMs) { first(predicate) } }
