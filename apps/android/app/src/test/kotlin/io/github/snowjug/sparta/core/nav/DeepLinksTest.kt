package io.github.snowjug.sparta.core.nav

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class DeepLinksTest {

    @Test
    fun `call link opens incoming call intelligence`() {
        assertEquals(DeepLink.Incoming("call_123"), DeepLinks.parse("sparta://call/call_123"))
        assertEquals(DeepLink.Incoming("abc-DEF_9"), DeepLinks.parse("sparta://call/abc-DEF_9/"))
    }

    @Test
    fun `detail and live suffixes`() {
        assertEquals(DeepLink.Detail("c1"), DeepLinks.parse("sparta://call/c1/detail"))
        assertEquals(DeepLink.Live("c1"), DeepLinks.parse("sparta://call/c1/live"))
        assertEquals(DeepLink.Live("c1"), DeepLinks.parse("SPARTA://CALL/c1/LIVE"))
    }

    @Test
    fun `query strings are ignored`() {
        assertEquals(DeepLink.Incoming("c1"), DeepLinks.parse("sparta://call/c1?source=notification"))
    }

    @Test
    fun `malformed or foreign links are rejected`() {
        assertNull(DeepLinks.parse(null))
        assertNull(DeepLinks.parse(""))
        assertNull(DeepLinks.parse("https://call/c1"))
        assertNull(DeepLinks.parse("sparta://other/c1"))
        assertNull(DeepLinks.parse("sparta://call"))
        assertNull(DeepLinks.parse("sparta://call/"))
        assertNull(DeepLinks.parse("sparta://call/c1/unknown"))
        assertNull(DeepLinks.parse("sparta://call/c1/detail/extra"))
        assertNull(DeepLinks.parse("sparta://call/has space"))
        assertNull(DeepLinks.parse("sparta://call/%2e%2e"))
        assertNull(DeepLinks.parse("sparta://user:pw@call/c1"))
        assertNull(DeepLinks.parse("sparta://call:8080/c1"))
        assertNull(DeepLinks.parse("not a uri at all ::"))
    }

    @Test
    fun `over long ids are rejected`() {
        assertNull(DeepLinks.parse("sparta://call/" + "a".repeat(65)))
        assertEquals(DeepLink.Incoming("a".repeat(64)), DeepLinks.parse("sparta://call/" + "a".repeat(64)))
    }

    @Test
    fun `builders round trip through the parser`() {
        assertEquals("sparta://call/c9", DeepLinks.incoming("c9"))
        assertEquals(DeepLink.Incoming("c9"), DeepLinks.parse(DeepLinks.incoming("c9")))
        assertEquals(DeepLink.Detail("c9"), DeepLinks.parse(DeepLinks.detail("c9")))
        assertEquals(DeepLink.Live("c9"), DeepLinks.parse(DeepLinks.live("c9")))
    }

    @Test
    fun `builders refuse invalid ids`() {
        assertThrows(IllegalArgumentException::class.java) { DeepLinks.incoming("bad id") }
        assertThrows(IllegalArgumentException::class.java) { DeepLinks.incoming("") }
        assertThrows(IllegalArgumentException::class.java) { DeepLinks.screeningEvent("a/b") }
    }

    @Test
    fun `screening event links open the on device decision`() {
        val id = "7d3f0a52-0000-4000-8000-000000000001"
        assertEquals(DeepLink.ScreeningEvent(id), DeepLinks.parse("sparta://event/$id"))
        assertEquals("sparta://event/$id", DeepLinks.screeningEvent(id))
        assertEquals(DeepLink.ScreeningEvent(id), DeepLinks.parse(DeepLinks.screeningEvent(id)))
        assertNull(DeepLinks.parse("sparta://event/$id/detail"))
        assertNull(DeepLinks.parse("sparta://event"))
        assertNull(DeepLinks.parse("sparta://events/$id"))
    }
}
