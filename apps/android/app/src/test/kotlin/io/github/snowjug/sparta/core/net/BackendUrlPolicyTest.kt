package io.github.snowjug.sparta.core.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackendUrlPolicyTest {

    private val release = BackendUrlPolicy(allowLocalCleartext = false)
    private val debug = BackendUrlPolicy(allowLocalCleartext = true)

    private fun valid(policy: BackendUrlPolicy, input: String): BackendUrlResult.Valid {
        val result = policy.validate(input)
        assertTrue("expected valid for '$input' but was $result", result is BackendUrlResult.Valid)
        return result as BackendUrlResult.Valid
    }

    private fun problem(policy: BackendUrlPolicy, input: String?): BackendUrlProblem {
        val result = policy.validate(input)
        assertTrue("expected invalid for '$input' but was $result", result is BackendUrlResult.Invalid)
        return (result as BackendUrlResult.Invalid).problem
    }

    @Test
    fun `https urls are normalized with a trailing slash`() {
        assertEquals("https://api.example.invalid/", valid(release, "https://api.example.invalid").url)
        assertEquals("https://api.example.invalid/sparta/", valid(release, "HTTPS://API.Example.invalid/sparta").url)
        assertEquals("https://api.example.invalid:8443/", valid(release, " https://api.example.invalid:8443/ ").url)
        assertFalse(valid(release, "https://api.example.invalid").isCleartext)
    }

    @Test
    fun `a bare host defaults to https`() {
        assertEquals("https://api.example.invalid/", valid(release, "api.example.invalid").url)
    }

    @Test
    fun `release builds refuse cleartext everywhere`() {
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(release, "http://10.0.2.2:8000"))
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(release, "http://api.example.invalid"))
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(release, "http://localhost:8000"))
    }

    @Test
    fun `debug builds allow cleartext only for local hosts`() {
        assertEquals("http://10.0.2.2:8000/", valid(debug, "http://10.0.2.2:8000").url)
        assertTrue(valid(debug, "http://10.0.2.2:8000").isCleartext)
        assertEquals("http://localhost:8000/", valid(debug, "http://localhost:8000").url)
        assertEquals("http://127.0.0.1:8000/", valid(debug, "http://127.0.0.1:8000/").url)
        assertEquals("http://192.168.1.20:8000/", valid(debug, "http://192.168.1.20:8000").url)
        assertEquals("http://172.20.0.5/", valid(debug, "http://172.20.0.5").url)
        assertEquals("http://dev-box.local:8000/", valid(debug, "http://dev-box.local:8000").url)
        assertEquals("http://[::1]:8000/", valid(debug, "http://[::1]:8000").url)
    }

    @Test
    fun `debug builds still refuse cleartext to public hosts`() {
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(debug, "http://api.example.invalid"))
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(debug, "http://8.8.8.8"))
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(debug, "http://172.32.0.1"))
        assertEquals(BackendUrlProblem.HTTPS_REQUIRED, problem(debug, "http://192.169.1.1"))
    }

    @Test
    fun `https is always fine in debug too`() {
        assertEquals("https://10.0.2.2:8443/", valid(debug, "https://10.0.2.2:8443").url)
    }

    @Test
    fun `empty malformed and unsupported inputs are rejected`() {
        assertEquals(BackendUrlProblem.EMPTY, problem(release, null))
        assertEquals(BackendUrlProblem.EMPTY, problem(release, "   "))
        assertEquals(BackendUrlProblem.UNSUPPORTED_SCHEME, problem(release, "ftp://example.invalid"))
        assertEquals(BackendUrlProblem.UNSUPPORTED_SCHEME, problem(release, "javascript://example.invalid"))
        assertEquals(BackendUrlProblem.MALFORMED, problem(release, "https://"))
        assertEquals(BackendUrlProblem.MALFORMED, problem(release, "https://exa mple.invalid"))
    }

    @Test
    fun `credentials queries and fragments are rejected`() {
        assertEquals(BackendUrlProblem.CREDENTIALS_NOT_ALLOWED, problem(release, "https://user:pw@api.example.invalid"))
        assertEquals(BackendUrlProblem.QUERY_OR_FRAGMENT_NOT_ALLOWED, problem(release, "https://api.example.invalid/?a=1"))
        assertEquals(BackendUrlProblem.QUERY_OR_FRAGMENT_NOT_ALLOWED, problem(release, "https://api.example.invalid/#x"))
    }

    @Test
    fun `local host classification`() {
        assertTrue(BackendUrlPolicy.isLocalHost("10.1.2.3"))
        assertTrue(BackendUrlPolicy.isLocalHost("169.254.10.10"))
        assertFalse(BackendUrlPolicy.isLocalHost("11.0.0.1"))
        assertFalse(BackendUrlPolicy.isLocalHost("999.0.0.1"))
        assertFalse(BackendUrlPolicy.isLocalHost("example.invalid"))
    }
}
