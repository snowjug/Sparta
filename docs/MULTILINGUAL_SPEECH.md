# Multilingual speech and language handling

How Sparta recognises which language a caller is using, follows a caller who switches language, maps languages to speech
locales and voices, and what it does when it cannot tell. Covers English, Hindi and Kannada and the code-switched forms
Hinglish and Kanglish.

Scope and honesty notes:

* Detection is a transparent script-and-lexicon heuristic, not a trained model, and it is **never a safety gate**: the
  risk rules run on all text whatever language was detected ([SAFETY_MODEL.md](SAFETY_MODEL.md)).
* The Hindi and Kannada vocabularies and templates, and the evaluation dataset, were **not reviewed by native speakers**.
  `packs/kn.toml` says so in a comment above its templates.
* Azure Speech was never called with real credentials. Everything about recognition quality, language identification and
  voices in real calls is **UNVERIFIED**; locale and voice support comes from documentation
  ([research/azure-speech-openai-verification.md](research/azure-speech-openai-verification.md),
  [research/phase2-provider-verification.md](research/phase2-provider-verification.md)). Phase 2's Hinglish and Kanglish
  journeys ([PHASE2_CONTROLLED_RESULTS.md](PHASE2_CONTROLLED_RESULTS.md)) feed *scripted* transcripts to the engine: they
  show what the engine does with a correct transcript, not that Azure produces one.
* Phase 3 added free **local** speech (faster-whisper and Piper, section 11). It *was* run, on real audio, on one machine: it
  recognises English, is unreliable for Hindi and cannot recognise Kannada with the small model. That is measured, not
  assumed, and it is the only recognition in this repository that has heard audio.
* Examples marked "verified by running" were executed on 2026-11-18 against commit `117752e` (`LanguageDetector.detect`,
  `SignalDetector.detect` and `ConversationEngine.on_caller_turn`). On the final tree of the same day (commit `5f980d1`,
  with the fixes in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) section 6) the development-split evaluation was run
  again and reproduced [eval/latest-dev.md](eval/latest-dev.md) except its timestamp, its latency figures and the noise
  sweep, so the detector's behaviour on that split did not change.

Related: [ARCHITECTURE.md](ARCHITECTURE.md), [TELEPHONY.md](TELEPHONY.md),
[eval/latest-dev.md](eval/latest-dev.md), [eval/latest-test.md](eval/latest-test.md).

## 1. Languages, profiles and locales

Language packs are TOML files in `services/api/src/sparta/language/packs/`. A pack's `[meta]` block fixes its locales and
default voice (`LanguageSpec` in `language/registry.py`).

| Code | Language | Status | STT locale | TTS locale | Default voice | Scripts handled |
| --- | --- | --- | --- | --- | --- | --- |
| `en-IN` | English (India) | supported | `en-IN` | `en-IN` | `en-IN-NeerjaNeural` | Latin |
| `hi-IN` | Hindi | supported | `hi-IN` | `hi-IN` | `hi-IN-SwaraNeural` | Devanagari, Latin (Hinglish) |
| `kn-IN` | Kannada | supported | `kn-IN` | `kn-IN` | `kn-IN-SapnaNeural` | Kannada, Latin (Kanglish) |
| `mr-IN` | Marathi | planned | `mr-IN` | `mr-IN` | none | Devanagari |
| `ta-IN` | Tamil | planned | `ta-IN` | `ta-IN` | none | Tamil |
| `te-IN` | Telugu | planned | `te-IN` | `te-IN` | none | Telugu |
| `ml-IN` | Malayalam | planned | `ml-IN` | `ml-IN` | none | Malayalam |
| `bn-IN` | Bengali | planned | `bn-IN` | `bn-IN` | none | Bengali |

A `planned` pack carries only identity (and, for Marathi, a few Devanagari marker words used to tell it from Hindi). It
contributes no rules, no lexicon and no templates, so it is detected but not spoken: the assistant asks the caller to
continue in a supported language (section 5). A test fails if a supported pack lacks a default voice or any of the
reply templates that English has (`tests/unit/test_language.py`).

The detector reports a **profile** for each utterance, and the call keeps a profile over its turns:

