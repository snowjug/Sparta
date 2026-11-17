package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.data.local.ScreeningEventEntity
import kotlin.math.ceil

/** Aggregates over recorded native screening decisions (never numbers or content). */
data class DecisionStats(
    val total: Int = 0,
    val allowed: Int = 0,
    val silenced: Int = 0,
    val rejected: Int = 0,
    val averageLatencyMs: Long? = null,
    val p95LatencyMs: Long? = null,
    val maxLatencyMs: Long? = null,
    val deadlineMisses: Int = 0,
)

object DecisionStatsCalculator {
    fun of(events: List<ScreeningEventEntity>): DecisionStats {
        if (events.isEmpty()) return DecisionStats()
        val latencies = events.map { it.decisionLatencyMs }.sorted()
        // Nearest-rank percentile: the smallest value that at least 95 % of the decisions did not exceed.
        val p95Index = (ceil(0.95 * latencies.size).toInt() - 1).coerceIn(0, latencies.lastIndex)
        return DecisionStats(
            total = events.size,
            allowed = events.count { it.decision == "allow" },
            silenced = events.count { it.decision == "silence" },
            rejected = events.count { it.decision == "reject" },
            averageLatencyMs = latencies.sum() / latencies.size,
            p95LatencyMs = latencies[p95Index],
            maxLatencyMs = latencies.last(),
            deadlineMisses = events.count { it.deadlineMissed },
        )
    }
}
