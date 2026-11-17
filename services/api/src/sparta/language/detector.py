"""Language and code-switch detection.

Native scripts are decisive (Devanagari → Hindi/Marathi, Kannada script → Kannada, …). Latin-script text is classified
token by token against per-language romanized lexicons, which is how Hinglish and Kanglish are recognised. The result
carries per-segment languages so the UI can show code-switching and the orchestrator can follow the caller's language.

This is deliberately a transparent heuristic, not a trained model: it is fast, deterministic and testable, and it
reports its own uncertainty. It is *never* a safety gate; the risk rules run on every language regardless.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from sparta.domain.models import LanguageSegment
from sparta.language.registry import LanguagePack, PackRegistry, load_registry
from sparta.language.text import canon_latin, compile_pattern, token_script, tokenize

SCRIPT_LANG = {"Knda": "kn-IN", "Taml": "ta-IN", "Telu": "te-IN", "Mlym": "ml-IN", "Beng": "bn-IN"}
SUFFIX_WEIGHT = 0.5
UNKNOWN = "und"


@dataclass
class Detection:
    language: str
    confidence: float
    languages: list[str]
    scores: dict[str, float]
    profile: str
    segments: list[LanguageSegment]
    supported: bool
    uncertain: bool
    hint_conflict: bool = False
    token_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_code_switched(self) -> bool:
        return self.profile in {"hinglish", "kanglish", "mixed"}


class LanguageDetector:
    def __init__(self, registry: PackRegistry | None = None) -> None:
        self.registry = registry or load_registry()
        self._latin: list[LanguagePack] = [p for p in self.registry.packs() if p.latin_words or p.latin_suffixes]
        self._suffix = {
            p.spec.code: [compile_pattern(s) for s in p.latin_suffixes] for p in self._latin if p.latin_suffixes
        }
        self._hi = self.registry.pack("hi-IN")
        self._mr = self.registry.pack("mr-IN")
        self._supported = set(self.registry.supported_codes())

    # ------------------------------------------------------------------ tokens
    def _classify_token(self, token: str, script: str, deva_hint: str) -> tuple[str | None, float]:
        if script == "Deva":
            return deva_hint, 1.0
        if script in SCRIPT_LANG:
            return SCRIPT_LANG[script], 1.0
        if script != "Latn":
            return None, 0.0
        canon = canon_latin(token.strip("'’"))
        if len(canon) < 2:
            return None, 0.0
        matches = [p.spec.code for p in self._latin if canon in p.latin_words]
        if len(matches) == 1:
            return matches[0], 1.0
        if len(matches) > 1:
            return None, 0.0
        if len(canon) >= 5:
            hits = [code for code, pats in self._suffix.items() if any(p.search(canon) for p in pats)]
            if len(hits) == 1:
                return hits[0], SUFFIX_WEIGHT
        return None, 0.0

    def _devanagari_language(self, tokens: list[tuple[str, int, int]]) -> str:
        if not self._mr or not self._hi:
            return "hi-IN"
        mr = sum(1 for t, _, _ in tokens if t.lower() in self._mr.native_words)
        hi = sum(1 for t, _, _ in tokens if t.lower() in self._hi.native_words)
        return "mr-IN" if mr >= 2 and mr > hi else "hi-IN"

    # ------------------------------------------------------------------ public
    def detect(
        self,
        text: str,
        hint: str | None = None,
        hint_confidence: float | None = None,
        forced: str | None = None,
    ) -> Detection:
        tokens = tokenize(text)
        scripts = [token_script(t) for t, _, _ in tokens]
        deva_tokens = [tok for tok, sc in zip(tokens, scripts, strict=True) if sc == "Deva"]
        deva_lang = self._devanagari_language(deva_tokens) if deva_tokens else "hi-IN"

        scores: dict[str, float] = {}
        labelled: list[tuple[int, int, str | None, str]] = []  # start, end, language, script
        for (tok, start, end), sc in zip(tokens, scripts, strict=True):
            lang, weight = self._classify_token(tok, sc, deva_lang)
            if lang:
                scores[lang] = scores.get(lang, 0.0) + weight
            labelled.append((start, end, lang, sc))

        total = sum(scores.values())
        if total <= 0:
            result = Detection(
                language=UNKNOWN,
                confidence=0.1,
                languages=[],
                scores={},
                profile="unknown",
                segments=[],
                supported=False,
                uncertain=True,
                token_count=len(tokens),
            )
            return self._apply_hint(result, hint, hint_confidence, forced)

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_lang, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = (top - second) / total
        evidence = min(1.0, total / 4.0)
        confidence = max(0.05, min(0.99, 0.35 + 0.45 * margin + 0.2 * evidence))

        languages = [code for code, s in ranked if s / total >= 0.15]
        profile = self._profile(top_lang, scores, total, labelled)
        result = Detection(
            language=top_lang,
            confidence=round(confidence, 3),
            languages=languages or [top_lang],
            scores={k: round(v, 3) for k, v in scores.items()},
            profile=profile,
            segments=self._segments(labelled, scores, total),
            supported=top_lang in self._supported,
            uncertain=confidence < 0.55,
            token_count=len(tokens),
        )
        return self._apply_hint(result, hint, hint_confidence, forced)

    # ------------------------------------------------------------------ helpers
    def _profile(
        self, top: str, scores: dict[str, float], total: float, labelled: list[tuple[int, int, str | None, str]]
    ) -> str:
        if top not in self._supported:
            return "unsupported"
        en = scores.get("en-IN", 0.0) / total
        hi = scores.get("hi-IN", 0.0) / total
        kn = scores.get("kn-IN", 0.0) / total
        if hi >= 0.2 and kn >= 0.2:
            return "mixed"
        native_share = sum(1 for _, _, lang, sc in labelled if lang and sc != "Latn") / max(
            1, sum(1 for _, _, lang, _ in labelled if lang)
        )
        if top == "en-IN":
            if hi >= 0.25:
                return "hinglish"
            if kn >= 0.25:
                return "kanglish"
            return "english"
        if top == "hi-IN":
            return "hindi" if native_share > 0.7 and en < 0.2 else "hinglish"
        if top == "kn-IN":
            return "kannada" if native_share > 0.7 and en < 0.2 else "kanglish"
        return "unknown"

    def _segments(
        self, labelled: list[tuple[int, int, str | None, str]], scores: dict[str, float], total: float
    ) -> list[LanguageSegment]:
        segments: list[LanguageSegment] = []
        current: dict[str, object] | None = None
        pending_start: int | None = None
        for start, end, lang, sc in labelled:
            if lang is None:
                if current is not None:
                    current["end"] = end
                elif pending_start is None:
                    pending_start = start
                continue
            if current is not None and current["language"] == lang:
                current["end"] = end
                current["scripts"][sc] = current["scripts"].get(sc, 0) + 1  # type: ignore[index,union-attr]
                continue
            if current is not None:
                segments.append(self._finish(current, scores, total))
            current = {
                "language": lang,
                "start": pending_start if pending_start is not None else start,
                "end": end,
                "scripts": {sc: 1},
            }
            pending_start = None
        if current is not None:
            segments.append(self._finish(current, scores, total))
        return segments

    def _finish(self, cur: dict[str, object], scores: dict[str, float], total: float) -> LanguageSegment:
        lang = str(cur["language"])
        scripts: dict[str, int] = cur["scripts"]  # type: ignore[assignment]
        script = max(scripts.items(), key=lambda kv: kv[1])[0]
        romanized = script == "Latn" and lang != "en-IN"
        variant = None
        if romanized and lang == "hi-IN":
            variant = "hinglish"
        elif romanized and lang == "kn-IN":
            variant = "kanglish"
        return LanguageSegment(
            language=lang,
            script=script if script in {"Latn", "Deva", "Knda"} else "Other",  # type: ignore[arg-type]
            romanized=romanized,
            start=int(cur["start"]),  # type: ignore[call-overload]
            end=int(cur["end"]),  # type: ignore[call-overload]
            confidence=round(min(0.99, 0.5 + scores.get(lang, 0.0) / max(total, 1.0) * 0.5), 3),
            variant=variant,  # type: ignore[arg-type]
        )

    def _apply_hint(
        self, result: Detection, hint: str | None, hint_confidence: float | None, forced: str | None
    ) -> Detection:
        if forced and forced != "auto":
            result.notes.append("language forced by call setting")
            result.language = forced
            result.confidence = 1.0
            result.supported = forced in self._supported
            result.uncertain = False
            if forced not in result.languages:
                result.languages = [forced, *result.languages]
            return result
        if not hint or hint == UNKNOWN:
            return result
        hint_conf = hint_confidence if hint_confidence is not None else 0.7
        if result.language == hint:
            result.confidence = round(min(0.99, result.confidence + 0.1 * hint_conf), 3)
            result.uncertain = result.confidence < 0.55
        elif result.confidence < 0.6 and hint_conf >= 0.7:
            result.notes.append(f"adopted speech-provider language hint {hint}")
            result.language = hint
            result.confidence = round(min(0.9, hint_conf * 0.8), 3)
            result.supported = hint in self._supported
            result.uncertain = result.confidence < 0.55
            if hint not in result.languages:
                result.languages = [hint, *result.languages]
        else:
            result.hint_conflict = True
            result.notes.append(f"speech-provider hint {hint} disagrees with text evidence")
        return result


@lru_cache
def get_detector() -> LanguageDetector:
    return LanguageDetector()


def display_name(profile: str) -> str:
    return {
        "english": "English",
        "hindi": "Hindi",
        "hinglish": "Hinglish",
        "kannada": "Kannada",
        "kanglish": "Kanglish",
        "mixed": "Mixed",
        "unsupported": "Unsupported language",
        "unknown": "Unknown",
    }.get(profile, profile)


_LATIN_RE = re.compile(r"[A-Za-z]")


def has_latin(text: str) -> bool:
    return bool(_LATIN_RE.search(text))
