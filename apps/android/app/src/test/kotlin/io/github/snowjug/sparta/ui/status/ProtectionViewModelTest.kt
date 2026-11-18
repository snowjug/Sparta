package io.github.snowjug.sparta.ui.status

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.testing.Samples
import io.github.snowjug.sparta.testutil.FakePermissionChecker
import io.github.snowjug.sparta.testutil.FakeRoleController
import io.github.snowjug.sparta.testutil.Fixtures
import io.github.snowjug.sparta.testutil.MainDispatcherRule
import io.github.snowjug.sparta.testutil.TestDeviceInfoProvider
import io.github.snowjug.sparta.testutil.VmHarness
import io.github.snowjug.sparta.testutil.await
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProtectionViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private var h: VmHarness? = null
    private val roles = FakeRoleController()
    private val permissions = FakePermissionChecker()

    @After
    fun tearDown() {
        h?.close()
    }

    private fun create(configured: Boolean = true, initial: (AppSettings) -> AppSettings = { it }): ProtectionViewModel {
        val harness = VmHarness(configured, initial).also { h = it }
        return ProtectionViewModel(
            settings = harness.settings,
            system = harness.system,
            screening = harness.screening,
            roles = roles,
            devices = TestDeviceInfoProvider,
            permissions = PermissionModel(permissions, harness.settings),
            clock = harness.clock,
        )
    }

    // ---- the call-screening role ----

    @Test
    fun `the role is read when the screen opens and again on resume`() {
        val vm = create(configured = false)
        assertEquals(RoleStatus.NOT_GRANTED, vm.state.await { it.device != null }.role.status)

        roles.held = true // switched on in system settings, behind the app's back
        vm.onResume()

        vm.state.await { it.role.status == RoleStatus.GRANTED }
    }

    @Test
    fun `declining the system dialog is remembered and accepting it clears that`() {
        val vm = create(configured = false)

        vm.onRoleResult(granted = false)
        val declined = vm.state.await { it.role.requestDeclined }
        assertEquals(RoleStatus.NOT_GRANTED, declined.role.status)
        assertTrue(h!!.settings.value.roleRequestDeclined)

        roles.held = true
        vm.onRoleResult(granted = true)
        vm.state.await { it.role.status == RoleStatus.GRANTED }
        assertFalse(h!!.settings.value.roleRequestDeclined)
    }

    @Test
    fun `a phone older than Android 10 is explained and cannot be asked for the role`() {
        roles.sdk = 28
        val vm = create(configured = false)

        assertEquals(RoleStatus.UNSUPPORTED_API, vm.state.await { it.device != null }.role.status)
        assertNull(vm.roleRequestIntent())
    }

    @Test
    fun `a phone that does not offer the role says so and cannot be asked for it`() {
        roles.available = false
        val vm = create(configured = false)

        assertEquals(RoleStatus.ROLE_UNAVAILABLE, vm.state.await { it.device != null }.role.status)
        assertNull(vm.roleRequestIntent())
    }

    @Test
    fun `a phone with the role gets the system request intent`() {
        val vm = create(configured = false)
        assertEquals("test.REQUEST_ROLE", vm.roleRequestIntent()?.action)
    }

    // ---- the backend ----

    @Test
    fun `without a backend the status says so and nothing is requested`() {
        val vm = create(configured = false)

        vm.refresh()
        val state = vm.state.await { it.backend == BackendReachability.NotConfigured }

        assertFalse(state.backendConfigured)
        assertEquals(0, h!!.api.server.requestCount)
    }

    @Test
    fun `a reachable backend is reported its screening key is pulled and calls that need the owner are counted`() {
        val vm = create()
        val item = SpartaJson.encodeToString(CallListItemDto.serializer(), Samples.callItem(attention = true))
        h!!.api.serve(
            "/api/v1/system/status" to Fixtures.text("system_status.json"),
            "/api/v1/screening/config" to Fixtures.text("screening_config.json"),
            "/api/v1/screening/lists" to Fixtures.text("screening_lists.json"),
            "/api/v1/home" to """{"attention":[$item,$item],"recent":[]}""",
        )

        vm.refresh()
        val state = vm.state.await { it.backend is BackendReachability.Reachable && it.attentionCount == 2 }

        assertEquals("0.1.0", state.status?.version)
        assertTrue("the simulator is labelled as one", state.simulated)
        assertFalse("no live calls are claimed", state.liveCallsSupported)
        assertTrue(state.devBanner)
        assertEquals("c3BhcnRhLXRlc3QtZmluZ2VycHJpbnQtc2FsdC0wMDAx", h!!.settings.value.fingerprintSalt)
    }

    @Test
    fun `an unreachable backend is reported and the last known status stays visible`() {
        val vm = create(initial = { it.copy(cachedStatusJson = Fixtures.text("system_status.json"), cachedStatusAtMs = 1_000L) })
        h!!.api.server.shutdown()

        vm.refresh()
        val state = vm.state.await { it.backend is BackendReachability.Unreachable }

        val unreachable = state.backend as BackendReachability.Unreachable
        assertTrue(unreachable.hasCachedStatus)
        assertEquals("0.1.0", state.status?.version)
        assertEquals(false, state.refreshing)
    }

    // ---- forwarding and notifications ----

    @Test
    fun `forwarding is only the owner's own note and the dialer helper is timestamped`() {
        val vm = create(configured = false)

        vm.confirmForwarding(true)
        vm.state.await { it.forwardingConfirmed }
        assertTrue(h!!.settings.value.forwardingConfirmedByOwner)

        vm.forwardingHelperOpened()
        val state = vm.state.await { it.forwardingHelperOpenedAtMs != null }
        assertEquals(h!!.clock.nowMs(), state.forwardingHelperOpenedAtMs)

        vm.confirmForwarding(false)
        vm.state.await { !it.forwardingConfirmed }
    }

    @Test
    fun `a refused notification prompt is interpreted and a later grant in settings is noticed on resume`() {
        val vm = create(configured = false)

        vm.onNotificationPermissionResult(granted = false, shouldShowRationale = false)
        vm.state.await { it.notifications == PermissionUiState.DENIED_PERMANENTLY }
        assertTrue(h!!.settings.value.notificationsPermissionAsked)

        permissions.notifications = true
        vm.onResume()
        vm.state.await { it.notifications == PermissionUiState.GRANTED }
    }
}
