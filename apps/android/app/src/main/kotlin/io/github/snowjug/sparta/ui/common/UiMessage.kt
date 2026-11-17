package io.github.snowjug.sparta.ui.common

import androidx.annotation.StringRes
import io.github.snowjug.sparta.data.remote.ApiError

/** A one-off message for the screen to show (snackbar or banner). Carries resource ids so ViewModels stay Android-light. */
sealed interface UiMessage {
    data class Text(@StringRes val res: Int, val args: List<Any> = emptyList()) : UiMessage

    /** A backend failure; the screen shows [ApiError.message] and the trace id when present. */
    data class Failure(val error: ApiError, @StringRes val context: Int? = null) : UiMessage
}

/** Async lifecycle of a one-shot action (connection test, save, delete). */
sealed interface Progress<out T> {
    data object Idle : Progress<Nothing>

    data object Running : Progress<Nothing>

    data class Done<T>(val value: T) : Progress<T>

    data class Failed(val error: ApiError) : Progress<Nothing>
}
