package io.github.snowjug.sparta.ui.studio

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.snowjug.sparta.R
import io.github.snowjug.sparta.core.ui.AdaptiveLayout
import io.github.snowjug.sparta.data.remote.dto.LanguageInfoDto
import io.github.snowjug.sparta.data.remote.dto.VoiceStatus
import io.github.snowjug.sparta.ui.Labels
import io.github.snowjug.sparta.ui.components.CheckRow
import io.github.snowjug.sparta.ui.components.ChoiceGroup
import io.github.snowjug.sparta.ui.components.EmptyState
import io.github.snowjug.sparta.ui.components.ErrorBlock
import io.github.snowjug.sparta.ui.components.InfoBanner
import io.github.snowjug.sparta.ui.components.KeyValueRow
import io.github.snowjug.sparta.ui.components.LoadingBlock
import io.github.snowjug.sparta.ui.components.MessageBanner
import io.github.snowjug.sparta.ui.components.PrimaryButton
import io.github.snowjug.sparta.ui.components.QuietButton
import io.github.snowjug.sparta.ui.components.RiskBadge
import io.github.snowjug.sparta.ui.components.ScreenTitle
import io.github.snowjug.sparta.ui.components.SecondaryButton
import io.github.snowjug.sparta.ui.components.SectionTitle
import io.github.snowjug.sparta.ui.components.SliderRow
import io.github.snowjug.sparta.ui.components.SpartaCard
import io.github.snowjug.sparta.ui.components.SwitchRow
import io.github.snowjug.sparta.ui.components.Tone
import io.github.snowjug.sparta.ui.components.politeLiveRegion
import io.github.snowjug.sparta.ui.theme.SpartaTheme

data class StudioActions(
    val onOwnerName: (String) -> Unit = {},
    val onStyle: (String) -> Unit = {},
    val onRate: (Double) -> Unit = {},
    val onVoice: (String, String) -> Unit = { _, _ -> },
    val onPrimaryLanguage: (String) -> Unit = {},
    val onToggleLanguage: (String) -> Unit = {},
    val onAutoDetect: (Boolean) -> Unit = {},
    val onTranslateTo: (String?) -> Unit = {},
    val onPreviewText: (String) -> Unit = {},
    val onPreview: () -> Unit = {},
    val onSave: () -> Unit = {},
    val onDiscard: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onConnectBackend: () -> Unit = {},
    val onDismissMessage: () -> Unit = {},
)

@Composable
fun StudioScreen(
    onConnectBackend: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: StudioViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    StudioContent(
        state = state,
        modifier = modifier,
        actions = StudioActions(
            onOwnerName = viewModel::setOwnerName,
            onStyle = viewModel::setResponseStyle,
            onRate = viewModel::setSpeakingRate,
            onVoice = viewModel::setVoice,
            onPrimaryLanguage = viewModel::setPrimaryLanguage,
            onToggleLanguage = viewModel::toggleLanguage,
            onAutoDetect = viewModel::setAutoDetect,
            onTranslateTo = viewModel::setTranslateTo,
            onPreviewText = viewModel::setPreviewText,
            onPreview = viewModel::runPreview,
            onSave = viewModel::save,
            onDiscard = viewModel::discard,
            onRetry = viewModel::load,
            onConnectBackend = onConnectBackend,
            onDismissMessage = viewModel::dismissMessage,
        ),
    )
}

