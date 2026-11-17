package io.github.snowjug.sparta.ui

import androidx.compose.ui.test.assertContentDescriptionContains
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import io.github.snowjug.sparta.testing.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.material3.Text
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.repo.CallFilter
import io.github.snowjug.sparta.data.repo.RecentItem
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testing.assertTextContains
import io.github.snowjug.sparta.ui.calls.CallsActions
import io.github.snowjug.sparta.ui.calls.CallsContent
import io.github.snowjug.sparta.ui.calls.CallsUiState
import io.github.snowjug.sparta.ui.theme.SpartaTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CallsContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun backend(id: String = "call_1", minutesAgo: Int = 30, build: io.github.snowjug.sparta.data.remote.dto.CallListItemDto.() -> io.github.snowjug.sparta.data.remote.dto.CallListItemDto = { this }) =
        RecentItem.Backend(Samples.callItem(id = id).build(), Samples.NOW - minutesAgo * 60_000L)

    private fun state(vararg items: RecentItem, build: CallsUiState.() -> CallsUiState = { this }) =
        CallsUiState(items = items.toList(), nowMs = Samples.NOW, backendConfigured = true, initialLoading = false).build()

    private fun show(
        state: CallsUiState,
        actions: CallsActions = CallsActions(),
        width: WidthClass = WidthClass.COMPACT,
        pane: @androidx.compose.runtime.Composable (String) -> Unit = {},
    ) {
        compose.setContent { SpartaTheme { CallsContent(state, width, actions, detailPane = pane) } }
    }

    private fun node(tag: String) = compose.onNodeWithTag(tag)

    @Test
    fun `a backend call row summarises who when and how risky and opens the call`() {
        var opened: String? = null
        show(state(backend()), CallsActions(onOpenCall = { opened = it }))

        node("call_row_call_1").assertContentDescriptionContains("Low risk", substring = true)
        node("call_row_call_1").assertContentDescriptionContains("30 min ago", substring = true)
        node("call_row_call_1").assertContentDescriptionContains(Samples.MASKED, substring = true)
        node("call_row_call_1").assertTextContains("Simulated")
        node("call_row_call_1").performClick()
        assertEquals("call_1", opened)
    }

    @Test
    fun `a simulated call is labelled simulated and a real one is not`() {
        show(
            state(
                backend("sim"),
                backend("real") { copy(simulated = false, provider = ProviderKind.AZURE) },
            ),
        )
        node("call_row_sim").assertTextContains("Simulated")
        compose.onNodeWithTag("call_row_real").assertTextContains("Azure Communication Services")
        compose.onNodeWithTag("simulated_badge", useUnmergedTree = true).assertExists() // only the simulated row has one
    }

    @Test
    fun `calls that need the owner are flagged`() {
        show(state(backend { copy(ownerAttentionRequired = true, status = CallStatus.ACTIVE) }))
        node("call_row_call_1").assertTextContains("Needs you")
    }

    @Test
    fun `an on device decision is marked as made on the phone and opens its own screen`() {
        var event: String? = null
        show(state(RecentItem.Local(Samples.event(id = "evt_1"))), CallsActions(onOpenEvent = { event = it }))

        node("event_row_evt_1").assertContentDescriptionContains("Decided on this phone", substring = true)
        node("event_row_evt_1").assertTextContains("On-device screening")
        node("event_row_evt_1").performClick()
        assertEquals("evt_1", event)
        compose.onNodeWithTag("risk_badge", useUnmergedTree = true).assertDoesNotExist()
    }

    @Test
    fun `the first load shows progress and no empty message`() {
        show(CallsUiState(backendConfigured = true, initialLoading = true))
        node("loading_indicator").assertExists()
        node("calls_empty").assertDoesNotExist()
    }

    @Test
    fun `no backend and no calls explains it and offers to connect one`() {
        var connect = 0
        show(CallsUiState(backendConfigured = false, initialLoading = false), CallsActions(onConnectBackend = { connect++ }))
        node("calls_empty_no_backend").assertTextContains("Connect a Sparta backend", substring = true)
        node("calls_empty_no_backend_action").performClick()
        assertEquals(1, connect)
    }

    @Test
    fun `a connected backend with no calls says nothing has been screened yet`() {
        show(state())
        node("calls_empty").assertTextContains("When Sparta screens a call it shows up here.")
    }

    @Test
    fun `an empty result from filters offers to clear them`() {
        var cleared = 0
        show(state { copy(filter = CallFilter(risk = RiskLevel.HIGH)) }, CallsActions(onClearFilters = { cleared++ }))
        node("calls_empty_filtered").assertTextContains("No calls match")
        node("calls_empty_filtered_action").performClick()
        assertEquals(1, cleared)
    }

    @Test
    fun `a failed refresh keeps the saved calls and says why`() {
        show(state(backend()) { copy(error = ApiError(ApiErrorKind.OFFLINE, "The backend could not be reached.")) })
        node("calls_error_cached").assertTextContains("Showing saved calls", substring = true)
        node("call_row_call_1").assertExists()
    }

    @Test
    fun `a failed first load shows the error with a retry`() {
        var retried = 0
        show(state { copy(error = ApiError(ApiErrorKind.SERVER, "The backend had a problem (HTTP 500).", traceId = "t-1")) }, CallsActions(onRefresh = { retried++ }))
        node("calls_error").assertTextContains("HTTP 500", substring = true)
        node("calls_error").assertTextContains("t-1", substring = true)
        node("calls_error_retry").performClick()
        assertEquals(1, retried)
    }

    @Test
    fun `filter chips report their choice and show their selection`() {
        var risk: RiskLevel? = null
        var language: String? = "unset"
        var attention: Boolean? = null
        show(
            state(backend()) { copy(filter = CallFilter(risk = RiskLevel.HIGH)) },
            CallsActions(onRisk = { risk = it }, onLanguage = { language = it }, onAttention = { attention = it }),
        )
        node("filter_risk_high").assertIsSelected()
        node("filter_risk_high").performClick()
        assertNull("tapping the selected chip clears it", risk)
        node("filter_risk_medium").performClick()
        assertEquals(RiskLevel.MEDIUM, risk)
        node("filter_language_hi-IN").performClick()
        assertEquals("hi-IN", language)
        node("filter_attention").performClick()
        assertEquals(true, attention)
    }

    @Test
    fun `choosing a category from the menu applies it`() {
        var category: CallCategory? = null
        show(state(backend()), CallsActions(onCategory = { category = it }))
        node("filter_category").performClick()
        node("category_possible_prize_scam").performClick()
        assertEquals(CallCategory.POSSIBLE_PRIZE_SCAM, category)
    }

    @Test
    fun `active filters are explained and can be cleared`() {
        var cleared = 0
        show(state(backend()) { copy(filter = CallFilter(attentionOnly = true)) }, CallsActions(onClearFilters = { cleared++ }))
        node("filters_note").assertTextContains("hidden while one of these filters is on", substring = true)
        node("filter_clear").performClick()
        assertEquals(1, cleared)
    }

    @Test
    fun `typing in the search box reports the query`() {
        var query = ""
        show(state(backend()), CallsActions(onQuery = { query = it }))
        node("calls_search").performTextInput("swift")
        assertEquals("swift", query)
    }

    @Test
    fun `load more appears only with another page and is disabled while loading`() {
        var more = 0
        show(state(backend()) { copy(hasMore = true) }, CallsActions(onLoadMore = { more++ }))
        node("calls_load_more").assertIsEnabled().performClick()
        assertEquals(1, more)
    }

    @Test
    fun `load more is disabled while a page is loading`() {
        show(state(backend()) { copy(hasMore = true, loadingMore = true) })
        node("calls_load_more").assertIsNotEnabled()
    }

    @Test
    fun `phones and medium windows show the list alone`() {
        show(state(backend()), width = WidthClass.MEDIUM)
        node("calls_two_pane").assertDoesNotExist()
        node("call_row_call_1").assertExists()
    }

    @Test
    fun `an expanded window shows the list beside the selected call`() {
        show(
            state(backend()) { copy(selectedCallId = "call_1") },
            width = WidthClass.EXPANDED,
            pane = { id -> Text("detail for $id") },
        )
        node("calls_two_pane").assertExists()
        node("call_row_call_1").assertExists()
        compose.onNodeWithTag("calls_detail_pane").assertTextContains("detail for call_1")
    }

    @Test
    fun `an expanded window with nothing selected invites a selection`() {
        show(state(backend()), width = WidthClass.EXPANDED)
        node("calls_select_prompt").assertTextContains("Select a call", substring = true)
    }

    @Test
    fun `screening only and conversational calls carry the right provider wording`() {
        show(
            state(
                backend("screened") { copy(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false) },
            ),
        )
        node("call_row_screened").assertTextContains("On-device screening")
    }
}
