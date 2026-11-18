package io.github.snowjug.sparta.ui.detail

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.data.local.ListKind
import io.github.snowjug.sparta.data.local.UploadState
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.ui.common.UiMessage
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ScreeningEventViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private lateinit var h: VmHarness
    private lateinit var vm: ScreeningEventViewModel
    private val fingerprint = "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12"

    @Before
    fun setUp() {
        h = VmHarness()
        vm = ScreeningEventViewModel(h.screening, h.calls, h.clock)
    }

    @After
    fun tearDown() = h.close()

    private fun insert(event: io.github.snowjug.sparta.data.local.ScreeningEventEntity = Samples.event(id = "evt_1")) {
        runBlocking { h.db.screeningEvents().insert(event) }
    }

    @Test
    fun `an existing event is loaded with its list membership`() {
        insert()
        vm.load("evt_1")
        val state = vm.state.await { !it.loading }
        assertEquals("evt_1", state.event?.clientEventId)
        assertTrue(state.canUseLists)
        assertNull(state.blockedEntry)
    }

    @Test
    fun `a missing event is not found`() {
        vm.load("gone")
        assertTrue(vm.state.await { !it.loading }.notFound)
    }

    @Test
    fun `blocking a number the backend does not know stays on the phone and needs no network`() {
        insert()
        vm.load("evt_1")
        vm.state.await { !it.loading }

        vm.block()
        val state = vm.state.await { it.blockedEntry != null && !it.busy }

        assertTrue(state.blockedEntry!!.deviceOnly)
        assertEquals(Samples.MASKED, state.blockedEntry.display)
        assertEquals(R.string.event_msg_blocked, (state.message as UiMessage.Text).res)
        assertEquals(0, h.api.server.requestCount)
        assertTrue("the fast path can match it at once", runBlocking { h.db.listEntries().isBlocked(fingerprint) })
    }

    @Test
    fun `an uploaded event also tells the backend which call to block`() {
        insert(Samples.event(id = "evt_1", backendCallId = "call_77", uploadState = UploadState.UPLOADED))
        h.api.enqueueJson("""{"id":"blk_1","number_display":"x"}""")
        vm.load("evt_1")
        vm.state.await { !it.loading }

        vm.block()
        val state = vm.state.await { it.blockedEntry != null && !it.busy }

        assertEquals("/api/v1/calls/call_77/block", h.api.takeRequest().path)
        assertEquals(R.string.event_msg_backend_noted, (state.message as UiMessage.Text).res)
    }

    @Test
    fun `when the backend cannot be told the number is still blocked on the phone and the reason is shown`() {
        insert(Samples.event(id = "evt_1", backendCallId = "call_77", uploadState = UploadState.UPLOADED))
        h.api.enqueueJson("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t"}}""", code = 500)
        vm.load("evt_1")
        vm.state.await { !it.loading }

        vm.block()
        val state = vm.state.await { it.blockedEntry != null && !it.busy }

        val message = state.message as UiMessage.Text
        assertEquals(R.string.event_msg_backend_failed, message.res)
        assertTrue(message.args.single().toString().contains("Boom"))
        assertTrue(runBlocking { h.db.listEntries().isBlocked(fingerprint) })
    }

    @Test
    fun `trusting adds a device entry and replaces a block on the same number`() {
        insert()
        vm.load("evt_1")
        vm.state.await { !it.loading }
        vm.block()
        vm.state.await { it.blockedEntry != null && !it.busy }

        vm.trust()
        // The state combines separate database flows, so a frame with the new trusted entry and the old blocked one is a
        // valid transient: wait for the settled state, then check the exclusivity.
        val state = vm.state.await { it.trustedEntry != null && it.blockedEntry == null && !it.busy }

        assertNull("blocked and trusted are mutually exclusive on the phone", state.blockedEntry)
        assertTrue(runBlocking { h.db.listEntries().isTrusted(fingerprint) })
        assertFalse(runBlocking { h.db.listEntries().isBlocked(fingerprint) })
    }

    @Test
    fun `a number without a fingerprint cannot be listed`() {
        insert(Samples.event(id = "evt_1", fingerprint = null))
        vm.load("evt_1")
        val state = vm.state.await { !it.loading }
        assertFalse(state.canUseLists)
        vm.block()
        assertEquals(0, runBlocking { h.db.listEntries().observe(ListKind.BLOCKED).first().size })
    }

    @Test
    fun `unblocking removes the device entry`() {
        insert()
        vm.load("evt_1")
        vm.state.await { !it.loading }
        vm.block()
        vm.state.await { it.blockedEntry != null && !it.busy }

        vm.unblock()
        val state = vm.state.await { it.blockedEntry == null && !it.busy && it.message is UiMessage.Text && it.message.res == R.string.event_msg_unblocked }
        assertNotNull(state)
    }

    @Test
    fun `deleting the record removes it and finishes the screen`() {
        insert()
        vm.load("evt_1")
        vm.state.await { !it.loading }
        vm.delete()
        vm.state.await { it.deleted }
        assertNull(runBlocking { h.db.screeningEvents().get("evt_1") })
    }
}
