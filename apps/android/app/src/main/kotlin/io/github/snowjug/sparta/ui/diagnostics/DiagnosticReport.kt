package io.github.snowjug.sparta.ui.diagnostics

import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.time.Timestamps
import io.github.snowjug.sparta.data.prefs.AppSettings
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.repo.DecisionStats
import io.github.snowjug.sparta.platform.DeviceInfo

/** Everything the report may mention. There is deliberately no field for a number, a transcript or the backend address. */
data class DiagnosticInput(
    val generatedAtMs: Long,
    val device: DeviceInfo?,
    val role: RoleState,
    val notifications: PermissionUiState,
    val contacts: PermissionUiState,
    val settings: AppSettings,
    val backendReachable: Boolean?,
    val status: SystemStatusDto?,
    val stats: DecisionStats,
    val pendingUploads: Int,
)

/** Plain-text report the owner can share when something is wrong. Sanitised by construction. */
object DiagnosticReport {
    const val HEADER = "SPARTA ANDROID DIAGNOSTIC REPORT"
    const val NOTE = "Sanitised: no phone numbers, no call content and no backend address are included."

    fun build(input: DiagnosticInput): String = buildString {
        val s = input.settings
        appendLine(HEADER)
        appendLine(NOTE)
        appendLine("Generated: ${Timestamps.formatIsoUtc(input.generatedAtMs)}")
        input.device?.let { d ->
            appendLine("App: ${d.appVersionName} (${d.appVersionCode}) ${if (d.debugBuild) "debug" else "release"}")
            appendLine("Device: Android ${d.androidRelease} (API ${d.apiLevel}), ${d.manufacturer} ${d.model}")
            d.securityPatch?.let { appendLine("Security patch: $it") }
        }
        appendLine("Screening role: ${input.role.status}${if (input.role.requestDeclined) " (request declined)" else ""}")
        appendLine("Permissions: notifications=${input.notifications}, contacts=${input.contacts}, contacts-as-known=${onOff(s.useContactsAsKnown)}")
        appendLine("Policy: unknown=${s.unknownCallerBehavior.wire}, trusted=${s.trustedContactBehavior.wire}, strictness=${s.strictness.wire}")
        appendLine("Backend: configured=${yesNo(s.backendConfigured)}, reachable=${input.backendReachable?.let(::yesNo) ?: "not checked"}")
        input.status?.let { st ->
            appendLine("Backend version: ${st.version}, env=${st.env}, auth=${st.authMode}")
            appendLine("Telephony: provider=${st.telephony.provider}, simulated=${yesNo(st.telephony.simulated)}, live calls=${yesNo(st.telephony.liveCallsSupported)}")
            appendLine("Policy/language pack: ${st.policyVersion} / ${st.languagePackVersion}")
        }
        appendLine("Sync: last=${s.lastSyncAtMs?.let(Timestamps::formatIsoUtc) ?: "never"}, last error=${s.lastSyncError ?: "none"}, pending uploads=${input.pendingUploads}, background sync=${onOff(s.backgroundSyncEnabled)}")
        val st = input.stats
        appendLine(
            "Decisions: total=${st.total}, allowed=${st.allowed}, silenced=${st.silenced}, rejected=${st.rejected}, " +
                "avg=${ms(st.averageLatencyMs)}, p95=${ms(st.p95LatencyMs)}, max=${ms(st.maxLatencyMs)}, deadline misses=${st.deadlineMisses} (lifetime ${s.deadlineMissCount})",
        )
    }

    private fun yesNo(value: Boolean) = if (value) "yes" else "no"

    private fun onOff(value: Boolean) = if (value) "on" else "off"

    private fun ms(value: Long?) = value?.let { "${it}ms" } ?: "n/a"
}
