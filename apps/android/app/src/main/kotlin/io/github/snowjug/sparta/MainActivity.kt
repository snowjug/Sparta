package io.github.snowjug.sparta

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import dagger.hilt.android.AndroidEntryPoint
import io.github.snowjug.sparta.core.nav.DeepLink
import io.github.snowjug.sparta.core.nav.DeepLinks
import io.github.snowjug.sparta.ui.app.AppViewModel
import io.github.snowjug.sparta.ui.app.SpartaRoot
import kotlinx.coroutines.launch

/**
 * Single activity. Notifications and sparta:// links arrive as an intent; [DeepLinks.parse] validates them (the id is
 * never trusted) and the shell opens the target once setup is finished.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val appViewModel: AppViewModel by viewModels()
    private var pendingLink: DeepLink? by mutableStateOf(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // A recreated activity (rotation) still holds the original intent; only a fresh launch may open its link.
        if (savedInstanceState == null) pendingLink = DeepLinks.parse(intent?.data?.toString())

        // Live "a call needs you" alerts run only while the UI is visible: no service, no wake lock.
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) { appViewModel.monitorEscalations() }
        }

        setContent {
            SpartaRoot(deepLink = pendingLink, onDeepLinkConsumed = { pendingLink = null })
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        DeepLinks.parse(intent.data?.toString())?.let { pendingLink = it }
    }
}
