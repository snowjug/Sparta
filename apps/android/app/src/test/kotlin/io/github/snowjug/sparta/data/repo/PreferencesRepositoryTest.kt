package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.FakeSettingsRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class PreferencesRepositoryTest {

    private lateinit var harness: ApiHarness
    private lateinit var settings: FakeSettingsRepository
    private lateinit var repo: PreferencesRepository

    private val remoteDocument =
        """{"onboarding_completed":true,"primary_language":"en-IN","enabled_languages":["en-IN","hi-IN"],"strictness":"balanced","trusted_contact_behavior":"allow_directly","unknown_caller_behavior":"screen","retention":{"store_transcripts":true,"transcript_retention_days":7,"summary_retention_days":90,"store_raw_audio":false,"store_full_caller_number":false},"notifications":{"notify_on_escalation":true,"notify_on_high_risk":false,"include_transcript_lines":true,"quiet_hours_start":null,"quiet_hours_end":null},"future_quiet_mode":{"x":1}}"""

    @Before
    fun setUp() {
        harness = ApiHarness()
        settings = FakeSettingsRepository()
        repo = PreferencesRepository(harness.api, settings, SpartaJson)
    }

    @After
    fun tearDown() = harness.close()

    @Test
    fun `refresh caches the document and mirrors the screening policy for offline use`() = runBlocking {
        harness.enqueueJson(remoteDocument.replace("\"balanced\"", "\"strict\"").replace("\"screen\"", "\"silence\""))
        val result = repo.refresh()

        assertTrue(result is ApiResult.Success)
        assertEquals(Strictness.STRICT, settings.value.strictness)
        assertEquals(UnknownCallerBehavior.SILENCE, settings.value.unknownCallerBehavior)
        assertNotNull(settings.value.cachedPreferencesJson)
        assertEquals(Strictness.STRICT, repo.preferences.first()?.strictness)
    }

    @Test
    fun `save applies the policy on the phone at once and pushes a merged document`() = runBlocking {
        harness.enqueueJson(remoteDocument) // GET inside push
        harness.enqueueJson(remoteDocument.replace("\"balanced\"", "\"strict\"")) // PUT response

        val result = repo.save(PreferencesPatch().strictness(Strictness.STRICT))

        assertEquals(SaveResult.Synced, result)
        assertEquals(Strictness.STRICT, settings.value.strictness)
        assertNull("nothing is pending after a successful push", settings.value.pendingPreferencesPatchJson)
        harness.takeRequest()
        val put = harness.takeRequest()
        assertEquals("PUT", put.method)
        assertEquals("/api/v1/preferences", put.path)
        val body = SpartaJson.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("strict", body.getValue("strictness").jsonPrimitive.content)
        assertTrue("fields this app does not know must survive the round trip", body.containsKey("future_quiet_mode"))
        assertEquals("true", body.getValue("onboarding_completed").jsonPrimitive.content)
    }

    @Test
    fun `nested edits change only their own key`() = runBlocking {
        harness.enqueueJson(remoteDocument)
        harness.enqueueJson(remoteDocument)
        repo.save(PreferencesPatch().transcriptRetentionDays(30).notifyOnHighRisk(true))
        harness.takeRequest()
        val body = SpartaJson.parseToJsonElement(harness.takeRequest().body.readUtf8()).jsonObject
        val retention = body.getValue("retention").jsonObject
        assertEquals("30", retention.getValue("transcript_retention_days").jsonPrimitive.content)
        assertEquals("90", retention.getValue("summary_retention_days").jsonPrimitive.content)
        assertEquals("true", body.getValue("notifications").jsonObject.getValue("notify_on_high_risk").jsonPrimitive.content)
        assertEquals("true", body.getValue("notifications").jsonObject.getValue("notify_on_escalation").jsonPrimitive.content)
    }

    @Test
    fun `offline edits are kept on the phone and pushed later`() = runBlocking {
        harness.server.shutdown()
        val result = repo.save(PreferencesPatch().unknownCallerBehavior(UnknownCallerBehavior.SILENCE).trustedContactBehavior(TrustedContactBehavior.SCREEN_ANYWAY))

        assertEquals(ApiErrorKind.OFFLINE, (result as SaveResult.SavedOnDevice).error.kind)
        assertEquals(UnknownCallerBehavior.SILENCE, settings.value.unknownCallerBehavior)
        assertEquals(TrustedContactBehavior.SCREEN_ANYWAY, settings.value.trustedContactBehavior)
        assertTrue(settings.value.preferencesDirty)
        assertEquals(UnknownCallerBehavior.SILENCE, repo.preferences.first()?.unknownCallerBehavior)

        val later = ApiHarness()
        val laterRepo = PreferencesRepository(later.api, settings, SpartaJson)
        later.enqueueJson(remoteDocument)
        later.enqueueJson(remoteDocument.replace("\"screen\"", "\"silence\""))
        assertTrue(laterRepo.push() is ApiResult.Success)
        assertFalse(settings.value.preferencesDirty)
        later.takeRequest()
        val body = SpartaJson.parseToJsonElement(later.takeRequest().body.readUtf8()).jsonObject
        assertEquals("silence", body.getValue("unknown_caller_behavior").jsonPrimitive.content)
        assertEquals("screen_anyway", body.getValue("trusted_contact_behavior").jsonPrimitive.content)
        later.close()
    }

    @Test
    fun `refresh does not overwrite pending local edits with older backend values`() = runBlocking {
        harness.server.shutdown()
        repo.save(PreferencesPatch().strictness(Strictness.RELAXED))
        val unreachable = repo.refresh()
        assertTrue(unreachable is ApiResult.Failure)
        assertEquals(Strictness.RELAXED, settings.value.strictness)
        assertEquals(Strictness.RELAXED, repo.preferences.first()?.strictness)
    }

    @Test
    fun `a validation error drops a patch the backend will never accept`() = runBlocking {
        harness.enqueueJson(remoteDocument)
        harness.enqueueJson("""{"error":{"code":"validation_error","message":"bad value","trace_id":"t"}}""", 422)
        val result = repo.save(PreferencesPatch().transcriptRetentionDays(9999))
        assertEquals(ApiErrorKind.VALIDATION, (result as SaveResult.SavedOnDevice).error.kind)
        assertNull(settings.value.pendingPreferencesPatchJson)
    }

    @Test
    fun `later edits to the same key win and unrelated pending edits stay`() {
        val patch = PreferencesPatch().strictness(Strictness.STRICT).primaryLanguage("hi-IN") +
            PreferencesPatch().strictness(Strictness.RELAXED)
        val prefs = UserPreferences().apply(patch)
        assertEquals(Strictness.RELAXED, prefs.strictness)
        assertEquals("hi-IN", prefs.primaryLanguage)
    }

    @Test
    fun `typed view reads defaults when the document is empty`() {
        val prefs = UserPreferences()
        assertEquals(Strictness.BALANCED, prefs.strictness)
        assertEquals(UnknownCallerBehavior.SCREEN, prefs.unknownCallerBehavior)
        assertEquals(TrustedContactBehavior.ALLOW_DIRECTLY, prefs.trustedContactBehavior)
        assertEquals(7, prefs.transcriptRetentionDays)
        assertEquals(listOf("en-IN", "hi-IN", "kn-IN"), prefs.enabledLanguages)
        assertFalse(prefs.storeFullCallerNumber)
        assertTrue(prefs.notifyOnEscalation)
    }

    @Test
    fun `enabled languages round trip as a json array`() {
        val patch = PreferencesPatch().enabledLanguages(listOf("en-IN", "kn-IN"))
        assertEquals(JsonArray(listOf(JsonPrimitive("en-IN"), JsonPrimitive("kn-IN"))), patch.values["enabled_languages"])
        assertEquals(listOf("en-IN", "kn-IN"), UserPreferences().apply(patch).enabledLanguages)
    }

    @Test
    fun `patches survive a json round trip`() {
        val patch = PreferencesPatch().strictness(Strictness.STRICT).transcriptRetentionDays(14)
        val decoded = PreferencesPatch.fromJson(SpartaJson, patch.toJsonString(SpartaJson))
        assertEquals(patch.values, decoded.values)
        assertTrue(PreferencesPatch.fromJson(SpartaJson, "garbage").isEmpty)
        assertTrue(PreferencesPatch.fromJson(SpartaJson, null).isEmpty)
    }

    @Test
    fun `assistant profile edits are merged onto the freshest document`() = runBlocking {
        val profile = """{"owner_display_name":"Asha","response_style":"concise","speaking_rate":1.0,"voice_ids":{"en-IN":"v1"},"use_personal_voice":false,"future":true}"""
        harness.enqueueJson(profile)
        harness.enqueueJson(profile.replace("1.0", "1.2"))

        val result = repo.saveAssistantProfile { it.withSpeakingRate(1.2).withVoice("hi-IN", "v2") }

        assertEquals(1.2, (result as ApiResult.Success).value.speakingRate, 0.0)
        harness.takeRequest()
        val body = SpartaJson.parseToJsonElement(harness.takeRequest().body.readUtf8()).jsonObject
        assertEquals("1.2", body.getValue("speaking_rate").jsonPrimitive.content)
        assertEquals("v1", body.getValue("voice_ids").jsonObject.getValue("en-IN").jsonPrimitive.content)
        assertEquals("v2", body.getValue("voice_ids").jsonObject.getValue("hi-IN").jsonPrimitive.content)
        assertTrue(body.containsKey("future"))
    }

    @Test
    fun `assistant profile save reports a refused personal voice honestly`() = runBlocking {
        harness.enqueueJson("""{"owner_display_name":"Asha"}""")
        harness.enqueueJson("""{"error":{"code":"conflict","message":"Personal voice is not ready","trace_id":"t"}}""", 409)
        val result = repo.saveAssistantProfile { it }
        assertEquals("Personal voice is not ready", (result as ApiResult.Failure).error.message)
    }
}
