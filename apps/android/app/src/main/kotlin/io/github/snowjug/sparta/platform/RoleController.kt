package io.github.snowjug.sparta.platform

import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.os.Build
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStateMapper

/** The call-screening role (Android 10+). Abstracted so ViewModels can be tested without a RoleManager. */
interface RoleController {
    fun currentState(requestDeclined: Boolean): RoleState

    /** The system role-request dialog intent, or null when the role cannot be requested on this device. */
    fun createRequestIntent(): Intent?
}

class AndroidRoleController(private val context: Context) : RoleController {

    override fun currentState(requestDeclined: Boolean): RoleState {
        val sdk = Build.VERSION.SDK_INT
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return RoleStateMapper.map(sdk, null, null, requestDeclined)
        return try {
            val manager = context.getSystemService(RoleManager::class.java)
            val available = manager?.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)
            val held = if (manager != null && available == true) manager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING) else null
            RoleStateMapper.map(sdk, available, held, requestDeclined)
        } catch (_: RuntimeException) {
            RoleStateMapper.map(sdk, roleAvailable = false, roleHeld = false, requestDeclined = requestDeclined)
        }
    }

    override fun createRequestIntent(): Intent? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return null
        return try {
            val manager = context.getSystemService(RoleManager::class.java) ?: return null
            if (!manager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) return null
            manager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING)
        } catch (_: RuntimeException) {
            null
        }
    }
}
