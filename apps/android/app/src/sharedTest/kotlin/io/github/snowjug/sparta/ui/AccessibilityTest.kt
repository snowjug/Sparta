package io.github.snowjug.sparta.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.isHeading
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.repo.RecentItem
import io.github.snowjug.sparta.data.repo.UserPreferences
import io.github.snowjug.sparta.core.live.LiveCallState
import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.data.repo.CallFilter
import io.github.snowjug.sparta.data.repo.LiveConnection
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.ui.calls.CallsContent
import io.github.snowjug.sparta.ui.calls.CallsActions
import io.github.snowjug.sparta.ui.calls.CallsUiState
import io.github.snowjug.sparta.ui.detail.CallDetailActions
import io.github.snowjug.sparta.ui.detail.CallDetailContent
import io.github.snowjug.sparta.ui.detail.CallDetailUiState
import io.github.snowjug.sparta.ui.detail.ScreeningEventActions
import io.github.snowjug.sparta.ui.detail.ScreeningEventContent
import io.github.snowjug.sparta.ui.detail.ScreeningEventUiState
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsActions
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsContent
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsUiState
import io.github.snowjug.sparta.ui.incoming.IncomingContent
import io.github.snowjug.sparta.ui.live.LiveCallActions
import io.github.snowjug.sparta.ui.live.LiveCallContent
import io.github.snowjug.sparta.ui.live.LiveCallUiState
import io.github.snowjug.sparta.ui.onboarding.OnboardingActions
import io.github.snowjug.sparta.ui.onboarding.OnboardingContent
import io.github.snowjug.sparta.ui.onboarding.OnboardingStep
import io.github.snowjug.sparta.ui.onboarding.OnboardingUiState
import io.github.snowjug.sparta.ui.privacy.PrivacyActions
import io.github.snowjug.sparta.ui.privacy.PrivacyContent
import io.github.snowjug.sparta.ui.privacy.PrivacyUiState
import io.github.snowjug.sparta.ui.status.BackendReachability
import io.github.snowjug.sparta.ui.status.ProtectionActions
import io.github.snowjug.sparta.ui.status.ProtectionContent
import io.github.snowjug.sparta.ui.status.ProtectionUiState
import io.github.snowjug.sparta.ui.studio.DEFAULT_LANGUAGES
import io.github.snowjug.sparta.ui.studio.StudioActions
import io.github.snowjug.sparta.ui.studio.StudioContent
import io.github.snowjug.sparta.ui.studio.StudioDraft
import io.github.snowjug.sparta.ui.studio.StudioUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Generic accessibility rules applied to every screen: each interactive element has an accessible name and a touch
 * target of at least 48 dp, and each screen has headings for screen-reader navigation.
 */
@RunWith(AndroidJUnit4::class)
class AccessibilityTest {

    @get:Rule
    val compose = createComposeRule()

    private fun assertAccessible(screen: String, requireHeading: Boolean = true) {
        compose.waitForIdle()
        val count = compose.onAllNodes(hasClickAction()).fetchSemanticsNodes().size
        assertTrue("$screen: expected interactive elements", count > 0)
        val minPx = 48 * compose.density.density - 1f
        for (index in 0 until count) {
            // Long screens scroll: bring each element into view, because off-screen nodes report empty bounds.
            val interaction = compose.onAllNodes(hasClickAction())[index]
            runCatching { interaction.performScrollTo() }
            val node = interaction.fetchSemanticsNode()
            val config = node.config
            val isTextField = config.contains(SemanticsActions.SetText)
            val labelled = !config.getOrNull(SemanticsProperties.Text).isNullOrEmpty() ||
                !config.getOrNull(SemanticsProperties.ContentDescription).isNullOrEmpty() ||
                isTextField
            assertTrue("$screen: interactive element #$index has no accessible name: $config", labelled)
            val bounds = node.touchBoundsInRoot
            assertTrue(
                "$screen: element #$index (${config.getOrNull(SemanticsProperties.Text)}) touch target ${bounds.width}x${bounds.height}px is below 48dp",
                bounds.width >= minPx && bounds.height >= minPx,
            )
        }
        if (requireHeading) {
            assertTrue("$screen: no headings for screen-reader navigation", compose.onAllNodes(isHeading()).fetchSemanticsNodes().isNotEmpty())
        }
    }

    private val device = io.github.snowjug.sparta.platform.DeviceInfo(35, "15", "Google", "Pixel", null, "0.1.0", 1, false)

    @Test
    fun protection() {
        compose.setContent {
            SpartaTheme {
                ProtectionContent(
                    ProtectionUiState(
                        role = RoleState(RoleStatus.NOT_GRANTED, requestDeclined = true),
                        device = device,
                        backendConfigured = true,
                        backend = BackendReachability.Reachable(Samples.NOW),
                        status = Samples.status(forwardingNumber = "+918012345678"),
                        forwardingNumber = "+918012345678",
                        lastDecision = Samples.event(),
                        attentionCount = 2,
                        notifications = PermissionUiState.DENIED_PERMANENTLY,
                    ),
                    actions = ProtectionActions(),
                )
            }
        }
        assertAccessible("Protection")
    }

