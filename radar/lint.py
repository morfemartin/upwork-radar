"""Deterministic checks of a drafted brief against the Bot v3.0 rules.

R1  hook first: no sender name / self-introduction in the first sentence
R2  no empty closing lines; R6 exactly one question, at the end
R5  full mode: phases with name, time and price (never a bare total)
R7  analog must be a real portfolio id
plus word limits per mode, banned phrases, unfilled blocks, hook rotation, and
anti-template checks: no pasted job title or client sentences, enough concrete
details of THIS job, and no two proposals of a run written from the same template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .brief import EN_END, EN_START, ES_END, ES_START, SRC_END, SRC_START, read_front_matter, section
from .config import Config

_SENT = re.compile(r"(?<=[.!?])\s+")
_PHASE = re.compile(r"(phase|milestone|step|stage)\b[^\n]*\$\s?\d[^\n]*", re.IGNORECASE)
_TIME = re.compile(r"\b\d+\s*(?:-\s*\d+\s*)?(day|days|week|weeks|business days|hours?)\b", re.IGNORECASE)
_SELF_INTRO = re.compile(r"^\s*(hi|hello|hey|dear|greetings)\b|\bmy name is\b", re.IGNORECASE)
_MONEY = re.compile(r"\$\s?(\d[\d,]*)")
_WORD = re.compile(r"[a-z][a-z'-]+")

COPY_WINDOW = 9            # this many consecutive words copied from the posting = pasted text
MIN_SPECIFIC_TERMS = 3     # distinct, job-specific words the proposal must use
MAX_SIMILARITY = 0.25      # shingle overlap between two proposals of the same run

STOP = set("""
about above after again against also among another anyone around because before being below between both
brand brief build business client clients content could create created creating deliver delivered delivery
design designer designs detail detailed details different during each early either every experience
experienced final first following freelancer from future great have help high ideal ideally include
including into just keep know large later least like looking make making many more most must need
needed needs only other our ours over own part people please portfolio prefer process professional
project projects provide quality ready really right same share should similar since skills small some
someone something start still such sure take team than that their them then there these they thing
think this those through time together under until using very want wants well were what when where
which while will with within without work working would your yours year years
""".split())


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9$’'%-]+", text))


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("’", "'"))


def specific_terms(source: str, title: str = "") -> set[str]:
    """Distinctive words of a posting: 5+ letters, not generic hiring vocabulary."""
    return {t for t in tokens(f"{title} {source}") if len(t) >= 5 and t not in STOP}


def copied_spans(en: str, source: str, n: int = COPY_WINDOW) -> list[str]:
    src = tokens(source)
    grams = {" ".join(src[i:i + n]) for i in range(len(src) - n + 1)}
    out = []
    toks = tokens(en)
    for i in range(len(toks) - n + 1):
        g = " ".join(toks[i:i + n])
        if g in grams:
            out.append(g)
    return out


def shingles(text: str, n: int = 5) -> set[str]:
    t = tokens(text)
    return {" ".join(t[i:i + n]) for i in range(len(t) - n + 1)}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def lint_text(text: str, cfg: Config, hooks_used_today: list[str] | None = None) -> LintResult:
    r = LintResult()
    fm, _ = read_front_matter(text)
    if "<!-- FILL:" in text:
        left = re.findall(r"<!-- FILL:(\w+) -->", text)
        r.errors.append(f"faltan bloques por llenar: {', '.join(left)}")
    en = section(text, EN_START, EN_END)
    es = section(text, ES_START, ES_END)
    src = section(text, SRC_START, SRC_END) or ""
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

    phase_lines = [l for l in en.splitlines() if _PHASE.search(l)]
    if mode == "full":
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

    # ---- anti-template checks ----
    title = str(fm.get("title") or "")
    if title and len(title) > 15 and title.lower() in low:
        r.errors.append("plantilla: pega el título del job dentro de la propuesta")
    if src:
        spans = copied_spans(en, src)
        if spans:
            r.errors.append(f"plantilla: copia frases del cliente (“{spans[0]}…”)")
        terms = specific_terms(src, title)
        used = sorted(terms & set(tokens(en)))
        if terms and len(used) < MIN_SPECIFIC_TERMS:
            r.errors.append(f"genérica: usa {len(used)} detalle(s) concretos del job, mínimo {MIN_SPECIFIC_TERMS}"
                            + (f" ({', '.join(used)})" if used else ""))
    else:
        r.warnings.append("el brief no trae la publicación original (sección 0); no se pudo medir especificidad")

    budget = fm.get("budget")
    prices = [float(m.replace(",", "")) for l in phase_lines for m in _MONEY.findall(l)]
    if budget and prices:
        total = sum(prices)
        if total < 0.4 * float(budget) or total > 3 * float(budget):
            r.warnings.append(f"precio: las fases suman ${total:,.0f} y el presupuesto es ${float(budget):,.0f}")
    return r


def lint_file(path: str | Path, cfg: Config, hooks_used_today: list[str] | None = None) -> LintResult:
    return lint_text(Path(path).read_text(encoding="utf-8"), cfg, hooks_used_today)


def lint_many(paths: list[str | Path], cfg: Config,
              hooks_used_today: list[str] | None = None) -> dict[str, LintResult]:
    """Lint each brief, then flag pairs of proposals written from the same template."""
    texts = {str(p): Path(p).read_text(encoding="utf-8") for p in paths}
    results = {p: lint_text(t, cfg, hooks_used_today) for p, t in texts.items()}
    ens = {p: section(t, EN_START, EN_END) or "" for p, t in texts.items()}
    keys = list(ens)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            s = similarity(ens[a], ens[b])
            if s > MAX_SIMILARITY:
                msg = "plantilla: {:.0%} igual a {}"
                results[a].errors.append(msg.format(s, Path(b).name[:40]))
                results[b].errors.append(msg.format(s, Path(a).name[:40]))
    return results
