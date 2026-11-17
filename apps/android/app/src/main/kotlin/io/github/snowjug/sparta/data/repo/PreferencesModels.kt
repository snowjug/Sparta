package io.github.snowjug.sparta.data.repo

import io.github.snowjug.sparta.core.screening.Strictness
import io.github.snowjug.sparta.core.screening.TrustedContactBehavior
import io.github.snowjug.sparta.core.screening.UnknownCallerBehavior
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull

private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull

private fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.intOrNull

private fun JsonObject.double(key: String): Double? = (this[key] as? JsonPrimitive)?.doubleOrNull

private fun JsonObject.obj(key: String): JsonObject = (this[key] as? JsonObject) ?: JsonObject(emptyMap())

private fun JsonObject.put(key: String, value: JsonElement): JsonObject = JsonObject(this + (key to value))

private fun stringList(element: JsonElement?): List<String> =
    (element as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } ?: emptyList()

/** Applies one dotted path ("strictness" or "retention.transcript_retention_days") to a JSON document. */
internal fun JsonObject.withPath(path: String, value: JsonElement): JsonObject {
    val dot = path.indexOf('.')
    if (dot < 0) return put(path, value)
    val parent = path.substring(0, dot)
    val child = path.substring(dot + 1)
    return put(parent, obj(parent).withPath(child, value))
}

/**
 * A set of preference edits expressed as dotted paths. Later edits to the same path win. Patches are what the app
 * persists while offline and re-applies to the freshest backend document when it can push.
 */
class PreferencesPatch(val values: JsonObject = JsonObject(emptyMap())) {
    val isEmpty: Boolean get() = values.isEmpty()

    operator fun plus(other: PreferencesPatch): PreferencesPatch = PreferencesPatch(JsonObject(values + other.values))

    fun toJsonString(json: Json): String = json.encodeToString(JsonObject.serializer(), values)

    fun strictness(value: Strictness) = set("strictness", JsonPrimitive(value.wire))

    fun unknownCallerBehavior(value: UnknownCallerBehavior) = set("unknown_caller_behavior", JsonPrimitive(value.wire))

    fun trustedContactBehavior(value: TrustedContactBehavior) = set("trusted_contact_behavior", JsonPrimitive(value.wire))

    fun primaryLanguage(value: String) = set("primary_language", JsonPrimitive(value))

    fun enabledLanguages(value: List<String>) = set("enabled_languages", JsonArray(value.map { JsonPrimitive(it) }))

    fun autoDetectLanguage(value: Boolean) = set("auto_detect_language", JsonPrimitive(value))

    fun transcriptRetentionDays(value: Int) = set("retention.transcript_retention_days", JsonPrimitive(value))

    fun storeTranscripts(value: Boolean) = set("retention.store_transcripts", JsonPrimitive(value))

    fun notifyOnEscalation(value: Boolean) = set("notifications.notify_on_escalation", JsonPrimitive(value))

    fun notifyOnHighRisk(value: Boolean) = set("notifications.notify_on_high_risk", JsonPrimitive(value))

    fun includeTranscriptLines(value: Boolean) = set("notifications.include_transcript_lines", JsonPrimitive(value))

    fun storeFullCallerNumber(value: Boolean) = set("retention.store_full_caller_number", JsonPrimitive(value))

    fun translateTranscriptsTo(value: String?) = set("translate_transcripts_to", if (value == null) JsonNull else JsonPrimitive(value))

    /** "HH:MM" bounds, or null for both to switch quiet hours off. */
    fun quietHours(start: String?, end: String?): PreferencesPatch =
        set("notifications.quiet_hours_start", if (start == null) JsonNull else JsonPrimitive(start))
            .set("notifications.quiet_hours_end", if (end == null) JsonNull else JsonPrimitive(end))

    fun onboardingCompleted(value: Boolean) = set("onboarding_completed", JsonPrimitive(value))

    private fun set(path: String, value: JsonElement) = PreferencesPatch(JsonObject(values + (path to value)))

    companion object {
        val EMPTY = PreferencesPatch()

        fun fromJson(json: Json, text: String?): PreferencesPatch {
            if (text.isNullOrBlank()) return EMPTY
            return try {
                PreferencesPatch(json.decodeFromString(JsonObject.serializer(), text))
            } catch (_: SerializationException) {
                EMPTY
            }
        }
    }
}