| Profile | Meaning |
| --- | --- |
| `english`, `hindi`, `kannada` | Mostly one language; Hindi and Kannada only when most tokens are in the native script and little English is mixed in |
| `hinglish` | Hindi written in Latin script, or Hindi mixed with English, or English with at least 25% Hindi tokens |
| `kanglish` | The same for Kannada |
| `mixed` | For one utterance: at least 20% each of Hindi and Kannada. For a call: the turns so far used two or more of English, Hindi (including Hinglish) and Kannada (including Kanglish) |
| `unsupported` | The top language has no supported pack (Marathi, Tamil, Telugu, Malayalam, Bengali) |
| `unknown` | Nothing recognisable (digits only, a stray word) |

Hinglish and Kanglish are profiles of `hi-IN` and `kn-IN`, not separate language codes. A `LanguageSegment` records the
language, script (`Latn`, `Deva`, `Knda`, `Mixed`, `Other`), whether it is romanised, character offsets, a confidence and
the variant (`hinglish` or `kanglish`), so the UI can show code-switching inside one utterance.

## 2. How detection works

Implementation: `language/detector.py` (`LanguageDetector.detect`), `language/text.py`.

1. **Normalise and tokenise.** `normalize` applies Unicode NFC, deletes invisible characters (zero-width characters,
   soft hyphen, bidirectional marks, variation selectors, tag and private-use characters), folds Cyrillic and Greek
   look-alike letters to Latin inside words that are otherwise Latin, converts Devanagari, Kannada and other Indic digits
   to ASCII, removes the Devanagari nukta (so `ज़रूर` and `जरूर` are the same), straightens curly apostrophes, collapses
   repeated letters (three or more of the same non-digit character become two) and turns most punctuation into spaces.
   Digit runs are never collapsed. Before that, the engine has already cleaned the caller's text with `sanitize_text`
   (section 6).
2. **Script is decisive for non-Latin tokens.** Kannada script maps to `kn-IN`; Tamil, Telugu, Malayalam and Bengali
   script map to their (unsupported) codes. Devanagari maps to `hi-IN`, or to `mr-IN` when at least two Marathi marker
   words appear and more than Hindi marker words do.
3. **Latin tokens are classified against romanised lexicons.** Each pack lists romanised words (`[detection]
   latin_words`). Tokens are folded with `canon_latin` first, which collapses common spelling variants:
   `aa`→`a`, `ee`→`i`, `ii`→`i`, `oo`→`u`, `uu`→`u`, `ph`→`f`, `kh`→`k`, `gh`→`g`, `w`→`v`, `z`→`j`, and repeated letters.
   A token in exactly one language's lexicon counts one point for that language; a token in more than one counts for
   none. A token of five or more characters that is in no lexicon but matches exactly one language's suffix list
   (`latin_suffixes`) counts 0.5. English has its own lexicon, so English words score for `en-IN`.
4. **Matrix language.** If English has the top score but Hindi or Kannada has at least 60% of it and an absolute score of
   at least 2.5, the Indic language wins. This makes a Kanglish sentence with an Indic frame and English nouns an
   Indic-language utterance.
5. **Confidence.** `0.35 + 0.45 * margin + 0.20 * evidence`, where `margin` is the gap between the top two scores divided
   by the total and `evidence = min(1, total / 4)`, clamped to 0.05 to 0.99. Below 0.55 the detection is `uncertain`.
6. **Profile and segments** are derived from the score shares and from runs of consecutive tokens in one language.

Unknown text is not guessed: an utterance with no recognisable tokens is language `und`, confidence 0.1 and `uncertain`.

