package io.github.snowjug.sparta.data.remote

import io.github.snowjug.sparta.data.remote.dto.ErrorEnvelopeDto
import io.github.snowjug.sparta.data.remote.dto.FieldErrorDto
import java.io.IOException
import java.io.InterruptedIOException
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy
import retrofit2.HttpException

/** Single tolerant JSON configuration shared by the API client, the WebSocket client and the Room cache. */
@OptIn(ExperimentalSerializationApi::class)
val SpartaJson: Json = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    explicitNulls = false
    encodeDefaults = true
    namingStrategy = JsonNamingStrategy.SnakeCase
}

enum class ApiErrorKind {
    NOT_CONFIGURED,
    OFFLINE,
    TIMEOUT,
    UNAUTHORIZED,
    FORBIDDEN,
    NOT_FOUND,
    VALIDATION,
    CONFLICT,
    UNSUPPORTED_BY_PROVIDER,
    RATE_LIMITED,
    PAYLOAD_TOO_LARGE,
    PROVIDER_UNAVAILABLE,
    SERVER,
    MALFORMED,
    UNKNOWN,
}

/** A failed backend interaction in a form the UI can explain honestly. Never carries numbers or transcripts. */
data class ApiError(
    val kind: ApiErrorKind,
    val message: String,
    val httpStatus: Int? = null,
    val code: String? = null,
    val traceId: String? = null,
    val details: List<FieldErrorDto> = emptyList(),
    val retryAfterSeconds: Long? = null,
) {
    /** Worth retrying later without changing the request. */
    val isTransient: Boolean
        get() = kind == ApiErrorKind.OFFLINE ||
            kind == ApiErrorKind.TIMEOUT ||
            kind == ApiErrorKind.RATE_LIMITED ||
            kind == ApiErrorKind.SERVER ||
            kind == ApiErrorKind.PROVIDER_UNAVAILABLE
}

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>

    data class Failure(val error: ApiError) : ApiResult<Nothing>
}

inline fun <T, R> ApiResult<T>.map(transform: (T) -> R): ApiResult<R> = when (this) {
    is ApiResult.Success -> ApiResult.Success(transform(value))
    is ApiResult.Failure -> this
}

fun <T> ApiResult<T>.getOrNull(): T? = (this as? ApiResult.Success)?.value

fun <T> ApiResult<T>.errorOrNull(): ApiError? = (this as? ApiResult.Failure)?.error

/** Thrown by the base-URL interceptor when no backend has been configured yet. */
class BackendNotConfiguredException : IOException("No backend URL configured")

/** Runs a Retrofit call and converts every expected failure into an [ApiError]; cancellation is rethrown. */
suspend fun <T> safeApiCall(json: Json = SpartaJson, block: suspend () -> T): ApiResult<T> =
    try {
        ApiResult.Success(block())
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (http: HttpException) {
        ApiResult.Failure(ApiErrors.fromHttp(json, http))
    } catch (_: BackendNotConfiguredException) {
        ApiResult.Failure(ApiError(ApiErrorKind.NOT_CONFIGURED, "No backend is configured yet."))
    } catch (_: InterruptedIOException) {
        ApiResult.Failure(ApiError(ApiErrorKind.TIMEOUT, "The backend did not answer in time."))
    } catch (_: IOException) {
        ApiResult.Failure(ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached."))
    } catch (_: SerializationException) {
        ApiResult.Failure(ApiError(ApiErrorKind.MALFORMED, "The backend sent a response this app could not read."))
    }

object ApiErrors {
    /** Maps an HTTP failure using the documented error envelope; falls back to status-based wording. */
    fun fromHttp(json: Json, http: HttpException): ApiError {
        val response = http.response()
        val body = try {
            response?.errorBody()?.string()
        } catch (_: IOException) {
            null
        }
        return fromResponse(
            json = json,
            status = http.code(),
            bodyText = body,
            requestId = response?.headers()?.get("X-Request-ID"),
            retryAfter = response?.headers()?.get("Retry-After"),
        )
    }

    fun fromResponse(json: Json, status: Int, bodyText: String?, requestId: String?, retryAfter: String?): ApiError {
        val envelope = bodyText?.takeIf { it.isNotBlank() }?.let {
            try {
                json.decodeFromString(ErrorEnvelopeDto.serializer(), it).error
            } catch (_: SerializationException) {
                null
            }
        }
        val code = envelope?.code?.takeIf { it.isNotBlank() }
        val kind = kindFor(status, code)
        return ApiError(
            kind = kind,
            message = envelope?.message?.takeIf { it.isNotBlank() } ?: defaultMessage(kind, status),
            httpStatus = status,
            code = code,
            traceId = envelope?.traceId?.takeIf { it.isNotBlank() } ?: requestId,
            details = envelope?.details.orEmpty(),
            retryAfterSeconds = retryAfter?.trim()?.toLongOrNull(),
        )
    }

    fun kindFor(status: Int, code: String?): ApiErrorKind = when {
        code == "unsupported_by_provider" -> ApiErrorKind.UNSUPPORTED_BY_PROVIDER
        code == "provider_unavailable" -> ApiErrorKind.PROVIDER_UNAVAILABLE
        status == 401 -> ApiErrorKind.UNAUTHORIZED
        status == 403 -> ApiErrorKind.FORBIDDEN
        status == 404 -> ApiErrorKind.NOT_FOUND
        status == 409 -> ApiErrorKind.CONFLICT
        status == 413 -> ApiErrorKind.PAYLOAD_TOO_LARGE
        status == 415 || status == 422 || status == 400 -> ApiErrorKind.VALIDATION
        status == 429 -> ApiErrorKind.RATE_LIMITED
        status == 503 -> ApiErrorKind.PROVIDER_UNAVAILABLE
        status in 500..599 -> ApiErrorKind.SERVER
        else -> ApiErrorKind.UNKNOWN
    }

    private fun defaultMessage(kind: ApiErrorKind, status: Int): String = when (kind) {
        ApiErrorKind.UNAUTHORIZED -> "The backend requires sign-in. Sign-in is not available in this app yet."
        ApiErrorKind.FORBIDDEN -> "The backend refused this request."
        ApiErrorKind.NOT_FOUND -> "The backend does not have that item."
        ApiErrorKind.VALIDATION -> "The backend rejected the request."
        ApiErrorKind.CONFLICT -> "The backend cannot do that right now."
        ApiErrorKind.UNSUPPORTED_BY_PROVIDER -> "The active telephony provider does not support this action."
        ApiErrorKind.RATE_LIMITED -> "Too many requests. Try again shortly."
        ApiErrorKind.PAYLOAD_TOO_LARGE -> "The request was too large."
        ApiErrorKind.PROVIDER_UNAVAILABLE -> "A backend provider is temporarily unavailable."
        ApiErrorKind.SERVER -> "The backend had a problem (HTTP $status)."
        else -> "Unexpected backend response (HTTP $status)."
    }
}
