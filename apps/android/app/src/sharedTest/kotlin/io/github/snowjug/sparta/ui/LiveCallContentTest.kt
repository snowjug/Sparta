package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertContentDescriptionContains
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.live.EndedInfo
import io.github.snowjug.sparta.core.live.LiveCallState
import io.github.snowjug.sparta.core.live.PartialTranscript
import io.github.snowjug.sparta.core.live.SpeakingInfo
import io.github.snowjug.sparta.core.live.VoicePhase
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.CallCapabilitiesDto
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.CallSummaryDto
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.remote.dto.Speaker
import io.github.snowjug.sparta.data.remote.ws.LiveCloseCodes
import io.github.snowjug.sparta.data.repo.LiveConnection
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.incoming.ControlId
import io.github.snowjug.sparta.ui.incoming.Unavailable
import io.github.snowjug.sparta.ui.live.LiveCallActions
import io.github.snowjug.sparta.ui.live.LiveCallContent
import io.github.snowjug.sparta.ui.live.LiveCallUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LiveCallContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun show(
        state: LiveCallUiState,
        actions: LiveCallActions = LiveCallActions(),
        width: WidthClass = WidthClass.COMPACT,
        reducedMotion: Boolean = false,
    ) {
        compose.setContent { SpartaTheme(reducedMotion = reducedMotion) { LiveCallContent(state, width, actions) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    private val activeCall = Samples.callDetail(
        item = Samples.callItem(status = CallStatus.ACTIVE, attention = true),
        capabilities = Samples.capabilities(takeOver = true, cont = true, end = true, takeoverNote = "Takeover is simulated."),
    )

    private fun live(
        phase: VoicePhase = VoicePhase.LISTENING,
        connection: LiveConnection = LiveConnection.CONNECTED,
        change: LiveCallState.() -> LiveCallState = { this },
    ) = LiveCallUiState(
        callId = "call_1",
        connection = connection,
        live = LiveCallState(callId = "call_1", phase = phase, call = activeCall, callState = CallState.IDENTIFY_PURPOSE, simulated = true).change(),
    )

    @Test
    fun `the connection banner tells the truth about the live feed`() {
        show(live(connection = LiveConnection.RECONNECTING))
        node("live_connection").assertTextContains("Reconnecting", substring = true)
    }

    @Test
    fun `a failed feed shows why`() {
        show(live(connection = LiveConnection.FAILED).copy(connectionError = ApiError(ApiErrorKind.OFFLINE, "The live connection was lost and could not be restored.")))
        node("live_connection").assertTextContains("could not be restored", substring = true)
    }

    @Test
    fun `a connected feed is confirmed`() {
        show(live())
        node("live_connection").assertTextContains("Live feed connected")
    }

    @Test
    fun `the status line and the visualisation follow the call phase and never pretend to be an audio meter`() {
        show(live(VoicePhase.ASSISTANT_SPEAKING))
        node("live_phase_text").assertTextContains("Sparta is speaking")
        node("voice_visualizer").assertContentDescriptionContains("Sparta is speaking", substring = true)
        node("voice_visualizer").assertContentDescriptionContains("not an audio level", substring = true)
    }

    @Test
    fun `every phase has its own wording`() {
        val wording = mapOf(
            VoicePhase.CONNECTING to "Connecting",
            VoicePhase.LISTENING to "Listening to the caller",
            VoicePhase.INTERRUPTED to "The caller interrupted Sparta",
            VoicePhase.OWNER_TAKEOVER to "You took over",
            VoicePhase.ENDED to "Call ended",
        )
        var state by mutableStateOf(live(VoicePhase.CONNECTING))
        compose.setContent { SpartaTheme { LiveCallContent(state, WidthClass.COMPACT, LiveCallActions()) } }
        wording.forEach { (phase, text) ->
            compose.runOnIdle { state = live(phase) }
            node("live_phase_text").assertTextContains(text)
        }
    }

    @Test
    fun `reduced motion keeps the same information`() {
        show(live(VoicePhase.LISTENING), reducedMotion = true)
        node("voice_visualizer").assertContentDescriptionContains("Listening to the caller", substring = true)
        node("live_phase_text").assertTextContains("Listening to the caller")
    }

    @Test
    fun `what the assistant is saying and what is being heard appear as they happen`() {
        show(
            live(VoicePhase.ASSISTANT_SPEAKING) {
                copy(
                    speaking = SpeakingInfo("turn_3", "May I know why you are calling?", "en-IN", 2000),
                    partial = PartialTranscript(Speaker.CALLER, "parcel ke liye", "hi-IN"),
                    transcript = listOf(Samples.turn("turn_2", 2, Speaker.CALLER, "Haan, main Swift Courier se bol raha hoon", "hi-IN", "Yes, I am calling from Swift Courier")),
                )
            },
        )
        node("live_speaking").assertTextContains("Sparta says: May I know why you are calling?")
        node("live_partial").assertTextContains("Hearing: parcel ke liye", substring = true)
        node("turn_turn_2").assertTextContains("Translation: Yes, I am calling from Swift Courier", substring = true)
    }

    @Test
    fun `an empty transcript says nobody has spoken yet`() {
        show(live())
        node("live_transcript_waiting").assertExists()
    }

    @Test
    fun `a simulated call is labelled and its audio claim is honest`() {
        show(live())
        node("live_simulated").assertTextContains("Simulated call: no real phone is ringing", substring = true)
        node("audio_honesty").assertTextContains("simulated call", substring = true)
    }

    @Test
    fun `risk and the escalation appear while the call is live`() {
        show(
            live {
                copy(
                    risk = Samples.riskAssessment(RiskLevel.HIGH, signals = listOf(Samples.signal())),
                    escalation = Samples.escalation(listOf("Please confirm the delivery address")),
                )
            },
        )
        node("live_risk").assertTextContains("Asked for a one-time password", substring = true)
        node("live_escalation").assertTextContains("Please confirm the delivery address", substring = true)
    }

    @Test
    fun `a provider problem is surfaced`() {
        show(live { copy(providerNotes = listOf(io.github.snowjug.sparta.core.live.ProviderNote("azure", "stt", "Speech service is slow", true))) })
        node("live_provider_issue").assertTextContains("Speech service is slow", substring = true)
    }

    @Test
    fun `controls follow the capabilities and report their action`() {
        val controls = mutableListOf<ControlId>()
        show(live(), LiveCallActions(onControl = { controls += it }))
        node("control_take_over").assertIsEnabled().performClick()
        node("control_end").assertIsEnabled().performClick()
        assertEquals(listOf(ControlId.TAKE_OVER, ControlId.END), controls)
        node("control_block").assertDoesNotExist()
    }

    @Test
    fun `while an action runs the controls are disabled`() {
        show(live().copy(busy = ControlId.END))
        node("control_take_over").assertIsNotEnabled()
        node("control_end").assertTextContains("Working")
    }

    @Test
    fun `when the call ends the summary replaces the controls and links to the details`() {
        var details: String? = null
        show(
            live(VoicePhase.ENDED) {
                copy(
                    ended = EndedInfo("spam", CallState.END_SPAM, 41_000),
                    summary = CallSummaryDto(callId = "call_1", text = "Ended a suspected scam call after an OTP request."),
                )
            },
            LiveCallActions(onOpenDetails = { details = it }),
        )
        node("live_summary_text").assertTextContains("Ended a suspected scam call", substring = true)
        node("live_controls").assertDoesNotExist()
        node("live_escalation").assertDoesNotExist()
        node("live_view_details").performScrollTo().performClick()
        assertEquals("call_1", details)
    }

    @Test
    fun `an ended call without a summary says it is still being written`() {
        show(live(VoicePhase.ENDED) { copy(call = activeCall.copy(summaryText = null)) })
        node("live_summary_text").assertTextContains("still being written", substring = true)
    }

    @Test
    fun `a call that does not exist is reported with a way back`() {
        var back = 0
        show(
            LiveCallUiState(callId = "gone", connection = LiveConnection.CLOSED, closeCode = LiveCloseCodes.CALL_NOT_FOUND),
            LiveCallActions(onBack = { back++ }),
        )
        node("live_not_found").assertExists()
        node("live_not_found_action").performClick()
        assertEquals(1, back)
    }

    @Test
    fun `a call screened natively never shows risk or live controls`() {
        val screened = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false, status = CallStatus.ACTIVE),
            capabilities = CallCapabilitiesDto(canTakeOver = true, canEnd = true),
        )
        show(LiveCallUiState(callId = "call_1", live = LiveCallState("call_1", call = screened, phase = VoicePhase.LISTENING), restCall = screened))
        node("control_take_over").assertDoesNotExist()
        node("control_live_unavailable").assertExists()
        node("audio_honesty").assertTextContains("cannot hear it", substring = true)
    }

    @Test
    fun `the expanded layout shows controls and transcript side by side`() {
        show(live { copy(transcript = listOf(Samples.turn("turn_1", 1, Speaker.ASSISTANT, "Hello, I am an AI assistant."))) }, width = WidthClass.EXPANDED)
        node("turn_turn_1").assertExists()
        node("control_take_over").assertExists()
    }

    @Test
    fun `the call is treated as ended as soon as the socket says so even if the snapshot still says active`() {
        val ended = live(VoicePhase.ENDED)
        show(ended)
        node("live_controls").assertDoesNotExist()
        assertEquals("the snapshot's own status was ACTIVE", CallStatus.ACTIVE, activeCall.status)
        assertEquals(CallStatus.ENDED, ended.call?.status)
        assertEquals(setOf(Unavailable.CALL_ENDED), ended.liveControls.mapNotNull { it.unavailable }.toSet())
    }
}
