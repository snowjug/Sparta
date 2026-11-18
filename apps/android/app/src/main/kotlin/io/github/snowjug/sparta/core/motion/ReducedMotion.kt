package io.github.snowjug.sparta.core.motion

enum class MotionPreference(val wire: String) {
    FOLLOW_SYSTEM("system"),
    REDUCE("reduce"),
    FULL("full"),
    ;

    companion object {
        fun fromWire(value: String?): MotionPreference = entries.firstOrNull { it.wire == value } ?: FOLLOW_SYSTEM
    }
}

object ReducedMotion {
    /**
     * Android's "Remove animations" accessibility toggle (and Developer options) sets
     * Settings.Global.ANIMATOR_DURATION_SCALE to 0. [animatorDurationScale] is null when it could not be read.
     */
    fun isReduced(animatorDurationScale: Float?, preference: MotionPreference): Boolean = when (preference) {
        MotionPreference.REDUCE -> true
        MotionPreference.FULL -> false
        MotionPreference.FOLLOW_SYSTEM -> animatorDurationScale != null && animatorDurationScale <= 0f
    }
}
