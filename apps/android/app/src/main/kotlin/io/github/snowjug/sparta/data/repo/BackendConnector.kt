package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiResult

/**
 * Connects the app to a backend the owner typed: probe first (read-only), then save the address and pull the
 * screening key, lists and policy. Used by onboarding and by settings.
 */
class BackendConnector(
    private val tester: ConnectionTester,
    private val settings: SettingsRepository,
    private val screening: ScreeningRepository,
    private val system: SystemRepository,
) {
    suspend fun test(input: String): ConnectionTestResult = tester.test(input)

    /** [validatedUrl] must come from a successful [test]. Returns the result of the first screening sync. */
    suspend fun connect(validatedUrl: String): ApiResult<Unit> {
        settings.update { it.copy(backendUrl = validatedUrl, cachedStatusJson = null, cachedStatusAtMs = null, lastSyncError = null) }
        system.refreshStatus()
        return screening.syncConfigAndLists()
    }

    /** Forgets the backend address and its cached status. Local lists and history stay on the phone. */
    suspend fun disconnect() {
        settings.update { it.copy(backendUrl = "", cachedStatusJson = null, cachedStatusAtMs = null, lastSyncError = null) }
    }
}
