package io.github.snowjug.sparta.core.role

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RoleStateMapperTest {

    @Test
    fun `android 9 and lower is an unsupported device even if a role claim is passed`() {
        for (sdk in listOf(26, 27, 28)) {
            val state = RoleStateMapper.map(sdkInt = sdk, roleAvailable = true, roleHeld = true)
            assertEquals(RoleStatus.UNSUPPORTED_API, state.status)
            assertFalse(state.canRequestRole)
            assertFalse(state.isScreeningActive)
        }
    }

    @Test
    fun `older devices may pass null role information`() {
        assertEquals(RoleStatus.UNSUPPORTED_API, RoleStateMapper.map(28, null, null).status)
    }

    @Test
    fun `android 10 without the role is role unavailable`() {
        val state = RoleStateMapper.map(sdkInt = 29, roleAvailable = false, roleHeld = false)
        assertEquals(RoleStatus.ROLE_UNAVAILABLE, state.status)
        assertFalse(state.canRequestRole)
    }

    @Test
    fun `unknown availability is treated as unavailable rather than guessed`() {
        assertEquals(RoleStatus.ROLE_UNAVAILABLE, RoleStateMapper.map(34, null, null).status)
    }

    @Test
    fun `available and held is granted`() {
        val state = RoleStateMapper.map(sdkInt = 36, roleAvailable = true, roleHeld = true)
        assertEquals(RoleStatus.GRANTED, state.status)
        assertTrue(state.isScreeningActive)
        assertFalse(state.canRequestRole)
    }

    @Test
    fun `available but not held can be requested`() {
        val state = RoleStateMapper.map(sdkInt = 33, roleAvailable = true, roleHeld = false)
        assertEquals(RoleStatus.NOT_GRANTED, state.status)
        assertTrue(state.canRequestRole)
        assertFalse(state.requestDeclined)
    }

    @Test
    fun `a declined request is remembered until the role is granted`() {
        val declined = RoleStateMapper.map(sdkInt = 33, roleAvailable = true, roleHeld = false, requestDeclined = true)
        assertEquals(RoleStatus.NOT_GRANTED, declined.status)
        assertTrue(declined.requestDeclined)

        val granted = RoleStateMapper.map(sdkInt = 33, roleAvailable = true, roleHeld = true, requestDeclined = true)
        assertEquals(RoleStatus.GRANTED, granted.status)
        assertFalse(granted.requestDeclined)
    }

    @Test
    fun `api 29 is the first supported level`() {
        assertEquals(29, RoleStateMapper.MIN_ROLE_SDK)
        assertEquals(RoleStatus.NOT_GRANTED, RoleStateMapper.map(29, true, false).status)
    }
}
