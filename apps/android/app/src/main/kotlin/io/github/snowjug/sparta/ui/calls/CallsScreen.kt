package io.github.snowjug.sparta.ui.calls

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.core.ui.WidthClass
import io.github.snowjug.sparta.data.remote.dto.CallCategory
import io.github.snowjug.sparta.data.remote.dto.RiskLevel
import io.github.snowjug.sparta.data.repo.RecentItem
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.components.CallRow
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.ErrorBlock
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.LoadingBlock
import io.github.snowjug.sparta.ui.components.LocalEventRow
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.ScreenTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.currentWidthClass
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class CallsActions(
    val onQuery: (String) -> Unit = {},
    val onRisk: (RiskLevel?) -> Unit = {},
    val onCategory: (CallCategory?) -> Unit = {},
    val onLanguage: (String?) -> Unit = {},
    val onAttention: (Boolean) -> Unit = {},
    val onClearFilters: () -> Unit = {},
    val onRefresh: () -> Unit = {},
    val onLoadMore: () -> Unit = {},
    val onOpenCall: (String) -> Unit = {},
    val onOpenEvent: (String) -> Unit = {},
    val onConnectBackend: () -> Unit = {},
)

/** [detailPane] renders a call inside the second pane of expanded layouts. */
@Composable
fun CallsScreen(
    onOpenCall: (String) -> Unit,
    onOpenEvent: (String) -> Unit,
    onConnectBackend: () -> Unit,
    modifier: Modifier = Modifier,
    detailPane: @Composable (String) -> Unit = {},
    viewModel: CallsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val widthClass = currentWidthClass()
    val twoPane = AdaptiveLayout.usesTwoPane(widthClass)
    CallsContent(
        state = state,
        widthClass = widthClass,
        modifier = modifier,
        detailPane = detailPane,
        actions = CallsActions(
            onQuery = viewModel::setQuery,
            onRisk = viewModel::setRisk,
            onCategory = viewModel::setCategory,
            onLanguage = viewModel::setLanguage,
            onAttention = viewModel::setAttentionOnly,
            onClearFilters = viewModel::clearFilters,
            onRefresh = viewModel::refresh,
            onLoadMore = viewModel::loadMore,
            onOpenCall = { id -> if (twoPane) viewModel.select(id) else onOpenCall(id) },
            onOpenEvent = onOpenEvent,
            onConnectBackend = onConnectBackend,
        ),
    )
}

