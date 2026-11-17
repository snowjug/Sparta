package io.github.snowjug.sparta.ui.studio

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewDto
import io.github.snowjug.sparta.data.remote.dto.LanguageInfoDto
import io.github.snowjug.sparta.data.remote.dto.VoiceOptionDto
import io.github.snowjug.sparta.data.remote.dto.VoiceProfileViewDto
import io.github.snowjug.sparta.data.repo.AssistantProfileDoc
import io.github.snowjug.sparta.data.repo.PreferencesPatch
import io.github.snowjug.sparta.data.repo.PreferencesRepository
import io.github.snowjug.sparta.data.repo.SaveResult
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.data.repo.UserPreferences
import io.github.snowjug.sparta.ui.common.UiMessage
import javax.inject.Inject
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The editable values of the studio. Whatever is not edited here is carried through untouched by the raw documents. */
data class StudioDraft(
    val ownerName: String = "",
    val responseStyle: String = "concise",
    val speakingRate: Double = 1.0,
    val voiceIds: Map<String, String> = emptyMap(),
    val primaryLanguage: String = "en-IN",
    val enabledLanguages: List<String> = listOf("en-IN", "hi-IN", "kn-IN"),
    val autoDetectLanguage: Boolean = true,
    val translateTo: String? = null,
) {
    val nameValid: Boolean get() = ownerName.trim().length in 1..MAX_NAME
    val languagesValid: Boolean get() = enabledLanguages.isNotEmpty() && primaryLanguage in enabledLanguages
    val valid: Boolean get() = nameValid && languagesValid && speakingRate in RATE_MIN..RATE_MAX

    companion object {
        const val MAX_NAME = 60
        const val RATE_MIN = 0.7
        const val RATE_MAX = 1.3
    }
}

sealed interface PreviewState {
    data object Idle : PreviewState

    data object Running : PreviewState

    data class Done(val result: AssistantPreviewDto) : PreviewState

    data class Failed(val error: ApiError) : PreviewState
}

data class StudioUiState(
    val backendConfigured: Boolean = false,
    val loading: Boolean = true,
    val loadError: ApiError? = null,
    val saved: StudioDraft? = null,
    val draft: StudioDraft? = null,
    val voices: List<VoiceOptionDto> = emptyList(),
    val voiceStatus: VoiceProfileViewDto? = null,
    val languages: List<LanguageInfoDto> = emptyList(),
    val saving: Boolean = false,
    val message: UiMessage? = null,
    val preview: PreviewState = PreviewState.Idle,
    val previewText: String = "",
) {
    val dirty: Boolean get() = draft != null && draft != saved
}

/** Fallback when the backend's language list has not been fetched yet (the three launch languages are always known). */
val DEFAULT_LANGUAGES: List<LanguageInfoDto> = listOf(
    LanguageInfoDto("en-IN", "English (India)", "English", "supported"),
    LanguageInfoDto("hi-IN", "Hindi", "हिन्दी", "supported"),
    LanguageInfoDto("kn-IN", "Kannada", "ಕನ್ನಡ", "supported"),
)

