package io.github.snowjug.sparta.core.net

import java.net.URI
import java.net.URISyntaxException

enum class BackendUrlProblem {
    EMPTY,
    MALFORMED,
    UNSUPPORTED_SCHEME,
    HTTPS_REQUIRED,
    CREDENTIALS_NOT_ALLOWED,
    QUERY_OR_FRAGMENT_NOT_ALLOWED,
}

sealed interface BackendUrlResult {
    /** [url] always ends with "/" and has a lower-case scheme and host. */
    data class Valid(val url: String, val isCleartext: Boolean) : BackendUrlResult

    data class Invalid(val problem: BackendUrlProblem) : BackendUrlResult
}

/**
 * Validates the backend URL typed by the owner.
 *
 * Release builds accept https only. Debug builds additionally accept http for loopback, the emulator host alias
 * (10.0.2.2), private LAN addresses and *.local names, because Android's network security config cannot express
 * "LAN only" and cleartext is permitted for debug builds as a whole.
 */
class BackendUrlPolicy(private val allowLocalCleartext: Boolean) {

    fun validate(input: String?): BackendUrlResult {
        val text = input?.trim().orEmpty()
        if (text.isEmpty()) return BackendUrlResult.Invalid(BackendUrlProblem.EMPTY)

        val withScheme = if (SCHEME_PATTERN.containsMatchIn(text)) text else "https://$text"
        val uri = try {
            URI(withScheme)
        } catch (_: URISyntaxException) {
            return BackendUrlResult.Invalid(BackendUrlProblem.MALFORMED)
        }

        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return BackendUrlResult.Invalid(BackendUrlProblem.UNSUPPORTED_SCHEME)
        val host = uri.host?.lowercase()
        if (host.isNullOrEmpty()) return BackendUrlResult.Invalid(BackendUrlProblem.MALFORMED)
        if (uri.userInfo != null) return BackendUrlResult.Invalid(BackendUrlProblem.CREDENTIALS_NOT_ALLOWED)
        if (uri.rawQuery != null || uri.rawFragment != null) {
            return BackendUrlResult.Invalid(BackendUrlProblem.QUERY_OR_FRAGMENT_NOT_ALLOWED)
        }

        val cleartext = scheme == "http"
        if (cleartext && !(allowLocalCleartext && isLocalHost(host))) {
            return BackendUrlResult.Invalid(BackendUrlProblem.HTTPS_REQUIRED)
        }

        val port = if (uri.port == -1) "" else ":${uri.port}"
        val path = uri.rawPath.orEmpty().trimEnd('/')
        val hostForUrl = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
        return BackendUrlResult.Valid("$scheme://$hostForUrl$port$path/", cleartext)
    }

    companion object {
        private val SCHEME_PATTERN = Regex("^[A-Za-z][A-Za-z0-9+.-]*://")

        fun isLocalHost(host: String): Boolean {
            val h = host.lowercase().removePrefix("[").removeSuffix("]")
            if (h == "localhost" || h == "10.0.2.2" || h == "::1" || h.endsWith(".local")) return true
            val octets = h.split('.').map { it.toIntOrNull() ?: return false }
            if (octets.size != 4 || octets.any { it !in 0..255 }) return false
            val (a, b) = octets
            return a == 127 ||
                a == 10 ||
                (a == 172 && b in 16..31) ||
                (a == 192 && b == 168) ||
                (a == 169 && b == 254)
        }
    }
}
