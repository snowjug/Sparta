package io.github.snowjug.sparta.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import io.github.snowjug.sparta.data.repo.BackgroundSync
import io.github.snowjug.sparta.data.repo.ScreeningUploader
import io.github.snowjug.sparta.data.repo.UploadOutcome

/** Maps an upload outcome to a WorkManager decision. Pure so the retry policy is unit-tested. */
enum class UploadWorkDecision { SUCCESS, RETRY, GIVE_UP }

object UploadWorkPolicy {
    /** After this many automatic attempts the work gives up; the event stays pending and the next periodic sync re-enqueues it. */
    const val MAX_RUN_ATTEMPTS = 6

    fun decide(outcome: UploadOutcome, runAttemptCount: Int): UploadWorkDecision = when (outcome) {
        is UploadOutcome.Uploaded, UploadOutcome.NothingToDo -> UploadWorkDecision.SUCCESS
        is UploadOutcome.Retry -> if (runAttemptCount + 1 < MAX_RUN_ATTEMPTS) UploadWorkDecision.RETRY else UploadWorkDecision.GIVE_UP
        is UploadOutcome.Deferred, is UploadOutcome.Rejected -> UploadWorkDecision.GIVE_UP
    }
}

/** Uploads one screening event (idempotent on its client_event_id). Retries with exponential backoff while the backend is unreachable. */
@HiltWorker
class ScreeningEventUploadWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val uploader: ScreeningUploader,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val eventId = inputData.getString(KEY_EVENT_ID) ?: return Result.failure()
        val outcome = try {
            uploader.upload(eventId)
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return if (runAttemptCount + 1 < UploadWorkPolicy.MAX_RUN_ATTEMPTS) Result.retry() else Result.failure()
        }
        return when (UploadWorkPolicy.decide(outcome, runAttemptCount)) {
            UploadWorkDecision.SUCCESS -> Result.success()
            UploadWorkDecision.RETRY -> Result.retry()
            UploadWorkDecision.GIVE_UP -> Result.failure()
        }
    }

    companion object {
        const val KEY_EVENT_ID = "event_id"
    }
}

/** Periodic, battery-conscious sync (see [BackgroundSync]). Always reports success so the periodic schedule continues. */
@HiltWorker
class PeriodicSyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val sync: BackgroundSync,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        try {
            sync.run()
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // The next period tries again; one failed pass must never end the schedule.
        }
        return Result.success()
    }
}
