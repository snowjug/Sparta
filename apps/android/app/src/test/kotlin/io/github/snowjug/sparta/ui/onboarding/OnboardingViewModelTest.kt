package io.github.snowjug.sparta.ui.onboarding

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.net.BackendUrlPolicy
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.ConnectionTester
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.testutil.FakePermissionChecker
import io.github.snowjug.sparta.testutil.FakeRoleController
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.TestDeviceInfoProvider
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OnboardingViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private var h: VmHarness? = null
    private val roles = FakeRoleController()
    private val permissions = FakePermissionChecker()

    @After
    fun tearDown() {
        h?.close()
    }

    private fun create(configured: Boolean = false): OnboardingViewModel {
        val harness = VmHarness(configured).also { h = it }
        val tester = ConnectionTester(harness.api.client, SpartaJson, BackendUrlPolicy(allowLocalCleartext = true), MonotonicClock { 0L })
        return OnboardingViewModel(
            settings = harness.settings,
            connector = BackendConnector(tester, harness.settings, harness.screening, harness.system),
            roles = roles,
            permissions = PermissionModel(permissions, harness.settings),
            preferences = harness.preferences,
            devices = TestDeviceInfoProvider,
        )
    }

    private fun serveBackend() = h!!.api.serve(
        "/api/v1/system/status" to Fixtures.text("system_status.json"),
        "/api/v1/screening/config" to Fixtures.text("screening_config.json"),
        "/api/v1/screening/lists" to Fixtures.text("screening_lists.json"),
    )

    @Test
    fun `the steps go forward and back and stop at both ends`() {
        val vm = create()
        assertEquals(OnboardingStep.WELCOME, vm.state.value.step)
        assertFalse(vm.state.value.canGoBack)

        vm.back()
        assertEquals(OnboardingStep.WELCOME, vm.state.value.step)

        repeat(OnboardingStep.count + 2) { vm.next() }
        assertEquals(OnboardingStep.FORWARDING, vm.state.value.step)
        assertTrue(vm.state.value.isLastStep)

        vm.back()
        assertEquals(OnboardingStep.PERMISSIONS, vm.state.value.step)
        assertTrue(vm.state.value.canGoBack)
    }

    // ---- connecting the backend ----

    @Test
    fun `testing an address saves nothing and using it saves it and pulls the screening key`() {
        val vm = create()
        serveBackend()
        vm.onUrlChange("http://localhost:${h!!.api.server.port}/")

        vm.testConnection()
        val tested = vm.state.await { it.connection is ConnectionUi.Success }
        assertFalse("a test is read-only", h!!.settings.value.backendConfigured)
        assertFalse(tested.backendSaved)

        vm.useBackend()
        vm.state.await { it.backendSaved }
        assertTrue(h!!.settings.value.backendConfigured)
        assertEquals("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", h!!.settings.value.fingerprintSalt)
    }

    @Test
    fun `an address the app refuses is reported and nothing is sent`() {
        val vm = create()
        vm.onUrlChange("ftp://example.com")

        vm.testConnection()
        vm.state.await { it.connection is ConnectionUi.InvalidUrl }
        vm.useBackend()

        assertFalse(vm.state.value.backendSaved)
        assertEquals(0, h!!.api.server.requestCount)
    }

    @Test
    fun `editing the address clears an earlier result`() {
        val vm = create()
        serveBackend()
        vm.onUrlChange("http://localhost:${h!!.api.server.port}/")
        vm.testConnection()
        vm.state.await { it.connection is ConnectionUi.Success }

        vm.onUrlChange("http://localhost:1/")

        assertEquals(ConnectionUi.Idle, vm.state.value.connection)
    }

    // ---- the role ----

    @Test
    fun `declining the role is remembered and a grant in system settings is noticed later`() {
        val vm = create()

        vm.onRoleResult(granted = false)
        vm.state.await { it.role.requestDeclined }
        assertTrue(h!!.settings.value.roleRequestDeclined)

        roles.held = true
        vm.refreshPermissions()
        vm.state.await { it.role.status == RoleStatus.GRANTED }
    }

    // ---- permissions ----

    @Test
    fun `notification refusals are told apart and recorded`() {
        val vm = create()

        vm.onNotificationsResult(granted = false, shouldShowRationale = true)
        vm.state.await { it.notifications == PermissionUiState.DENIED_CAN_ASK_AGAIN }
        assertTrue(h!!.settings.value.notificationsPermissionAsked)

        vm.onNotificationsResult(granted = false, shouldShowRationale = false)
        vm.state.await { it.notifications == PermissionUiState.DENIED_PERMANENTLY }

        vm.onNotificationsResult(granted = true, shouldShowRationale = false)
        vm.state.await { it.notifications == PermissionUiState.GRANTED }
    }

    @Test
    fun `saved contacts are used only after the permission was granted and switching off needs no prompt`() {
        val vm = create()

        vm.onContactsResult(granted = false, shouldShowRationale = false)
        val refused = vm.state.await { it.contacts == PermissionUiState.DENIED_PERMANENTLY }
        assertFalse(refused.useContactsAsKnown)
        assertFalse(h!!.settings.value.useContactsAsKnown)
        assertTrue(h!!.settings.value.contactsPermissionAsked)

        permissions.contacts = true
        vm.onContactsResult(granted = true, shouldShowRationale = false)
        vm.state.await { it.useContactsAsKnown }
        assertTrue(h!!.settings.value.useContactsAsKnown)

        vm.disableContactsOption()
        vm.state.await { !it.useContactsAsKnown }
        assertFalse(h!!.settings.value.useContactsAsKnown)
    }

    @Test
    fun `the contacts option is dropped when the permission is revoked behind the app's back`() {
        val vm = create()
        permissions.contacts = true
        vm.onContactsResult(granted = true, shouldShowRationale = false)
        vm.state.await { it.useContactsAsKnown }

        permissions.contacts = false // revoked in system settings
        vm.refreshPermissions()

        vm.state.await { !it.useContactsAsKnown }
    }

    // ---- finishing ----

    @Test
    fun `finishing without a backend completes setup on the phone only`() {
        val vm = create(configured = false)

        vm.finish()
        vm.state.await { it.finished }

        assertTrue(h!!.settings.value.onboardingCompleted)
        assertEquals(0, h!!.api.server.requestCount)
    }

    @Test
    fun `finishing with a backend also tells the backend and keeps fields this app does not know`() {
        val vm = create(configured = true)
        h!!.api.serve("/api/v1/preferences" to """{"onboarding_completed":false,"future_field":{"keep":"me"}}""")

        vm.finish()
        vm.state.await { it.finished }

        assertTrue(h!!.settings.value.onboardingCompleted)
        assertEquals("GET", h!!.api.takeRequest().method)
        val put = h!!.api.takeRequest()
        assertEquals("PUT", put.method)
        val body = SpartaJson.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("true", body.getValue("onboarding_completed").jsonPrimitive.content)
        assertTrue("future_field" in body)
    }
}
