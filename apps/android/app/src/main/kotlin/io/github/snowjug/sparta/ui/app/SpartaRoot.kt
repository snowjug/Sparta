package io.github.snowjug.sparta.ui.app

import androidx.activity.compose.LocalActivity
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Call
import androidx.compose.material.icons.rounded.PrivacyTip
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Troubleshoot
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.nav.DeepLink
import io.github.snowjug.sparta.core.nav.Routes
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.ui.calls.CallsScreen
import io.github.snowjug.sparta.ui.components.DevIdentityStrip
import io.github.snowjug.sparta.ui.components.SpartaLogo
import io.github.snowjug.sparta.ui.components.currentWidthClass
import io.github.snowjug.sparta.ui.detail.CallDetailRoute
import io.github.snowjug.sparta.ui.detail.ScreeningEventRoute
import io.github.snowjug.sparta.ui.diagnostics.DiagnosticsScreen
import io.github.snowjug.sparta.ui.incoming.IncomingRoute
import io.github.snowjug.sparta.ui.live.LiveCallRoute
import io.github.snowjug.sparta.ui.onboarding.OnboardingScreen
import io.github.snowjug.sparta.ui.privacy.PrivacyScreen
import io.github.snowjug.sparta.ui.status.ProtectionScreen
import io.github.snowjug.sparta.ui.studio.StudioScreen
import io.github.snowjug.sparta.ui.theme.SpartaTheme

/** The five tabs, in display order. */
enum class TopLevelDestination(val route: String, val labelRes: Int, val icon: ImageVector) {
    STATUS(Routes.STATUS, R.string.nav_status, Icons.Rounded.Shield),
    CALLS(Routes.CALLS, R.string.nav_calls, Icons.Rounded.Call),
    STUDIO(Routes.STUDIO, R.string.nav_studio, Icons.Rounded.RecordVoiceOver),
    PRIVACY(Routes.PRIVACY, R.string.nav_privacy, Icons.Rounded.PrivacyTip),
    DIAGNOSTICS(Routes.DIAGNOSTICS, R.string.nav_diagnostics, Icons.Rounded.Troubleshoot),
}

/**
 * The app shell: theme, motion preference, the adaptive navigation (bottom bar on phones, rail on wider windows) and
 * the navigation graph. [deepLink] comes from a notification or a sparta:// link and is consumed exactly once.
 */
@Composable
fun SpartaRoot(
    deepLink: DeepLink?,
    onDeepLinkConsumed: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AppViewModel = hiltViewModel(),
) {
    val app by viewModel.state.collectAsStateWithLifecycle()
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { viewModel.onResume() }
    }

    SpartaTheme(themeMode = app.themeMode, reducedMotion = app.reducedMotion) {
        SystemBarIcons()
        Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!app.loaded) {
                Box(modifier = Modifier.fillMaxSize().testTag("splash"), contentAlignment = Alignment.Center) {
                    SpartaLogo(size = 96.dp)
                }
            } else {
                SpartaNavHost(app = app, deepLink = deepLink, onDeepLinkConsumed = onDeepLinkConsumed)
            }
        }
    }
}

/** The status and navigation bar icons must contrast with the in-app theme, which may differ from the system's. */
@Composable
private fun SystemBarIcons() {
    val dark = SpartaTheme.extras.isDark
    val activity = LocalActivity.current
    SideEffect {
        val window = activity?.window ?: return@SideEffect
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }
}

@Composable
fun SpartaNavHost(
    app: AppUiState,
    deepLink: DeepLink?,
    onDeepLinkConsumed: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val widthClass = currentWidthClass()
    val start = if (app.onboardingCompleted) Routes.STATUS else Routes.ONBOARDING

    // A link that arrives before setup is finished waits for it; afterwards it is opened once on top of the tabs.
    LaunchedEffect(deepLink, app.onboardingCompleted) {
        if (deepLink != null && app.onboardingCompleted) {
            navController.navigate(Routes.forLink(deepLink)) { launchSingleTop = true }
            onDeepLinkConsumed()
        }
    }

    val showBars = Routes.isTopLevel(route)
    Scaffold(
        modifier = modifier.fillMaxSize(),
        bottomBar = {
            if (showBars && !AdaptiveLayout.usesNavigationRail(widthClass)) {
                BottomBar(route) { navController.navigateTab(it) }
            }
        },
    ) { padding ->
        Row(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (showBars && AdaptiveLayout.usesNavigationRail(widthClass)) {
                Rail(route) { navController.navigateTab(it) }
            }
            Column(modifier = Modifier.weight(1f).fillMaxSize()) {
                if (app.devBanner) DevIdentityStrip()
                AppNavGraph(navController, start, app.reducedMotion, Modifier.weight(1f))
            }
        }
    }
}

