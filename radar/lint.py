"""Deterministic checks of a drafted brief against the Bot v3.0 rules.

R1  hook first: no sender name / self-introduction in the first sentence
R2  no empty closing lines; R6 exactly one question, at the end
R5  full mode: phases with name, time and price (never a bare total)
R7  analog must be a real portfolio id
plus word limits per mode, banned phrases, unfilled blocks, hook rotation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .brief import EN_END, EN_START, ES_END, ES_START, read_front_matter, section
from .config import Config

_SENT = re.compile(r"(?<=[.!?])\s+")
_PHASE = re.compile(r"(phase|milestone|step|stage)\b[^\n]*\$\s?\d[^\n]*", re.IGNORECASE)
_TIME = re.compile(r"\b\d+\s*(?:-\s*\d+\s*)?(day|days|week|weeks|business days|hours?)\b", re.IGNORECASE)
_SELF_INTRO = re.compile(r"^\s*(hi|hello|hey|dear|greetings)\b|\bmy name is\b", re.IGNORECASE)


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9$’'%-]+", text))


def lint_text(text: str, cfg: Config, hooks_used_today: list[str] | None = None) -> LintResult:
    r = LintResult()
    fm, _ = read_front_matter(text)
    if "<!-- FILL:" in text:
        left = re.findall(r"<!-- FILL:(\w+) -->", text)
        r.errors.append(f"faltan bloques por llenar: {', '.join(left)}")
    en = section(text, EN_START, EN_END)
    es = section(text, ES_START, ES_END)
    if not en:
        r.errors.append("no hay propuesta en inglés entre los marcadores EN")
        return r
    if not es:
        r.errors.append("no hay borrador en español entre los marcadores ES")

    mode = fm.get("mode", "fast")
    lo, hi = cfg.rules.full_words if mode == "full" else cfg.rules.fast_words
    n = words(en)
    if not lo <= n <= hi:
        r.errors.append(f"largo {n} palabras; modo {mode} pide {lo}–{hi}")

    first = _SENT.split(en.strip(), maxsplit=1)[0]
    names = [t for t in cfg.rules.name_tokens if re.search(rf"\b{re.escape(t)}\b", first, re.IGNORECASE)]
    if names or _SELF_INTRO.search(first):
        r.errors.append(f"R1: la primera oración presenta al emisor ({', '.join(names) or 'saludo/presentación'})")

    q = en.count("?")
    paragraphs = [p for p in re.split(r"\n\s*\n", en.strip()) if p.strip()]
    if q != 1:
        r.errors.append(f"R6: debe haber exactamente una pregunta y hay {q}")
    elif "?" not in paragraphs[-1]:
        r.errors.append("R2: la única pregunta tiene que ir en el último párrafo")

    if mode == "full":
        phase_lines = [l for l in en.splitlines() if _PHASE.search(l)]
        if len(phase_lines) < 2:
            r.errors.append("R5: modo completo necesita al menos 2 fases con nombre y precio")
        elif not all(_TIME.search(l) for l in phase_lines):
            r.warnings.append("R5: alguna fase no indica tiempo")

    low = en.lower()
    for phrase in cfg.rules.banned_phrases:
        if phrase.lower() in low:
            r.errors.append(f"frase prohibida: “{phrase}”")

    analog = fm.get("analog_id")
    if not analog:
        r.errors.append("R7: falta analog_id en el encabezado")
    elif not cfg.portfolio.get(str(analog)):
        r.errors.append(f"R7: analog_id {analog!r} no existe en portfolio.yaml")

    hook = fm.get("hook_type")
    if hook not in cfg.rules.hook_types:
        r.errors.append(f"hook_type debe ser uno de {cfg.rules.hook_types}")
    elif hooks_used_today and hook in hooks_used_today:
        r.warnings.append(f"el hook {hook} ya se usó hoy")

    if re.search(r"\[[^\]]+\]|\{\{|TODO|XXX", en):
        r.errors.append("quedan marcadores sin reemplazar ([...], {{ }}, TODO)")
    return r


def lint_file(path: str | Path, cfg: Config, hooks_used_today: list[str] | None = None) -> LintResult:
    return lint_text(Path(path).read_text(encoding="utf-8"), cfg, hooks_used_today)