Examples (verified by running the detector; confidence is the detector's own number, not an accuracy):

| Input | Language | Profile | Confidence |
| --- | --- | --- | --- |
| `Hello, this is Rahul from State Bank.` | `en-IN` | english | 0.99 |
| `Namaste main Rahul bol raha hoon` | `hi-IN` | hinglish | 0.99 |
| `aapka account block ho jayega abhi OTP bataiye` | `hi-IN` | hinglish | 0.743 |
| `nimma account block aagide, OTP heli` | `kn-IN` | kanglish | 0.64 |
| `nanu State Bank inda maatadtidini` | `kn-IN` | kanglish | 0.718 |
| `ಬ್ಯಾಂಕಿನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ` | `kn-IN` | kannada | 0.9 |
| `ok ok` and `12345` | `und` | unknown | 0.1, uncertain |

Unit tests pin Devanagari Hindi, Hinglish, Kannada script, Kanglish, Tamil (`ta-IN`, unsupported) and Marathi (`mr-IN`,
unsupported) detection (`tests/unit/test_language.py::test_detects_language_and_profile`).

Known weakness: short code-switched utterances with few Indic words are decided by the word counts and can come out in
English, and the Kanglish suffix list is spelling-specific. Verified by running: `nanu Sahyadri Bank customer care inda
maatadtidini` scores Kannada 2.5 against English 3.0, which is enough for the matrix-language rule, so the detected
language is `kn-IN` (profile `kanglish`, confidence 0.55). The same sentence spelled `maatadthidini` scores Kannada 2.0
against 3.0, so the detected language is `en-IN` (profile `kanglish`) and the assistant would answer in English, because
the suffix list contains `tidini` but not `thidini`. The comment in `LanguageDetector.detect` uses the `maatadtidini`
spelling as its example and names `maatadthidini` as a romanisation the lexicon does not list. The shorter
`nanu State Bank inda maatadtidini` is detected as Kannada (0.718).

## 3. Following a caller who switches language

* `CallerInput` text is detected on every caller turn (`ConversationEngine.on_caller_turn`). The detected languages are
  appended to the call's `detected_languages` (what the **caller** spoke; the assistant's own opening language is not
  counted), and each turn's profile is appended to `turn_languages`.
* The **reply language** is chosen by `_resolve_language`: a forced language wins; otherwise the detected language is
  used if it is supported, enabled in the owner's `enabled_languages`, and the detection is not uncertain; otherwise the
  assistant keeps the language it was already using. When the reply language changes a `language.changed` event
  `{from, to, profile, confidence}` is emitted.
* Replies are rendered from the **base language's** templates, in its native script: a Hinglish caller is answered in
  Hindi (Devanagari) and a Kanglish caller in Kannada (Kannada script), not in romanised Hinglish or Kanglish. A Latin
  transliteration is stored beside each Hindi and Kannada reply (`SpeechPlan.transliteration`) for developers and testers.
  English wording of the same template keys is stored as the turn's `translation`, so an owner can read what the
  assistant said (`CallTurn.translation` is filled for assistant turns only). Machine translation of caller speech is
  not implemented: `GET /system/status` always reports `features.translation: false` (hard-coded in
  `services/owner.py`; there is no setting for it), and the `translate_transcripts_to` preference is stored for a future
  translation provider but nothing acts on it.
* The simulator scenario `language-switch-journey` exercises this. Replayed on 2026-11-18 it emitted
  `language.changed` from `en-IN` to `hi-IN` (profile hinglish), then to `kn-IN` (kanglish), then back to `en-IN`
  (english), with the assistant's replies rendered in Hindi, Kannada and English respectively, and ended with the OTP
  refusal.

Controls (owner preferences and per-call mode): `UserPreferences.primary_language`, `enabled_languages` (default all
three), `auto_detect_language` (default true; when false the primary language is used for replies), and a per-call
`language_mode` (`auto` or one supported code). Unsupported codes are rejected with a 422.

## 4. Locale mapping, speech recognition and voices

