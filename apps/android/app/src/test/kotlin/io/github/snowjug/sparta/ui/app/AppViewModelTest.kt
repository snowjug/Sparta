package io.github.snowjug.sparta.ui.app

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.WorkManagerTestInitHelper
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.notify.EscalationNotice
import io.github.snowjug.sparta.core.time.MinuteOfDayProvider
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.remote.ws.LiveEventSource
import io.github.snowjug.sparta.data.remote.ws.LiveSocketEvent
import io.github.snowjug.sparta.data.repo.EscalationAnnouncer
import io.github.snowjug.sparta.data.repo.EscalationMonitor
import io.github.snowjug.sparta.data.repo.EscalationNotifier
import io.github.snowjug.sparta.platform.AnimatorScaleReader
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.work.WorkScheduler
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AppViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private lateinit var context: Context
    private lateinit var h: VmHarness
    private var scale: Float? = 1f

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        WorkManagerTestInitHelper.initializeTestWorkManager(context)
        h = VmHarness(configured = false)
    }

    @After
    fun tearDown() = h.close()

    private fun viewModel(): AppViewModel {
        val source = object : LiveEventSource {
            override fun events(callId: String?): Flow<LiveSocketEvent> = emptyFlow()
        }
        val announcer = EscalationAnnouncer(
            notified = h.db.notifiedItems(),
            settings = h.settings,
            preferences = h.preferences,
            notifier = object : EscalationNotifier {
                override fun notifyEscalation(notice: EscalationNotice, silent: Boolean) = Unit
            },
            clock = h.clock,
            minuteOfDay = MinuteOfDayProvider { 12 * 60 },
        )
        return AppViewModel(
            settings = h.settings,
            system = h.system,
            scheduler = WorkScheduler(WorkManager.getInstance(context)),
            animatorScale = AnimatorScaleReader { scale },
            monitor = EscalationMonitor(source, announcer, h.calls, h.settings, SpartaJson),
        )
    }

    private fun periodicSyncStates(): List<WorkInfo.State> =
        WorkManager.getInstance(context).getWorkInfosForUniqueWork(WorkScheduler.PERIODIC_SYNC).get().map { it.state }

    @Test
    fun `the shell reports loaded and follows the stored theme and onboarding state`() {
        val vm = viewModel()
        val state = vm.state.await { it.loaded }
        assertFalse(state.onboardingCompleted)
        assertEquals(io.github.snowjug.sparta.data.prefs.ThemeMode.DARK, state.themeMode)
    }

    @Test
    fun `the development identity banner needs a configured backend that says so`() {
        val vm = viewModel()
        val devStatus = SpartaJson.encodeToString(SystemStatusDto.serializer(), Samples.status(devBanner = true))
        kotlinx.coroutines.runBlocking {
            h.settings.update { it.copy(cachedStatusJson = devStatus) }
        }
        assertFalse("a stale status from a backend that is no longer configured is not shown", vm.state.await { it.loaded }.devBanner)

        kotlinx.coroutines.runBlocking { h.settings.update { it.copy(backendUrl = "https://sparta.example.com/") } }
        assertTrue(vm.state.await { it.devBanner }.devBanner)

        val productionStatus = SpartaJson.encodeToString(SystemStatusDto.serializer(), Samples.status(devBanner = false))
        kotlinx.coroutines.runBlocking { h.settings.update { it.copy(cachedStatusJson = productionStatus) } }
        assertFalse(vm.state.await { !it.devBanner }.devBanner)
    }

    @Test
    fun `reduced motion follows the system animation scale and the owner preference`() {
        scale = 0f
        val vm = viewModel()
        assertTrue("remove animations in system settings", vm.state.await { it.loaded }.reducedMotion)

        scale = 1f
        vm.onResume()
        assertFalse("re-read when the app returns to the foreground", vm.state.await { !it.reducedMotion }.reducedMotion)

        kotlinx.coroutines.runBlocking { h.settings.update { it.copy(motionPreference = MotionPreference.REDUCE) } }
        assertTrue(vm.state.await { it.reducedMotion }.reducedMotion)
    }

    @Test
    fun `background sync is one periodic job that exists only while it can be useful`() {
        val vm = viewModel()
        vm.state.await { it.loaded }
        assertTrue("no backend and no onboarding: nothing scheduled", periodicSyncStates().isEmpty())

        kotlinx.coroutines.runBlocking { h.settings.update { it.copy(onboardingCompleted = true, backendUrl = "https://sparta.example.com/") } }
        vm.state.await { it.onboardingCompleted }
        awaitCondition { periodicSyncStates().isNotEmpty() && periodicSyncStates().none { it == WorkInfo.State.CANCELLED } }
        assertEquals("one unique periodic job, never a loop", 1, periodicSyncStates().size)

        kotlinx.coroutines.runBlocking { h.settings.update { it.copy(backgroundSyncEnabled = false) } }
        awaitCondition { periodicSyncStates().all { it == WorkInfo.State.CANCELLED } }
    }

    private fun awaitCondition(timeoutMs: Long = 5_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!condition()) {
            check(System.currentTimeMillis() < deadline) { "condition not reached in $timeoutMs ms" }
            Thread.sleep(25)
        }
    }
}
