package io.github.snowjug.sparta.platform

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import io.github.snowjug.sparta.MainActivity
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.nav.DeepLinks
import io.github.snowjug.sparta.core.notify.EscalationNotice
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.data.repo.EscalationNotifier
import io.github.snowjug.sparta.data.repo.ScreeningNotifier
import io.github.snowjug.sparta.ui.ScreeningText

object NotificationChannels {
    /** High importance: the backend needs the owner's decision on a call. */
    const val ESCALATIONS = "escalations"

    /** Default importance: quiet updates about on-device screening decisions. */
    const val SCREENING = "screening"

    fun create(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        val escalations = NotificationChannel(
            ESCALATIONS,
            context.getString(R.string.channel_escalations_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply { description = context.getString(R.string.channel_escalations_desc) }
        val screening = NotificationChannel(
            SCREENING,
            context.getString(R.string.channel_screening_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply { description = context.getString(R.string.channel_screening_desc) }
        manager.createNotificationChannels(listOf(escalations, screening))
    }
}

/**
 * Posts the two kinds of Sparta notification. Both deep-link into the app (sparta://call/{id} or sparta://event/{id}),
 * and the lock screen only ever shows a generic title: numbers and content appear after unlocking.
 */
class AndroidNotifier(private val context: Context) : ScreeningNotifier, EscalationNotifier {

    override fun notifyEscalation(notice: EscalationNotice, silent: Boolean) {
        val title = context.getString(if (notice.highRisk && notice.purpose == null) R.string.notif_highrisk_title else R.string.notif_escalation_title)
        val text = notice.purpose?.let { context.getString(R.string.notif_escalation_text_purpose, notice.callerDisplay, it) }
            ?: context.getString(R.string.notif_escalation_text_plain, notice.callerDisplay)
        val lines = notice.importantLines.joinToString(separator = "\n")
        val builder = base(NotificationChannels.ESCALATIONS, title, text, DeepLinks.incoming(notice.callId), notice.callId.hashCode())
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setSilent(silent)
        if (lines.isNotEmpty()) builder.setStyle(NotificationCompat.BigTextStyle().bigText("$text\n$lines"))
        post(notice.callId.hashCode(), builder)
    }

    override fun notifyScreened(eventId: String, decision: ScreeningDecision, numberDisplay: String) {
        val rejected = decision.action == ScreeningAction.REJECT
        val title = context.getString(
            if (rejected) R.string.notif_screening_rejected_title else R.string.notif_screening_silenced_title,
            numberDisplay,
        )
        val text = context.getString(ScreeningText.reasonExplanation(decision.reason.wire))
        val builder = base(NotificationChannels.SCREENING, title, text, DeepLinks.screeningEvent(eventId), eventId.hashCode())
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setStyle(NotificationCompat.BigTextStyle().bigText("$text\n${context.getString(R.string.notif_screening_note)}"))
        post(eventId.hashCode(), builder)
    }

    private fun base(channel: String, title: String, text: String, link: String, requestCode: Int): NotificationCompat.Builder {
        val publicVersion = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_sparta)
            .setContentTitle(context.getString(R.string.app_name))
            .build()
        return NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_sparta)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion)
            .setContentIntent(open(link, requestCode))
    }

    private fun open(link: String, requestCode: Int): PendingIntent {
        val intent = Intent(Intent.ACTION_VIEW, link.toUri())
            .setClass(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    @SuppressLint("MissingPermission") // guarded by canPost(): POST_NOTIFICATIONS is requested only after an explanation.
    private fun post(id: Int, builder: NotificationCompat.Builder) {
        if (!canPost()) return
        try {
            NotificationManagerCompat.from(context).notify(id, builder.build())
        } catch (_: SecurityException) {
            // Permission revoked between the check and the call: nothing else to do.
        }
    }

    private fun canPost(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }
        return NotificationManagerCompat.from(context).areNotificationsEnabled()
    }
}
