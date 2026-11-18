package io.github.snowjug.sparta.data.repo

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.screening.CallDirection
import io.github.snowjug.sparta.core.screening.CallerVerification
import io.github.snowjug.sparta.core.screening.ScreenedNumber
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningOutcome
import io.github.snowjug.sparta.core.screening.ScreeningReason
import io.github.snowjug.sparta.core.screening.ScreeningRequest
import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.data.local.SpartaDatabase
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.FakeSettingsRepository
import io.github.snowjug.sparta.testutil.inMemoryDatabase
import kotlinx.coroutines.runBlocking
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
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ScreeningUploadAndRecorderTest {

    private lateinit var db: SpartaDatabase
    private lateinit var harness: ApiHarness
    private lateinit var uploader: ScreeningUploader
    private lateinit var settings: FakeSettingsRepository
    private val scheduled = mutableListOf<String>()
    private val notified = mutableListOf<Triple<String, ScreeningDecision, String>>()
    private var counter = 0
    private lateinit var recorder: ScreeningRecorder

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        harness = ApiHarness()
        uploader = ScreeningUploader(db.screeningEvents(), harness.api, SpartaJson)
        settings = FakeSettingsRepository()
        recorder = ScreeningRecorder(
            events = db.screeningEvents(),
            settings = settings,
            scheduler = object : UploadScheduler {
                override fun enqueueUpload(eventId: String) {
                    scheduled += eventId
                }
            },
            notifier = object : ScreeningNotifier {
                override fun notifyScreened(eventId: String, decision: ScreeningDecision, numberDisplay: String) {
                    notified += Triple(eventId, decision, numberDisplay)
                }
            },
            ids = IdGenerator { "00000000-0000-4000-8000-%012d".format(++counter) },
        )
    }

    @After
    fun tearDown() {
        harness.close()
        db.close()
    }

    private val request = ScreeningRequest("tel:+919876543221", CallDirection.INCOMING, CallerVerification.NOT_VERIFIED)
    private val number = ScreenedNumber(null, "fingerprint-hex", "+91 98•••• ••21")

    private fun outcome(
        action: ScreeningAction = ScreeningAction.SILENCE,
        reason: ScreeningReason = ScreeningReason.UNKNOWN_SCREENED,
        notify: Boolean = true,
        missed: Boolean = false,
        latency: Long = 37,
    ) = ScreeningOutcome(ScreeningDecision(action, reason, notify), latency, missed, responseDelivered = true)

    private val okResponse =
        """{"id":"call_77","provider":"android_screening","mode":"screening_only","simulated":false,"status":"ended","state":"COMPLETED","started_at":"2026-11-17T10:00:00Z","caller_display":"+91 98•••• ••21"}"""

    // ---- recorder ----

    @Test
    fun `recording persists the event with masked display latency and schedules one upload`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1_000L)!!
        val event = db.screeningEvents().get(id)!!
        assertEquals("+91 98•••• ••21", event.numberDisplay)
        assertEquals("fingerprint-hex", event.numberFingerprint)
        assertEquals("silence", event.decision)
        assertEquals("unknown_screened", event.reason)
        assertEquals("not_verified", event.verificationStatus)
        assertEquals("incoming", event.direction)
        assertEquals(37L, event.decisionLatencyMs)
        assertEquals(1_000L, event.occurredAtMs)
        assertEquals(UploadState.PENDING, event.uploadState)
        assertEquals(listOf(id), scheduled)
        assertFalse("the raw number must never be stored", event.toString().contains("9876543221"))
    }

    @Test
    fun `a deadline miss is counted and the safe default is what gets recorded`() = runBlocking {
        val id = recorder.record(
            request,
            number,
            outcome(ScreeningAction.ALLOW, ScreeningReason.DEADLINE_EXCEEDED, notify = false, missed = true, latency = 1500),
            occurredAtMs = 5L,
        )!!
        assertEquals(1L, settings.value.deadlineMissCount)
        assertTrue(db.screeningEvents().get(id)!!.deadlineMissed)
        assertTrue(notified.isEmpty())
    }

    @Test
    fun `outgoing calls are never recorded`() = runBlocking {
        val id = recorder.record(request, number, outcome(ScreeningAction.ALLOW, ScreeningReason.OUTGOING_CALL, notify = false), occurredAtMs = 1L)
        assertNull(id)
        assertTrue(scheduled.isEmpty())
    }

    @Test
    fun `a number without a fingerprint stays local only and is not scheduled`() = runBlocking {
        val id = recorder.record(request, ScreenedNumber(null, null, "Private number"), outcome(), occurredAtMs = 1L)!!
        assertEquals(UploadState.LOCAL_ONLY, db.screeningEvents().get(id)!!.uploadState)
        assertTrue(scheduled.isEmpty())
    }

    @Test
    fun `screen decisions notify the owner only when screening notifications are enabled`() = runBlocking {
        recorder.record(request, number, outcome(), occurredAtMs = 1L)
        assertEquals(1, notified.size)
        assertEquals("+91 98•••• ••21", notified.single().third)

        settings.update { it.copy(notifyScreening = false) }
        recorder.record(request, number, outcome(), occurredAtMs = 2L)
        assertEquals(1, notified.size)
    }

    @Test
    fun `a failing notifier or scheduler never loses the recorded event`() = runBlocking {
        val failing = ScreeningRecorder(
            db.screeningEvents(),
            settings,
            object : UploadScheduler {
                override fun enqueueUpload(eventId: String) = error("work manager unavailable")
            },
            object : ScreeningNotifier {
                override fun notifyScreened(eventId: String, decision: ScreeningDecision, numberDisplay: String) = error("no channel")
            },
            IdGenerator { "evt-1" },
        )
        assertEquals("evt-1", failing.record(request, number, outcome(), occurredAtMs = 1L))
        assertNotNull(db.screeningEvents().get("evt-1"))
    }

    // ---- uploader ----

    @Test
    fun `upload sends the documented body and marks the event uploaded`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1_794_909_600_000L)!!
        harness.enqueueJson(okResponse)

        val result = uploader.upload(id)

        assertEquals(UploadOutcome.Uploaded("call_77"), result)
        val stored = db.screeningEvents().get(id)!!
        assertEquals(UploadState.UPLOADED, stored.uploadState)
        assertEquals("call_77", stored.backendCallId)

        val sent = harness.takeRequest()
        assertEquals("/api/v1/screening/events", sent.path)
        assertEquals(id, sent.getHeader("Idempotency-Key"))
        val raw = sent.body.readUtf8()
        val body = SpartaJson.parseToJsonElement(raw).jsonObject
        assertEquals(id, body.getValue("client_event_id").jsonPrimitive.content)
        assertEquals("fingerprint-hex", body.getValue("number_fingerprint").jsonPrimitive.content)
        assertEquals("+91 98•••• ••21", body.getValue("number_display").jsonPrimitive.content)
        assertEquals("silence", body.getValue("decision").jsonPrimitive.content)
        assertEquals("unknown_screened", body.getValue("reason").jsonPrimitive.content)
        assertEquals("2026-11-17T10:00:00Z", body.getValue("occurred_at").jsonPrimitive.content)
        assertFalse("the raw number must never be uploaded", raw.contains("9876543221"))
    }

    @Test
    fun `an unknown call direction is omitted because the backend only accepts incoming or outgoing`() = runBlocking {
        val unknownDirection = ScreeningRequest("tel:+919876543221", CallDirection.UNKNOWN, CallerVerification.UNKNOWN)
        val id = recorder.record(unknownDirection, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson(okResponse)

        uploader.upload(id)

        val body = SpartaJson.parseToJsonElement(harness.takeRequest().body.readUtf8()).jsonObject
        assertFalse("direction" in body)
        assertEquals("unknown", body.getValue("verification_status").jsonPrimitive.content)
    }

    @Test
    fun `uploading twice is idempotent and sends nothing the second time`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson(okResponse)
        uploader.upload(id)
        assertEquals(UploadOutcome.NothingToDo, uploader.upload(id))
        assertEquals(1, harness.server.requestCount)
    }

    @Test
    fun `a retry after a lost response reuses the same client event id`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.server.shutdown()
        val first = uploader.upload(id)
        assertEquals(ApiErrorKind.OFFLINE, (first as UploadOutcome.Retry).error.kind)
        assertEquals(UploadState.PENDING, db.screeningEvents().get(id)!!.uploadState)
        assertEquals(1, db.screeningEvents().get(id)!!.uploadAttempts)

        val second = ApiHarness().also { harness = it }
        uploader = ScreeningUploader(db.screeningEvents(), second.api, SpartaJson)
        second.enqueueJson(okResponse)
        assertEquals(UploadOutcome.Uploaded("call_77"), uploader.upload(id))
        assertEquals(id, second.takeRequest().getHeader("Idempotency-Key"))
    }

    @Test
    fun `server errors and rate limits retry`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson("{}", 503)
        harness.enqueueJson("{}", 429)
        harness.enqueueJson("{}", 500)
        repeat(3) { assertTrue(uploader.upload(id) is UploadOutcome.Retry) }
        assertEquals(UploadState.PENDING, db.screeningEvents().get(id)!!.uploadState)
        assertEquals(3, db.screeningEvents().get(id)!!.uploadAttempts)
    }

    @Test
    fun `an unreadable success body retries because the backend may already have stored it`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson("not json")
        assertTrue(uploader.upload(id) is UploadOutcome.Retry)
    }

    @Test
    fun `validation errors are permanent`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson("""{"error":{"code":"validation_error","message":"bad","trace_id":"t"}}""", 422)
        val result = uploader.upload(id)
        assertTrue(result is UploadOutcome.Rejected)
        assertEquals(UploadState.FAILED, db.screeningEvents().get(id)!!.uploadState)
        assertEquals(UploadOutcome.NothingToDo, uploader.upload(id))
    }

    @Test
    fun `missing sign in defers without failing the event`() = runBlocking {
        val id = recorder.record(request, number, outcome(), occurredAtMs = 1L)!!
        harness.enqueueJson("{}", 401)
        assertTrue(uploader.upload(id) is UploadOutcome.Deferred)
        assertEquals(UploadState.PENDING, db.screeningEvents().get(id)!!.uploadState)
    }

    @Test
    fun `unknown events and local only events are nothing to do`() = runBlocking {
        assertEquals(UploadOutcome.NothingToDo, uploader.upload("missing"))
        val id = recorder.record(request, ScreenedNumber(null, null, "Private number"), outcome(), occurredAtMs = 1L)!!
        assertEquals(UploadOutcome.NothingToDo, uploader.upload(id))
        assertEquals(0, harness.server.requestCount)
    }
}
