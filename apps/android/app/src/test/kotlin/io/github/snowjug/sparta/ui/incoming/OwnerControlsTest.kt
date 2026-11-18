package io.github.snowjug.sparta.ui.incoming

import io.github.snowjug.sparta.data.remote.dto.CallMode
import io.github.snowjug.sparta.data.remote.dto.CallState
import io.github.snowjug.sparta.data.remote.dto.CallStatus
import io.github.snowjug.sparta.data.remote.dto.ProviderKind
import io.github.snowjug.sparta.testing.Samples
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OwnerControlsTest {

    private fun controls(call: io.github.snowjug.sparta.data.remote.dto.CallDetailDto?) = OwnerControls.evaluate(call).associateBy { it.id }

    private fun active(vararg caps: Pair<String, Boolean>, simulated: Boolean = true, note: String? = null) = Samples.callDetail(
        item = Samples.callItem(status = CallStatus.ACTIVE, attention = true),
        capabilities = Samples.capabilities(
            takeOver = caps.toMap()["takeover"] ?: false,
            cont = caps.toMap()["continue"] ?: false,
            end = caps.toMap()["end"] ?: false,
            simulated = simulated,
            takeoverNote = note,
        ),
    )

    @Test
    fun `nothing is enabled before the call has loaded`() {
        val all = controls(null)
        assertEquals(ControlId.entries.toSet(), all.keys)
        assertTrue(all.values.none { it.enabled })
        assertTrue(all.values.all { it.unavailable == Unavailable.NOT_LOADED })
    }

    @Test
    fun `a live call enables exactly what the provider reports`() {
        val all = controls(active("takeover" to true, "end" to true))
        assertTrue(all.getValue(ControlId.TAKE_OVER).enabled)
        assertFalse("the provider did not offer continue", all.getValue(ControlId.CONTINUE).enabled)
        assertEquals(Unavailable.PROVIDER_CANNOT, all.getValue(ControlId.CONTINUE).unavailable)
        assertTrue(all.getValue(ControlId.END).enabled)
    }

    @Test
    fun `simulated controls say they are simulations and carry the backend note`() {
        val take = controls(active("takeover" to true, note = "Takeover is simulated in the simulator.")).getValue(ControlId.TAKE_OVER)
        assertTrue(take.enabled)
        assertTrue(take.simulated)
        assertEquals("Takeover is simulated in the simulator.", take.note)
    }

    @Test
    fun `a real provider is not labelled a simulation`() {
        val take = controls(active("takeover" to true, simulated = false, note = "Bridges to your number")).getValue(ControlId.TAKE_OVER)
        assertFalse(take.simulated)
        assertNull("the note is only repeated next to simulated controls", take.note)
    }

    @Test
    fun `an ended call has no live controls but can still be blocked and trusted`() {
        val all = controls(Samples.callDetail(item = Samples.callItem(status = CallStatus.ENDED), capabilities = Samples.capabilities(takeOver = true, cont = true, end = true)))
        listOf(ControlId.TAKE_OVER, ControlId.CONTINUE, ControlId.END).forEach {
            assertFalse(all.getValue(it).enabled)
            assertEquals(Unavailable.CALL_ENDED, all.getValue(it).unavailable)
        }
        assertTrue(all.getValue(ControlId.BLOCK).enabled)
        assertTrue(all.getValue(ControlId.TRUST).enabled)
    }

    @Test
    fun `native screening never offers to join or steer a call even if capabilities claim otherwise`() {
        val screening = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false, status = CallStatus.ACTIVE),
            capabilities = Samples.capabilities(takeOver = true, cont = true, end = true, simulated = false),
        )
        val all = controls(screening)
        listOf(ControlId.TAKE_OVER, ControlId.CONTINUE, ControlId.END).forEach {
            assertFalse(all.getValue(it).enabled)
            assertEquals(Unavailable.SCREENING_ONLY, all.getValue(it).unavailable)
        }
    }

    @Test
    fun `taking over twice is refused with a reason`() {
        val call = Samples.callDetail(
            item = Samples.callItem(status = CallStatus.ACTIVE).let { it.copy(state = CallState.OWNER_TAKEOVER) },
            capabilities = Samples.capabilities(takeOver = true, cont = true, end = true),
        )
        val take = controls(call).getValue(ControlId.TAKE_OVER)
        assertFalse(take.enabled)
        assertEquals(Unavailable.ALREADY_TAKEN_OVER, take.unavailable)
    }

    @Test
    fun `blocking follows the provider capability`() {
        val denied = controls(Samples.callDetail(capabilities = Samples.capabilities(block = false))).getValue(ControlId.BLOCK)
        assertFalse(denied.enabled)
        assertEquals(Unavailable.PROVIDER_CANNOT, denied.unavailable)
    }
}

class AudioHonestyTest {
    @Test
    fun `two way audio is claimed only for a real non simulated conversational call that reports it`() {
        val real = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.AZURE, simulated = false),
            capabilities = Samples.capabilities(simulated = false, twoWay = true),
        )
        assertEquals(AudioClaim.TWO_WAY_AUDIO, AudioHonesty.claim(real))
    }

    @Test
    fun `a simulated call never claims real audio even if the flag is set`() {
        val simulated = Samples.callDetail(capabilities = Samples.capabilities(simulated = true, twoWay = true))
        assertEquals(AudioClaim.SIMULATED, AudioHonesty.claim(simulated))
    }

    @Test
    fun `native screening is never two way audio`() {
        val screening = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.ANDROID_SCREENING, mode = CallMode.SCREENING_ONLY, simulated = false),
            capabilities = Samples.capabilities(simulated = false, twoWay = true),
        )
        assertEquals(AudioClaim.NO_AUDIO, AudioHonesty.claim(screening))
    }

    @Test
    fun `a real call without a media stream has no audio claim`() {
        val real = Samples.callDetail(
            item = Samples.callItem(provider = ProviderKind.AZURE, simulated = false),
            capabilities = Samples.capabilities(simulated = false, twoWay = false),
        )
        assertEquals(AudioClaim.NO_AUDIO, AudioHonesty.claim(real))
    }
}
