"""Language registry: loads data-driven language packs (``packs/*.toml``).

A pack contributes:
* ``[meta]``      – identity, scripts, speech locales, support status;
* ``[detection]`` – romanized word lists / suffixes / native-script marker words used by the detector;
* ``[terms]`` and ``[cues]`` – named regex vocabularies that the (language-neutral) safety policy refers to by name;
* ``[templates.*]`` – assistant utterances (native script text + Latin transliteration).

Terms and cues with the same name are **merged across all packs**. Rules therefore apply to every language at once,
which is essential for Hinglish/Kanglish code-switching and means detection errors can never switch safety off.
Adding a language is adding a pack file; no rule code changes.
"""

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from sparta.language.text import canon_latin, compile_pattern

PackStatus = Literal["supported", "planned"]
PACK_PACKAGE = "sparta.language.packs"


@dataclass(frozen=True)
class Template:
    text: str
    translit: str | None = None


@dataclass(frozen=True)
class LanguageSpec:
    code: str  # BCP-47, e.g. "hi-IN"
    iso: str  # e.g. "hi"
    name: str
    native_name: str
    scripts: tuple[str, ...]
    status: PackStatus
    stt_locale: str
    tts_locale: str
    default_voice: str | None
    pack_version: str


@dataclass
class LanguagePack:
    spec: LanguageSpec
    latin_words: frozenset[str] = frozenset()
    latin_suffixes: tuple[str, ...] = ()
    native_words: frozenset[str] = frozenset()
    terms: dict[str, list[str]] = field(default_factory=dict)
    cues: dict[str, list[str]] = field(default_factory=dict)
    templates: dict[str, dict[str, Template]] = field(default_factory=dict)
    owner_ref: dict[str, dict[str, str]] = field(default_factory=dict)


class PackError(ValueError):
    pass


OWNER_PLACEHOLDER = "{OWNER}"
_DUMMY_OWNER = "(?:owner)"


def _load_pack(raw: dict[str, Any], source: str) -> LanguagePack:
    try:
        meta = raw["meta"]
        spec = LanguageSpec(
            code=meta["code"],
            iso=meta["iso"],
            name=meta["name"],
            native_name=meta["native_name"],
            scripts=tuple(meta["scripts"]),
            status=meta["status"],
            stt_locale=meta.get("stt_locale", meta["code"]),
            tts_locale=meta.get("tts_locale", meta["code"]),
            default_voice=meta.get("default_voice"),
            pack_version=str(raw.get("version", "1")),
        )
    except KeyError as exc:
        raise PackError(f"{source}: missing meta field {exc}") from exc

    detection = raw.get("detection", {})
    pack = LanguagePack(
        spec=spec,
        latin_words=frozenset(canon_latin(w) for w in detection.get("latin_words", [])),
        latin_suffixes=tuple(detection.get("latin_suffixes", [])),
        native_words=frozenset(w.lower() for w in detection.get("native_words", [])),
        terms={k: list(v) for k, v in raw.get("terms", {}).items()},
        cues={k: list(v) for k, v in raw.get("cues", {}).items()},
        owner_ref={k: dict(v) for k, v in raw.get("owner_ref", {}).items()},
    )
    for key, variants in raw.get("templates", {}).items():
        pack.templates[key] = {
            variant: Template(body["text"], body.get("translit")) for variant, body in variants.items()
        }
    # Fail at load time (not in the middle of a call) if a pattern does not compile.
    for name, fragments in {**pack.terms, **pack.cues}.items():
        for fragment in fragments:
            try:
                compile_pattern(fragment.replace(OWNER_PLACEHOLDER, _DUMMY_OWNER))
            except Exception as exc:
                raise PackError(f"{source}: bad pattern in '{name}': {fragment!r}: {exc}") from exc
    return pack


class PackRegistry:
    def __init__(self, packs: list[LanguagePack]) -> None:
        self._packs: dict[str, LanguagePack] = {p.spec.code: p for p in packs}
        merged_terms: dict[str, list[str]] = {}
        merged_cues: dict[str, list[str]] = {}
        for pack in packs:
            if pack.spec.status != "supported":
                continue
            for name, frags in pack.terms.items():
                merged_terms.setdefault(name, []).extend(frags)
            for name, frags in pack.cues.items():
                merged_cues.setdefault(name, []).extend(frags)
        self.terms = merged_terms
        self.cues = merged_cues

    @property
    def codes(self) -> list[str]:
        return sorted(self._packs)

    def pack(self, code: str) -> LanguagePack | None:
        return self._packs.get(code)

    def specs(self) -> list[LanguageSpec]:
        return [p.spec for p in sorted(self._packs.values(), key=lambda p: p.spec.code)]

    def supported(self) -> list[LanguageSpec]:
        return [s for s in self.specs() if s.status == "supported"]

    def supported_codes(self) -> list[str]:
        return [s.code for s in self.supported()]

    def packs(self) -> list[LanguagePack]:
        return list(self._packs.values())

    def version(self) -> str:
        return ",".join(f"{p.spec.iso}:{p.spec.pack_version}" for p in self._packs.values())


@lru_cache
def load_registry() -> PackRegistry:
    packs: list[LanguagePack] = []
    root = resources.files(PACK_PACKAGE)
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml"):
            raw = tomllib.loads(entry.read_text(encoding="utf-8"))
            packs.append(_load_pack(raw, entry.name))
    if not packs:
        raise PackError("no language packs found")
    return PackRegistry(packs)
