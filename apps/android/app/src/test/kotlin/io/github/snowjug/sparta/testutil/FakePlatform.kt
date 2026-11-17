package io.github.snowjug.sparta.testutil

import android.content.Intent
import io.github.snowjug.sparta.core.role.RoleState
import io.github.snowjug.sparta.core.role.RoleStateMapper
import io.github.snowjug.sparta.platform.AppPermission
import io.github.snowjug.sparta.platform.DeviceInfo
import io.github.snowjug.sparta.platform.DeviceInfoProvider
import io.github.snowjug.sparta.platform.PermissionChecker
import io.github.snowjug.sparta.platform.RoleController

/** A phone whose role state the test controls, mapped by the real [RoleStateMapper]. */
class FakeRoleController(var sdk: Int = 35, var available: Boolean = true, var held: Boolean = false) : RoleController {
    private val modern: Boolean get() = sdk >= RoleStateMapper.MIN_ROLE_SDK

    override fun currentState(requestDeclined: Boolean): RoleState =
        RoleStateMapper.map(sdk, if (modern) available else null, if (modern && available) held else null, requestDeclined)

    override fun createRequestIntent(): Intent? = if (modern && available) Intent("test.REQUEST_ROLE") else null
}

class FakePermissionChecker(
    var contacts: Boolean = false,
    var notificationsRequired: Boolean = true,
    var notifications: Boolean = false,
) : PermissionChecker {
    override fun isRequired(permission: AppPermission) = permission == AppPermission.CONTACTS || notificationsRequired

    override fun isGranted(permission: AppPermission) = if (permission == AppPermission.CONTACTS) contacts else notifications
}

val TestDevice = DeviceInfo(35, "15", "Google", "Pixel", null, "0.1.0", 1, true)

val TestDeviceInfoProvider = DeviceInfoProvider { TestDevice }
