package io.github.snowjug.sparta.ui.studio

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.ui.common.UiMessage
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StudioViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private var h: VmHarness? = null
    private val requests = CopyOnWriteArrayList<RecordedRequest>()

    @After
    fun tearDown() {
        h?.close()
    }

    private val profile = """{"owner_display_name":"Atharv","response_style":"warm","speaking_rate":1.1,"voice_ids":{"hi-IN":"hi-IN-SwaraNeural"},"use_personal_voice":false,"future_profile_field":7}"""
    private val prefs = """{"onboarding_completed":true,"primary_language":"en-IN","enabled_languages":["en-IN","hi-IN"],"auto_detect_language":true,"translate_transcripts_to":"en-IN","future_pref":"x"}"""
    private val voices = """[{"id":"hi-IN-SwaraNeural","locale":"hi-IN","display_name":"Swara","gender":"female","provider":"azure","verified":true}]"""
    private val voiceStatus = """{"status":"not_enrolled","detail":"No personal voice enrolled."}"""

    /** Answers by path so the parallel loads of the studio do not depend on arrival order. */
    private fun create(
        configured: Boolean = true,
        profileResponse: () -> MockResponse = { json(profile) },
        putProfile: () -> MockResponse = { json(profile) },
    ): StudioViewModel {
        val harness = VmHarness(configured).also { h = it }
        harness.api.server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests += request
                return when (request.method to request.path) {
                    "GET" to "/api/v1/assistant-profile" -> profileResponse()
                    "PUT" to "/api/v1/assistant-profile" -> putProfile()
                    "GET" to "/api/v1/preferences" -> json(prefs)
                    "PUT" to "/api/v1/preferences" -> json(prefs)
                    "GET" to "/api/v1/voices" -> json(voices)
                    "GET" to "/api/v1/voice/status" -> json(voiceStatus)
                    "GET" to "/api/v1/system/status" -> json(Fixtures.text("system_status.json"))
                    "POST" to "/api/v1/assistant-profile/preview" ->
                        json("""{"disclosure":{"text":"Hello, I'm Atharv's AI call assistant.","locale":"en-IN"},"reply":{"text":"I cannot share that.","locale":"en-IN"},"detected_language":"en-IN"}""")
                    else -> MockResponse().setResponseCode(404)
                }
            }
        }
        return StudioViewModel(harness.preferences, harness.system, harness.settings)
    }

    private fun json(body: String) = MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(body)

    private fun StudioViewModel.loaded() = state.await { !it.loading && it.draft != null }

    @Test
    fun `without a backend the studio has nothing to load`() {
        val vm = create(configured = false)
        val state = vm.state.await { !it.loading }
        assertFalse(state.backendConfigured)
        assertNull(state.draft)
        assertTrue(requests.isEmpty())
    }

    @Test
    fun `loading builds the draft from the profile and the preferences`() {
        val vm = create()
        val state = vm.loaded()

        val draft = state.draft!!
        assertEquals("Atharv", draft.ownerName)
        assertEquals("warm", draft.responseStyle)
        assertEquals(1.1, draft.speakingRate, 0.0)
        assertEquals(mapOf("hi-IN" to "hi-IN-SwaraNeural"), draft.voiceIds)
        assertEquals(listOf("en-IN", "hi-IN"), draft.enabledLanguages)
        assertEquals("en-IN", draft.translateTo)
        assertEquals(draft, state.saved)
        assertFalse(state.dirty)
        assertEquals(1, state.voices.size)
        assertEquals("not_enrolled", state.voiceStatus?.status?.wire)
        assertTrue("languages come from the backend status", state.languages.any { it.code == "ta-IN" && it.status == "planned" })
    }

    @Test
    fun `a failed profile load is reported with the reason`() {
        val vm = create(profileResponse = { MockResponse().setResponseCode(500).setBody("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t"}}""") })
        val state = vm.state.await { !it.loading }
        assertEquals(ApiErrorKind.SERVER, state.loadError?.kind)
        assertNull(state.draft)
    }

    @Test
    fun `editing marks the draft dirty and discarding restores it`() {
        val vm = create()
        vm.loaded()
        vm.setOwnerName("Atharv S")
        assertTrue(vm.state.value.dirty)
        vm.discard()
        assertFalse(vm.state.value.dirty)
    }

    @Test
    fun `the primary language cannot be switched off and one language always stays enabled`() {
        val vm = create()
        vm.loaded()
        vm.toggleLanguage("en-IN") // primary
        assertEquals(listOf("en-IN", "hi-IN"), vm.state.value.draft!!.enabledLanguages)
        vm.toggleLanguage("hi-IN")
        assertEquals(listOf("en-IN"), vm.state.value.draft!!.enabledLanguages)
        vm.toggleLanguage("en-IN") // the last one
        assertEquals(listOf("en-IN"), vm.state.value.draft!!.enabledLanguages)
    }

    @Test
    fun `switching off the translation target language clears the target`() {
        val vm = create()
        vm.loaded()
        vm.setTranslateTo("hi-IN")
        vm.toggleLanguage("hi-IN")
        assertNull(vm.state.value.draft!!.translateTo)
    }

    @Test
    fun `choosing another primary language enables it`() {
        val vm = create()
        vm.loaded()
        vm.setPrimaryLanguage("kn-IN")
        val draft = vm.state.value.draft!!
        assertEquals("kn-IN", draft.primaryLanguage)
        assertTrue("kn-IN" in draft.enabledLanguages)
        assertTrue(draft.languagesValid)
    }

    @Test
    fun `the name is limited the speed is clamped and an empty default voice removes the choice`() {
        val vm = create()
        vm.loaded()
        vm.setOwnerName("x".repeat(100))
        assertEquals(StudioDraft.MAX_NAME, vm.state.value.draft!!.ownerName.length)
        vm.setSpeakingRate(5.0)
        assertEquals(StudioDraft.RATE_MAX, vm.state.value.draft!!.speakingRate, 0.0)
        vm.setSpeakingRate(0.0)
        assertEquals(StudioDraft.RATE_MIN, vm.state.value.draft!!.speakingRate, 0.0)
        vm.setVoice("hi-IN", "")
        assertTrue(vm.state.value.draft!!.voiceIds.isEmpty())
    }

    @Test
    fun `saving writes the profile then the language preferences and keeps fields it does not know`() {
        val vm = create()
        vm.loaded()
        vm.setOwnerName("Atharv S")
        vm.setVoice("en-IN", "en-IN-NeerjaNeural")
        vm.setAutoDetect(false)

        vm.save()
        val state = vm.state.await { !it.saving && it.message != null }

        val profilePut = requests.first { it.method == "PUT" && it.path == "/api/v1/assistant-profile" }
        val profileBody = SpartaJson.parseToJsonElement(profilePut.body.readUtf8()).jsonObject
        assertEquals("Atharv S", profileBody.getValue("owner_display_name").jsonPrimitive.content)
        assertEquals("en-IN-NeerjaNeural", (profileBody.getValue("voice_ids") as JsonObject).getValue("en-IN").jsonPrimitive.content)
        assertTrue("future_profile_field" in profileBody)
        assertEquals("the AI disclosure is not part of the profile and cannot be switched off", false, profileBody.getValue("use_personal_voice").jsonPrimitive.content.toBoolean())

        val prefsPut = requests.first { it.method == "PUT" && it.path == "/api/v1/preferences" }
        val prefsBody = SpartaJson.parseToJsonElement(prefsPut.body.readUtf8()).jsonObject
        assertEquals("false", prefsBody.getValue("auto_detect_language").jsonPrimitive.content)
        assertTrue("future_pref" in prefsBody)
        assertEquals(R.string.studio_saved, (state.message as UiMessage.Text).res)
        assertFalse(state.dirty)
    }

    @Test
    fun `when the profile cannot be saved the edits are kept and the reason is shown`() {
        val vm = create(putProfile = { MockResponse().setResponseCode(409).setBody("""{"error":{"code":"conflict","message":"Personal voice is not ready.","trace_id":"t"}}""") })
        vm.loaded()
        vm.setOwnerName("Atharv S")
        vm.save()
        val state = vm.state.await { !it.saving && it.message != null }
        assertTrue(state.message is UiMessage.Failure)
        assertTrue("nothing was lost", state.dirty)
        assertTrue(requests.none { it.method == "PUT" && it.path == "/api/v1/preferences" })
    }

    @Test
    fun `an invalid draft cannot be saved`() {
        val vm = create()
        vm.loaded()
        vm.setOwnerName("")
        vm.save()
        assertTrue(requests.none { it.method == "PUT" })
    }

    @Test
    fun `the preview runs the real pipeline with auto language and the sample text`() {
        val vm = create()
        vm.loaded()
        vm.setPreviewText("Please share the OTP")
        vm.runPreview()
        val state = vm.state.await { it.preview is PreviewState.Done }

        val request = requests.first { it.path == "/api/v1/assistant-profile/preview" }
        val body = SpartaJson.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals("auto", body.getValue("language").jsonPrimitive.content)
        assertEquals("Please share the OTP", body.getValue("sample_text").jsonPrimitive.content)
        assertEquals("I cannot share that.", (state.preview as PreviewState.Done).result.reply?.text)
    }
}
