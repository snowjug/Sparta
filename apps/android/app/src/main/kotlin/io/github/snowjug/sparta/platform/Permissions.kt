package io.github.snowjug.sparta.platform

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/** The only runtime permissions Sparta ever asks for. It never asks for microphone, call log or phone state. */
enum class AppPermission {
    /** Optional: only to treat saved contacts as known callers, and only if the owner opts in. */
    CONTACTS,

    /** Android 13+: needed to show escalation and screening notifications. */
    NOTIFICATIONS,
}

interface PermissionChecker {
    /** False when the permission does not exist as a runtime permission on this Android version. */
    fun isRequired(permission: AppPermission): Boolean

    fun isGranted(permission: AppPermission): Boolean
}

class AndroidPermissionChecker(private val context: Context) : PermissionChecker {

    override fun isRequired(permission: AppPermission): Boolean = when (permission) {
        AppPermission.CONTACTS -> true
        AppPermission.NOTIFICATIONS -> Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
    }

    override fun isGranted(permission: AppPermission): Boolean = when (permission) {
        AppPermission.CONTACTS ->
            ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED
        AppPermission.NOTIFICATIONS -> {
            val runtimeGranted = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            runtimeGranted && NotificationManagerCompat.from(context).areNotificationsEnabled()
        }
    }

    companion object {
        /** Manifest name for the runtime request; null when no runtime permission exists on this Android version. */
        fun manifestName(permission: AppPermission): String? = when (permission) {
            AppPermission.CONTACTS -> Manifest.permission.READ_CONTACTS
            AppPermission.NOTIFICATIONS ->
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) Manifest.permission.POST_NOTIFICATIONS else null
        }
    }
}