@HiltViewModel
class StudioViewModel @Inject constructor(
    private val preferences: PreferencesRepository,
    private val system: SystemRepository,
    private val settings: SettingsRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(StudioUiState())
    val state: StateFlow<StudioUiState> = _state.asStateFlow()

    private var profileDoc: AssistantProfileDoc? = null

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            if (!settings.current().backendConfigured) {
                _state.update { it.copy(backendConfigured = false, loading = false) }
                return@launch
            }
            _state.update { it.copy(backendConfigured = true, loading = true, loadError = null) }
            coroutineScope {
                val profile = async { preferences.loadAssistantProfile() }
                val prefs = async { preferences.refresh() }
                val voices = async { preferences.voices() }
                val voiceStatus = async { preferences.voiceStatus() }
                val status = async { system.refreshStatus() }

                val profileResult = profile.await()
                val prefsResult = prefs.await()
                val statusResult = status.await()
                val languages = (statusResult as? ApiResult.Success)?.value?.languages?.takeIf { it.isNotEmpty() }
                    ?: system.cachedStatus.first()?.status?.languages?.takeIf { it.isNotEmpty() }
                    ?: DEFAULT_LANGUAGES

                val failure = (profileResult as? ApiResult.Failure)?.error
                val doc = (profileResult as? ApiResult.Success)?.value
                profileDoc = doc
                val userPrefs = (prefsResult as? ApiResult.Success)?.value ?: preferences.preferences.first()
                val draft = if (doc != null) draftOf(doc, userPrefs ?: UserPreferences()) else null
                _state.update {
                    it.copy(
                        loading = false,
                        loadError = failure,
                        saved = draft,
                        draft = draft,
                        voices = (voices.await() as? ApiResult.Success)?.value.orEmpty(),
                        voiceStatus = (voiceStatus.await() as? ApiResult.Success)?.value,
                        languages = languages,
                    )
                }
            }
        }
    }

    private fun draftOf(doc: AssistantProfileDoc, prefs: UserPreferences) = StudioDraft(
        ownerName = doc.ownerDisplayName,
        responseStyle = doc.responseStyle,
        speakingRate = doc.speakingRate,
        voiceIds = doc.voiceIds,
        primaryLanguage = prefs.primaryLanguage,
        enabledLanguages = prefs.enabledLanguages,
        autoDetectLanguage = prefs.autoDetectLanguage,
        translateTo = prefs.translateTranscriptsTo,
    )

    private fun edit(change: (StudioDraft) -> StudioDraft) = _state.update { s ->
        val draft = s.draft ?: return@update s
        s.copy(draft = change(draft), message = null)
    }

    fun setOwnerName(value: String) = edit { it.copy(ownerName = value.take(StudioDraft.MAX_NAME)) }

    fun setResponseStyle(value: String) = edit { it.copy(responseStyle = value) }

    fun setSpeakingRate(value: Double) = edit { it.copy(speakingRate = value.coerceIn(StudioDraft.RATE_MIN, StudioDraft.RATE_MAX)) }

    /** An empty [voiceId] returns that language to the catalogue default. */
    fun setVoice(locale: String, voiceId: String) = edit { d ->
        d.copy(voiceIds = if (voiceId.isEmpty()) d.voiceIds - locale else d.voiceIds + (locale to voiceId))
    }

    fun setPrimaryLanguage(tag: String) = edit { d ->
        d.copy(primaryLanguage = tag, enabledLanguages = if (tag in d.enabledLanguages) d.enabledLanguages else d.enabledLanguages + tag)
    }

    /** The primary language cannot be switched off, and at least one language always stays enabled. */
    fun toggleLanguage(tag: String) = edit { d ->
        when {
            tag in d.enabledLanguages && (tag == d.primaryLanguage || d.enabledLanguages.size == 1) -> d
            tag in d.enabledLanguages -> d.copy(
                enabledLanguages = d.enabledLanguages - tag,
                translateTo = d.translateTo?.takeIf { it != tag },
            )
            else -> d.copy(enabledLanguages = d.enabledLanguages + tag)
        }
    }

    fun setAutoDetect(value: Boolean) = edit { it.copy(autoDetectLanguage = value) }

    fun setTranslateTo(tag: String?) = edit { it.copy(translateTo = tag) }

    fun setPreviewText(value: String) = _state.update { it.copy(previewText = value.take(MAX_PREVIEW)) }

    fun dismissMessage() = _state.update { it.copy(message = null) }

    fun discard() = _state.update { it.copy(draft = it.saved, message = null) }

    fun save() {
        val current = _state.value
        val draft = current.draft ?: return
        if (!draft.valid || current.saving || !current.dirty) return
        _state.update { it.copy(saving = true, message = null) }
        viewModelScope.launch {
            val profileResult = preferences.saveAssistantProfile { doc ->
                doc.withOwnerDisplayName(draft.ownerName.trim())
                    .withResponseStyle(draft.responseStyle)
                    .withSpeakingRate(draft.speakingRate)
                    .withVoices(draft.voiceIds)
            }
            if (profileResult is ApiResult.Failure) {
                _state.update { it.copy(saving = false, message = UiMessage.Failure(profileResult.error)) }
                return@launch
            }
            profileDoc = (profileResult as ApiResult.Success).value
            val patch = PreferencesPatch()
                .primaryLanguage(draft.primaryLanguage)
                .enabledLanguages(draft.enabledLanguages)
                .autoDetectLanguage(draft.autoDetectLanguage)
                .translateTranscriptsTo(draft.translateTo)
            val message = when (val saved = preferences.save(patch)) {
                SaveResult.Synced -> UiMessage.Text(R.string.studio_saved)
                is SaveResult.SavedOnDevice -> UiMessage.Text(R.string.common_saved_on_phone, listOf(saved.error.message))
            }
            _state.update { it.copy(saving = false, saved = draft, message = message) }
        }
    }

    fun runPreview() {
        val current = _state.value
        val draft = current.draft ?: return
        if (current.preview == PreviewState.Running) return
        _state.update { it.copy(preview = PreviewState.Running) }
        viewModelScope.launch {
            val language = if (draft.autoDetectLanguage) "auto" else draft.primaryLanguage
            val result = when (val r = preferences.previewDisclosure(language, current.previewText)) {
                is ApiResult.Success -> PreviewState.Done(r.value)
                is ApiResult.Failure -> PreviewState.Failed(r.error)
            }
            _state.update { it.copy(preview = result) }
        }
    }

    private companion object {
        const val MAX_PREVIEW = 400
    }
}
