package io.github.snowjug.sparta.work

import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import io.github.snowjug.sparta.data.repo.UploadScheduler
import java.util.concurrent.TimeUnit

/** WorkManager-backed scheduling. No foreground service, no wake locks, no alarms. */
class WorkScheduler(private val workManager: WorkManager) : UploadScheduler {

    /** One unique job per event: enqueueing the same event twice is a no-op while the first is still pending. */
    override fun enqueueUpload(eventId: String) {
        val request = OneTimeWorkRequestBuilder<ScreeningEventUploadWorker>()
            .setInputData(workDataOf(ScreeningEventUploadWorker.KEY_EVENT_ID to eventId))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, UPLOAD_BACKOFF_SECONDS, TimeUnit.SECONDS)
            .addTag(TAG_UPLOAD)
            .build()
        workManager.enqueueUniqueWork("$UPLOAD_PREFIX$eventId", ExistingWorkPolicy.KEEP, request)
    }

    /** At most every 15 minutes (the WorkManager minimum), only with a network and a battery that is not low. */
    fun setPeriodicSyncEnabled(enabled: Boolean) {
        if (!enabled) {
            workManager.cancelUniqueWork(PERIODIC_SYNC)
            return
        }
        val request = PeriodicWorkRequestBuilder<PeriodicSyncWorker>(PERIODIC_MINUTES, TimeUnit.MINUTES, FLEX_MINUTES, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .setRequiresBatteryNotLow(true)
                    .build(),
            )
            .addTag(TAG_SYNC)
            .build()
        workManager.enqueueUniquePeriodicWork(PERIODIC_SYNC, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    companion object {
        const val UPLOAD_PREFIX = "screening-upload-"
        const val PERIODIC_SYNC = "sparta-periodic-sync"
        const val TAG_UPLOAD = "screening-upload"
        const val TAG_SYNC = "sparta-sync"
        const val PERIODIC_MINUTES = 30L
        const val FLEX_MINUTES = 10L
        const val UPLOAD_BACKOFF_SECONDS = 30L
    }
}