@Composable
fun StudioContent(
    state: StudioUiState,
    actions: StudioActions,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize().testTag("studio_screen")) {
        val draft = state.draft
        Box(modifier = Modifier.weight(1f)) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item(key = "content") {
                    Column(
                        modifier = Modifier.widthIn(max = AdaptiveLayout.CONTENT_MAX_WIDTH_DP.dp).fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        ScreenTitle(stringResource(R.string.studio_title), subtitle = stringResource(R.string.studio_subtitle))
                        when {
                            !state.backendConfigured && !state.loading -> EmptyState(
                                title = stringResource(R.string.studio_no_backend_title),
                                body = stringResource(R.string.studio_no_backend_body),
                                actionLabel = stringResource(R.string.calls_connect_backend),
                                onAction = actions.onConnectBackend,
                                testTag = "studio_no_backend",
                            )
                            state.loading && draft == null -> LoadingBlock()
                            draft == null -> ErrorBlock(
                                message = state.loadError?.message ?: stringResource(R.string.api_error_offline),
                                traceId = state.loadError?.traceId,
                                onRetry = actions.onRetry,
                                testTag = "studio_error",
                            )
                            else -> {
                                MessageBanner(state.message, actions.onDismissMessage)
                                DisclosureCard(draft)
                                ProfileCard(draft, actions)
                                VoiceCard(state, draft, actions)
                                LanguagesCard(state, draft, actions)
                                PreviewCard(state, actions)
                            }
                        }
                    }
                }
            }
        }
        if (draft != null && (state.dirty || state.saving)) SaveBar(state, draft, actions)
    }
}

@Composable
private fun DisclosureCard(draft: StudioDraft) {
    SpartaCard(modifier = Modifier.testTag("studio_disclosure")) {
        SectionTitle(stringResource(R.string.studio_disclosure_title))
        Text(
            stringResource(R.string.studio_disclosure_example, draft.ownerName.trim().ifEmpty { stringResource(R.string.studio_default_owner) }),
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.testTag("studio_disclosure_example"),
        )
        Text(
            stringResource(R.string.studio_disclosure_always_on),
            style = MaterialTheme.typography.bodyMedium,
            color = SpartaTheme.extras.textSecondary,
            modifier = Modifier.testTag("studio_disclosure_note"),
        )
    }
}