* **Recognition.** The Azure adapter (`providers/stt/azure.py`, Fast Transcription REST, api-version `2025-10-15`) sends
  `definition.locales` = the language hint first, then the owner's enabled languages' STT locales, without duplicates,
  at most 10. For uploads the hint is the request's `language_hint`; for live provider audio it is the forced language's
  locale or the language the previous utterance came back in. The adapter returns the most common locale among the
  returned phrases and the mean phrase confidence. The language is passed to the detector as a hint (no hint confidence is
  set, so the detector assumes 0.7); the mean phrase confidence becomes the turn's `stt_confidence`.
  **Streaming (Phase 2).** With the Speech SDK installed (`pip install 'sparta-api[azure]'`, pinned in the locks) and
  `SPARTA_AZURE_SPEECH_STREAMING=auto` (the default; `on` makes a missing SDK a configuration problem, `off` forces REST),
  `start_stream` (`providers/stt/azure_sdk.py`) opens one SDK recogniser per utterance on a push stream (8 or 16 kHz
  PCM16): `recognizing` events become partial transcripts (live captions on a real call), `recognized` events become the
  final with `NBest[0].Confidence`, the identified language and the service's own latency (`stt_service` metric). With
  several candidate locales it uses **continuous language identification** (`SpeechServiceConnection_LanguageIdMode =
  Continuous`, hint first, at most 10 locales) on the documented v2 endpoint
  `wss://{region}.stt.speech.microsoft.com/speech/universal/v2`; with one locale it recognises that locale directly.
  A custom-domain endpoint is passed to the SDK unchanged (multi-locale identification there is **UNVERIFIED**).
  SDK cancellations become static, code-mapped errors (the SDK's text can quote endpoints and request ids and is never
  forwarded); an utterance that is not recognised is an empty turn, not an error. Without the SDK the REST behaviour
  above applies: audio is buffered until the voice-activity detector ends the utterance, then one `final` is produced, with
  no partial results.
  **Not implemented, documented alternatives:** the GA *multilingual post-stream refinement*
  (`SpeechServiceResponse_PostProcessingOption = "PostRefinement"`, SDK 1.50 or later, open-range detection; short
  utterances may not improve) and the `MAI-Transcribe-2` models that document mid-utterance Hinglish code-switching. They
  are the first things to try if a real test shows Hinglish or Kanglish recognition failing
  ([research/phase2-provider-verification.md](research/phase2-provider-verification.md), section 3).
* **Documented support.** `en-IN`, `hi-IN` and `kn-IN` are listed for real-time STT, Fast Transcription and TTS in the
  Microsoft documentation as read on 2026-11-17 (research note above). Continuous language identification is documented
  as not detecting a language change inside one sentence, and the accuracy of intra-sentence Hinglish and Kanglish
  recognition is **UNVERIFIED**. That is why Sparta segments the transcript text itself and runs its rules on all text.
* **Voices.** Predefined neural voices, from `providers/tts/catalog.py` (names verified in the documentation, not by
  listening): English `en-IN-NeerjaNeural` (default), `-AartiNeural`, `-AnanyaNeural`, `-PrabhatNeural`, `-KunalNeural`,
  `-ArjunNeural`; Hindi `hi-IN-SwaraNeural` (default), `-AnanyaNeural`, `-AartiNeural`, `-MadhurNeural`, `-AaravNeural`,
  `-KunalNeural`; Kannada `kn-IN-SapnaNeural` (default) and `kn-IN-GaganNeural`. An owner may choose a voice per locale
  (`AssistantProfile.voice_ids`); an unknown voice is rejected.
* **Speech markup.** Hindi and Kannada replies are sent as native-script SSML to the matching locale voice. Latin-script
  words inside the templates (for example "AI") are left to the voice; per-word language switching needs a multilingual
  voice and is not enabled. How the Azure voices pronounce those words is **UNVERIFIED**. The `kn-IN` voices do not
  support phonemes, custom lexicons or visemes (research note).
* **Personal voice** is not available for Kannada (not listed in the documentation) and is not usable at all in this
  release; see [PRIVACY.md](PRIVACY.md).

## 5. Fallback behaviour

| Situation | Behaviour |
| --- | --- |
| Detection is uncertain (confidence below 0.55) | The assistant keeps its current reply language. Risk rules still run on the text |
| Provider language hint present | The hint is used only in limited cases: if the text's language equals the hint, confidence rises by `0.1 * hint_confidence`; if the text's confidence is below 0.6 and the hint's is at least 0.7, the hint is **adopted** (the detection's confidence becomes 0.8 times the hint's, at most 0.9); otherwise the disagreement is noted (`hint_conflict`) and the text evidence stands. A test pins that a strong English sentence is not overridden by a Kannada hint |
| Language fixed by the owner or the call (`language_mode`) | Detection is overridden with confidence 1.0; the forced language is the reply language |
| Caller speaks a language with no supported pack | The assistant answers in the call's current reply language (English at the start of a call) that it can help in English, Hindi or Kannada and asks the caller to continue in one of them. It asks at most twice (`max_clarify_attempts` = 2), then says a short farewell, records action `human_review` and ends the call with reason `unsupported_language` (unless a risk signal fired in that utterance) |
| Transcript unreadable (recognition confidence below 0.55, or no recognisable language) and no signal | The assistant asks the caller to repeat, at most twice per call |
| Reply language has no template for a key | The planner falls back to the English template (`ReplyPlanner._template`); every supported pack is tested to have every key |
| Protected request in any supported language | Refused whatever language was detected, because rules are merged across all supported packs |

