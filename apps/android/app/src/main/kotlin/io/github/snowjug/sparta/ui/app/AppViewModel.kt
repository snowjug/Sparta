package io.github.snowjug.sparta.ui.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.snowjug.sparta.core.motion.ReducedMotion
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.prefs.ThemeMode
import io.github.snowjug.sparta.data.repo.EscalationMonitor
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.platform.AnimatorScaleReader
import io.github.snowjug.sparta.work.WorkScheduler
import javax.inject.Inject
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** What the app shell needs before it can show anything: has setup finished, which theme, is motion reduced. */
data class AppUiState(
    val loaded: Boolean = false,
    val onboardingCompleted: Boolean = false,
    val themeMode: ThemeMode = ThemeMode.DARK,
    val reducedMotion: Boolean = false,
    /** The backend says it runs with a development identity: every screen must say so. */
    val devBanner: Boolean = false,
)

@HiltViewModel
class AppViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val system: SystemRepository,
    private val scheduler: WorkScheduler,
    private val animatorScale: AnimatorScaleReader,
    private val monitor: EscalationMonitor,
) : ViewModel() {

    private val systemScale = MutableStateFlow(animatorScale.read())

    val state: StateFlow<AppUiState> = combine(settings.settings, system.cachedStatus, systemScale) { s, cached, scale ->
        AppUiState(
            loaded = true,
            onboardingCompleted = s.onboardingCompleted,
            themeMode = s.themeMode,
            reducedMotion = ReducedMotion.isReduced(scale, s.motionPreference),
            devBanner = s.backendConfigured && cached?.status?.devBanner == true,
        )
    }.stateIn(viewModelScope, SharingStarted.Eagerly, AppUiState())

    init {
        // Battery: one periodic WorkManager job, only while it can do something useful, never a service or a wake lock.
        viewModelScope.launch {
            settings.settings
                .map { it.onboardingCompleted && it.backendConfigured && it.backgroundSyncEnabled }
                .distinctUntilChanged()
                .collect { enabled -> runCatching { scheduler.setPeriodicSyncEnabled(enabled) } }
        }
    }

    /** The system "remove animations" switch can change while the app is in the background. */
    fun onResume() {
        systemScale.value = animatorScale.read()
    }

    /**
     * Listens for "a call needs you" over the live socket while the UI is on screen (the caller cancels this when the
     * UI stops). It restarts by itself if the backend, the notification switch or onboarding changes.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    suspend fun monitorEscalations() {
        settings.settings
            .map { it.backendConfigured && it.onboardingCompleted && it.notifyEscalations }
            .distinctUntilChanged()
            .collectLatest { eligible -> if (eligible) monitor.run() }
    }
}
