package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.net.BackendUrlProblem
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.onboarding.ConnectionUi
import io.github.snowjug.sparta.ui.onboarding.OnboardingActions
import io.github.snowjug.sparta.ui.onboarding.OnboardingContent
import io.github.snowjug.sparta.ui.onboarding.OnboardingStep
import io.github.snowjug.sparta.ui.onboarding.OnboardingUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OnboardingContentTest {

    @get:Rule
    val compose = createComposeRule()

    private val device = DeviceInfo(35, "15", "Google", "Pixel", null, "0.1.0", 1, false)

    private fun show(state: OnboardingUiState, actions: OnboardingActions = OnboardingActions(), debug: Boolean = false) {
        compose.setContent { SpartaTheme { OnboardingContent(state, actions, isDebugBuild = debug) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    @Test
    fun `the first step says what Sparta is and is not and has no back button`() {
        show(OnboardingUiState(step = OnboardingStep.WELCOME))
        node("onboarding_step_label").assertTextContains("Step 1 of 5")
        node("onboarding_step_welcome").assertTextContains("Your calls. Your voice. Your shield.")
        node("onboarding_step_welcome").assertTextContains("it always says it is an AI assistant", substring = true)
        node("onboarding_limits").assertTextContains("cannot answer an ordinary phone call", substring = true)
        node("onboarding_back").assertDoesNotExist()
    }

    @Test
    fun `next and back move through the steps`() {
        var next = 0
        var back = 0
        show(OnboardingUiState(step = OnboardingStep.ROLE), OnboardingActions(onNext = { next++ }, onBack = { back++ }))
        node("onboarding_next").performClick()
        node("onboarding_back").performClick()
        assertEquals(1, next)
        assertEquals(1, back)
    }

    @Test
    fun `the last step finishes setup and cannot be pressed twice`() {
        var finished = 0
        show(OnboardingUiState(step = OnboardingStep.FORWARDING), OnboardingActions(onFinish = { finished++ }))
        node("onboarding_next").assertDoesNotExist()
        node("onboarding_finish").assertIsEnabled().performClick()
        assertEquals(1, finished)
    }

    @Test
    fun `finishing in progress disables the button`() {
        show(OnboardingUiState(step = OnboardingStep.FORWARDING, finishing = true))
        node("onboarding_finish").assertIsNotEnabled()
    }

    // ---- backend ----

    @Test
    fun `testing needs an address and the use button needs a successful test`() {
        show(OnboardingUiState(step = OnboardingStep.BACKEND, urlInput = ""))
        node("onboarding_test_connection").assertIsNotEnabled()
        node("onboarding_use_backend").assertIsNotEnabled()
    }

    @Test
    fun `typing an address and testing calls back`() {
        var typed = ""
        var tested = 0
        show(
            OnboardingUiState(step = OnboardingStep.BACKEND, urlInput = "https://x"),
            OnboardingActions(onUrlChange = { typed = it }, onTestConnection = { tested++ }),
        )
        node("onboarding_backend_url").performTextInput("y")
        assertTrue(typed.contains("y"))
        node("onboarding_test_connection").assertIsEnabled().performClick()
        assertEquals(1, tested)
    }

    @Test
    fun `a reachable simulator is reported as a simulator with the development identity warning`() {
        var used = 0
        show(
            OnboardingUiState(
                step = OnboardingStep.BACKEND,
                urlInput = "http://10.0.2.2:8000/",
                connection = ConnectionUi.Success("http://10.0.2.2:8000/", "0.1.0", "simulator", simulated = true, devBanner = true, forwardingNumber = null),
            ),
            OnboardingActions(onUseBackend = { used++ }),
        )
        node("backend_result_success").assertTextContains("Backend version 0.1.0", substring = true)
        node("backend_result_simulated").assertTextContains("no real phone calls reach it", substring = true)
        node("backend_result_dev").assertTextContains("Development identity")
        node("onboarding_use_backend").assertIsEnabled().performClick()
        assertEquals(1, used)
        node("onboarding_next").assertTextContains("Skip for now")
    }

    @Test
    fun `a saved backend shows confirmation and the next button no longer says skip`() {
        show(OnboardingUiState(step = OnboardingStep.BACKEND, backendSaved = true))
        node("onboarding_backend_saved").assertExists()
        node("onboarding_use_backend").assertDoesNotExist()
        node("onboarding_next").assertTextContains("Next")
    }

    @Test
    fun `failures and invalid addresses are explained`() {
        show(OnboardingUiState(step = OnboardingStep.BACKEND, connection = ConnectionUi.Failure(ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached."))))
        node("backend_result_failure").assertTextContains("could not be reached", substring = true)
    }

    @Test
    fun `an http address in a release build is refused with the reason`() {
        show(OnboardingUiState(step = OnboardingStep.BACKEND, connection = ConnectionUi.InvalidUrl(BackendUrlProblem.HTTPS_REQUIRED)), debug = false)
        node("backend_result_invalid").assertTextContains("only connects over HTTPS", substring = true)
        node("onboarding_url_hint").assertTextContains("Release builds only connect over HTTPS", substring = true)
    }

    @Test
    fun `a debug build says which http addresses are allowed`() {
        show(OnboardingUiState(step = OnboardingStep.BACKEND), debug = true)
        node("onboarding_url_hint").assertTextContains("10.0.2.2", substring = true)
    }

    // ---- role ----

    @Test
    fun `choosing the screening role is explained first and then launches the system dialog`() {
        var chosen = 0
        show(OnboardingUiState(step = OnboardingStep.ROLE, role = RoleState(RoleStatus.NOT_GRANTED)), OnboardingActions(onChooseRole = { chosen++ }))
        node("onboarding_step_role").assertTextContains("cannot answer the call or hear what is said", substring = true)
        node("onboarding_choose_role").performClick()
        assertEquals(1, chosen)
    }

    @Test
    fun `declining the role leaves a way forward`() {
        show(OnboardingUiState(step = OnboardingStep.ROLE, role = RoleState(RoleStatus.NOT_GRANTED, requestDeclined = true)))
        node("onboarding_role_declined").assertTextContains("continue without screening", substring = true)
        node("onboarding_next").assertIsEnabled()
    }

    @Test
    fun `a held role is confirmed`() {
        show(OnboardingUiState(step = OnboardingStep.ROLE, role = RoleState(RoleStatus.GRANTED)))
        node("onboarding_role_done").assertExists()
        node("onboarding_choose_role").assertDoesNotExist()
    }

    @Test
    fun `an old android version and a phone without the role are explained and can continue`() {
        show(OnboardingUiState(step = OnboardingStep.ROLE, role = RoleState(RoleStatus.UNSUPPORTED_API), device = device.copy(apiLevel = 28, androidRelease = "9")))
        node("onboarding_role_unsupported").assertTextContains("Android 10 or newer", substring = true)
        node("onboarding_choose_role").assertDoesNotExist()
        node("onboarding_next").assertIsEnabled()
    }

    @Test
    fun `a phone whose maker removed the role is explained`() {
        show(OnboardingUiState(step = OnboardingStep.ROLE, role = RoleState(RoleStatus.ROLE_UNAVAILABLE)))
        node("onboarding_role_unavailable").assertExists()
    }

    // ---- permissions: the explanation is on screen before any system prompt ----

    @Test
    fun `both permission explanations are visible before anything is requested`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, notifications = PermissionUiState.NOT_ASKED, contacts = PermissionUiState.NOT_ASKED))
        node("onboarding_notifications_card").assertTextContains("tell you when a call needs your decision", substring = true)
        node("onboarding_contacts_rationale").assertTextContains("does not read, copy or upload your contacts", substring = true)
        node("onboarding_allow_notifications").assertExists()
    }

    @Test
    fun `the notification prompt is started only by the button`() {
        var asked = 0
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS), OnboardingActions(onAllowNotifications = { asked++ }))
        assertEquals("no prompt without a press", 0, asked)
        node("onboarding_allow_notifications").performClick()
        assertEquals(1, asked)
    }

    @Test
    fun `a refused notification permission can be retried and says what is lost`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, notifications = PermissionUiState.DENIED_CAN_ASK_AGAIN))
        node("onboarding_notifications_denied").assertTextContains("Notifications are off", substring = true)
        node("onboarding_allow_notifications").assertExists()
    }

    @Test
    fun `a permanently refused notification permission points to the system settings`() {
        var settings = 0
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, notifications = PermissionUiState.DENIED_PERMANENTLY), OnboardingActions(onOpenNotificationSettings = { settings++ }))
        node("onboarding_allow_notifications").assertDoesNotExist()
        node("onboarding_notification_settings").performClick()
        assertEquals(1, settings)
    }

    @Test
    fun `granted and not required notification states need no button`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, notifications = PermissionUiState.GRANTED))
        node("onboarding_notifications_granted").assertExists()
        node("onboarding_allow_notifications").assertDoesNotExist()
    }

    @Test
    fun `older android needs no notification permission`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, notifications = PermissionUiState.NOT_REQUIRED))
        node("onboarding_notifications_not_required").assertExists()
    }

    @Test
    fun `the contacts option is off by default and switching it on asks for the permission`() {
        var toggled: Boolean? = null
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, useContactsAsKnown = false), OnboardingActions(onContactsToggle = { toggled = it }))
        node("onboarding_contacts_switch").performClick()
        assertEquals(true, toggled)
    }

    @Test
    fun `a refused contacts permission keeps the option off and says so`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, contacts = PermissionUiState.DENIED_CAN_ASK_AGAIN, useContactsAsKnown = false))
        node("onboarding_contacts_denied").assertTextContains("option stays off", substring = true)
        node("onboarding_contacts_switch").assertIsEnabled()
    }

    @Test
    fun `a permanently refused contacts permission disables the switch and offers settings`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, contacts = PermissionUiState.DENIED_PERMANENTLY))
        node("onboarding_contacts_switch").assertIsNotEnabled()
        node("onboarding_contacts_settings").assertExists()
    }

    @Test
    fun `a granted contacts option shows as on`() {
        show(OnboardingUiState(step = OnboardingStep.PERMISSIONS, contacts = PermissionUiState.GRANTED, useContactsAsKnown = true))
        node("onboarding_contacts_switch").assertIsOn()
        node("onboarding_contacts_granted").assertExists()
    }

    // ---- forwarding ----

    @Test
    fun `without a forwarding number live ai audio is said to be unavailable`() {
        show(OnboardingUiState(step = OnboardingStep.FORWARDING, forwardingNumber = null))
        node("onboarding_forwarding_unavailable").assertTextContains("live AI audio on real calls is not available", substring = true)
        node("onboarding_forwarding_helper").assertDoesNotExist()
    }

    @Test
    fun `with a forwarding number the helper opens the dialer flow and claims nothing`() {
        var opened = 0
        show(OnboardingUiState(step = OnboardingStep.FORWARDING, forwardingNumber = "+918012345678"), OnboardingActions(onOpenForwarding = { opened++ }))
        node("onboarding_forwarding_number").assertTextContains("+918012345678", substring = true)
        node("onboarding_forwarding_helper").performClick()
        assertEquals(1, opened)
        node("onboarding_step_forwarding").assertTextContains("Screening on this phone works without it", substring = true)
    }
}
