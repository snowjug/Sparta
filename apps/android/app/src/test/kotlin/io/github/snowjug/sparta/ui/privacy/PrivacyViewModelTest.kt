package io.github.snowjug.sparta.ui.privacy

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.motion.MotionPreference
import io.github.snowjug.sparta.core.net.BackendUrlPolicy
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import io.github.snowjug.sparta.data.local.ListKind
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.ConnectionTester
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.prefs.ThemeMode
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testutil.FakePermissionChecker
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import io.github.snowjug.sparta.ui.common.UiMessage
import io.github.snowjug.sparta.ui.onboarding.ConnectionUi
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PrivacyViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private var h: VmHarness? = null
    private val permissions = FakePermissionChecker()

    @After
    fun tearDown() {
        h?.close()
    }

    private fun create(configured: Boolean = true): Pair<VmHarness, PrivacyViewModel> {
        val harness = VmHarness(configured).also { h = it }
        val tester = ConnectionTester(harness.api.client, SpartaJson, BackendUrlPolicy(allowLocalCleartext = true), MonotonicClock { 0L })
        val connector = BackendConnector(tester, harness.settings, harness.screening, harness.system)
        val vm = PrivacyViewModel(
            settings = harness.settings,
            preferences = harness.preferences,
            screening = harness.screening,
            calls = harness.calls,
            system = harness.system,
            permissions = PermissionModel(permissions, harness.settings),
            connector = connector,
        )
        return harness to vm
    }

    private val prefsJson = """{"onboarding_completed":true,"strictness":"balanced","unknown_caller_behavior":"screen","trusted_contact_behavior":"allow_directly","future_field":{"keep":"me"}}"""

    // ---- screening behaviour ----

    @Test
    fun `without a backend a changed rule applies on this phone at once and says so`() {
        val (harness, vm) = create(configured = false)

        vm.setStrictness(Strictness.STRICT)
        val state = vm.state.await { it.message != null }

        assertEquals(Strictness.STRICT, harness.settings.value.strictness)
        assertEquals(R.string.privacy_saved_local, (state.message as UiMessage.Text).res)
        assertEquals("no request without a backend", 0, harness.api.server.requestCount)
    }

    @Test
    fun `with a backend the change is merged onto the backend document and unknown fields survive`() {
        val (harness, vm) = create()
        harness.api.enqueueJson(prefsJson)
        harness.api.enqueueJson(prefsJson.replace("\"balanced\"", "\"strict\""))

        vm.setStrictness(Strictness.STRICT)
        val state = vm.state.await { it.message != null }

        assertEquals("GET", harness.api.takeRequest().method)
        val put = harness.api.takeRequest()
        assertEquals("PUT", put.method)
        val body = SpartaJson.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("strict", body.getValue("strictness").jsonPrimitive.content)
        assertTrue("fields this app does not know are sent back untouched", "future_field" in body)
        assertEquals(R.string.privacy_saved, (state.message as UiMessage.Text).res)
        assertEquals(Strictness.STRICT, harness.settings.value.strictness)
    }

    @Test
    fun `when the backend is unreachable the change is kept and reported as saved on the phone`() {
        val (harness, vm) = create()
        harness.api.enqueueJson("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t"}}""", code = 500)

        vm.setUnknownBehavior(UnknownCallerBehavior.ALLOW)
        val state = vm.state.await { it.message != null }

        assertEquals(UnknownCallerBehavior.ALLOW, harness.settings.value.unknownCallerBehavior)
        val message = state.message as UiMessage.Text
        assertEquals(R.string.common_saved_on_phone, message.res)
        assertTrue(harness.settings.value.preferencesDirty)
    }

    // ---- notifications and permissions ----

    @Test
    fun `local notification switches are stored`() {
        val (harness, vm) = create(configured = false)
        vm.setNotifyEscalations(false)
        vm.setNotifyScreening(false)
        vm.state.await { !it.settings.notifyEscalations && !it.settings.notifyScreening }
        assertFalse(harness.settings.value.notifyEscalations)
        assertFalse(harness.settings.value.notifyScreening)
    }

    @Test
    fun `a refused notification prompt is interpreted from the rationale flag`() {
        val (_, vm) = create(configured = false)
        vm.onNotificationsResult(granted = false, shouldShowRationale = true)
        assertEquals(PermissionUiState.DENIED_CAN_ASK_AGAIN, vm.state.await { it.notifications != PermissionUiState.NOT_ASKED }.notifications)
        vm.onNotificationsResult(granted = false, shouldShowRationale = false)
        assertEquals(PermissionUiState.DENIED_PERMANENTLY, vm.state.await { it.notifications == PermissionUiState.DENIED_PERMANENTLY }.notifications)
    }

    @Test
    fun `the contacts option cannot be switched on without the permission`() {
        val (harness, vm) = create(configured = false)
        permissions.contacts = false
        assertFalse(vm.enableContactsIfGranted())
        assertFalse(harness.settings.value.useContactsAsKnown)

        permissions.contacts = true
        assertTrue(vm.enableContactsIfGranted())
        vm.state.await { it.settings.useContactsAsKnown }
    }

    @Test
    fun `a refused contacts prompt leaves the option off`() {
        val (harness, vm) = create(configured = false)
        vm.onContactsResult(granted = false, shouldShowRationale = false)
        val state = vm.state.await { it.contacts == PermissionUiState.DENIED_PERMANENTLY }
        assertFalse(state.settings.useContactsAsKnown)
        assertTrue(harness.settings.value.contactsPermissionAsked)
    }

    @Test
    fun `switching contacts off needs no prompt`() {
        val (harness, vm) = create(configured = false)
        permissions.contacts = true
        vm.enableContactsIfGranted()
        vm.state.await { it.settings.useContactsAsKnown }
        vm.disableContacts()
        vm.state.await { !it.settings.useContactsAsKnown }
        assertFalse(harness.settings.value.useContactsAsKnown)
    }

    // ---- data ----

    @Test
    fun `deleting all call data clears the backend then this phone`() {
        val (harness, vm) = create()
        runBlocking { harness.db.screeningEvents().insert(Samples.event(id = "evt_1")) }
        harness.api.enqueueEmpty(204)

        vm.deleteAllCallData()
        val state = vm.state.await { !it.deleting && it.message != null }

        val request = harness.api.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/api/v1/calls", request.path)
        assertEquals(R.string.privacy_deleted_all, (state.message as UiMessage.Text).res)
        assertNull(runBlocking { harness.db.screeningEvents().get("evt_1") })
    }

    @Test
    fun `if the backend refuses the deletion the phone keeps its history so nothing is half deleted silently`() {
        val (harness, vm) = create()
        runBlocking { harness.db.screeningEvents().insert(Samples.event(id = "evt_1")) }
        harness.api.enqueueJson("""{"error":{"code":"internal_error","message":"Boom","trace_id":"t"}}""", code = 500)

        vm.deleteAllCallData()
        val state = vm.state.await { !it.deleting && it.message != null }

        assertTrue(state.message is UiMessage.Failure)
        assertTrue(runBlocking { harness.db.screeningEvents().get("evt_1") } != null)
    }

    @Test
    fun `without a backend deleting all data clears the phone only`() {
        val (harness, vm) = create(configured = false)
        runBlocking { harness.db.screeningEvents().insert(Samples.event(id = "evt_1")) }
        vm.deleteAllCallData()
        vm.state.await { !it.deleting && it.message != null }
        assertNull(runBlocking { harness.db.screeningEvents().get("evt_1") })
        assertEquals(0, harness.api.server.requestCount)
    }

    @Test
    fun `deleting local history never touches the network`() {
        val (harness, vm) = create()
        runBlocking { harness.db.screeningEvents().insert(Samples.event(id = "evt_1")) }
        vm.deleteLocalHistory()
        vm.state.await { it.message != null }
        assertNull(runBlocking { harness.db.screeningEvents().get("evt_1") })
        assertEquals(0, harness.api.server.requestCount)
    }

    @Test
    fun `list entries are removed through the repository`() {
        val (harness, vm) = create(configured = false)
        runBlocking { harness.screening.addDeviceEntry(ListKind.BLOCKED, "fp1", Samples.MASKED) }
        val entry = vm.state.await { it.blocked.isNotEmpty() }.blocked.single()
        vm.removeEntry(entry)
        vm.state.await { it.blocked.isEmpty() }
        assertEquals(R.string.privacy_entry_removed, ((vm.state.await { it.message != null }).message as UiMessage.Text).res)
    }

    // ---- appearance ----

    @Test
    fun `theme motion and background sync are stored`() {
        val (harness, vm) = create(configured = false)
        vm.setTheme(ThemeMode.LIGHT)
        vm.setMotion(MotionPreference.REDUCE)
        vm.setBackgroundSync(false)
        vm.state.await { it.settings.themeMode == ThemeMode.LIGHT && it.settings.motionPreference == MotionPreference.REDUCE && !it.settings.backgroundSyncEnabled }
        assertEquals(ThemeMode.LIGHT, harness.settings.value.themeMode)
    }

    // ---- backend ----

    @Test
    fun `testing an address reports the backend then using it saves it and pulls the screening key`() {
        val (harness, vm) = create(configured = false)
        vm.onUrlChange("http://localhost:${harness.api.server.port}/")
        harness.api.enqueueJson(Fixtures.text("system_status.json"))

        vm.testConnection()
        val tested = vm.state.await { it.connection is ConnectionUi.Success }
        assertTrue((tested.connection as ConnectionUi.Success).simulated)
        assertEquals("/api/v1/system/status", harness.api.takeRequest().path)

        harness.api.enqueueJson(Fixtures.text("system_status.json"))
        harness.api.enqueueJson(Fixtures.text("screening_config.json"))
        harness.api.enqueueJson(Fixtures.text("screening_lists.json"))
        harness.api.enqueueJson("{}") // the refresh that follows saving the backend: preferences
        harness.api.enqueueJson("{}") // and the safety policy
        vm.useBackend()
        vm.state.await { it.message is UiMessage.Text && it.message.res == R.string.privacy_backend_saved }

        assertTrue(harness.settings.value.backendConfigured)
        assertEquals("the screening key arrived", "c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", harness.settings.value.fingerprintSalt)
    }

    @Test
    fun `an https only build style address problem is reported not sent`() {
        val (harness, vm) = create(configured = false)
        vm.onUrlChange("ftp://example.com")
        vm.testConnection()
        val state = vm.state.await { it.connection is ConnectionUi.InvalidUrl }
        assertTrue(state.connection is ConnectionUi.InvalidUrl)
        assertEquals(0, harness.api.server.requestCount)
    }

    @Test
    fun `disconnecting forgets the address and keeps the phone's own lists`() {
        val (harness, vm) = create()
        runBlocking { harness.screening.addDeviceEntry(ListKind.BLOCKED, "fp1", Samples.MASKED) }
        vm.disconnect()
        vm.state.await { !it.backendConfigured }
        assertEquals("", harness.settings.value.backendUrl)
        assertTrue(runBlocking { harness.db.listEntries().isBlocked("fp1") })
    }

    @Test
    fun `resuming refreshes the safety policy only when a backend exists`() {
        val (harness, vm) = create(configured = false)
        vm.onResume()
        vm.state.await { it.notifications == PermissionUiState.NOT_ASKED }
        assertEquals(0, harness.api.server.requestCount)
    }
}
