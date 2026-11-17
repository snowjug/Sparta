package io.github.snowjug.sparta.ui.diagnostics

import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStatus
import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.repo.DecisionStats
import io.github.snowjug.sparta.data.repo.DecisionStatsCalculator
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.testing.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DecisionStatsTest {
    @Test
    fun `no decisions give empty statistics not a division by zero`() {
        assertEquals(DecisionStats(), DecisionStatsCalculator.of(emptyList()))
    }

    @Test
    fun `counts averages and the nearest rank 95th percentile are exact`() {
        val events = (1..20).map { Samples.event(id = "e$it", latencyMs = it.toLong() * 10, decision = if (it <= 5) "allow" else if (it <= 18) "silence" else "reject", missed = it == 20) }
        val stats = DecisionStatsCalculator.of(events)
        assertEquals(20, stats.total)
        assertEquals(5, stats.allowed)
        assertEquals(13, stats.silenced)
        assertEquals(2, stats.rejected)
        assertEquals(105L, stats.averageLatencyMs) // (10 + 20 + ... + 200) / 20
        assertEquals(190L, stats.p95LatencyMs) // nearest rank: ceil(0.95 * 20) = 19th value
        assertEquals(200L, stats.maxLatencyMs)
        assertEquals(1, stats.deadlineMisses)
    }

    @Test
    fun `a single decision is its own percentile`() {
        val stats = DecisionStatsCalculator.of(listOf(Samples.event(latencyMs = 42)))
        assertEquals(42L, stats.p95LatencyMs)
        assertEquals(42L, stats.maxLatencyMs)
    }
}

class DiagnosticReportTest {
    private val device = DeviceInfo(35, "15", "Google", "Pixel 9", "2026-10-05", "0.1.0", 1, debugBuild = false)

    private fun input(settings: AppSettings = AppSettings(backendUrl = "https://secret-backend.example.com/", strictness = Strictness.STRICT)) = DiagnosticInput(
        generatedAtMs = Samples.NOW,
        device = device,
        role = RoleState(RoleStatus.GRANTED),
        notifications = PermissionUiState.GRANTED,
        contacts = PermissionUiState.NOT_ASKED,
        settings = settings,
        backendReachable = true,
        status = Samples.status(),
        stats = DecisionStatsCalculator.of(listOf(Samples.event(latencyMs = 20), Samples.event(id = "e2", decision = "reject", latencyMs = 40))),
        pendingUploads = 2,
    )

    @Test
    fun `the report states what it leaves out and contains no address number or content`() {
        val report = DiagnosticReport.build(input())
        assertTrue(report.startsWith(DiagnosticReport.HEADER))
        assertTrue(report.contains(DiagnosticReport.NOTE))
        assertFalse("the backend address stays out", report.contains("secret-backend"))
        assertFalse(report.contains("9876543221"))
        assertFalse("masked numbers are not needed either", report.contains("98\u2022"))
    }

    @Test
    fun `it reports the facts support needs`() {
        val report = DiagnosticReport.build(input())
        assertTrue(report.contains("App: 0.1.0 (1) release"))
        assertTrue(report.contains("Android 15 (API 35), Google Pixel 9"))
        assertTrue(report.contains("Screening role: GRANTED"))
        assertTrue(report.contains("notifications=GRANTED, contacts=NOT_ASKED"))
        assertTrue(report.contains("strictness=strict"))
        assertTrue(report.contains("configured=yes, reachable=yes"))
        assertTrue(report.contains("provider=simulator, simulated=yes, live calls=no"))
        assertTrue(report.contains("pending uploads=2"))
        assertTrue(report.contains("total=2, allowed=0, silenced=1, rejected=1"))
        assertTrue(report.contains("avg=30ms, p95=40ms, max=40ms"))
    }

    @Test
    fun `an unconfigured backend and a declined role are visible`() {
        val report = DiagnosticReport.build(
            input(AppSettings()).copy(role = RoleState(RoleStatus.NOT_GRANTED, requestDeclined = true), backendReachable = null, status = null),
        )
        assertTrue(report.contains("Screening role: NOT_GRANTED (request declined)"))
        assertTrue(report.contains("configured=no, reachable=not checked"))
        assertNull(Regex("Telephony:").find(report))
    }
}
