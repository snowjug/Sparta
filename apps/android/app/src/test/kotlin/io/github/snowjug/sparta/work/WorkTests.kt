package io.github.snowjug.sparta.work

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.ListenableWorker
import androidx.work.NetworkType
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import androidx.work.testing.WorkManagerTestInitHelper
import androidx.work.workDataOf
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
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.repo.ScreeningNotifier
import io.github.snowjug.sparta.data.repo.ScreeningRecorder
import io.github.snowjug.sparta.data.repo.ScreeningUploader
import io.github.snowjug.sparta.data.repo.UploadScheduler
import io.github.snowjug.sparta.testutil.ApiHarness
import io.github.snowjug.sparta.testutil.FakeSettingsRepository
import io.github.snowjug.sparta.testutil.inMemoryDatabase
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UploadWorkerTest {

    private lateinit var context: Context
    private lateinit var db: SpartaDatabase
    private lateinit var harness: ApiHarness
    private lateinit var uploader: ScreeningUploader

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        db = inMemoryDatabase()
        harness = ApiHarness()
        uploader = ScreeningUploader(db.screeningEvents(), harness.api, SpartaJson)
    }

    @After
    fun tearDown() {
        harness.close()
        db.close()
    }

    private fun recordEvent(): String = runBlocking {
        val recorder = ScreeningRecorder(
            db.screeningEvents(),
            FakeSettingsRepository(),
            object : UploadScheduler {
                override fun enqueueUpload(eventId: String) = Unit
            },
            object : ScreeningNotifier {
                override fun notifyScreened(eventId: String, decision: ScreeningDecision, numberDisplay: String) = Unit
            },
            IdGenerator { "11111111-1111-4111-8111-111111111111" },
        )
        recorder.record(
            ScreeningRequest("+919876543221", CallDirection.INCOMING, CallerVerification.NOT_VERIFIED),
            ScreenedNumber(null, "fingerprint-hex", "+91 98•••• ••21"),
            ScreeningOutcome(ScreeningDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, true), 20, false, true),
            occurredAtMs = 1_794_909_600_000L,
        )!!
    }

    private fun worker(eventId: String?, attempt: Int = 0) = TestListenableWorkerBuilder<ScreeningEventUploadWorker>(context)
        .setInputData(if (eventId == null) androidx.work.Data.EMPTY else workDataOf(ScreeningEventUploadWorker.KEY_EVENT_ID to eventId))
        .setRunAttemptCount(attempt)
        .setWorkerFactory(
            object : WorkerFactory() {
                override fun createWorker(appContext: Context, workerClassName: String, workerParameters: WorkerParameters): ListenableWorker =
                    ScreeningEventUploadWorker(appContext, workerParameters, uploader)
            },
        )
        .build()

    private val ok =
        """{"id":"call_77","provider":"android_screening","mode":"screening_only","simulated":false,"status":"ended","state":"COMPLETED","started_at":"2026-11-17T10:00:00Z","caller_display":"+91 98•••• ••21"}"""

    @Test
    fun `success uploads once and a rerun does nothing`() = runBlocking {
        val id = recordEvent()
        harness.enqueueJson(ok)
        assertEquals(ListenableWorker.Result.success(), worker(id).doWork())
        assertEquals(UploadState.UPLOADED, db.screeningEvents().get(id)!!.uploadState)

        assertEquals(ListenableWorker.Result.success(), worker(id).doWork())
        assertEquals("the second run is idempotent: no second request", 1, harness.server.requestCount)
    }

    @Test
    fun `an unreachable backend retries with backoff and keeps the event pending`() = runBlocking {
        val id = recordEvent()
        harness.server.shutdown()
        assertEquals(ListenableWorker.Result.retry(), worker(id).doWork())
        assertEquals(UploadState.PENDING, db.screeningEvents().get(id)!!.uploadState)
    }

    @Test
    fun `server errors retry until the attempt budget is spent then give up but stay pending`() = runBlocking {
        val id = recordEvent()
        harness.enqueueJson("{}", 503)
        harness.enqueueJson("{}", 503)
        assertEquals(ListenableWorker.Result.retry(), worker(id, attempt = 0).doWork())
        assertEquals(ListenableWorker.Result.failure(), worker(id, attempt = UploadWorkPolicy.MAX_RUN_ATTEMPTS - 1).doWork())
        assertEquals(UploadState.PENDING, db.screeningEvents().get(id)!!.uploadState)
    }

    @Test
    fun `a permanent refusal fails the work and marks the event failed`() = runBlocking {
        val id = recordEvent()
        harness.enqueueJson("""{"error":{"code":"validation_error","message":"bad","trace_id":"t"}}""", 422)
        assertEquals(ListenableWorker.Result.failure(), worker(id).doWork())
        assertEquals(UploadState.FAILED, db.screeningEvents().get(id)!!.uploadState)
    }

    @Test
    fun `missing input fails immediately`() = runBlocking {
        assertEquals(ListenableWorker.Result.failure(), worker(null).doWork())
    }
}

@RunWith(AndroidJUnit4::class)
class WorkSchedulerTest {

    private lateinit var context: Context
    private lateinit var workManager: WorkManager
    private lateinit var scheduler: WorkScheduler

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        WorkManagerTestInitHelper.initializeTestWorkManager(context)
        workManager = WorkManager.getInstance(context)
        scheduler = WorkScheduler(workManager)
    }

    private fun infos(name: String) = workManager.getWorkInfosForUniqueWork(name).get()

    @Test
    fun `an upload is one unique network constrained job per event`() {
        scheduler.enqueueUpload("evt-1")
        scheduler.enqueueUpload("evt-1")
        scheduler.enqueueUpload("evt-2")

        assertEquals(1, infos("${WorkScheduler.UPLOAD_PREFIX}evt-1").size)
        assertEquals(1, infos("${WorkScheduler.UPLOAD_PREFIX}evt-2").size)
        val info = infos("${WorkScheduler.UPLOAD_PREFIX}evt-1").single()
        assertTrue(info.tags.contains(WorkScheduler.TAG_UPLOAD))
        assertEquals(WorkInfo.State.ENQUEUED, info.state)
        assertEquals(NetworkType.CONNECTED, info.constraints.requiredNetworkType)
    }

    @Test
    fun `periodic sync is battery conscious and never faster than the platform minimum`() {
        scheduler.setPeriodicSyncEnabled(true)
        val info = infos(WorkScheduler.PERIODIC_SYNC).single()
        assertTrue(info.tags.contains(WorkScheduler.TAG_SYNC))
        assertTrue(info.constraints.requiresBatteryNotLow())
        assertEquals(NetworkType.CONNECTED, info.constraints.requiredNetworkType)
        assertTrue("at least 15 minutes", info.periodicityInfo!!.repeatIntervalMillis >= 15 * 60 * 1000L)
    }

    @Test
    fun `periodic sync can be switched off`() {
        scheduler.setPeriodicSyncEnabled(true)
        scheduler.setPeriodicSyncEnabled(false)
        assertEquals(WorkInfo.State.CANCELLED, infos(WorkScheduler.PERIODIC_SYNC).single().state)
    }
}