private fun NavHostController.navigateTab(route: String) {
    navigate(route) {
        popUpTo(Routes.STATUS) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
private fun BottomBar(currentRoute: String?, onSelect: (String) -> Unit) {
    NavigationBar(modifier = Modifier.testTag("bottom_bar")) {
        TopLevelDestination.entries.forEach { destination ->
            val label = stringResource(destination.labelRes)
            NavigationBarItem(
                selected = currentRoute == destination.route,
                onClick = { onSelect(destination.route) },
                icon = { Icon(destination.icon, contentDescription = null) },
                label = { Text(label) },
                modifier = Modifier.testTag("tab_${destination.route}"),
            )
        }
    }
}

@Composable
private fun Rail(currentRoute: String?, onSelect: (String) -> Unit) {
    NavigationRail(modifier = Modifier.testTag("navigation_rail")) {
        TopLevelDestination.entries.forEach { destination ->
            val label = stringResource(destination.labelRes)
            NavigationRailItem(
                selected = currentRoute == destination.route,
                onClick = { onSelect(destination.route) },
                icon = { Icon(destination.icon, contentDescription = null) },
                label = { Text(label) },
                modifier = Modifier.testTag("tab_${destination.route}"),
            )
        }
    }
}

@Composable
private fun AppNavGraph(
    navController: NavHostController,
    start: String,
    reducedMotion: Boolean,
    modifier: Modifier = Modifier,
) {
    // Reduced motion: screens swap instantly. Otherwise a short cross-fade (no sliding or scaling).
    NavHost(
        navController = navController,
        startDestination = start,
        modifier = modifier,
        enterTransition = { if (reducedMotion) EnterTransition.None else fadeIn() },
        exitTransition = { if (reducedMotion) ExitTransition.None else fadeOut() },
        popEnterTransition = { if (reducedMotion) EnterTransition.None else fadeIn() },
        popExitTransition = { if (reducedMotion) ExitTransition.None else fadeOut() },
    ) {
        composable(Routes.ONBOARDING) {
            OnboardingScreen(onFinished = {
                navController.navigate(Routes.STATUS) { popUpTo(Routes.ONBOARDING) { inclusive = true } }
            })
        }
        composable(Routes.STATUS) {
            ProtectionScreen(onReviewCalls = { navController.navigateTab(Routes.CALLS) })
        }
        composable(Routes.CALLS) {
            CallsScreen(
                onOpenCall = { navController.navigate(Routes.call(it)) },
                onOpenEvent = { navController.navigate(Routes.event(it)) },
                onConnectBackend = { navController.navigateTab(Routes.PRIVACY) },
                detailPane = { id ->
                    CallDetailRoute(
                        callId = id,
                        onBack = null,
                        onOpenLive = { navController.navigate(Routes.live(it)) },
                        embedded = true,
                    )
                },
            )
        }
        composable(Routes.STUDIO) { StudioScreen(onConnectBackend = { navController.navigateTab(Routes.PRIVACY) }) }
        composable(Routes.PRIVACY) { PrivacyScreen() }
        composable(Routes.DIAGNOSTICS) { DiagnosticsScreen() }

        idRoute(Routes.CALL_PATTERN) { id ->
            CallDetailRoute(
                callId = id,
                onBack = { navController.popBackStack() },
                onOpenLive = { navController.navigate(Routes.live(it)) },
            )
        }
        idRoute(Routes.INCOMING_PATTERN) { id ->
            IncomingRoute(
                callId = id,
                onBack = { navController.popBackStack() },
                onOpenDetails = { navController.navigate(Routes.call(it)) },
                onOpenLive = { navController.navigate(Routes.live(it)) },
            )
        }
        idRoute(Routes.LIVE_PATTERN) { id ->
            LiveCallRoute(
                callId = id,
                onBack = { navController.popBackStack() },
                onOpenDetails = { navController.navigate(Routes.call(it)) },
            )
        }
        idRoute(Routes.EVENT_PATTERN) { id -> ScreeningEventRoute(eventId = id, onBack = { navController.popBackStack() }) }
    }
}

private fun NavGraphBuilder.idRoute(pattern: String, content: @Composable (String) -> Unit) {
    composable(
        route = pattern,
        arguments = listOf(navArgument(Routes.ARG_ID) { type = NavType.StringType }),
    ) { entry: NavBackStackEntry ->
        entry.arguments?.getString(Routes.ARG_ID)?.takeIf { it.isNotBlank() }?.let { content(it) }
    }
}
