package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewDto
import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewRequestDto
import io.github.snowjug.sparta.data.remote.dto.VoiceConsentDto
import io.github.snowjug.sparta.data.remote.dto.VoiceOptionDto
import io.github.snowjug.sparta.data.remote.dto.VoiceProfileViewDto
import io.github.snowjug.sparta.data.remote.map
import io.github.snowjug.sparta.data.remote.safeApiCall
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

sealed interface SaveResult {
    /** The backend has the change. */
    data object Synced : SaveResult

    /** The change is effective on this phone and queued for the backend (which could not be reached or refused it for now). */
    data class SavedOnDevice(val error: ApiError) : SaveResult
}

/**
 * Owner preferences: the screening-relevant fields apply on this phone immediately (so the fast path works
 * offline) and are pushed to the backend as a patch merged onto the freshest backend document.
 */
class PreferencesRepository(
    private val api: SpartaApi,
    private val settings: SettingsRepository,
    private val json: Json,
) {
    private val pushLock = Mutex()

    /** The cached backend document with any not-yet-pushed local edits applied; null before the first successful load. */
    val preferences: Flow<UserPreferences?> = settings.settings
        .map { s -> effective(s) }
        .distinctUntilChanged()

    suspend fun refresh(): ApiResult<UserPreferences> {
        if (settings.current().preferencesDirty) return push()
        return when (val result = safeApiCall(json) { api.preferences() }) {
            is ApiResult.Success -> {
                settings.update { s -> mirrorPolicy(s.copy(cachedPreferencesJson = encode(result.value)), UserPreferences(result.value)) }
                ApiResult.Success(UserPreferences(result.value))
            }
            is ApiResult.Failure -> result
        }
    }

    suspend fun save(patch: PreferencesPatch): SaveResult {
        settings.update { s ->
            val merged = PreferencesPatch.fromJson(json, s.pendingPreferencesPatchJson) + patch
            mirrorPatchedPolicy(s, patch).copy(pendingPreferencesPatchJson = merged.toJsonString(json))
        }
        return when (val pushed = push()) {
            is ApiResult.Success -> SaveResult.Synced
            is ApiResult.Failure -> SaveResult.SavedOnDevice(pushed.error)
        }
    }

    /** Pushes pending edits (also called by the periodic sync). No-op when nothing is pending. */
    suspend fun push(): ApiResult<UserPreferences> = pushLock.withLock {
        val pendingJson = settings.current().pendingPreferencesPatchJson
        val patch = PreferencesPatch.fromJson(json, pendingJson)
        if (patch.isEmpty) {
            settings.update { it.copy(pendingPreferencesPatchJson = null) }
            return@withLock refreshCurrent()
        }
        val remote = when (val r = safeApiCall(json) { api.preferences() }) {
            is ApiResult.Success -> r.value
            is ApiResult.Failure -> return@withLock r
        }
        val merged = UserPreferences(remote).apply(patch)
        when (val put = safeApiCall(json) { api.putPreferences(merged.raw) }) {
            is ApiResult.Success -> {
                settings.update { s ->
                    val stillPending = if (s.pendingPreferencesPatchJson == pendingJson) null else s.pendingPreferencesPatchJson
                    mirrorPolicy(s.copy(cachedPreferencesJson = encode(put.value), pendingPreferencesPatchJson = stillPending), UserPreferences(put.value))
                }
                ApiResult.Success(UserPreferences(put.value))
            }
            is ApiResult.Failure -> {
                // A request the backend will never accept must not be retried forever.
                if (put.error.kind == ApiErrorKind.VALIDATION || put.error.kind == ApiErrorKind.PAYLOAD_TOO_LARGE) {
                    settings.update { s -> if (s.pendingPreferencesPatchJson == pendingJson) s.copy(pendingPreferencesPatchJson = null) else s }
                }
                put
            }
        }
    }

    private suspend fun refreshCurrent(): ApiResult<UserPreferences> = when (val result = safeApiCall(json) { api.preferences() }) {
        is ApiResult.Success -> {
            settings.update { s -> mirrorPolicy(s.copy(cachedPreferencesJson = encode(result.value)), UserPreferences(result.value)) }
            ApiResult.Success(UserPreferences(result.value))
        }
        is ApiResult.Failure -> result
    }

    suspend fun loadAssistantProfile(): ApiResult<AssistantProfileDoc> =
        safeApiCall(json) { api.assistantProfile() }.map { AssistantProfileDoc(it) }

    /** Whole-document PUT merged onto the freshest profile so unknown fields survive. Requires the backend. */
    suspend fun saveAssistantProfile(edit: (AssistantProfileDoc) -> AssistantProfileDoc): ApiResult<AssistantProfileDoc> {
        val current = when (val r = safeApiCall(json) { api.assistantProfile() }) {
            is ApiResult.Success -> AssistantProfileDoc(r.value)
            is ApiResult.Failure -> return r
        }
        val updated = edit(current)
        return safeApiCall(json) { api.putAssistantProfile(updated.raw) }.map { AssistantProfileDoc(it) }
    }

    suspend fun voices(): ApiResult<List<VoiceOptionDto>> = safeApiCall(json) { api.voices() }

    suspend fun voiceStatus(): ApiResult<VoiceProfileViewDto> = safeApiCall(json) { api.voiceStatus() }

    suspend fun voiceConsent(): ApiResult<VoiceConsentDto> = safeApiCall(json) { api.voiceConsent() }

    suspend fun previewDisclosure(language: String?, sampleText: String?): ApiResult<AssistantPreviewDto> =
        safeApiCall(json) { api.previewAssistant(AssistantPreviewRequestDto(language, sampleText?.trim()?.ifEmpty { null })) }

    private fun effective(settings: AppSettings): UserPreferences? {
        val cached = decode(settings.cachedPreferencesJson)
        val patch = PreferencesPatch.fromJson(json, settings.pendingPreferencesPatchJson)
        if (cached == null && patch.isEmpty) return null
        return UserPreferences(cached ?: JsonObject(emptyMap())).apply(patch)
    }

    private fun encode(doc: JsonObject): String = json.encodeToString(JsonObject.serializer(), doc)

    private fun decode(text: String?): JsonObject? {
        if (text.isNullOrBlank()) return null
        return try {
            json.decodeFromString(JsonObject.serializer(), text)
        } catch (_: SerializationException) {
            null
        }
    }

    /** Adopts the backend values for the fields the screening fast path reads, unless local edits are pending. */
    private fun mirrorPolicy(settings: AppSettings, prefs: UserPreferences): AppSettings {
        if (settings.preferencesDirty) return settings
        return settings.copy(
            unknownCallerBehavior = prefs.unknownCallerBehavior,
            trustedContactBehavior = prefs.trustedContactBehavior,
            strictness = prefs.strictness,
        )
    }

    private fun mirrorPatchedPolicy(settings: AppSettings, patch: PreferencesPatch): AppSettings {
        val probe = UserPreferences().apply(patch)
        var next = settings
        if ("unknown_caller_behavior" in patch.values) next = next.copy(unknownCallerBehavior = probe.unknownCallerBehavior)
        if ("trusted_contact_behavior" in patch.values) next = next.copy(trustedContactBehavior = probe.trustedContactBehavior)
        if ("strictness" in patch.values) next = next.copy(strictness = probe.strictness)
        return next
    }
}