/**
 * Typed view over the backend's `UserPreferences` document. The backend replaces the whole document on PUT and
 * rejects unknown fields, so edits are applied to the raw JSON: anything this app does not understand round-trips
 * untouched.
 */
data class UserPreferences(val raw: JsonObject = JsonObject(emptyMap())) {
    val onboardingCompleted: Boolean get() = raw.bool("onboarding_completed") ?: false
    val primaryLanguage: String get() = raw.string("primary_language") ?: "en-IN"
    val enabledLanguages: List<String>
        get() = raw["enabled_languages"]?.let(::stringList)?.takeIf { it.isNotEmpty() } ?: listOf("en-IN", "hi-IN", "kn-IN")
    val autoDetectLanguage: Boolean get() = raw.bool("auto_detect_language") ?: true
    val translateTranscriptsTo: String? get() = raw.string("translate_transcripts_to")
    val strictness: Strictness get() = Strictness.fromWire(raw.string("strictness"))
    val trustedContactBehavior: TrustedContactBehavior get() = TrustedContactBehavior.fromWire(raw.string("trusted_contact_behavior"))
    val unknownCallerBehavior: UnknownCallerBehavior get() = UnknownCallerBehavior.fromWire(raw.string("unknown_caller_behavior"))

    val storeTranscripts: Boolean get() = raw.obj("retention").bool("store_transcripts") ?: true
    val transcriptRetentionDays: Int get() = raw.obj("retention").int("transcript_retention_days") ?: 7
    val summaryRetentionDays: Int get() = raw.obj("retention").int("summary_retention_days") ?: 90
    val storeFullCallerNumber: Boolean get() = raw.obj("retention").bool("store_full_caller_number") ?: false

    val notifyOnEscalation: Boolean get() = raw.obj("notifications").bool("notify_on_escalation") ?: true
    val notifyOnHighRisk: Boolean get() = raw.obj("notifications").bool("notify_on_high_risk") ?: false
    val includeTranscriptLines: Boolean get() = raw.obj("notifications").bool("include_transcript_lines") ?: true
    val quietHoursStart: String? get() = raw.obj("notifications").string("quiet_hours_start")
    val quietHoursEnd: String? get() = raw.obj("notifications").string("quiet_hours_end")

    fun apply(patch: PreferencesPatch): UserPreferences =
        copy(raw = patch.values.entries.fold(raw) { doc, (path, value) -> doc.withPath(path, value) })
}

/** Typed view over the backend's `AssistantProfile` document (same raw-JSON round-trip rule). */
data class AssistantProfileDoc(val raw: JsonObject = JsonObject(emptyMap())) {
    val ownerDisplayName: String get() = raw.string("owner_display_name") ?: "the owner"
    val responseStyle: String get() = raw.string("response_style") ?: "concise"
    val speakingRate: Double get() = raw.double("speaking_rate") ?: 1.0
    val usePersonalVoice: Boolean get() = raw.bool("use_personal_voice") ?: false
    val voiceIds: Map<String, String>
        get() = raw.obj("voice_ids").mapNotNull { (locale, element) ->
            (element as? JsonPrimitive)?.contentOrNull?.let { locale to it }
        }.toMap()

    fun withOwnerDisplayName(value: String) = copy(raw = raw.put("owner_display_name", JsonPrimitive(value)))

    fun withResponseStyle(value: String) = copy(raw = raw.put("response_style", JsonPrimitive(value)))

    fun withSpeakingRate(value: Double) = copy(raw = raw.put("speaking_rate", JsonPrimitive(value)))

    fun withVoice(locale: String, voiceId: String) = copy(raw = raw.put("voice_ids", raw.obj("voice_ids").put(locale, JsonPrimitive(voiceId))))

    /** Replaces the whole locale -> voice map (an empty map returns every language to the catalogue default). */
    fun withVoices(voices: Map<String, String>) =
        copy(raw = raw.put("voice_ids", JsonObject(voices.mapValues { (_, id) -> JsonPrimitive(id) })))
}
