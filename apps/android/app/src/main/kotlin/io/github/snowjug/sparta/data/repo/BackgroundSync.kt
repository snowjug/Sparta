package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.notify.EscalationNotice
import io.github.snowjug.sparta.core.notify.EscalationNoticePolicy
import io.github.snowjug.sparta.core.notify.QuietHours
import io.github.snowjug.sparta.core.time.MinuteOfDayProvider
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.CachedCallDao
import io.github.snowjug.sparta.data.local.NotifiedItemDao
import io.github.snowjug.sparta.data.local.NotifiedItemEntity
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.ApiResult
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import kotlinx.coroutines.flow.first

/** Posts the high-importance "Escalations" notification (implemented with NotificationManager; faked in tests). */
interface EscalationNotifier {
    fun notifyEscalation(notice: EscalationNotice, silent: Boolean)
}

/**
 * Decides whether an escalation or high-risk call deserves a notification (owner switches, quiet hours, content
 * opt-in) and guarantees each call notifies at most once, whether it arrives over the live socket or the periodic sync.
 */
class EscalationAnnouncer(
    private val notified: NotifiedItemDao,
    private val settings: SettingsRepository,
    private val preferences: PreferencesRepository,
    private val notifier: EscalationNotifier,
    private val clock: WallClock,
    private val minuteOfDay: MinuteOfDayProvider,
) {
    /** [key] identifies the thing being announced (for example "call:{id}"); returns true when a notification was posted. */
    suspend fun announce(key: String, notice: EscalationNotice, kind: Kind): Boolean {
        if (!settings.current().notifyEscalations) return false
        val prefs = preferences.preferences.first()
        val allowed = when (kind) {
            Kind.ESCALATION -> prefs?.notifyOnEscalation ?: true
            Kind.HIGH_RISK -> prefs?.notifyOnHighRisk ?: false
        }
        if (!allowed) return false
        if (notified.insert(NotifiedItemEntity(key, clock.nowMs())) == -1L) return false

        val silent = QuietHours.isQuiet(minuteOfDay.minuteOfDay(), prefs?.quietHoursStart, prefs?.quietHoursEnd)
        val shown = if (prefs?.includeTranscriptLines == false) notice.copy(purpose = null, importantLines = emptyList()) else notice
        notifier.notifyEscalation(shown, silent)
        return true
    }

    enum class Kind { ESCALATION, HIGH_RISK }
}

data class SyncReport(
    val skipped: Boolean = false,
    val listsSynced: Boolean = false,
    val uploadsRequeued: Int = 0,
    val notificationsPosted: Int = 0,
    val error: ApiErrorKind? = null,
)

/**
 * One battery-conscious background pass (WorkManager, at most every 15 minutes, only with a network and a
 * not-low battery): push pending preference edits, refresh the local screening cache, retry pending uploads, announce
 * calls that need the owner, and prune old local data. It never holds a foreground service or a wake lock.
 */
class BackgroundSync(
    private val settings: SettingsRepository,
    private val screening: ScreeningRepository,
    private val preferences: PreferencesRepository,
    private val calls: CallsRepository,
    private val scheduler: UploadScheduler,
    private val announcer: EscalationAnnouncer,
    private val cachedCalls: CachedCallDao,
    private val notified: NotifiedItemDao,
    private val clock: WallClock,
) {
    suspend fun run(): SyncReport {
        if (!settings.current().backendConfigured) return SyncReport(skipped = true)
        var error: ApiErrorKind? = null

        if (settings.current().preferencesDirty) {
            (preferences.push() as? ApiResult.Failure)?.let { error = it.error.kind }
        }
        val synced = when (val result = screening.syncConfigAndLists()) {
            is ApiResult.Success -> true
            is ApiResult.Failure -> {
                error = result.error.kind
                false
            }
        }

        val pending = screening.pendingEventIds()
        pending.forEach { scheduler.enqueueUpload(it) }

        var posted = 0
        val now = clock.nowMs()
        (calls.refresh(CallFilter(attentionOnly = true)) as? ApiResult.Success)?.value?.items.orEmpty().forEach { call ->
            if (shouldAnnounceEscalation(call, now) && announce(call, EscalationAnnouncer.Kind.ESCALATION, "call:${call.id}")) posted++
        }
        (calls.refresh(CallFilter(risk = RiskLevel.HIGH)) as? ApiResult.Success)?.value?.items.orEmpty().forEach { call ->
            val fresh = EscalationNoticePolicy.isFresh(Timestamps.parseMs(call.startedAt), now)
            if (fresh && !call.ownerAttentionRequired && announce(call, EscalationAnnouncer.Kind.HIGH_RISK, "risk:${call.id}")) posted++
        }

        prune(now)
        return SyncReport(listsSynced = synced, uploadsRequeued = pending.size, notificationsPosted = posted, error = error)
    }

    private fun shouldAnnounceEscalation(call: CallListItemDto, now: Long): Boolean =
        call.ownerAttentionRequired &&
            call.status != CallStatus.FAILED &&
            EscalationNoticePolicy.isFresh(Timestamps.parseMs(call.startedAt), now)

    private suspend fun announce(call: CallListItemDto, kind: EscalationAnnouncer.Kind, key: String): Boolean =
        announcer.announce(
            key = key,
            notice = EscalationNotice(
                callId = call.id,
                callerDisplay = call.callerDisplay,
                purpose = call.purpose ?: call.callerClaim.organization,
                importantLines = emptyList(),
                highRisk = call.riskLevel == RiskLevel.HIGH,
            ),
            kind = kind,
        )

    private suspend fun prune(now: Long) {
        screening.pruneEventsOlderThan(now - EVENT_RETENTION_MS)
        cachedCalls.deleteOlderThan(now - CALL_CACHE_RETENTION_MS)
        notified.deleteOlderThan(now - NOTIFIED_RETENTION_MS)
    }

    companion object {
        const val EVENT_RETENTION_MS = 90L * 24 * 60 * 60 * 1000
        const val CALL_CACHE_RETENTION_MS = 60L * 24 * 60 * 60 * 1000
        const val NOTIFIED_RETENTION_MS = 30L * 24 * 60 * 60 * 1000
    }
}
