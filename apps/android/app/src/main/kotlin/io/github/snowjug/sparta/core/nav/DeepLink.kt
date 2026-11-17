package io.github.snowjug.sparta.core.nav

import java.net.URI
import java.net.URISyntaxException

/** Targets reachable from notifications and links: sparta://call/{id}[/detail|/live] and sparta://event/{id}. */
sealed interface DeepLink {
    /** Incoming-call intelligence for a call that may need the owner. */
    data class Incoming(val callId: String) : DeepLink

    data class Detail(val callId: String) : DeepLink

    data class Live(val callId: String) : DeepLink

    /** A decision made natively on this phone (no backend call needed). */
    data class ScreeningEvent(val eventId: String) : DeepLink
}

object DeepLinks {
    const val SCHEME = "sparta"
    const val HOST_CALL = "call"
    const val HOST_EVENT = "event"
    private val ID_PATTERN = Regex("^[A-Za-z0-9_-]{1,64}$")

    fun incoming(callId: String): String = build(HOST_CALL, callId, null)

    fun detail(callId: String): String = build(HOST_CALL, callId, "detail")

    fun live(callId: String): String = build(HOST_CALL, callId, "live")

    fun screeningEvent(eventId: String): String = build(HOST_EVENT, eventId, null)

    private fun build(host: String, id: String, suffix: String?): String {
        require(ID_PATTERN.matches(id)) { "invalid id" }
        return "$SCHEME://$host/$id" + (suffix?.let { "/$it" } ?: "")
    }

    /** Returns null for anything that is not a well-formed Sparta link; the id is validated, never trusted. */
    fun parse(uri: String?): DeepLink? {
        if (uri.isNullOrBlank()) return null
        val parsed = try {
            URI(uri.trim())
        } catch (_: URISyntaxException) {
            return null
        }
        if (!SCHEME.equals(parsed.scheme, ignoreCase = true)) return null
        if (parsed.userInfo != null || parsed.port != -1) return null
        val host = parsed.host?.lowercase() ?: return null

        val segments = parsed.rawPath.orEmpty().split('/').filter { it.isNotEmpty() }
        val id = segments.firstOrNull() ?: return null
        if (!ID_PATTERN.matches(id)) return null
        return when (host) {
            HOST_CALL -> when (segments.size) {
                1 -> DeepLink.Incoming(id)
                2 -> when (segments[1].lowercase()) {
                    "detail" -> DeepLink.Detail(id)
                    "live" -> DeepLink.Live(id)
                    else -> null
                }
                else -> null
            }
            HOST_EVENT -> if (segments.size == 1) DeepLink.ScreeningEvent(id) else null
            else -> null
        }
    }
}
