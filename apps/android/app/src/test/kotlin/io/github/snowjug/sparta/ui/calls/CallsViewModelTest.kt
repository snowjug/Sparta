package io.github.snowjug.sparta.ui.calls

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.repo.RecentItem
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CallsViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private var h: VmHarness? = null

    @After
    fun tearDown() {
        h?.close()
    }

    private fun harness(configured: Boolean = true): VmHarness = VmHarness(configured).also { h = it }

    private fun viewModel(harness: VmHarness) = CallsViewModel(harness.calls, harness.screening, harness.settings, harness.clock)

    private val page = Fixtures.text("call_page.json")

    @Test
    fun `without a backend there is nothing to load and local decisions are listed`() {
        val harness = harness(configured = false)
        runBlocking { harness.db.screeningEvents().insert(Samples.event(id = "evt_1", uploadState = UploadState.LOCAL_ONLY)) }
        val vm = viewModel(harness)

        val state = vm.state.await { !it.initialLoading && it.items.isNotEmpty() }

        assertFalse(state.backendConfigured)
        assertTrue(state.items.single() is RecentItem.Local)
        assertEquals("no request was made", 0, harness.api.server.requestCount)
    }

    @Test
    fun `with a backend the first refresh fills the list from the backend`() {
        val harness = harness()
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)

        val state = vm.state.await { it.items.any { item -> item is RecentItem.Backend } }

        assertFalse(state.initialLoading)
        assertNull(state.error)
        assertEquals("/api/v1/calls?limit=50", harness.api.takeRequest().path)
    }

    @Test
    fun `a failed refresh keeps what was cached and reports the reason`() {
        val harness = harness()
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)
        vm.state.await { it.items.any { item -> item is RecentItem.Backend } }

        harness.api.enqueueJson("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t-1"}}""", code = 500)
        vm.refresh()
        val state = vm.state.await { it.error != null }

        assertEquals(ApiErrorKind.SERVER, state.error?.kind)
        assertTrue("the saved calls stay visible", state.items.any { it is RecentItem.Backend })
        assertFalse(state.refreshing)
    }

    @Test
    fun `choosing a risk filter asks the backend with that filter after the debounce`() {
        val harness = harness()
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)
        vm.state.await { !it.initialLoading }
        harness.api.takeRequest()

        harness.api.enqueueJson("""{"items":[],"next_cursor":null}""")
        vm.setRisk(RiskLevel.HIGH)
        val request = harness.api.takeRequest() // blocks until the debounce has elapsed and the request is sent

        assertTrue(request.path!!.contains("risk_level=high"))
        vm.state.await { !it.refreshing && it.filter.risk == RiskLevel.HIGH }
        assertTrue(vm.state.value.filtersActive)
    }

    @Test
    fun `typing quickly sends one request not one per keystroke`() {
        val harness = harness()
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)
        vm.state.await { !it.initialLoading }
        harness.api.takeRequest()
        harness.api.enqueueJson("""{"items":[],"next_cursor":null}""")

        "swift".forEachIndexed { index, _ -> vm.setQuery("swift".substring(0, index + 1)) }
        val request = harness.api.takeRequest()
        Thread.sleep(500) // any extra request caused by an earlier keystroke would have been sent by now

        assertTrue(request.path!!.contains("q=swift"))
        assertEquals("one initial page and one search", 2, harness.api.server.requestCount)
    }

    @Test
    fun `a next cursor enables load more which fetches the following page`() {
        val harness = harness()
        harness.api.enqueueJson(page) // the fixture's first page says next_cursor = cursor-2
        val vm = viewModel(harness)
        val first = vm.state.await { it.hasMore }
        assertTrue(first.hasMore)
        harness.api.takeRequest()

        harness.api.enqueueJson("""{"items":[],"next_cursor":null}""")
        vm.loadMore()
        vm.state.await { !it.hasMore && !it.loadingMore }

        assertTrue(harness.api.takeRequest().path!!.contains("cursor=cursor-2"))
    }

    @Test
    fun `clearing the filters returns to the full list`() {
        val harness = harness()
        harness.api.enqueueJson(page)
        harness.api.enqueueJson("""{"items":[],"next_cursor":null}""")
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)
        vm.state.await { !it.initialLoading }
        vm.setAttentionOnly(true)
        assertTrue(vm.state.await { it.filtersActive }.filter.attentionOnly)
        vm.clearFilters()
        assertFalse(vm.state.await { !it.filtersActive }.filtersActive)
    }

    @Test
    fun `selecting a call is remembered for the two pane layout`() {
        val harness = harness(configured = false)
        val vm = viewModel(harness)
        vm.select("call_1")
        assertEquals("call_1", vm.state.await { it.selectedCallId != null }.selectedCallId)
        vm.select(null)
        assertNotNull(vm.state.await { it.selectedCallId == null })
    }

    @Test
    fun `an on device decision is hidden once the backend copy of it is in the list`() {
        val harness = harness()
        runBlocking {
            harness.db.screeningEvents().insert(Samples.event(id = "uploaded", backendCallId = "call_2", uploadState = UploadState.UPLOADED))
            harness.db.screeningEvents().insert(Samples.event(id = "pending", backendCallId = null, occurredAtMs = Samples.NOW))
        }
        harness.api.enqueueJson(page)
        val vm = viewModel(harness)
        val state = vm.state.await { it.items.any { item -> item is RecentItem.Backend } }

        assertEquals(setOf("call_1", "call_2"), state.items.filterIsInstance<RecentItem.Backend>().map { it.call.id }.toSet())
        assertEquals("only the not yet uploaded decision stays as its own row", listOf("pending"), state.items.filterIsInstance<RecentItem.Local>().map { it.event.clientEventId })
    }
}
