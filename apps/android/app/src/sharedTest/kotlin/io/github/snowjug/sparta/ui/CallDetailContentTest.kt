package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.FeedbackKind
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.SignalKind
import io.github.snowjug.sparta.data.remote.dto.SignalSeverity
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.detail.CallDetailActions
import io.github.snowjug.sparta.ui.detail.CallDetailContent
import io.github.snowjug.sparta.ui.detail.CallDetailUiState
import io.github.snowjug.sparta.ui.detail.DeleteKind
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CallDetailContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun show(state: CallDetailUiState, actions: CallDetailActions = CallDetailActions()) {
        compose.setContent { SpartaTheme { CallDetailContent(state, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    private fun loaded(
        call: io.github.snowjug.sparta.data.remote.dto.CallDetailDto = Samples.callDetail(),
        build: CallDetailUiState.() -> CallDetailUiState = { this },
    ) = CallDetailUiState(callId = call.id, loading = false, call = call, nowMs = Samples.NOW).build()

    // ---- header and honesty ----

    @Test
    fun `the header shows the masked number the claim the status and that the call was simulated`() {
        show(loaded())
        node("detail_caller").assertTextContains(Samples.MASKED)
        node("detail_header").assertTextContains("Ravi, Swift Courier", substring = true)
        node("detail_status").assertTextContains("Ended", substring = true)
        node("simulated_badge").assertExists()
        node("audio_honesty").assertTextContains("simulated call", substring = true)
    }

    @Test
    fun `a real call with a media stream may say two way audio and only then`() {
        val real = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.AZURE, simulated = false),
            capabilities = Samples.capabilities(simulated = false, twoWay = true, audioNote = "Media streaming is connected."),
        )
        show(loaded(real))
        node("audio_honesty").assertTextContains("Two-way audio is connected", substring = true)
        node("audio_note").assertTextContains("Media streaming is connected.", substring = true)
        node("simulated_badge").assertDoesNotExist()
    }

    @Test
    fun `a real call without a media stream makes no audio claim`() {
        val real = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.AZURE, simulated = false),
            capabilities = Samples.capabilities(simulated = false, twoWay = false),
        )
        show(loaded(real))
        node("audio_honesty").assertTextContains("No call audio is available on this phone", substring = true)
    }

    @Test
    fun `a call screened on this phone has no transcript no analysis and no live controls and says why`() {
        val screened = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false, risk = RiskLevel.UNKNOWN, summary = null, claimName = null, organization = null, purpose = null),
            capabilities = Samples.capabilities(simulated = false),
        )
        show(loaded(screened))
        node("audio_honesty").assertTextContains("did not answer the call and cannot hear it", substring = true)
        node("transcript_none_screening").assertExists()
        node("detail_risk").assertDoesNotExist()
        node("detail_feedback").assertDoesNotExist()
        node("control_live_unavailable").assertTextContains("Android does not let Sparta join or steer a call", substring = true)
        node("control_block").assertIsEnabled()
        node("provider_badge").assertTextContains("On-device screening")
    }

    // ---- risk and evidence ----

    @Test
    fun `risk is shown with its score confidence advice and the evidence behind it`() {
        val risky = Samples.callDetail(
            item = Samples.callItem(risk = RiskLevel.HIGH, score = 0.93, confidence = 0.88, category = io.github.snowjug.sparta.data.remote.dto.CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION),
            risk = Samples.riskAssessment(
                level = RiskLevel.HIGH,
                signals = listOf(
                    Samples.signal(),
                    Samples.signal("LEGIT", SignalKind.LEGITIMATE, SignalSeverity.INFO, "Delivery coordination language", null),
                ),
                reasons = listOf("Asked for an OTP"),
            ),
        )
        show(loaded(risky))
        node("risk_meter").assertTextContains("Score 93%", substring = true)
        node("risk_meter").assertTextContains("Confidence 88%", substring = true)
        node("detail_advice").assertTextContains("Needs your decision", substring = true)
        node("signal_OTP_REQUEST").assertTextContains("Asked for a one-time password", substring = true)
        node("signal_OTP_REQUEST").assertTextContains("share the OTP", substring = true)
        node("signal_LEGIT").assertTextContains("Reassuring sign", substring = true)
        node("detail_risk").assertTextContains("Asked for an OTP", substring = true)
    }

    @Test
    fun `an unclassified call says there is not enough evidence instead of a number`() {
        show(loaded(Samples.callDetail(item = Samples.callItem(risk = RiskLevel.UNKNOWN))))
        node("detail_risk").assertTextContains("Not enough evidence yet", substring = true)
        node("risk_meter").assertDoesNotExist()
    }

    // ---- owner controls follow capabilities ----

    private val liveCall = Samples.callItem(status = CallStatus.ACTIVE, attention = true)

    @Test
    fun `controls are enabled only for what the provider reports and a simulated action says so`() {
        val controls = mutableListOf<ControlId>()
        show(
            loaded(Samples.callDetail(item = liveCall, capabilities = Samples.capabilities(takeOver = true, end = true, takeoverNote = "Takeover is a simulation."))),
            CallDetailActions(onControl = { controls += it }),
        )
        node("control_take_over").assertTextContains("Take over (simulation)").assertIsEnabled().performClick()
        node("control_continue").assertIsNotEnabled()
        node("control_continue_reason").assertTextContains("provider cannot do this", substring = true)
        node("control_end").assertIsEnabled().performClick()
        node("control_take_over_note").assertTextContains("Takeover is a simulation.", substring = true)
        assertEquals(listOf(ControlId.TAKE_OVER, ControlId.END), controls)
    }

    @Test
    fun `an ended call collapses the live controls into one explanation`() {
        show(loaded())
        node("control_live_unavailable").assertTextContains("This call is over", substring = true)
        node("control_take_over").assertDoesNotExist()
    }

    @Test
    fun `an active call offers to watch it live`() {
        var live: String? = null
        show(loaded(Samples.callDetail(item = liveCall)), CallDetailActions(onOpenLive = { live = it }))
        node("open_live").performScrollTo().performClick()
        assertEquals("call_1", live)
    }

    @Test
    fun `block and trust report their action and show their state`() {
        val controls = mutableListOf<ControlId>()
        show(loaded(), CallDetailActions(onControl = { controls += it }))
        node("control_block").performScrollTo().performClick()
        node("control_trust").performScrollTo().performClick()
        assertEquals(listOf(ControlId.BLOCK, ControlId.TRUST), controls)
    }

    @Test
    fun `an already blocked caller shows blocked and cannot be blocked again`() {
        show(loaded(Samples.callDetail(item = Samples.callItem(blocked = true))))
        node("control_block").assertTextContains("Caller is blocked").assertIsNotEnabled()
        node("blocked_badge").assertExists()
    }

    @Test
    fun `while an action runs every control is disabled and shows progress`() {
        show(loaded(Samples.callDetail(item = liveCall, capabilities = Samples.capabilities(takeOver = true, cont = true, end = true))) { copy(busy = ControlId.TAKE_OVER) })
        node("control_take_over").assertTextContains("Working").assertIsNotEnabled()
        node("control_end").assertIsNotEnabled()
        node("control_block").assertIsNotEnabled()
    }

    // ---- feedback ----

    @Test
    fun `feedback chips send their kind once`() {
        var sent: FeedbackKind? = null
        show(loaded { copy(feedbackSent = setOf(FeedbackKind.CORRECT_CLASSIFICATION)) }, CallDetailActions(onFeedback = { sent = it }))
        node("feedback_was_spam").performScrollTo().performClick()
        assertEquals(FeedbackKind.WAS_SPAM, sent)
        node("feedback_correct_classification").assertIsNotEnabled()
        node("feedback_correct_classification").assertTextContains("Sent", substring = true)
    }

    // ---- transcript ----

    @Test
    fun `the transcript labels the assistant as an ai and offers translations on request`() {
        var toggled = 0
        show(loaded(), CallDetailActions(onToggleTranslations = { toggled++ }))
        node("detail_transcript").assertTextContains("Sparta, AI assistant", substring = true)
        node("detail_transcript").assertTextContains("Haan, main Swift Courier se bol raha hoon", substring = true)
        node("toggle_translations").performScrollTo().performClick()
        assertEquals(1, toggled)
    }

    @Test
    fun `translations appear only when switched on`() {
        show(loaded { copy(showTranslations = true) })
        node("turn_turn_2").assertTextContains("Translation: Yes, I am calling from Swift Courier", substring = true)
    }

    @Test
    fun `deleted content is explained`() {
        show(loaded(Samples.callDetail(item = Samples.callItem(hasContent = false))))
        node("transcript_deleted").assertExists()
        node("delete_content").assertDoesNotExist()
    }

    @Test
    fun `a call with no turns yet says nobody has spoken`() {
        show(loaded(Samples.callDetail(turns = emptyList())))
        node("transcript_empty").assertExists()
    }

    // ---- deletion needs confirmation ----

    @Test
    fun `deleting the call asks first and cancelling does nothing`() {
        var deleted: DeleteKind? = null
        show(loaded(), CallDetailActions(onDelete = { deleted = it }))
        node("delete_call").performScrollTo().performClick()
        node("delete_dialog").assertTextContains("This cannot be undone", substring = true)
        node("delete_cancel").performClick()
        assertNull(deleted)
        node("delete_dialog").assertDoesNotExist()
    }

    @Test
    fun `confirming deletes the call and the content deletion is separate`() {
        val kinds = mutableListOf<DeleteKind>()
        show(loaded(), CallDetailActions(onDelete = { kinds += it }))
        node("delete_content").performScrollTo().performClick()
        node("delete_confirm").performClick()
        node("delete_call").performScrollTo().performClick()
        node("delete_confirm").performClick()
        assertEquals(listOf(DeleteKind.CONTENT, DeleteKind.CALL), kinds)
    }

    // ---- states ----

    @Test
    fun `while loading the cached row appears at once without controls`() {
        show(CallDetailUiState(callId = "call_1", loading = true, cached = Samples.callItem(), nowMs = Samples.NOW))
        node("detail_caller").assertTextContains(Samples.MASKED)
        node("owner_controls").assertDoesNotExist()
    }

    @Test
    fun `an unknown call is reported as not available`() {
        show(CallDetailUiState(callId = "gone", loading = false, error = ApiError(ApiErrorKind.NOT_FOUND, "The backend does not have that item.")))
        node("detail_not_found").assertExists()
    }

    @Test
    fun `a failed load shows the reason and a retry`() {
        var retried = 0
        show(
            CallDetailUiState(callId = "x", loading = false, error = ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached.")),
            CallDetailActions(onRefresh = { retried++ }),
        )
        node("detail_error").assertTextContains("could not be reached", substring = true)
        node("detail_error_retry").performClick()
        assertEquals(1, retried)
    }

    @Test
    fun `saved information stays visible when a refresh fails`() {
        show(loaded { copy(error = ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached.")) })
        node("detail_cached_note").assertTextContains("Showing saved information", substring = true)
        node("detail_caller").assertExists()
    }

    @Test
    fun `results of actions appear as a message and failures show the trace id`() {
        show(loaded { copy(message = UiMessage.Text(R.string.detail_msg_blocked)) })
        node("message_banner").assertTextContains("Caller blocked", substring = true)
    }

    @Test
    fun `a failed action shows the backend explanation`() {
        show(loaded { copy(message = UiMessage.Failure(ApiError(ApiErrorKind.UNSUPPORTED_BY_PROVIDER, "The active telephony provider does not support this action.", traceId = "abc-1"))) })
        node("message_error").assertTextContains("does not support this action", substring = true)
        node("message_error").assertTextContains("abc-1", substring = true)
    }

    @Test
    fun `technical details include the trace id for support`() {
        show(loaded())
        node("detail_trace").performScrollTo().assertTextContains("trace-123", substring = true)
    }
}
