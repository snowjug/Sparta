"""Reply planning from language-pack templates.

The assistant never free-styles: every utterance is rendered from a closed set of vetted templates, so it cannot ask for
protected information, reveal owner details or claim to be the owner. Anything that is *not* a template (for example a
suggestion from an LLM provider) must pass :class:`sparta.orchestrator.validator.OutputValidator` first.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from sparta.domain.enums import ResponseStyle
from sparta.domain.models import SpeechPlan
from sparta.language.registry import LanguagePack, PackRegistry, Template, load_registry
from sparta.providers.tts.ssml import estimate_duration_ms

FALLBACK_LANGUAGE = "en-IN"
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>{}\[\]`\\\"]")
_SPACES = re.compile(r"\s+")
GENERIC_NAMES = {"", "the owner", "owner", "the user", "user"}


def clean_owner_name(name: str | None) -> str | None:
    """Sanitised display name or ``None`` (→ generic wording). Guards templates against odd characters.

    An e-mail address or user principal name is an identifier, not a name: identity providers send one as the display name
    when the account has none, and the assistant would read it out to an unknown caller. It is spoken as "the owner"."""
    if not name:
        return None
    cleaned = _SPACES.sub(" ", _CONTROL.sub("", name)).strip()[:40]
    if cleaned.lower() in GENERIC_NAMES or "@" in cleaned:
        return None
    return cleaned


@dataclass(frozen=True)
class PlannerConfig:
    owner_name: str | None = None
    response_style: ResponseStyle = ResponseStyle.CONCISE
    speaking_rate: float = 1.0
    voice_ids: Mapping[str, str] = field(default_factory=dict)


def _capfirst(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1 :]
        if not ch.isspace():
            break
    return text


class ReplyPlanner:
    def __init__(self, registry: PackRegistry | None = None) -> None:
        self.registry = registry or load_registry()

    # ------------------------------------------------------------------ lookup
    def _pack(self, language: str) -> LanguagePack:
        pack = self.registry.pack(language)
        if pack is None or pack.spec.status != "supported" or not pack.templates:
            pack = self.registry.pack(FALLBACK_LANGUAGE)
        assert pack is not None  # en-IN ships with the product
        return pack

    def _template(self, pack: LanguagePack, key: str, variant: str) -> Template:
        group = pack.templates.get(key)
        if group is None:
            fallback = self.registry.pack(FALLBACK_LANGUAGE)
            assert fallback is not None
            group = fallback.templates[key]
        return group.get(variant) or group.get("default") or group.get("concise") or next(iter(group.values()))

    @staticmethod
    def _owner_fill(pack: LanguagePack, name: str | None, translit: bool) -> dict[str, str]:
        ref = pack.owner_ref.get("named" if name else "generic", {})
        out: dict[str, str] = {}
        for slot in ("poss", "to", "subj"):
            raw = ref.get(f"{slot}_translit" if translit and f"{slot}_translit" in ref else slot, "")
            out[slot] = raw.replace("{name}", name) if name else raw
        return out

    def _fill(self, template: str, pack: LanguagePack, name: str | None, translit: bool) -> str:
        owner = self._owner_fill(pack, name, translit)
        return (
            template.replace("{owner_poss}", owner["poss"])
            .replace("{owner_to}", owner["to"])
            .replace("{owner_subj}", owner["subj"])
        )

    # ------------------------------------------------------------------ rendering
    def render_keys(self, keys: list[str], language: str, cfg: PlannerConfig, variant: str | None = None) -> SpeechPlan:
        """Render one or more template keys, in order, into a single plan in ``language``."""
        pack = self._pack(language)
        name = clean_owner_name(cfg.owner_name)
        style = variant or cfg.response_style.value
        texts: list[str] = []
        translits: list[str] = []
        has_translit = False
        for key in keys:
            tpl = self._template(pack, key, style)
            texts.append(_capfirst(self._fill(tpl.text, pack, name, translit=False)))
            if tpl.translit:
                has_translit = True
                translits.append(_capfirst(self._fill(tpl.translit, pack, name, translit=True)))
            else:
                translits.append(texts[-1])
        text = " ".join(texts)
        spec = pack.spec
        return SpeechPlan(
            text=text,
            locale=spec.tts_locale,
            voice_id=cfg.voice_ids.get(spec.tts_locale) or spec.default_voice,
            rate=cfg.speaking_rate,
            style=None,
            transliteration=" ".join(translits) if has_translit else None,
            est_duration_ms=estimate_duration_ms(text, spec.tts_locale, cfg.speaking_rate),
        )

    def render(self, key: str, language: str, cfg: PlannerConfig, variant: str | None = None) -> SpeechPlan:
        return self.render_keys([key], language, cfg, variant)

    def english_equivalent(self, keys: list[str], cfg: PlannerConfig, variant: str | None = None) -> str:
        """Exact English wording of the same template keys: an honest translation of assistant lines."""
        return self.render_keys(keys, FALLBACK_LANGUAGE, cfg, variant).text

    def disclosure(self, language: str, cfg: PlannerConfig) -> SpeechPlan:
        return self.render("disclosure", language, cfg)

    def template_keys(self) -> list[str]:
        pack = self.registry.pack(FALLBACK_LANGUAGE)
        assert pack is not None
        return sorted(pack.templates)
