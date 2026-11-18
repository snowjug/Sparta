package io.github.snowjug.sparta

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import io.github.snowjug.sparta.platform.NotificationChannels
import javax.inject.Inject

/**
 * Keeps start-up cheap on purpose: the call-screening service can cold-start this process, and its fast path has a
 * hard deadline. Everything else (WorkManager scheduling, backend sync) starts from the UI, not from here.
 */
@HiltAndroidApp
class SpartaApp : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    override fun onCreate() {
        super.onCreate()
        NotificationChannels.create(this)
    }
}
