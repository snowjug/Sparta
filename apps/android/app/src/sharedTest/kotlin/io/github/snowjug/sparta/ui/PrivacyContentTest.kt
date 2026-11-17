package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.prefs.ThemeMode
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.ProtectedInfoDto
import io.github.snowjug.sparta.data.remote.dto.SafetyPolicyDto
import io.github.snowjug.sparta.data.repo.ListEntry
import io.github.snowjug.sparta.data.repo.UserPreferences
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.onboarding.ConnectionUi
import io.github.snowjug.sparta.ui.privacy.PrivacyActions
import io.github.snowjug.sparta.ui.privacy.PrivacyContent
import io.github.snowjug.sparta.ui.privacy.PrivacyUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PrivacyContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun userPrefs(json: String = "{}") = UserPreferences(Json.parseToJsonElement(json).jsonObject)

    private fun connected(change: PrivacyUiState.() -> PrivacyUiState = { this }) = PrivacyUiState(
        settings = AppSettings(backendUrl = "https://sparta.example.com/"),
        prefs = userPrefs("""{"retention":{"store_transcripts":true,"transcript_retention_days":7},"notifications":{"notify_on_high_risk":false,"include_transcript_lines":true}}"""),
    ).change()

    private fun show(state: PrivacyUiState, actions: PrivacyActions = PrivacyActions()) {
        compose.setContent { SpartaTheme { PrivacyContent(state, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    // ---- screening behaviour ----

    @Test
    fun `the current screening rules are selected and every choice is reported`() {
        var unknown: UnknownCallerBehavior? = null
        var trusted: TrustedContactBehavior? = null
        var strictness: Strictness? = null
        show(
            connected(),
            PrivacyActions(onUnknownBehavior = { unknown = it }, onTrustedBehavior = { trusted = it }, onStrictness = { strictness = it }),
        )
        node("unknown_SCREEN").assertIsSelected()
        node("trusted_ALLOW_DIRECTLY").assertIsSelected()
        node("strictness_BALANCED").assertIsSelected()
        node("unknown_SILENCE").performClick()
        node("trusted_SCREEN_ANYWAY").performClick()
        node("strictness_STRICT").performClick()
        assertEquals(UnknownCallerBehavior.SILENCE, unknown)
        assertEquals(TrustedContactBehavior.SCREEN_ANYWAY, trusted)
        assertEquals(Strictness.STRICT, strictness)
    }

    @Test
    fun `screening explains that sparta does not answer calls on this phone`() {
        show(connected())
        node("privacy_screening").assertTextContains("Sparta does not answer calls on this phone", substring = true)
    }

    @Test
    fun `without a backend the settings say they are stored on this phone only`() {
        show(PrivacyUiState())
        node("privacy_local_note").assertTextContains("only stored on this phone", substring = true)
    }

    // ---- contacts: explanation first, graceful refusal ----

    @Test
    fun `the contacts explanation is shown before the switch and switching on is reported`() {
        var toggled: Boolean? = null
        show(connected(), PrivacyActions(onContactsToggle = { toggled = it }))
        node("contacts_rationale").assertTextContains("does not read, copy or upload your contacts", substring = true)
        node("contacts_switch").assertIsOff().performClick()
        assertEquals(true, toggled)
    }

    @Test
    fun `a refused contacts permission is explained`() {
        show(connected { copy(contacts = PermissionUiState.DENIED_CAN_ASK_AGAIN) })
        node("contacts_denied").assertTextContains("option stays off", substring = true)
    }

    @Test
    fun `a permanently refused contacts permission disables the switch and opens app settings`() {
        var opened = 0
        show(connected { copy(contacts = PermissionUiState.DENIED_PERMANENTLY) }, PrivacyActions(onOpenAppSettings = { opened++ }))
        node("contacts_switch").assertIsNotEnabled()
        node("contacts_open_settings").performClick()
        assertEquals(1, opened)
    }

    @Test
    fun `a granted option shows as on`() {
        show(connected { copy(settings = settings.copy(useContactsAsKnown = true), contacts = PermissionUiState.GRANTED) })
        node("contacts_switch").assertIsOn()
    }

    // ---- lists ----

    @Test
    fun `blocked and trusted numbers are listed masked with where they came from and can be removed`() {
        val removed = mutableListOf<ListEntry>()
        val blocked = ListEntry("blocked", "aaaaaaaa11", "blk_1", "+91 98\u2022\u2022\u2022\u2022 \u2022\u202221", null, 1)
        val trusted = ListEntry("trusted", "bbbbbbbb22", null, "+91 70\u2022\u2022\u2022\u2022 \u2022\u202205", "Mum", 2)
        show(connected { copy(blocked = listOf(blocked), trusted = listOf(trusted)) }, PrivacyActions(onRemoveEntry = { removed += it }))
        node("privacy_lists").assertTextContains("Blocked (1)", substring = true)
        node("privacy_lists").assertTextContains("Trusted (1)", substring = true)
        node("blocked_entry_aaaaaaaa").assertTextContains("from your backend", substring = true)
        node("trusted_entry_bbbbbbbb").assertTextContains("Mum", substring = true)
        node("trusted_entry_bbbbbbbb").assertTextContains("added on this phone", substring = true)
        node("blocked_remove_aaaaaaaa").performClick()
        node("trusted_remove_bbbbbbbb").performClick()
        assertEquals(listOf(blocked, trusted), removed)
    }

    @Test
    fun `empty lists say none`() {
        show(connected())
        node("blocked_none").assertExists()
        node("trusted_none").assertExists()
    }

    // ---- notifications ----

    @Test
    fun `notification permission states are handled`() {
        var allowed = 0
        show(connected { copy(notifications = PermissionUiState.NOT_ASKED) }, PrivacyActions(onAllowNotifications = { allowed++ }))
        node("notifications_rationale").assertTextContains("tell you when a call needs your decision", substring = true)
        node("notifications_allow").performClick()
        assertEquals(1, allowed)
    }

    @Test
    fun `a permanently refused notification permission opens the settings and a granted one needs nothing`() {
        var opened = 0
        show(connected { copy(notifications = PermissionUiState.DENIED_PERMANENTLY) }, PrivacyActions(onOpenNotificationSettings = { opened++ }))
        node("notifications_allow").assertDoesNotExist()
        node("notifications_open_settings").performClick()
        assertEquals(1, opened)
    }

    @Test
    fun `a granted permission is confirmed`() {
        show(connected { copy(notifications = PermissionUiState.GRANTED) })
        node("notifications_granted").assertExists()
        node("notifications_allow").assertDoesNotExist()
    }

    @Test
    fun `local and backend notification switches report their values`() {
        var escalations: Boolean? = null
        var screening: Boolean? = null
        var highRisk: Boolean? = null
        var lines: Boolean? = null
        show(
            connected(),
            PrivacyActions(onNotifyEscalations = { escalations = it }, onNotifyScreening = { screening = it }, onNotifyHighRisk = { highRisk = it }, onIncludeLines = { lines = it }),
        )
        node("notify_escalations").assertIsOn().performClick()
        node("notify_screening").assertIsOn().performClick()
        node("notify_high_risk").assertIsOff().performClick()
        node("include_lines").assertIsOn().performClick()
        assertEquals(false, escalations)
        assertEquals(false, screening)
        assertEquals(true, highRisk)
        assertEquals(false, lines)
    }

    @Test
    fun `backend only notification settings are hidden without a backend`() {
        show(PrivacyUiState())
        node("notify_escalations").assertExists()
        node("notify_high_risk").assertDoesNotExist()
        node("quiet_hours").assertDoesNotExist()
    }

    @Test
    fun `quiet hours can be switched on and their bounds moved in half hour steps`() {
        val moves = mutableListOf<String>()
        val withQuiet = connected {
            copy(prefs = userPrefs("""{"notifications":{"quiet_hours_start":"22:00","quiet_hours_end":"07:00"}}"""))
        }
        show(
            withQuiet,
            PrivacyActions(onQuietStart = { moves += "start$it" }, onQuietEnd = { moves += "end$it" }),
        )
        node("quiet_hours").assertIsOn()
        node("quiet_start_value").assertTextContains("22:00")
        node("quiet_end_value").assertTextContains("07:00")
        node("quiet_start_later").performClick()
        node("quiet_end_earlier").performClick()
        assertEquals(listOf("start30", "end-30"), moves)
    }

    @Test
    fun `quiet hours off hides the steppers`() {
        var on: Boolean? = null
        show(connected(), PrivacyActions(onQuietHours = { on = it }))
        node("quiet_start_value").assertDoesNotExist()
        node("quiet_hours").performClick()
        assertEquals(true, on)
    }

    @Test
    fun `the notification card is honest that closed app alerts are periodic and not instant`() {
        show(connected())
        node("notifications_limit").assertTextContains("Instant push alerts are not set up", substring = true)
    }

    // ---- data ----

    @Test
    fun `the data card says there is no recording and lets the owner choose retention`() {
        var days = 0
        show(connected(), PrivacyActions(onRetentionDays = { days = it }))
        node("privacy_never_record").assertTextContains("no call recording at all", substring = true)
        node("retention_7").assertIsSelected()
        node("retention_30").performClick()
        assertEquals(30, days)
    }

    @Test
    fun `a retention value set elsewhere is shown as it is and not rounded`() {
        show(connected { copy(prefs = userPrefs("""{"retention":{"store_transcripts":true,"transcript_retention_days":14}}""")) })
        node("retention_14").assertIsSelected()
    }

    @Test
    fun `turning transcripts off hides the retention choice and full numbers are off by default`() {
        show(connected { copy(prefs = userPrefs("""{"retention":{"store_transcripts":false}}""")) })
        node("retention_7").assertDoesNotExist()
        node("store_number").assertIsOff()
    }

    @Test
    fun `deleting all data asks for confirmation and cancelling does nothing`() {
        var deleted = 0
        show(connected(), PrivacyActions(onDeleteAll = { deleted++ }))
        node("delete_all").performClick()
        node("privacy_confirm_dialog").assertTextContains("cannot be undone", substring = true)
        node("privacy_confirm_cancel").performClick()
        assertEquals(0, deleted)
        node("delete_all").performClick()
        node("privacy_confirm").performClick()
        assertEquals(1, deleted)
    }

    @Test
    fun `deleting only the history on this phone is a separate confirmed action`() {
        var local = 0
        var all = 0
        show(connected(), PrivacyActions(onDeleteLocal = { local++ }, onDeleteAll = { all++ }))
        node("delete_local").performClick()
        node("privacy_confirm").performClick()
        assertEquals(1, local)
        assertEquals(0, all)
    }

    // ---- appearance ----

    @Test
    fun `theme motion and background sync choices are reported`() {
        var theme: ThemeMode? = null
        var motion: MotionPreference? = null
        var sync: Boolean? = null
        show(connected(), PrivacyActions(onTheme = { theme = it }, onMotion = { motion = it }, onBackgroundSync = { sync = it }))
        node("theme_DARK").assertIsSelected()
        node("motion_FOLLOW_SYSTEM").assertIsSelected()
        node("theme_LIGHT").performClick()
        node("motion_REDUCE").performClick()
        node("background_sync").assertIsOn().performClick()
        assertEquals(ThemeMode.LIGHT, theme)
        assertEquals(MotionPreference.REDUCE, motion)
        assertEquals(false, sync)
    }

    @Test
    fun `background sync explains it uses no service and no wake lock`() {
        show(connected())
        node("background_sync").assertTextContains("No foreground service and no wake lock", substring = true)
    }

    // ---- backend ----

    @Test
    fun `no backend is said plainly and testing needs an address`() {
        show(PrivacyUiState(urlInput = ""))
        node("backend_none").assertExists()
        node("backend_test").assertIsNotEnabled()
        node("backend_use").assertIsNotEnabled()
        node("backend_disconnect").assertDoesNotExist()
    }

    @Test
    fun `a tested backend can be used and results are explained`() {
        var tested = 0
        var used = 0
        show(
            PrivacyUiState(
                urlInput = "https://sparta.example.com/",
                connection = ConnectionUi.Success("https://sparta.example.com/", "0.1.0", "azure", simulated = false, devBanner = false, forwardingNumber = "+918012345678"),
            ),
            PrivacyActions(onTestConnection = { tested++ }, onUseBackend = { used++ }),
        )
        node("backend_result_success").assertTextContains("Backend version 0.1.0", substring = true)
        node("backend_test").assertIsEnabled().performClick()
        node("backend_use").assertIsEnabled().performClick()
        assertEquals(1, tested)
        assertEquals(1, used)
    }

    @Test
    fun `an insecure address and an unreachable server are explained`() {
        show(PrivacyUiState(urlInput = "http://example.com", connection = ConnectionUi.InvalidUrl(BackendUrlProblem.HTTPS_REQUIRED)))
        node("backend_result_invalid").assertTextContains("only connects over HTTPS", substring = true)
    }

    @Test
    fun `a failed test shows the backend problem`() {
        show(PrivacyUiState(urlInput = "https://x", connection = ConnectionUi.Failure(ApiError(ApiErrorKind.TIMEOUT, "The backend did not answer in time."))))
        node("backend_result_failure").assertTextContains("did not answer in time", substring = true)
    }

    @Test
    fun `disconnecting asks first`() {
        var disconnected = 0
        show(connected(), PrivacyActions(onDisconnect = { disconnected++ }))
        node("backend_address").assertTextContains("https://sparta.example.com/", substring = true)
        node("backend_disconnect").performClick()
        node("privacy_confirm_dialog").assertTextContains("Sparta forgets the address", substring = true)
        node("privacy_confirm").performClick()
        assertEquals(1, disconnected)
    }

    // ---- safety, permissions, messages ----

    @Test
    fun `the safety policy lists what callers can never extract`() {
        show(connected { copy(policy = SafetyPolicyDto("default-v1", "Default", listOf(ProtectedInfoDto("OTP", "One-time passwords"), ProtectedInfoDto("CVV", "Card security codes")), "balanced")) })
        node("privacy_safety").assertTextContains("One-time passwords", substring = true)
        node("privacy_safety").assertTextContains("Policy version default-v1", substring = true)
    }

    @Test
    fun `without the policy the card asks for a backend instead of inventing a list`() {
        show(PrivacyUiState())
        node("safety_needs_backend").assertExists()
    }

    @Test
    fun `every permission is documented with its reason and the never list is explicit`() {
        show(PrivacyUiState())
        node("privacy_permissions").assertTextContains("Call-screening role", substring = true)
        node("privacy_permissions").assertTextContains("Notifications (optional)", substring = true)
        node("privacy_permissions").assertTextContains("Contacts (optional, off by default)", substring = true)
        node("privacy_permissions").assertTextContains("Internet", substring = true)
        node("permissions_never").assertTextContains("never asks for the microphone", substring = true)
    }

    @Test
    fun `saving and failure messages are shown`() {
        show(connected { copy(message = UiMessage.Text(R.string.privacy_saved_local)) })
        node("message_banner").assertTextContains("Saved on this phone", substring = true)
    }
}
