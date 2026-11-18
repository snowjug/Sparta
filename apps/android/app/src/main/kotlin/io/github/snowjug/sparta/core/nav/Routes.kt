package io.github.snowjug.sparta.core.nav

/** In-app navigation routes. Ids are percent-encoded so any backend id is safe inside a route. */
object Routes {
    const val ONBOARDING = "onboarding"
    const val STATUS = "status"
    const val CALLS = "calls"
    const val STUDIO = "studio"
    const val PRIVACY = "privacy"
    const val DIAGNOSTICS = "diagnostics"

    const val ARG_ID = "id"
    const val CALL_PATTERN = "call/{$ARG_ID}"
    const val INCOMING_PATTERN = "incoming/{$ARG_ID}"
    const val LIVE_PATTERN = "live/{$ARG_ID}"
    const val EVENT_PATTERN = "event/{$ARG_ID}"

    /** Tabs of the main scaffold, in display order. */
    val topLevel: List<String> = listOf(STATUS, CALLS, STUDIO, PRIVACY, DIAGNOSTICS)

    fun isTopLevel(route: String?): Boolean = route != null && route in topLevel

    fun call(id: String) = "call/${encode(id)}"

    fun incoming(id: String) = "incoming/${encode(id)}"

    fun live(id: String) = "live/${encode(id)}"

    fun event(id: String) = "event/${encode(id)}"

    fun forLink(link: DeepLink): String = when (link) {
        is DeepLink.Incoming -> incoming(link.callId)
        is DeepLink.Detail -> call(link.callId)
        is DeepLink.Live -> live(link.callId)
        is DeepLink.ScreeningEvent -> event(link.eventId)
    }

    private fun encode(id: String): String = buildString {
        for (byte in id.toByteArray(Charsets.UTF_8)) {
            val c = byte.toInt().toChar()
            if (byte >= 0 && (c.isLetterOrDigit() || c == '-' || c == '_' || c == '.' || c == '~')) {
                append(c)
            } else {
                append('%').append("%02X".format(byte.toInt() and 0xFF))
            }
        }
    }
}
