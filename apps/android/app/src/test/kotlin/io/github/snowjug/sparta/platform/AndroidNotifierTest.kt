package io.github.snowjug.sparta.platform

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.nav.DeepLink
import io.github.snowjug.sparta.core.nav.DeepLinks
import io.github.snowjug.sparta.core.nav.Routes
import io.github.snowjug.sparta.core.notify.EscalationNotice
import io.github.snowjug.sparta.core.screening.ScreeningAction
import io.github.snowjug.sparta.core.screening.ScreeningDecision
import io.github.snowjug.sparta.core.screening.ScreeningReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf

@RunWith(AndroidJUnit4::class)
class AndroidNotifierTest {

    private lateinit var context: Context
    private lateinit var manager: NotificationManager
    private lateinit var notifier: AndroidNotifier
    private val masked = "+91 98\u2022\u2022\u2022\u2022 \u2022\u202221"

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        manager = context.getSystemService(NotificationManager::class.java)
        shadowOf(context as android.app.Application).grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        NotificationChannels.create(context)
        notifier = AndroidNotifier(context)
    }

    private fun posted(): List<Notification> = shadowOf(manager).allNotifications

    private fun Notification.title(): String = extras.getCharSequence(Notification.EXTRA_TITLE).toString()

    private fun Notification.text(): String = extras.getCharSequence(Notification.EXTRA_TEXT).toString()

    private fun Notification.openedLink(): String? = shadowOf(contentIntent).savedIntent.data?.toString()

    private val notice = EscalationNotice(
        callId = "call_77",
        callerDisplay = "+91 98\u2022\u2022\u2022\u2022 \u2022\u202221",
        purpose = "Parcel delivery",
        importantLines = listOf("Please confirm the address"),
        highRisk = false,
    )

    @Test
    fun `there are two channels one urgent for calls that need the owner and one quiet for decisions`() {
        val escalations = manager.getNotificationChannel(NotificationChannels.ESCALATIONS)
        val screening = manager.getNotificationChannel(NotificationChannels.SCREENING)
        assertEquals(NotificationManager.IMPORTANCE_HIGH, escalations.importance)
        assertEquals(NotificationManager.IMPORTANCE_DEFAULT, screening.importance)
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.channel_escalations_name), escalations.name.toString())
        assertTrue(escalations.description.isNotBlank())

        NotificationChannels.create(context) // idempotent: running it again keeps exactly two channels
        assertEquals(2, manager.notificationChannels.size)
    }

    @Test
    fun `an escalation opens the incoming call screen through a validated deep link`() {
        notifier.notifyEscalation(notice, silent = false)

        val notification = posted().single()
        assertEquals(NotificationChannels.ESCALATIONS, notification.channelId)
        val link = notification.openedLink()
        assertEquals("sparta://call/call_77", link)
        // The whole path a tap takes: notification -> intent data -> parsed link -> in-app route.
        val parsed = DeepLinks.parse(link)
        assertEquals(DeepLink.Incoming("call_77"), parsed)
        assertEquals(Routes.incoming("call_77"), Routes.forLink(parsed!!))
    }

    @Test
    fun `an escalation shows the masked number and the purpose but the lock screen only a generic title`() {
        notifier.notifyEscalation(notice, silent = false)

        val notification = posted().single()
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.notif_escalation_title), notification.title())
        assertTrue(notification.text().contains(masked))
        assertTrue(notification.text().contains("Parcel delivery"))
        assertEquals(Notification.VISIBILITY_PRIVATE, notification.visibility)
        val publicVersion = notification.publicVersion
        assertNotNull(publicVersion)
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.app_name), publicVersion.title())
        assertFalse("nothing about the caller on the lock screen", publicVersion.text().contains("98"))
    }

    @Test
    fun `important lines appear only in the expanded text`() {
        notifier.notifyEscalation(notice, silent = false)
        val expanded = posted().single().extras.getCharSequence(Notification.EXTRA_BIG_TEXT).toString()
        assertTrue(expanded.contains("Please confirm the address"))

        manager.cancelAll()
        notifier.notifyEscalation(notice.copy(importantLines = emptyList()), silent = false)
        assertEquals("no content lines means no big text", null, posted().single().extras.getCharSequence(Notification.EXTRA_BIG_TEXT))
    }

    @Test
    fun `a high risk call without a purpose uses the high risk title`() {
        notifier.notifyEscalation(notice.copy(purpose = null, importantLines = emptyList(), highRisk = true), silent = true)
        val notification = posted().single()
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.notif_highrisk_title), notification.title())
    }

    @Test
    fun `without the notification permission nothing is posted and nothing crashes`() {
        shadowOf(context as android.app.Application).denyPermissions(Manifest.permission.POST_NOTIFICATIONS)
        notifier.notifyEscalation(notice, silent = false)
        notifier.notifyScreened("evt_1", ScreeningDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, true), masked)
        assertTrue(posted().isEmpty())
    }

    @Test
    fun `a silenced call is announced quietly and opens the event screen`() {
        notifier.notifyScreened("evt_9", ScreeningDecision(ScreeningAction.SILENCE, ScreeningReason.UNKNOWN_SCREENED, true), masked)

        val notification = posted().single()
        assertEquals(NotificationChannels.SCREENING, notification.channelId)
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.notif_screening_silenced_title, masked), notification.title())
        assertEquals(Routes.event("evt_9"), Routes.forLink(DeepLinks.parse(notification.openedLink())!!))
        val expanded = notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT).toString()
        assertTrue("it must say Sparta did not answer the call", expanded.contains(context.getString(io.github.snowjug.sparta.R.string.notif_screening_note)))
    }

    @Test
    fun `a rejected call says blocked`() {
        notifier.notifyScreened("evt_2", ScreeningDecision(ScreeningAction.REJECT, ScreeningReason.BLOCKED_NUMBER, true), masked)
        assertEquals(context.getString(io.github.snowjug.sparta.R.string.notif_screening_rejected_title, masked), posted().single().title())
    }

    @Test
    fun `the same call updates its notification instead of stacking another`() {
        notifier.notifyEscalation(notice, silent = false)
        notifier.notifyEscalation(notice.copy(purpose = "Parcel delivery, updated"), silent = false)
        assertEquals(1, posted().size)
    }
}