@Composable
fun CallsContent(
    state: CallsUiState,
    widthClass: WidthClass,
    actions: CallsActions,
    modifier: Modifier = Modifier,
    detailPane: @Composable (String) -> Unit = {},
) {
    if (AdaptiveLayout.usesTwoPane(widthClass)) {
        Row(modifier = modifier.fillMaxSize().testTag("calls_two_pane")) {
            Box(modifier = Modifier.width(AdaptiveLayout.LIST_PANE_WIDTH_DP.dp).fillMaxHeight()) {
                CallsList(state, actions, Modifier.fillMaxSize())
            }
            VerticalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Box(modifier = Modifier.weight(1f).fillMaxHeight().testTag("calls_detail_pane")) {
                val selected = state.selectedCallId
                if (selected == null) {
                    EmptyState(
                        title = stringResource(R.string.calls_select_prompt),
                        body = stringResource(R.string.calls_subtitle),
                        testTag = "calls_select_prompt",
                    )
                } else {
                    detailPane(selected)
                }
            }
        }
    } else {
        CallsList(state, actions, modifier.fillMaxSize())
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun CallsList(state: CallsUiState, actions: CallsActions, modifier: Modifier = Modifier) {
    PullToRefreshBox(
        isRefreshing = state.refreshing,
        onRefresh = actions.onRefresh,
        modifier = modifier.testTag("calls_screen"),
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item(key = "header") {
                Column(modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                        ScreenTitle(stringResource(R.string.calls_title), subtitle = stringResource(R.string.calls_subtitle), modifier = Modifier.weight(1f))
                        IconButton(onClick = actions.onRefresh, modifier = Modifier.testTag("calls_refresh")) {
                            Icon(Icons.Rounded.Refresh, contentDescription = stringResource(R.string.calls_refresh))
                        }
                    }
                    SearchField(state.filter.query, actions.onQuery)
                    FilterRow(state, actions)
                    if (state.error != null && !state.isEmpty) {
                        InfoBanner(stringResource(R.string.calls_error_cached, state.error.message), Tone.CAUTION, testTag = "calls_error_cached")
                    }
                }
            }
            if (state.initialLoading && state.isEmpty) {
                item(key = "loading") { LoadingBlock() }
            } else if (state.isEmpty) {
                item(key = "empty") { EmptyOrError(state, actions) }
            } else {
                items(state.items, key = { it.key }) { item ->
                    Box(modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth()) {
                        when (item) {
                            is RecentItem.Backend -> CallRow(
                                item = item.call,
                                nowMs = state.nowMs,
                                onClick = { actions.onOpenCall(item.call.id) },
                                selected = item.call.id == state.selectedCallId,
                            )
                            is RecentItem.Local -> LocalEventRow(
                                event = item.event,
                                nowMs = state.nowMs,
                                onClick = { actions.onOpenEvent(item.event.clientEventId) },
                            )
                        }
                    }
                }
                if (state.hasMore) {
                    item(key = "more") {
                        SecondaryButton(
                            text = stringResource(if (state.loadingMore) R.string.calls_loading_more else R.string.calls_load_more),
                            onClick = actions.onLoadMore,
                            enabled = !state.loadingMore,
                            testTag = "calls_load_more",
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun EmptyOrError(state: CallsUiState, actions: CallsActions) {
    Column(modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth()) {
        when {
            state.error != null -> ErrorBlock(
                message = stringResource(R.string.calls_error_empty, state.error.message),
                traceId = state.error.traceId,
                onRetry = actions.onRefresh,
                testTag = "calls_error",
            )
            state.filtersActive -> EmptyState(
                title = stringResource(R.string.calls_empty_filtered_title),
                body = stringResource(R.string.calls_empty_filtered_body),
                actionLabel = stringResource(R.string.calls_filter_clear),
                onAction = actions.onClearFilters,
                testTag = "calls_empty_filtered",
            )
            !state.backendConfigured -> EmptyState(
                title = stringResource(R.string.calls_empty_title),
                body = stringResource(R.string.calls_empty_no_backend),
                actionLabel = stringResource(R.string.calls_connect_backend),
                onAction = actions.onConnectBackend,
                testTag = "calls_empty_no_backend",
            )
            else -> EmptyState(
                title = stringResource(R.string.calls_empty_title),
                body = stringResource(R.string.calls_empty_body),
                testTag = "calls_empty",
            )
        }
    }
}

@Composable
private fun SearchField(query: String, onQuery: (String) -> Unit) {
    // The text is kept locally: round-tripping every keystroke through an async flow would drop characters.
    var text by rememberSaveable { mutableStateOf(query) }
    LaunchedEffect(query) { if (query.isEmpty()) text = "" }
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it
            onQuery(it)
        },
        modifier = Modifier.fillMaxWidth().testTag("calls_search"),
        label = { Text(stringResource(R.string.calls_search_label)) },
        singleLine = true,
        leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null) },
        trailingIcon = {
            if (text.isNotEmpty()) {
                IconButton(
                    onClick = {
                        text = ""
                        onQuery("")
                    },
                    modifier = Modifier.testTag("calls_search_clear"),
                ) { Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.calls_search_clear)) }
            }
        },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FilterRow(state: CallsUiState, actions: CallsActions) {
    val filter = state.filter
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            FilterChip(
                selected = filter.attentionOnly,
                onClick = { actions.onAttention(!filter.attentionOnly) },
                label = { Text(stringResource(R.string.calls_filter_attention)) },
                modifier = Modifier.testTag("filter_attention"),
            )
            listOf(
                RiskLevel.HIGH to R.string.calls_filter_high,
                RiskLevel.MEDIUM to R.string.calls_filter_medium,
                RiskLevel.LOW to R.string.calls_filter_low,
            ).forEach { (risk, label) ->
                FilterChip(
                    selected = filter.risk == risk,
                    onClick = { actions.onRisk(if (filter.risk == risk) null else risk) },
                    label = { Text(stringResource(label)) },
                    modifier = Modifier.testTag("filter_risk_${risk.wire}"),
                )
            }
            listOf(
                "en-IN" to R.string.calls_filter_language_en,
                "hi-IN" to R.string.calls_filter_language_hi,
                "kn-IN" to R.string.calls_filter_language_kn,
            ).forEach { (tag, label) ->
                FilterChip(
                    selected = filter.language == tag,
                    onClick = { actions.onLanguage(if (filter.language == tag) null else tag) },
                    label = { Text(stringResource(label)) },
                    modifier = Modifier.testTag("filter_language_$tag"),
                )
            }
        }
        CategoryMenu(filter.category, actions.onCategory)
        if (state.filtersActive) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                QuietButton(stringResource(R.string.calls_filter_clear), actions.onClearFilters, testTag = "filter_clear")
            }
            Text(
                stringResource(R.string.calls_filters_note),
                style = MaterialTheme.typography.bodySmall,
                color = SpartaTheme.extras.textSecondary,
                modifier = Modifier.testTag("filters_note"),
            )
        }
    }
}

@Composable
private fun CategoryMenu(selected: CallCategory?, onSelect: (CallCategory?) -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    val label = selected?.let { stringResource(Labels.category(it)) } ?: stringResource(R.string.calls_filter_any)
    Box {
        SecondaryButton(
            text = stringResource(R.string.calls_filter_category) + ": " + label,
            onClick = { open = true },
            testTag = "filter_category",
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.calls_filter_any)) },
                onClick = {
                    open = false
                    onSelect(null)
                },
                modifier = Modifier.testTag("category_any"),
            )
            CallCategory.entries.forEach { category ->
                DropdownMenuItem(
                    text = { Text(stringResource(Labels.category(category))) },
                    onClick = {
                        open = false
                        onSelect(category)
                    },
                    modifier = Modifier.testTag("category_${category.wire}"),
                )
            }
        }
    }
}
