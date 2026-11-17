package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.net.BackendUrlPolicy
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.net.BackendUrlResult
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.AbsoluteUrl
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiErrors
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.dto.HomeSummaryDto
import io.github.snowjug.sparta.data.remote.dto.SafetyPolicyDto
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.remote.safeApiCall
import java.io.IOException
import java.io.InterruptedIOException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request

sealed interface ConnectionTestResult {
    data class Reachable(val status: SystemStatusDto, val roundTripMs: Long, val url: String) : ConnectionTestResult

    data class Unreachable(val error: ApiError, val url: String) : ConnectionTestResult

    data class InvalidUrl(val problem: BackendUrlProblem) : ConnectionTestResult
}

/** Probes a candidate backend URL (before it is saved) with a read-only `GET /api/v1/system/status`. */
class ConnectionTester(
    private val client: OkHttpClient,
    private val json: Json,
    private val policy: BackendUrlPolicy,
    private val clock: MonotonicClock,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    suspend fun test(input: String): ConnectionTestResult = withContext(io) {
        val valid = when (val result = policy.validate(input)) {
            is BackendUrlResult.Valid -> result
            is BackendUrlResult.Invalid -> return@withContext ConnectionTestResult.InvalidUrl(result.problem)
        }
        val url = valid.url.toHttpUrlOrNull()?.newBuilder()?.addPathSegments("api/v1/system/status")?.build()
            ?: return@withContext ConnectionTestResult.InvalidUrl(BackendUrlProblem.MALFORMED)
        val request = Request.Builder().url(url).get().tag(AbsoluteUrl::class.java, AbsoluteUrl).build()

        val started = clock.nowMs()
        try {
            client.newCall(request).execute().use { response ->
                val body = response.body.string()
                val elapsed = clock.nowMs() - started
                if (!response.isSuccessful) {
                    val error = ApiErrors.fromResponse(json, response.code, body, response.header("X-Request-ID"), response.header("Retry-After"))
                    return@withContext ConnectionTestResult.Unreachable(error, valid.url)
                }
                val status = try {
                    json.decodeFromString(SystemStatusDto.serializer(), body.orEmpty())
                } catch (_: SerializationException) {
                    null
                }
                if (status == null || (status.version.isBlank() && status.env.isBlank())) {
                    return@withContext ConnectionTestResult.Unreachable(
                        ApiError(ApiErrorKind.MALFORMED, "That address answered, but it does not look like a Sparta backend."),
                        valid.url,
                    )
                }
                ConnectionTestResult.Reachable(status, elapsed, valid.url)
            }
        } catch (_: InterruptedIOException) {
            ConnectionTestResult.Unreachable(ApiError(ApiErrorKind.TIMEOUT, "The backend did not answer in time."), valid.url)
        } catch (_: IOException) {
            ConnectionTestResult.Unreachable(ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached."), valid.url)
        }
    }
}

/** Backend identity and capability state, cached so the status screen is honest even while offline. */
class SystemRepository(
    private val api: SpartaApi,
    private val settings: SettingsRepository,
    private val json: Json,
    private val clock: WallClock,
) {
    /** Last known `GET /system/status`; the cache time lets the UI say how old it is. */
    val cachedStatus: Flow<CachedStatus?> = settings.settings
        .map { s ->
            val text = s.cachedStatusJson ?: return@map null
            val status = try {
                json.decodeFromString(SystemStatusDto.serializer(), text)
            } catch (_: SerializationException) {
                return@map null
            }
            CachedStatus(status, s.cachedStatusAtMs)
        }
        .distinctUntilChanged()

    suspend fun refreshStatus(): ApiResult<SystemStatusDto> {
        val result = safeApiCall(json) { api.systemStatus() }
        if (result is ApiResult.Success) {
            val encoded = json.encodeToString(SystemStatusDto.serializer(), result.value)
            settings.update { it.copy(cachedStatusJson = encoded, cachedStatusAtMs = clock.nowMs()) }
        }
        return result
    }

    suspend fun home(): ApiResult<HomeSummaryDto> = safeApiCall(json) { api.home() }

    suspend fun safetyPolicy(): ApiResult<SafetyPolicyDto> = safeApiCall(json) { api.safetyPolicy() }
}

data class CachedStatus(val status: SystemStatusDto, val fetchedAtMs: Long?)