    @Test
    fun onboardingEveryStep() {
        var step by mutableStateOf(OnboardingStep.WELCOME)
        compose.setContent {
            SpartaTheme {
                OnboardingContent(
                    OnboardingUiState(step = step, urlInput = "https://x", forwardingNumber = "+918012345678", role = RoleState(RoleStatus.NOT_GRANTED)),
                    OnboardingActions(),
                )
            }
        }
        OnboardingStep.entries.forEach {
            compose.runOnIdle { step = it }
            assertAccessible("Onboarding ${it.name}")
        }
    }

    @Test
    fun calls() {
        compose.setContent {
            SpartaTheme {
                CallsContent(
                    CallsUiState(
                        filter = CallFilter(risk = RiskLevel.HIGH),
                        items = listOf(
                            RecentItem.Backend(Samples.callItem(attention = true, status = CallStatus.ACTIVE), Samples.NOW),
                            RecentItem.Local(Samples.event()),
                        ),
                        nowMs = Samples.NOW,
                        backendConfigured = true,
                        initialLoading = false,
                        hasMore = true,
                    ),
                    WidthClass.COMPACT,
                    CallsActions(),
                )
            }
        }
        assertAccessible("Recent calls")
    }

    @Test
    fun callDetail() {
        val call = Samples.callDetail(
            item = Samples.callItem(status = CallStatus.ACTIVE, attention = true),
            capabilities = Samples.capabilities(takeOver = true, cont = true, end = true),
        )
        compose.setContent {
            SpartaTheme { CallDetailContent(CallDetailUiState(callId = call.id, loading = false, call = call, nowMs = Samples.NOW), CallDetailActions(onBack = {})) }
        }
        assertAccessible("Call detail")
    }

    @Test
    fun incoming() {
        val call = Samples.callDetail(
            item = Samples.callItem(status = CallStatus.ACTIVE, attention = true),
            capabilities = Samples.capabilities(takeOver = true, cont = true, end = true),
            escalations = listOf(Samples.escalation()),
        )
        compose.setContent {
            SpartaTheme { IncomingContent(CallDetailUiState(callId = call.id, loading = false, call = call, nowMs = Samples.NOW), CallDetailActions(onBack = {}), onOpenDetails = {}) }
        }
        assertAccessible("Incoming call intelligence")
    }

    @Test
    fun liveCall() {
        val call = Samples.callDetail(
            item = Samples.callItem(status = CallStatus.ACTIVE, attention = true),
            capabilities = Samples.capabilities(takeOver = true, cont = true, end = true),
        )
        compose.setContent {
            SpartaTheme {
                LiveCallContent(
                    LiveCallUiState(callId = "call_1", connection = LiveConnection.CONNECTED, live = LiveCallState("call_1", phase = VoicePhase.LISTENING, call = call)),
                    WidthClass.COMPACT,
                    LiveCallActions(),
                )
            }
        }
        assertAccessible("Live call")
    }

    @Test
    fun studio() {
        val draft = StudioDraft(ownerName = "Atharv")
        compose.setContent {
            SpartaTheme {
                StudioContent(
                    StudioUiState(backendConfigured = true, loading = false, saved = draft, draft = draft.copy(ownerName = "Atharv S"), languages = DEFAULT_LANGUAGES),
                    StudioActions(),
                )
            }
        }
        assertAccessible("Assistant Studio")
    }

    @Test
    fun privacy() {
        compose.setContent {
            SpartaTheme {
                PrivacyContent(
                    PrivacyUiState(
                        settings = AppSettings(backendUrl = "https://sparta.example.com/"),
                        prefs = UserPreferences(Json.parseToJsonElement("""{"notifications":{"quiet_hours_start":"22:00","quiet_hours_end":"07:00"}}""").jsonObject),
                        blocked = listOf(io.github.snowjug.sparta.data.repo.ListEntry("blocked", "aaaaaaaa", null, Samples.MASKED, null, 1)),
                    ),
                    PrivacyActions(),
                )
            }
        }
        assertAccessible("Privacy and safety")
    }

    @Test
    fun diagnostics() {
        compose.setContent {
            SpartaTheme {
                DiagnosticsContent(
                    DiagnosticsUiState(device = device, settings = AppSettings(backendUrl = "https://sparta.example.com/"), status = Samples.status(), recent = listOf(Samples.event()), nowMs = Samples.NOW, reportText = "report"),
                    DiagnosticsActions(),
                )
            }
        }
        assertAccessible("Diagnostics")
    }

    @Test
    fun screeningEvent() {
        compose.setContent {
            SpartaTheme { ScreeningEventContent(ScreeningEventUiState(eventId = "evt_1", loading = false, event = Samples.event(), nowMs = Samples.NOW), ScreeningEventActions()) }
        }
        assertAccessible("Decision on this phone")
    }

    @Test
    fun theLightThemeMeetsTheSameRules() {
        compose.setContent {
            SpartaTheme(themeMode = io.github.snowjug.sparta.data.prefs.ThemeMode.LIGHT) {
                ProtectionContent(ProtectionUiState(role = RoleState(RoleStatus.GRANTED), device = device), actions = ProtectionActions())
            }
        }
        compose.waitForIdle()
        assertTrue(compose.onAllNodes(isHeading()).fetchSemanticsNodes().isNotEmpty())
    }
}
