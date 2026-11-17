package io.github.snowjug.sparta.platform

import android.content.Context
import android.os.Build
import android.provider.Settings
import io.github.snowjug.sparta.BuildConfig

/** Non-personal facts about the device and build, shown in Diagnostics and in the sanitized report. */
data class DeviceInfo(
    val apiLevel: Int,
    val androidRelease: String,
    val manufacturer: String,
    val model: String,
    val securityPatch: String?,
    val appVersionName: String,
    val appVersionCode: Long,
    val debugBuild: Boolean,
)

fun interface DeviceInfoProvider {
    fun get(): DeviceInfo
}

class AndroidDeviceInfoProvider : DeviceInfoProvider {
    override fun get(): DeviceInfo = DeviceInfo(
        apiLevel = Build.VERSION.SDK_INT,
        androidRelease = Build.VERSION.RELEASE.orEmpty(),
        manufacturer = Build.MANUFACTURER.orEmpty(),
        model = Build.MODEL.orEmpty(),
        securityPatch = Build.VERSION.SECURITY_PATCH.takeIf { it.isNotBlank() },
        appVersionName = BuildConfig.VERSION_NAME,
        appVersionCode = BuildConfig.VERSION_CODE.toLong(),
        debugBuild = BuildConfig.DEBUG,
    )
}

/** Reads the system animation scale ("Remove animations" / Developer options set it to 0). */
fun interface AnimatorScaleReader {
    fun read(): Float?
}

class AndroidAnimatorScaleReader(private val context: Context) : AnimatorScaleReader {
    override fun read(): Float? = try {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE)
    } catch (_: Settings.SettingNotFoundException) {
        null
    }
}
