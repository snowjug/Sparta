package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.testing.performClick
import io.github.snowjug.sparta.ui.status.BackendReachability
import io.github.snowjug.sparta.ui.status.ProtectionActions
import io.github.snowjug.sparta.ui.status.ProtectionContent
import io.github.snowjug.sparta.ui.status.ProtectionUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProtectionContentTest {

    @get:Rule
    val compose = createComposeRule()

    private val device = DeviceInfo(35, "15", "Google", "Pixel", "2026-10-05", "0.1.0", 1, false)

    private fun show(state: ProtectionUiState, actions: ProtectionActions = ProtectionActions()) {
        compose.setContent { SpartaTheme { ProtectionContent(state = state, actions = actions) } }
    }

    private fun tag(tag: String) = compose.onNodeWithTag(tag)

    @Test
    fun screeningOnShowsPositiveStateAndNoEnableButton() {
        show(ProtectionUiState(role = RoleState(RoleStatus.GRANTED), device = device))
        tag("role_state_granted").assertIsDisplayed()
        tag("role_headline").assertTextContains("Screening is on")
        tag("enable_screening").assertDoesNotExist()
    }

    @Test
    fun screeningOffOffersTheSystemRoleRequest() {
        var clicked = 0
        show(
            ProtectionUiState(role = RoleState(RoleStatus.NOT_GRANTED), device = device),
            ProtectionActions(onEnableScreening = { clicked++ }),
        )
        tag("role_headline").assertTextContains("Screening is off")
        tag("enable_screening").performScrollTo().assertIsEnabled().performClick()
        assertEquals(1, clicked)
    }

    @Test
    fun aDeclinedRoleRequestExplainsAndOffersAnotherPath() {
        var openedSettings = 0
        show(
            ProtectionUiState(role = RoleState(RoleStatus.NOT_GRANTED, requestDeclined = true), device = device),
            ProtectionActions(onOpenDefaultApps = { openedSettings++ }),
        )
        tag("role_declined_note").assertExists()
        tag("enable_screening").assertTextContains("Try again")
        tag("open_default_apps").performScrollTo().performClick()
        assertEquals(1, openedSettings)
    }

    @Test
    fun androidNineAndOlderIsExplainedNotBroken() {
        show(ProtectionUiState(role = RoleState(RoleStatus.UNSUPPORTED_API), device = device.copy(apiLevel = 28, androidRelease = "9")))
        tag("role_state_unsupported").assertExists()
        tag("unsupported_explanation").assertTextContains("Android 9", substring = true)
        tag("unsupported_explanation").assertTextContains("API 28", substring = true)
        tag("enable_screening").assertDoesNotExist()
    }

    @Test
    fun aPhoneWithoutTheRoleIsExplained() {
        show(ProtectionUiState(role = RoleState(RoleStatus.ROLE_UNAVAILABLE), device = device))
        tag("role_state_unavailable").assertExists()
        tag("unavailable_explanation").assertExists()
        tag("enable_screening").assertDoesNotExist()
    }

    @Test
    fun notificationsCardAppearsOnlyWhenNotificationsCannotBeShown() {
        show(ProtectionUiState(role = RoleState(RoleStatus.GRANTED), notifications = PermissionUiState.GRANTED))
        tag("notifications_card").assertDoesNotExist()
    }

    @Test
    fun notificationsNeverAskedOffersAnExplainedPrompt() {
        var allowed = 0
        show(
            ProtectionUiState(notifications = PermissionUiState.NOT_ASKED),
            ProtectionActions(onAllowNotifications = { allowed++ }),
        )
        tag("notifications_card").assertExists()
        tag("allow_notifications").performScrollTo().performClick()
        assertEquals(1, allowed)
    }

    @Test
    fun permanentlyDeniedNotificationsPointToSystemSettings() {
        var opened = 0
        show(
            ProtectionUiState(notifications = PermissionUiState.DENIED_PERMANENTLY),
            ProtectionActions(onOpenNotificationSettings = { opened++ }),
        )
        tag("allow_notifications").assertDoesNotExist()
        tag("notification_settings").performScrollTo().performClick()
        assertEquals(1, opened)
    }

    @Test
    fun callsThatNeedTheOwnerAreCountedAndLinked() {
        var reviewed = 0
        show(ProtectionUiState(attentionCount = 2), ProtectionActions(onReviewCalls = { reviewed++ }))
        tag("attention_card").assertTextContains("2 calls are waiting for your decision", substring = true)
        tag("review_calls").performScrollTo().performClick()
        assertEquals(1, reviewed)
    }

    @Test
    fun oneCallThatNeedsTheOwnerIsSaidInTheSingular() {
        show(ProtectionUiState(attentionCount = 1))
        tag("attention_card").assertTextContains("1 call is waiting for your decision", substring = true)
    }

    @Test
    fun noBackendIsSaidPlainlyAndHasNoRefresh() {
        show(ProtectionUiState(backendConfigured = false, backend = BackendReachability.NotConfigured))
        tag("backend_not_configured").assertExists()
        tag("refresh_status").assertDoesNotExist()
        tag("forwarding_unavailable").assertExists()
    }

    @Test
    fun aSimulatedBackendIsLabelledSimulatedAndNeverImpliesLiveCalls() {
        show(
            ProtectionUiState(
                backendConfigured = true,
                backend = BackendReachability.Reachable(Samples.NOW),
                status = Samples.status(simulated = true, liveCalls = false),
            ),
        )
        tag("backend_reachable").assertExists()
        tag("provider_row").assertTextContains("simulator (simulated)", substring = true)
        tag("simulated_label").assertExists()
        tag("live_calls_note").assertTextContains("no live telephony", substring = true)
    }

    @Test
    fun aRealProviderIsNotLabelledSimulated() {
        show(
            ProtectionUiState(
                backendConfigured = true,
                backend = BackendReachability.Reachable(Samples.NOW),
                status = Samples.status(simulated = false, liveCalls = true, provider = "azure", devBanner = false),
            ),
        )
        tag("simulated_label").assertDoesNotExist()
        tag("live_calls_note").assertTextContains("can take forwarded calls", substring = true)
    }

    @Test
    fun anUnreachableBackendKeepsTheLastKnownStatusVisible() {
        show(
            ProtectionUiState(
                backendConfigured = true,
                backend = BackendReachability.Unreachable(ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached."), hasCachedStatus = true),
                status = Samples.status(),
            ),
        )
        tag("backend_unreachable").assertTextContains("Showing the last known status", substring = true)
        tag("provider_row").assertExists()
    }

    @Test
    fun forwardingIsOfferedOnlyForAPlainNumberAndNeverClaimedActive() {
        var opened = 0
        show(
            ProtectionUiState(backendConfigured = true, forwardingNumber = "+918012345678"),
            ProtectionActions(onOpenForwardingHelper = { opened++ }),
        )
        tag("forwarding_status_text").assertTextContains("cannot tell whether it is on", substring = true)
        tag("open_forwarding_helper").performScrollTo().performClick()
        assertEquals(1, opened)
    }

    @Test
    fun theOwnerCanNoteThatForwardingIsSetUpAndItIsLabelledAsTheirWordOnly() {
        val confirmed = mutableListOf<Boolean>()
        show(
            ProtectionUiState(backendConfigured = true, forwardingNumber = "+918012345678", forwardingConfirmed = true),
            ProtectionActions(onConfirmForwarding = { confirmed += it }),
        )
        tag("forwarding_status_text").assertTextContains("not verified by the app", substring = true)
        tag("forwarding_confirm").performScrollTo().performClick()
        assertEquals(listOf(false), confirmed)
    }

    @Test
    fun aForwardingNumberWithDialerCodesIsNotOfferedToTheDialer() {
        show(ProtectionUiState(backendConfigured = true, forwardingNumber = "*21*+918012345678#"))
        tag("open_forwarding_helper").assertDoesNotExist()
    }

    @Test
    fun theLastDecisionIsShownWithItsReason() {
        show(ProtectionUiState(lastDecision = Samples.event(decision = "reject", reason = "blocked_number", latencyMs = 12), pendingUploads = 3))
        tag("last_decision_text").assertTextContains("Rejected", substring = true)
        tag("last_decision_text").assertTextContains("On your block list", substring = true)
        tag("last_decision_card").assertTextContains("3 screening events are waiting to sync", substring = true)
    }

    @Test
    fun noDecisionYetIsSaid() {
        show(ProtectionUiState())
        tag("last_decision_none").assertExists()
    }

    @Test
    fun theLimitsCardNeverClaimsTheAppCanAnswerCalls() {
        show(ProtectionUiState())
        tag("limits_card").assertTextContains("Answer a phone call on this phone", substring = true)
        tag("limits_card").assertTextContains("Sparta never records calls", substring = true)
    }
}