@Composable
private fun ProfileCard(draft: StudioDraft, actions: StudioActions) {
    SpartaCard(modifier = Modifier.testTag("studio_profile")) {
        SectionTitle(stringResource(R.string.studio_profile_title))
        OutlinedTextField(
            value = draft.ownerName,
            onValueChange = actions.onOwnerName,
            label = { Text(stringResource(R.string.studio_name_label)) },
            supportingText = { Text(stringResource(if (draft.nameValid) R.string.studio_name_help else R.string.studio_name_error)) },
            isError = !draft.nameValid,
            singleLine = true,
            modifier = Modifier.fillMaxWidth().testTag("studio_owner_name"),
        )
        Text(stringResource(R.string.studio_style_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = listOf(
                "concise" to stringResource(R.string.studio_style_concise),
                "warm" to stringResource(R.string.studio_style_warm),
                "formal" to stringResource(R.string.studio_style_formal),
            ),
            selected = draft.responseStyle,
            onSelect = actions.onStyle,
            testTagPrefix = "studio_style",
        )
        SliderRow(
            label = stringResource(R.string.studio_rate_label),
            value = draft.speakingRate.toFloat(),
            onValueChange = { actions.onRate(it.toDouble()) },
            valueRange = StudioDraft.RATE_MIN.toFloat()..StudioDraft.RATE_MAX.toFloat(),
            valueText = stringResource(R.string.studio_rate_value, "%.2f".format(draft.speakingRate)),
            steps = 11,
            testTag = "studio_rate",
        )
    }
}

@Composable
private fun VoiceCard(state: StudioUiState, draft: StudioDraft, actions: StudioActions) {
    SpartaCard(modifier = Modifier.testTag("studio_voice")) {
        SectionTitle(stringResource(R.string.studio_voice_title))
        Text(stringResource(R.string.studio_voice_body), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        val languages = languagesOf(state)
        draft.enabledLanguages.forEach { tag ->
            val info = languages.firstOrNull { it.code == tag }
            val options = state.voices.filter { it.locale.equals(tag, ignoreCase = true) }
            Text(languageTitle(tag, info), style = MaterialTheme.typography.titleSmall)
            if (options.isEmpty()) {
                Text(stringResource(R.string.studio_voice_none), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
            } else {
                ChoiceGroup(
                    options = listOf("" to stringResource(R.string.studio_voice_default)) + options.map { it.id to voiceLabel(it.displayName, it.gender, it.verified) },
                    selected = draft.voiceIds[tag] ?: "",
                    onSelect = { actions.onVoice(tag, it) },
                    testTagPrefix = "studio_voice_$tag",
                )
            }
        }
        val status = state.voiceStatus
        Text(stringResource(R.string.studio_personal_title), style = MaterialTheme.typography.titleSmall)
        if (status == null) {
            Text(stringResource(R.string.common_unknown), style = MaterialTheme.typography.bodyMedium)
        } else {
            KeyValueRow(stringResource(R.string.studio_personal_status), stringResource(voiceStatusRes(status.status)), testTag = "studio_voice_status")
            if (status.detail.isNotBlank()) Text(status.detail, style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
        }
        InfoBanner(stringResource(R.string.studio_personal_note), Tone.INFO, testTag = "studio_personal_note")
    }
}

private fun voiceStatusRes(status: VoiceStatus): Int = when (status) {
    VoiceStatus.NOT_ENROLLED -> R.string.voice_status_not_enrolled
    VoiceStatus.CONSENT_RECORDED -> R.string.voice_status_consent_recorded
    VoiceStatus.PENDING_PROVIDER_APPROVAL -> R.string.voice_status_pending
    VoiceStatus.READY -> R.string.voice_status_ready
    VoiceStatus.FAILED -> R.string.voice_status_failed
    VoiceStatus.DELETED -> R.string.voice_status_deleted
    VoiceStatus.UNKNOWN -> R.string.common_unknown
}

@Composable
private fun voiceLabel(name: String, gender: String, verified: Boolean): String {
    val base = if (gender == "neutral" || gender.isBlank()) name else "$name ($gender)"
    return if (verified) base else stringResource(R.string.studio_voice_unverified, base)
}

private fun languagesOf(state: StudioUiState): List<LanguageInfoDto> = state.languages.ifEmpty { DEFAULT_LANGUAGES }

@Composable
private fun languageTitle(tag: String, info: LanguageInfoDto?): String {
    val name = info?.name?.takeIf { it.isNotBlank() } ?: Labels.languageName(tag)
    val native = info?.nativeName?.takeIf { it.isNotBlank() && it != name }
    return if (native == null) name else "$name · $native"
}

@Composable
private fun LanguagesCard(state: StudioUiState, draft: StudioDraft, actions: StudioActions) {
    val languages = languagesOf(state)
    val supported = languages.filter { it.status == "supported" }
    SpartaCard(modifier = Modifier.testTag("studio_languages")) {
        SectionTitle(stringResource(R.string.studio_languages_title))
        Text(stringResource(R.string.studio_languages_body), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        languages.forEach { info ->
            val planned = info.status != "supported"
            CheckRow(
                title = languageTitle(info.code, info),
                subtitle = if (planned) stringResource(R.string.studio_language_planned) else if (info.code == draft.primaryLanguage) stringResource(R.string.studio_language_primary) else null,
                checked = info.code in draft.enabledLanguages,
                onCheckedChange = { actions.onToggleLanguage(info.code) },
                enabled = !planned,
                testTag = "studio_language_${info.code}",
            )
        }
        Text(stringResource(R.string.studio_primary_title), style = MaterialTheme.typography.titleSmall)
        ChoiceGroup(
            options = supported.filter { it.code in draft.enabledLanguages }.map { it.code to languageTitle(it.code, it) },
            selected = draft.primaryLanguage,
            onSelect = actions.onPrimaryLanguage,
            testTagPrefix = "studio_primary",
        )
        SwitchRow(
            title = stringResource(R.string.studio_auto_detect),
            subtitle = stringResource(R.string.studio_auto_detect_body),
            checked = draft.autoDetectLanguage,
            onCheckedChange = actions.onAutoDetect,
            testTag = "studio_auto_detect",
        )
        Text(stringResource(R.string.studio_translate_title), style = MaterialTheme.typography.titleSmall)
        if (!state.translationAvailable) {
            Text(
                stringResource(R.string.studio_translate_unavailable),
                style = MaterialTheme.typography.bodySmall,
                color = SpartaTheme.extras.textSecondary,
                modifier = Modifier.testTag("studio_translate_unavailable"),
            )
        }
        // The stored target stays visible but read-only while the backend offers no translation.
        ChoiceGroup(
            options = listOf<Pair<String?, String>>(null to stringResource(R.string.studio_translate_none)) +
                supported.filter { it.code in draft.enabledLanguages }.map { it.code to languageTitle(it.code, it) },
            selected = draft.translateTo,
            onSelect = actions.onTranslateTo,
            enabled = state.translationAvailable,
            testTagPrefix = "studio_translate",
        )
    }
}

@Composable
private fun PreviewCard(state: StudioUiState, actions: StudioActions) {
    SpartaCard(modifier = Modifier.testTag("studio_preview")) {
        SectionTitle(stringResource(R.string.studio_preview_title))
        Text(stringResource(R.string.studio_preview_body), style = MaterialTheme.typography.bodyMedium, color = SpartaTheme.extras.textSecondary)
        if (state.dirty) {
            Text(stringResource(R.string.studio_preview_unsaved), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.caution, modifier = Modifier.testTag("studio_preview_unsaved"))
        }
        OutlinedTextField(
            value = state.previewText,
            onValueChange = actions.onPreviewText,
            label = { Text(stringResource(R.string.studio_preview_sample_label)) },
            modifier = Modifier.fillMaxWidth().testTag("studio_preview_text"),
        )
        SecondaryButton(
            text = stringResource(if (state.preview == PreviewState.Running) R.string.studio_preview_running else R.string.studio_preview_run),
            onClick = actions.onPreview,
            enabled = state.preview != PreviewState.Running,
            icon = Icons.Rounded.PlayArrow,
            modifier = Modifier.fillMaxWidth(),
            testTag = "studio_preview_run",
        )
        Box(modifier = Modifier.politeLiveRegion()) {
            when (val preview = state.preview) {
                PreviewState.Idle, PreviewState.Running -> Unit
                is PreviewState.Failed -> ErrorBlock(preview.error.message, traceId = preview.error.traceId, testTag = "studio_preview_error")
                is PreviewState.Done -> Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("studio_preview_result")) {
                    Text(stringResource(R.string.studio_preview_disclosure), style = MaterialTheme.typography.titleSmall)
                    Text(preview.result.disclosure.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.testTag("studio_preview_disclosure"))
                    preview.result.reply?.let {
                        Text(stringResource(R.string.studio_preview_reply), style = MaterialTheme.typography.titleSmall)
                        Text(it.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.testTag("studio_preview_reply"))
                    }
                    preview.result.risk?.let {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            RiskBadge(it.riskLevel)
                            Text(stringResource(R.string.studio_preview_category, stringResource(Labels.category(it.category))), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    preview.result.detectedLanguage?.let {
                        Text(stringResource(R.string.studio_preview_language, Labels.languageName(it)), style = MaterialTheme.typography.bodySmall, color = SpartaTheme.extras.textSecondary)
                    }
                }
            }
        }
    }
}

@Composable
private fun SaveBar(state: StudioUiState, draft: StudioDraft, actions: StudioActions) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 3.dp,
        modifier = Modifier.fillMaxWidth().testTag("studio_save_bar"),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.End),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            QuietButton(stringResource(R.string.studio_discard), actions.onDiscard, enabled = !state.saving, testTag = "studio_discard")
            PrimaryButton(
                text = stringResource(if (state.saving) R.string.studio_saving else R.string.common_save),
                onClick = actions.onSave,
                enabled = draft.valid && !state.saving,
                testTag = "studio_save",
            )
        }
    }
}