Verified by running the engine: three consecutive Tamil-script turns produced `unsupported_language`,
`unsupported_language`, then `farewell_message` with action `human_review`.

## 6. Kannada and Kanglish specifics

* **Unicode handling.** Python's `\w` and `\b` do not treat Indic vowel signs and viramas as word characters.
  `compile_pattern` rewrites `\w`, `\W` and `\b` in every pack pattern to Indic-aware classes, so a rule such as `\bಒಟಿಪಿ\b`
  matches inside Kannada text and a Devanagari word glued to its neighbours is not matched as a separate word
  (`tests/unit/test_text.py` covers Devanagari and Kannada boundaries). Invisible characters are handled in two places.
  `sanitize_text` in the engine (NFKC, then a 1000-character cap) deletes soft hyphens, bidirectional marks, variation
  selectors, tag and private-use characters and zero-width spaces, and treats a zero-width joiner or non-joiner according
  to its neighbours: next to an Indic letter it becomes a space (Kannada and Hindi writers put one between a word and its
  suffix, and the lexicons were written for that tokenisation), between Latin letters it is deleted. `normalize` then
  deletes every invisible character and removes them from the patterns too, and folds Cyrillic and Greek look-alike
  letters to Latin inside otherwise-Latin words. Verified by running the engine at commit `117752e`: `ನಿಮ್ಮ ಪಾಸ್ವರ್ಡ್ ಹೇಳಿ`
  with and without a ZWNJ or ZWJ inside the word raises `PASSWORD_REQUEST` in all three forms (the sanitised text of the
  two joiner forms has a space inside the word, and the Kannada patterns list the split form); `tell me your O<zero-width
  space>TP now`, `O<soft hyphen>TP` and a Cyrillic `о` in `оtp` raise `OTP_REQUEST`. Not folded: other confusables, a
  digit zero for the letter O (`0TP`) and hyphenated letters (`o-t-p`); `0TP` and `o-t-p` raised nothing. The security
  review lists joiners next to Indic letters as an open item: a person typing into a text channel can split an Indic
  keyword with one ([SECURITY_REVIEW.md](SECURITY_REVIEW.md)). Tests: `tests/unit/test_text.py`,
  `tests/unit/test_signals.py`, `tests/unit/test_engine.py`.
* **Loanword stems and inflection.** Kannada attaches case endings to loanwords. The organisation vocabularies match a
  stem followed by any ending (`\w*`): stems such as ಬ್ಯಾಂಕ (bank), ಪೊಲೀಸ (police) and ಇನ್ಸ್ಪೆಕ್ಟರ (inspector). Verified by
  running: `ಬ್ಯಾಂಕಿನಿಂದ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ` ("speaking from the bank") raises `IMPERSONATION_BANK`.
