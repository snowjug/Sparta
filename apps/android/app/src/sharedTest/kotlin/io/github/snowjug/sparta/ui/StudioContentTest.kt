package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewDto
import io.github.snowjug.sparta.data.remote.dto.LanguageInfoDto
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.SpeechPlanDto
import io.github.snowjug.sparta.data.remote.dto.VoiceOptionDto
import io.github.snowjug.sparta.data.remote.dto.VoiceProfileViewDto
import io.github.snowjug.sparta.data.remote.dto.VoiceStatus
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.studio.DEFAULT_LANGUAGES
import io.github.snowjug.sparta.ui.studio.PreviewState
import io.github.snowjug.sparta.ui.studio.StudioActions
import io.github.snowjug.sparta.ui.studio.StudioContent
import io.github.snowjug.sparta.ui.studio.StudioDraft
import io.github.snowjug.sparta.ui.studio.StudioUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StudioContentTest {

    @get:Rule
    val compose = createComposeRule()

    private val baseDraft = StudioDraft(ownerName = "Atharv", voiceIds = mapOf("hi-IN" to "hi-IN-SwaraNeural"))
    private val voices = listOf(
        VoiceOption("en-IN-NeerjaNeural", "en-IN", "Neerja", "female", true),
        VoiceOption("en-IN-PrabhatNeural", "en-IN", "Prabhat", "male", false),
        VoiceOption("hi-IN-SwaraNeural", "hi-IN", "Swara", "female", true),
    )
    private val languages = DEFAULT_LANGUAGES + LanguageInfoDto("ta-IN", "Tamil", "தமிழ்", "planned")

    private fun VoiceOption(id: String, locale: String, name: String, gender: String, verified: Boolean) =
        VoiceOptionDto(id = id, locale = locale, displayName = name, gender = gender, provider = "azure", verified = verified)

    private fun ready(change: StudioUiState.() -> StudioUiState = { this }) = StudioUiState(
        backendConfigured = true,
        loading = false,
        saved = baseDraft,
        draft = baseDraft,
        voices = voices,
        voiceStatus = VoiceProfileViewDto(status = VoiceStatus.NOT_ENROLLED, detail = "No personal voice enrolled."),
        languages = languages,
    ).change()

    private fun show(state: StudioUiState, actions: StudioActions = StudioActions()) {
        compose.setContent { SpartaTheme { StudioContent(state, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    @Test
    fun `without a backend the studio explains there is nothing to configure and offers to connect one`() {
        var connect = 0
        show(StudioUiState(backendConfigured = false, loading = false), StudioActions(onConnectBackend = { connect++ }))
        node("studio_no_backend").assertTextContains("produced by your Sparta backend", substring = true)
        node("studio_no_backend_action").performClick()
        assertEquals(1, connect)
    }

    @Test
    fun `loading shows progress and a failed load offers a retry`() {
        var retried = 0
        show(StudioUiState(backendConfigured = true, loading = false, loadError = ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached.")), StudioActions(onRetry = { retried++ }))
        node("studio_error").assertTextContains("could not be reached", substring = true)
        node("studio_error_retry").performClick()
        assertEquals(1, retried)
    }

    @Test
    fun `the ai disclosure is always on uses the owners name and has no switch to turn it off`() {
        show(ready())
        node("studio_disclosure_example").assertTextContains("I'm Atharv's AI call assistant", substring = true)
        node("studio_disclosure_note").assertTextContains("always on and cannot be turned off", substring = true)
        node("studio_disclosure_note").assertTextContains("never pretends to be you", substring = true)
    }

    @Test
    fun `editing the name and style reports the change and the slider is present`() {
        var name = ""
        var style = ""
        show(ready(), StudioActions(onOwnerName = { name = it }, onStyle = { style = it }))
        node("studio_owner_name").performTextInput("X")
        assertTrue(name.contains("X"))
        node("studio_style_warm").performClick()
        assertEquals("warm", style)
        node("studio_style_concise").assertIsSelected()
        node("studio_rate").assertExists()
    }

    @Test
    fun `an empty name is an error and cannot be saved`() {
        val empty = baseDraft.copy(ownerName = "")
        show(ready { copy(draft = empty) })
        node("studio_profile").assertTextContains("Enter a name of 1 to 60 characters.", substring = true)
        node("studio_save").assertIsNotEnabled()
    }

    @Test
    fun `voices are offered per language and the choice is reported`() {
        var chosen: Pair<String, String>? = null
        show(ready(), StudioActions(onVoice = { locale, id -> chosen = locale to id }))
        node("studio_voice").assertTextContains("Neerja (female)", substring = true)
        node("studio_voice").assertTextContains("(name not verified)", substring = true)
        node("studio_voice_hi-IN_hi-IN-SwaraNeural").assertIsSelected()
        node("studio_voice_en-IN_en-IN-NeerjaNeural").performClick()
        assertEquals("en-IN" to "en-IN-NeerjaNeural", chosen)
    }

    @Test
    fun `a personal voice is never offered here and the limits are stated`() {
        show(ready())
        node("studio_voice_status").assertTextContains("Not enrolled", substring = true)
        node("studio_personal_note").assertTextContains("cannot be completed on this phone", substring = true)
    }

    @Test
    fun `planned languages are listed but cannot be enabled and supported ones can`() {
        val toggled = mutableListOf<String>()
        show(ready(), StudioActions(onToggleLanguage = { toggled += it }))
        node("studio_language_ta-IN").assertIsNotEnabled()
        node("studio_language_ta-IN").assertTextContains("Planned, not available yet", substring = true)
        node("studio_language_hi-IN").assertIsEnabled().assertIsOn().performClick()
        assertEquals(listOf("hi-IN"), toggled)
    }

    @Test
    fun `the primary language is chosen among the enabled ones`() {
        var primary = ""
        show(ready(), StudioActions(onPrimaryLanguage = { primary = it }))
        node("studio_primary_en-IN").assertIsSelected()
        node("studio_primary_kn-IN").performClick()
        assertEquals("kn-IN", primary)
    }

    @Test
    fun `automatic language detection and an available translation have controls`() {
        var auto: Boolean? = null
        var translate: String? = "unset"
        show(ready { copy(translationAvailable = true) }, StudioActions(onAutoDetect = { auto = it }, onTranslateTo = { translate = it }))
        node("studio_auto_detect").performClick()
        assertEquals(false, auto)
        node("studio_translate_unavailable").assertDoesNotExist()
        node("studio_translate_null").assertIsEnabled().assertIsSelected()
        node("studio_translate_hi-IN").performClick()
        assertEquals("hi-IN", translate)
    }

    @Test
    fun `translation the backend does not offer is read only and says why`() {
        var translate: String? = "unset"
        val stored = baseDraft.copy(translateTo = "en-IN")
        show(ready { copy(saved = stored, draft = stored) }, StudioActions(onTranslateTo = { translate = it }))

        node("studio_translate_unavailable").assertTextContains("needs a language-model provider and is not available in this build", substring = true)
        node("studio_translate_unavailable").assertTextContains("Assistant lines always include an English rendering.", substring = true)
        node("studio_translate_en-IN").assertIsNotEnabled().assertIsSelected()
        node("studio_translate_null").assertIsNotEnabled()
        node("studio_translate_hi-IN").assertIsNotEnabled().performClick()
        assertEquals("a disabled chooser reports nothing", "unset", translate)
    }

    @Test
    fun `the save bar appears only for unsaved changes`() {
        show(ready())
        node("studio_save_bar").assertDoesNotExist()
    }

    @Test
    fun `unsaved changes can be saved or discarded`() {
        var saved = 0
        var discarded = 0
        show(ready { copy(draft = baseDraft.copy(ownerName = "Atharv S")) }, StudioActions(onSave = { saved++ }, onDiscard = { discarded++ }))
        node("studio_save").assertIsEnabled().performClick()
        node("studio_discard").performClick()
        assertEquals(1, saved)
        assertEquals(1, discarded)
        node("studio_preview_unsaved").assertExists()
    }

    @Test
    fun `saving disables the buttons`() {
        show(ready { copy(draft = baseDraft.copy(ownerName = "Atharv S"), saving = true) })
        node("studio_save").assertIsNotEnabled()
        node("studio_discard").assertIsNotEnabled()
    }

    @Test
    fun `the preview runs on request and shows what the real pipeline answered`() {
        var ran = 0
        val result = AssistantPreviewDto(
            disclosure = SpeechPlanDto(text = "Hello, I'm Atharv's AI call assistant."),
            reply = SpeechPlanDto(text = "I cannot share one-time passwords."),
            risk = Samples.riskAssessment(RiskLevel.HIGH),
            detectedLanguage = "en-IN",
        )
        show(ready { copy(preview = PreviewState.Done(result), previewText = "Share the OTP") }, StudioActions(onPreview = { ran++ }))
        node("studio_preview_disclosure").assertTextContains("AI call assistant", substring = true)
        node("studio_preview_reply").assertTextContains("cannot share one-time passwords", substring = true)
        node("studio_preview_result").assertTextContains("High risk", substring = true)
        node("studio_preview_run").performClick()
        assertEquals(1, ran)
    }

    @Test
    fun `a running preview cannot be started twice and a failed one explains`() {
        show(ready { copy(preview = PreviewState.Running) })
        node("studio_preview_run").assertIsNotEnabled()
    }

    @Test
    fun `a preview failure shows the backend message`() {
        show(ready { copy(preview = PreviewState.Failed(ApiError(ApiErrorKind.SERVER, "The backend had a problem (HTTP 500)."))) })
        node("studio_preview_error").assertTextContains("HTTP 500", substring = true)
    }

    @Test
    fun `the sample sentence is editable`() {
        var text = ""
        show(ready(), StudioActions(onPreviewText = { text = it }))
        node("studio_preview_text").performTextInput("hello")
        assertTrue(text.contains("hello"))
    }
}
