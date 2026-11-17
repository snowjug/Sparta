package io.github.snowjug.sparta.core.screening

import io.github.snowjug.sparta.core.notify.EscalationNoticePolicy
import io.github.snowjug.sparta.core.notify.QuietHours
import io.github.snowjug.sparta.core.permissions.PermissionStates
import io.github.snowjug.sparta.core.permissions.PermissionUiState
import io.github.snowjug.sparta.data.repo.UploadOutcome
import io.github.snowjug.sparta.data.remote.ApiError
import io.github.snowjug.sparta.data.remote.ApiErrorKind
import io.github.snowjug.sparta.work.UploadWorkDecision
import io.github.snowjug.sparta.work.UploadWorkPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlatformCodesTest {

    @Test
    fun `call direction constants`() {
        assertEquals(CallDirection.INCOMING, PlatformCodes.direction(0))
        assertEquals(CallDirection.OUTGOING, PlatformCodes.direction(1))
        assertEquals(CallDirection.UNKNOWN, PlatformCodes.direction(-1))
        assertEquals(CallDirection.UNKNOWN, PlatformCodes.direction(null))
        assertEquals(CallDirection.UNKNOWN, PlatformCodes.direction(7))
    }

    @Test
    fun `stir shaken verification constants`() {
        assertEquals(CallerVerification.NOT_VERIFIED, PlatformCodes.verification(0))
        assertEquals(CallerVerification.PASSED, PlatformCodes.verification(1))
        assertEquals(CallerVerification.FAILED, PlatformCodes.verification(2))
        assertEquals(CallerVerification.UNKNOWN, PlatformCodes.verification(null))
        assertEquals(CallerVerification.UNKNOWN, PlatformCodes.verification(99))
    }

    @Test
    fun `wire values uploaded to the backend are stable`() {
        assertEquals("not_verified", CallerVerification.NOT_VERIFIED.wire)
        assertEquals("failed", CallerVerification.FAILED.wire)
        assertEquals("incoming", CallDirection.INCOMING.wire)
        assertEquals("unknown_screened", ScreeningReason.UNKNOWN_SCREENED.wire)
        assertEquals("silence", ScreeningAction.SILENCE.wire)
        assertEquals(ScreeningReason.BLOCKED_NUMBER, ScreeningReason.fromWire("blocked_number"))
        assertNull(ScreeningReason.fromWire("nonsense"))
    }
}

class PermissionStatesTest {

    @Test
    fun `result of a system prompt`() {
        assertEquals(PermissionUiState.GRANTED, PermissionStates.afterRequest(granted = true, shouldShowRationale = false))
        assertEquals(PermissionUiState.DENIED_CAN_ASK_AGAIN, PermissionStates.afterRequest(granted = false, shouldShowRationale = true))
        assertEquals(PermissionUiState.DENIED_PERMANENTLY, PermissionStates.afterRequest(granted = false, shouldShowRationale = false))
    }

    @Test
    fun `state when a screen opens`() {
        assertEquals(PermissionUiState.NOT_REQUIRED, PermissionStates.current(granted = false, required = false, requestedBefore = false, shouldShowRationale = false))
        assertEquals(PermissionUiState.GRANTED, PermissionStates.current(true, true, false, false))
        assertEquals(PermissionUiState.NOT_ASKED, PermissionStates.current(false, true, false, false))
        assertEquals(PermissionUiState.DENIED_CAN_ASK_AGAIN, PermissionStates.current(false, true, true, true))
        assertEquals(PermissionUiState.DENIED_PERMANENTLY, PermissionStates.current(false, true, true, false))
    }
}

class QuietHoursTest {

    private fun minutes(h: Int, m: Int = 0) = h * 60 + m

    @Test
    fun `window within a day`() {
        assertTrue(QuietHours.isQuiet(minutes(13), "12:00", "14:00"))
        assertFalse(QuietHours.isQuiet(minutes(14), "12:00", "14:00"))
        assertTrue(QuietHours.isQuiet(minutes(12), "12:00", "14:00"))
    }

    @Test
    fun `window that wraps midnight`() {
        assertTrue(QuietHours.isQuiet(minutes(23, 30), "22:00", "07:00"))
        assertTrue(QuietHours.isQuiet(minutes(3), "22:00", "07:00"))
        assertFalse(QuietHours.isQuiet(minutes(7), "22:00", "07:00"))
        assertFalse(QuietHours.isQuiet(minutes(12), "22:00", "07:00"))
    }

    @Test
    fun `missing invalid or empty windows are never quiet`() {
        assertFalse(QuietHours.isQuiet(minutes(3), null, "07:00"))
        assertFalse(QuietHours.isQuiet(minutes(3), "22:00", null))
        assertFalse(QuietHours.isQuiet(minutes(3), "25:00", "07:00"))
        assertFalse(QuietHours.isQuiet(minutes(3), "ab", "07:00"))
        assertFalse(QuietHours.isQuiet(minutes(3), "08:00", "08:00"))
        assertNull(QuietHours.parseMinutes("7"))
        assertEquals(7 * 60 + 5, QuietHours.parseMinutes("07:05"))
    }

    @Test
    fun `escalation freshness`() {
        val now = 10_000_000_000L
        assertTrue(EscalationNoticePolicy.isFresh(now - 60_000, now))
        assertFalse(EscalationNoticePolicy.isFresh(now - EscalationNoticePolicy.MAX_AGE_MS - 1, now))
        assertFalse(EscalationNoticePolicy.isFresh(null, now))
        assertFalse(EscalationNoticePolicy.isFresh(now + 5_000, now))
    }
}

class UploadWorkPolicyTest {

    private val error = ApiError(ApiErrorKind.OFFLINE, "offline")

    @Test
    fun `finished or pointless uploads succeed`() {
        assertEquals(UploadWorkDecision.SUCCESS, UploadWorkPolicy.decide(UploadOutcome.Uploaded("c1"), 0))
        assertEquals(UploadWorkDecision.SUCCESS, UploadWorkPolicy.decide(UploadOutcome.NothingToDo, 3))
    }

    @Test
    fun `transient failures retry with backoff until the attempt budget is used`() {
        val retry = UploadOutcome.Retry(error)
        assertEquals(UploadWorkDecision.RETRY, UploadWorkPolicy.decide(retry, 0))
        assertEquals(UploadWorkDecision.RETRY, UploadWorkPolicy.decide(retry, UploadWorkPolicy.MAX_RUN_ATTEMPTS - 2))
        assertEquals(UploadWorkDecision.GIVE_UP, UploadWorkPolicy.decide(retry, UploadWorkPolicy.MAX_RUN_ATTEMPTS - 1))
    }

    @Test
    fun `deferred and rejected uploads stop retrying now`() {
        assertEquals(UploadWorkDecision.GIVE_UP, UploadWorkPolicy.decide(UploadOutcome.Deferred(error), 0))
        assertEquals(UploadWorkDecision.GIVE_UP, UploadWorkPolicy.decide(UploadOutcome.Rejected(error), 0))
    }
}