* **Sandhi.** Kannada joins words, so the same question appears spaced and fused. The owner-availability patterns accept
  both, with optional whitespace between the stem and the ending: verified by running, `ಮನೆಯಲ್ಲಿದ್ದಾರಾ` ("is he at
  home", fused) and `ಮನೆಯಲ್ಲಿ ಇದ್ದಾರಾ` (spaced) both raise `OWNER_AVAILABILITY_PROBE`.
* **Denials.** Kannada denial phrases are part of the `negation` cues. `ಯಾರಿಗೂ ಒಟಿಪಿ ಹೇಳಬೇಡಿ` ("do not tell anyone the
  OTP") raises no signal, while `ಯಾರಿಗೂ ಒಟಿಪಿ ಹೇಳಬೇಡಿ, ನನಗೆ ಒಟಿಪಿ ಹೇಳಿ` (adding "tell me the OTP") raises
  `OTP_REQUEST`; see [SAFETY_MODEL.md](SAFETY_MODEL.md#8-denials-versus-requests) for the residual risks.
* **Kanglish (romanised Kannada).** Recognition relies on the Kannada pack's `latin_words` and `latin_suffixes`
  (verb endings such as `-beku`, `-illa`, `-inda`, `-annu`, `-iddira`). Spelling varies a lot (`maadi` and `madi`,
  `beku` and `beeku`); `canon_latin` folds the common variants (`canon_latin("maadbeku")` is `madbeku`), and the pack
  lists several spellings explicitly. Suffix patterns are matched against the folded token.
* **Voices.** Only `kn-IN-SapnaNeural` and `kn-IN-GaganNeural` are listed; no multilingual voice is configured.

## 7. Hindi and Hinglish specifics

* **Two scripts, one vocabulary.** Each sensitive term has Devanagari and romanised patterns in `packs/hi.toml`
  (`[terms]`), for example the OTP term matches `ओटीपी`, `ओ टी पी`, "वन टाइम पासवर्ड" and "message mein aaya hua code".
  Romanised variants are folded by `canon_latin` in the detector; the rule patterns themselves list the common spellings.
  Unit tests cover `kyaa`/`kya`, `aapka`/`apka`, `hoon`/`hun`, `beeku`/`biku` and `wo`/`vo` (`tests/unit/test_text.py`).
* **Digits and nukta.** Devanagari digits are converted to ASCII before matching, and the nukta is removed, so `जरूर` and
  `ज़रूर` match the same patterns.
* **Hindi versus Marathi.** The two share Devanagari. The detector counts marker words for each (`native_words` in the
  packs) and labels the text Marathi only when at least two Marathi markers appear and there are more of them than Hindi
  markers; a Marathi sentence is then `unsupported` (`tests/unit/test_language.py`).
* **Replies.** A Hinglish caller is answered in Hindi in Devanagari, using the `hi-IN-SwaraNeural` voice by default.
  The Latin transliteration ("Namaste, main ... AI call assistant hoon") is kept for developers and testers.

## 8. Test corpus

| What | Where | Notes |
| --- | --- | --- |
| Evaluation dataset v1 | `packages/evaluation/dataset/v1/{dev,test}.jsonl` and `MANIFEST.md`, schema `packages/evaluation/scenario.schema.json` | 70 development and 70 held-out test scenarios. Per split: english 15, hindi 9, hinglish 15, kannada 9, kanglish 15, mixed 4, unsupported 3. Synthetic, written by an AI assistant, not reviewed by native speakers; labels are one author's judgement; 26% of scenarios per split are written as noisy, unpunctuated transcripts with author-assigned confidence values |
| Language detection tests | `services/api/tests/unit/test_language.py`, `test_text.py` | Registry contents, pack completeness, detection of each profile, code-switch segmentation, forced language, provider-hint behaviour, determinism |
| Signal rules per language | `services/api/tests/unit/test_signals.py` | Detection of each signal in English, Hindi, Kannada, Hinglish and Kanglish, plus the denial cases |
| Claim extraction | `services/api/tests/unit/test_extraction.py` | Name and organisation extraction, including a Kanglish sentence |
| Reply templates | `services/api/tests/unit/test_planner_validator.py`, `tests/unit/test_engine.py` | Every template in every language passes the output validator for the owner name `Atharv`, for no name and for six full names (initials, the directory form `Doe, Jane`, a Devanagari and a Kannada name among them; the default style); every disclosure, in every language and style and for those names, says it is an AI assistant; the engine's opening line discloses the AI for each of the six names in each style, and for names with digits, a phone-like number, a link-like word or an e-mail address (`test_opening_discloses_the_ai_whatever_the_owner_is_called`) |
| Language-following in a call | `services/api/tests/unit/test_engine.py`, `tests/integration/test_call_service.py` | Switching, forced mode, unsupported-language flow |

## 9. Measured detector results

Copied from `docs/eval/latest-dev.md` and `docs/eval/latest-test.md` (generated 2026-11-17 by `python -m sparta evaluate`
against policy `2026.11.2`; method and caveats in [EVALUATION.md](EVALUATION.md), which also records that the test split
was not re-run after the input hardening of commit `117752e`). The dev split was used for tuning; the
test split is held out. The harness gives the engine
scripted text only, with no language hint, so this measures the text detector, not speech recognition. Intervals are the
95% intervals printed in the reports.

| Measure | Dev | Test |
| --- | --- | --- |
| Per-turn language detected correctly (en/hi/kn/other) | 94.0% (141/150), 89.0% to 96.8% | 97.1% (165/170), 93.3% to 98.7% |
| Call language profile exact match | 94.3% (66/70), 86.2% to 97.8% | 95.7% (67/70), 88.1% to 98.5% |
| Code-switched calls (Hinglish, Kanglish, mixed): profile match | 97.1% (33/34), 85.1% to 99.5% | 97.1% (33/34), 85.1% to 99.5% |

| Language | Dev precision / recall / F1 | Test precision / recall / F1 |
| --- | --- | --- |
| en-IN | 83.3% / 100.0% / 90.9% | 89.6% / 100.0% / 94.5% |
| hi-IN | 96.2% / 100.0% / 98.1% | 100.0% / 100.0% / 100.0% |
| kn-IN | 100.0% / 94.5% / 97.2% | 100.0% / 96.4% / 98.2% |
| other | 100.0% / 33.3% / 50.0% | 100.0% / 66.7% / 80.0% |

Read with care: the "other" class (unsupported languages) has three scenarios per split, so its figures are very
uncertain; English precision below 100% means some turns that were not English were labelled English; synthetic
transcripts are cleaner than real speech-recognition output; and the dev and test numbers differ because the rules were
tuned on dev.
The reports also hold a robustness sweep with synthetic recognition noise (dropped words, swapped letters); it is not real
recogniser error.

## 10. Adding a language

1. Add `services/api/src/sparta/language/packs/<iso>.toml` with `[meta]` (`code`, `iso`, `name`, `native_name`, `scripts`,
   `status`, `stt_locale`, `tts_locale`, `default_voice`), `[detection]` (romanised or native marker words), `[terms]` and
   `[cues]` (named regular-expression vocabularies that the policy refers to), `[owner_ref.named]` and
   `[owner_ref.generic]`, and `[templates.*]` for every template key in the English pack. Start with `status = "planned"`.
2. Patterns are compiled at load time, so a broken pattern fails at startup, not during a call
   (`tests/unit/test_language.py::test_bad_pattern_fails_at_load_time_not_mid_call`). No rule code changes are needed
   (`test_adding_a_language_needs_only_a_pack_not_new_rule_code`).
3. Switch to `status = "supported"` only after a native speaker has reviewed the vocabularies and templates, the
   language has a documented STT locale and a default voice, and dataset scenarios for it exist. A supported pack must
   have a default voice and every English template key (tested).
4. Add scenarios to the **dev** split and tune there; keep the test split untouched (see
   [SAFETY_MODEL.md](SAFETY_MODEL.md#13-changing-the-rules)).

## 11. Free local speech (Phase 3): what it can and cannot do

`SPARTA_STT_PROVIDER=local` and `SPARTA_TTS_PROVIDER=local` run recognition and synthesis on the machine itself, with no cloud
account: **faster-whisper** (MIT, CPU int8, the `small` model by default) hears the caller and **Piper** (a GPL-3.0 engine) speaks.
They are an optional extra (`pip install "sparta-api[local-speech]"`, or `SPARTA_LOCAL_SPEECH=1` in the Docker build), never part of
the default install, and they never download anything while running: `python -m sparta models fetch` is the only command that
does (from Hugging Face, pinned to a commit and a SHA-256 per file, redirects not followed), and `models verify` re-checks the files.
ONNX Runtime's telemetry is switched off. This is an **experimental developer stack**, not a quality claim.

**What works, measured on one Windows laptop (CPU only, shared with other work, so treat the times as upper bounds):**

| Language | Recognition (Whisper `small`) | Voice (Piper) |
| --- | --- | --- |
| English (`en-IN`) | **Works.** "I'm calling from your bank. Tell me your OTP." spoken by Piper, down-sampled to 8 kHz and read back by Whisper came back word for word (confidence 0.77). No claim is made for telephone-band audio or Indian-English accents: they were not measured. | `en_US-ljspeech-medium` (an American voice; there is no Indian-English voice in the official catalogue) |
| Hindi (`hi-IN`) | **Unreliable.** The Devanagari OTP request came back as "सर आपका के वाईसी अप्देट करना है, क्रपिया उतीपी बताएगे" (the word for OTP became "उतीपी") with a confidence of 0.69 to 0.73, so it passes the poor-audio gate while wrong. | `hi_IN-priyamvada-medium` |
| Kannada (`kn-IN`) | **Not usable.** The Kannada sentence came back in Devanagari script as the wrong words (confidence 0.50). The research figure for `small` is a 100% word error rate on FLEURS Kannada. | `kn_IN-syspin_male-medium` (a community voice) |
| Hinglish, Kanglish | **Unreliable.** Measured through real SIP with the *English* voice reading the Latin text (a machine reading romanised words, which is not how a person speaks, so a real caller may do better or worse): "Sir KYC update karna hai, OTP bata dijiye." came back as "Sir KYC Update, Kanner High, OTP, Barter, D.G.I." (0.62); "Sir nimma account update madbeku, OTP heli." as "CERN number, account, update, MABICU, OTP, HELLING." (0.62); "Verification ge nimma UPI PIN heli." as "Verification G, Numer UPIPIN, Kelly." (0.50). None was refused. | (the English voice) |

Confidence is **capped** where the small model is known to be poor (Hindi and Kannada), so that the engine treats such a transcript
as poor audio instead of acting on it; a forced Whisper language reports a probability of 1.0, which is not a confidence and is
ignored. The deterministic rules run on whatever text comes back, so a wrong transcript can **miss** a scam: a Hindi, Hinglish,
Kanglish or Kannada caller is not reliably screened with the small model. The rules themselves are not what failed in those
calls: given the words that were actually said, they refuse all five lines ([PHASE3_ASTERISK_PLAN.md](PHASE3_ASTERISK_PLAN.md)
section 8). A larger model (`large-v3-turbo`) is the next thing to try; it was not
downloaded or measured (the machine had too little free memory), and its cost is an extrapolation, not a measurement.

**Measurements** (local, this machine, CPU int8, `small`, shared machine):

| What | Value |
| --- | --- |
| Start-up (warm-up, now done once at server start) | import 3.5 s, model load 2.8 s, first inference 2.6 s; each voice loads in about 1.5 s; memory 94 MB to 679 MB with the model and three voices. The very first start after a download, with the CPU saturated: recogniser warm-up 51.7 s, voices 18.2 s |
| Recognising a 3.7 s English utterance (15 runs) | p50 2.69 s, p95 4.02 s with the language forced; p50 4.56 s with automatic language detection (it runs the encoder twice). Whisper always processes a padded 30 s window, which is about 2.4 s of the cost |
| Piper, first audio chunk | English 0.29 s p50 (5.2 s of speech), Hindi 0.39 s, Kannada 0.44 s; real-time factor about 0.10 |
| Stopping speech on a barge-in | the audio ends about 0.1 ms after the stop; the next line starts about 66 ms later |
| Event-loop delay while recognising | a 5 ms ticker was up to 42 ms late (the Asterisk playback lead is 40 ms) |

Known limits that follow from the design: the language is sticky for the rest of a call once the first utterance has set it;
with one inference worker, recognitions from different calls queue behind each other; a missing voice raises a clear error
instead of speaking another language (an English fallback would need the English text carried through the speech request, which
it is not); and a decoder limit stops the runaway loops that the small model produced on Hindi and Kannada (which once held the only
worker for 34 to 53 s).

**Licences, which need a legal review before any distribution:** faster-whisper and the Whisper weights are MIT. Piper's engine is
**GPL-3.0-or-later** (copyleft), which is why it is an opt-in extra and a separate lock file. The English voice is trained on the
LJ Speech dataset (public domain). The Hindi voice's dataset licence is **CC-BY-NC-SA-4.0** (non-commercial, share-alike) and the grant
for the trained weights is not established; the Kannada voice is a community model whose author states **non-commercial use only**.
Do not use the Hindi and Kannada voices commercially without clearing this.

**No native speaker has reviewed any of this**, and nothing here has been heard by a person on a phone.
