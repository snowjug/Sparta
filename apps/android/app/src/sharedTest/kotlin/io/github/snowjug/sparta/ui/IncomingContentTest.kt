package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.detail.CallDetailActions
import io.github.snowjug.sparta.ui.detail.CallDetailUiState
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.IncomingContent
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class IncomingContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun show(state: CallDetailUiState, actions: CallDetailActions = CallDetailActions(), onDetails: (String) -> Unit = {}) {
        compose.setContent { SpartaTheme { IncomingContent(state, actions, onDetails) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    private val escalated = Samples.callDetail(
        item = Samples.callItem(status = CallStatus.ACTIVE, attention = true, category = CallCategory.LEGITIMATE_DELIVERY),
        risk = Samples.riskAssessment(RiskLevel.LOW, signals = listOf(Samples.signal("LEGIT_DELIVERY", io.github.snowjug.sparta.data.remote.dto.SignalKind.LEGITIMATE, io.github.snowjug.sparta.data.remote.dto.SignalSeverity.INFO, "Delivery coordination language", "parcel ke liye address confirm"))),
        capabilities = Samples.capabilities(takeOver = true, cont = true, end = true, takeoverNote = "Takeover is simulated."),
        escalations = listOf(Samples.escalation()),
    )

    private fun loaded(call: io.github.snowjug.sparta.data.remote.dto.CallDetailDto = escalated) =
        CallDetailUiState(callId = call.id, loading = false, call = call, nowMs = Samples.NOW)

    @Test
    fun `a call that needs the owner says so first and shows who is calling and why`() {
        show(loaded())
        node("incoming_needs_you").assertTextContains("Sparta needs your decision")
        node("incoming_caller").assertTextContains(Samples.MASKED, substring = true)
        node("incoming_caller").assertTextContains("Says they are Ravi, Swift Courier", substring = true)
        node("incoming_caller").assertTextContains("About: Parcel delivery", substring = true)
        node("incoming_evidence").assertTextContains("Delivery coordination language", substring = true)
        node("incoming_evidence").assertTextContains("Sparta's advice: Needs your decision", substring = true)
    }

    @Test
    fun `what the caller said is shown as quoted lines`() {
        show(loaded())
        node("incoming_line").assertTextContains("Parcel ke liye address confirm karna hai", substring = true)
    }

    @Test
    fun `the controls match the providers capabilities and the simulation is labelled`() {
        val clicked = mutableListOf<ControlId>()
        show(loaded(), CallDetailActions(onControl = { clicked += it }))
        node("control_take_over").assertTextContains("Take over (simulation)").assertIsEnabled().performClick()
        node("control_continue").assertIsEnabled().performClick()
        node("control_end").assertIsEnabled().performClick()
        assertEquals(listOf(ControlId.TAKE_OVER, ControlId.CONTINUE, ControlId.END), clicked)
    }

    @Test
    fun `a provider that cannot take over gets a disabled control with the reason`() {
        show(loaded(escalated.copy(capabilities = Samples.capabilities(takeOver = false, cont = true, end = true, simulated = false))))
        node("control_take_over").assertIsNotEnabled()
        node("control_take_over_reason").assertTextContains("provider cannot do this", substring = true)
    }

    @Test
    fun `watching live and opening the details navigate`() {
        var live: String? = null
        var details: String? = null
        show(loaded(), CallDetailActions(onOpenLive = { live = it }), onDetails = { details = it })
        node("incoming_open_live").performScrollTo().performClick()
        node("incoming_open_details").performScrollTo().performClick()
        assertEquals("call_1", live)
        assertEquals("call_1", details)
    }

    @Test
    fun `an ended call that needs nothing says so and offers no live button`() {
        show(loaded(Samples.callDetail(item = Samples.callItem(status = CallStatus.ENDED, attention = false))))
        node("incoming_no_attention").assertTextContains("This call has ended")
        node("incoming_open_live").assertDoesNotExist()
    }

    @Test
    fun `a call screened natively has no evidence section and never offers live controls`() {
        val screened = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false, status = CallStatus.ACTIVE, risk = RiskLevel.UNKNOWN),
            capabilities = Samples.capabilities(takeOver = true, simulated = false),
        )
        show(loaded(screened))
        node("incoming_evidence").assertDoesNotExist()
        node("control_take_over").assertDoesNotExist()
        node("control_live_unavailable").assertExists()
        node("incoming_open_live").assertDoesNotExist()
    }

    @Test
    fun `the cached row is shown while the call loads and a missing call is explained`() {
        show(CallDetailUiState(callId = "call_1", loading = true, cached = Samples.callItem(), nowMs = Samples.NOW))
        node("incoming_caller").assertExists()
        node("incoming_controls").assertDoesNotExist()
    }

    @Test
    fun `an unknown call is reported as unavailable`() {
        show(CallDetailUiState(callId = "x", loading = false, error = ApiError(ApiErrorKind.NOT_FOUND, "The backend does not have that item.")))
        node("incoming_not_found").assertExists()
    }

    @Test
    fun `a failed load offers a retry`() {
        var retried = 0
        show(CallDetailUiState(callId = "x", loading = false, error = ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached.")), CallDetailActions(onRefresh = { retried++ }))
        node("incoming_error_retry").performClick()
        assertEquals(1, retried)
    }
}
