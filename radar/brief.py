"""Render the per-job Markdown brief.

The code fills every factual section. The drafting agent fills only the blocks marked
`<!-- FILL:... -->`, then `radar lint` checks the result.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import Config
from .models import ScoredJob

FILL = "<!-- FILL:{name} -->"
ES_START, ES_END = "<!-- ES:START -->", "<!-- ES:END -->"
EN_START, EN_END = "<!-- EN:START -->", "<!-- EN:END -->"

FACTOR_ES = {
    "client": "Calidad del cliente",
    "competition": "Competencia",
    "portfolio_fit": "Alineación con portafolio",
    "skill_combo": "Combinación de habilidades",
    "pay_size": "Tamaño del cobro",
    "pay_speed": "Velocidad del cobro",
    "specificity": "Especificidad del brief",
    "lane_priority": "Prioridad de la arista",
}


def slug(text: str, n: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "job"


def brief_path(sj: ScoredJob, out_dir: str | Path, day: str | None = None) -> Path:
    day = day or datetime.now(timezone.utc).date().isoformat()
    return Path(out_dir) / day / f"{sj.job.id}-{slug(sj.job.title)}.md"


def _yes(v: bool | None) -> str:
    return "?" if v is None else ("sí" if v else "no")


def _money(v: float | None) -> str:
    return f"${v:,.0f}" if v is not None else "?"


def render(sj: ScoredJob, cfg: Config) -> str:
    j, c = sj.job, sj.job.client
    ident = next(i for i in cfg.profiles.identities if i.id == sj.identity)
    person = cfg.profiles.people[sj.assignee]
    analog = cfg.portfolio.get(sj.analog_id) if sj.analog_id else None
    front = {
        "job_id": j.id,
        "url": j.url,
        "title": j.title,
        "identity": sj.identity,
        "assignee": sj.assignee,
        "lane": sj.primary_lane,
        "mode": sj.mode,
        "hook_suggested": sj.hook_suggestion,
        "hook_type": None,          # drafting agent sets A-E
        "analog_id": sj.analog_id,  # drafting agent may change it to another portfolio id
        "score": round(sj.score, 1),
        "probability": sj.probability,
        "status": "draft",
    }
    budget = (_money(j.budget_fixed) + " fijo") if j.budget_fixed else \
        (f"${j.rate_min or '?'}–{j.rate_max or '?'}/h" if (j.rate_min or j.rate_max) else "no indicado")
    rows = "\n".join(
        f"| {FACTOR_ES.get(f.name, f.name)} | {f.value:.2f} | {f.weight:g} | {f.note} |" for f in sj.factors)
    options = "\n".join(f"- `{o.identity}`: {o.score:.1f} pts, P {o.probability:.0%} ({o.reason})"
                        for o in sj.identity_options)
    warnings = "\n".join(f"- {w}" for w in sj.warnings) or "- Ninguna"
    screening = "\n".join(f"{i}. {q}" for i, q in enumerate(j.screening_questions, 1))
    word_range = cfg.rules.full_words if sj.mode == "full" else cfg.rules.fast_words

    parts = [
        "---", yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip(), "---", "",
        f"# {j.title}", "",
        f"[Abrir en Upwork]({j.url}) · arista **{sj.primary_lane}** · modo **{sj.mode}** · "
        f"score **{sj.score:.0f}/100** · P(contratación) **{sj.probability:.0%}**"
        + (f" · EV **{_money(sj.expected_value)}**" if sj.expected_value is not None else ""), "",
        "## 1. Qué pide el cliente (en español)", "",
        FILL.format(name="resumen_es"),
        "Resume en español qué quiere el cliente de verdad (resultado, no tarea), entregables, plazos y lo que pide adjuntar.", "",
        "## 2. El cliente", "",
        f"- País: {c.country or '?'} · pago verificado: {_yes(c.payment_verified)}",
        f"- Gasto total: {_money(c.total_spent)} · jobs publicados: {c.jobs_posted} · con contratación: {c.hires} · hire rate: {c.hire_rate}%",
        f"- Rating que le dan los freelancers: {c.rating} ({c.total_reviews} reseñas)",
        f"- Presupuesto: {budget} · duración: {j.duration} · nivel: {j.experience_level}",
        f"- Competencia: {j.activity.proposals if j.activity.proposals is not None else j.activity.proposals_tier} propuestas · "
        f"entrevistando: {j.activity.invited_to_interview} · connects: {j.connects_cost or '?'}",
        "", "**Alertas**", warnings, "",
        "## 3. Por qué pasó el filtro", "",
        "| Factor | Valor | Peso | Detalle |", "|---|---|---|---|", rows, "",
        f"Aristas detectadas: {', '.join(f'{h.lane} ({h.strength:.2f})' for h in sj.lanes)} · "
        f"banderas: {', '.join(sj.flags) or 'ninguna'}", "",
        "## 4. Quién envía", "",
        f"**{ident.label}** → lo envía **{person.name}**.", "", options, "",
        "## 5. Estrategia", "",
        f"- Modo: **{sj.mode}** ({word_range[0]}–{word_range[1]} palabras)",
        f"- Hook sugerido: **{sj.hook_suggestion}** (no repetir un tipo ya usado hoy)",
        f"- Análogo sugerido: **{sj.analog_id}**" + (f": {analog.name}. Frase base: _{analog.phrase_en}_" if analog else ""),
        "", FILL.format(name="estrategia_es"),
        "En español: qué quiere realmente, por qué somos los adecuados, diagnóstico, recomendación, fases con tiempo y precio, pregunta activadora.", "",
        "## 6. Borrador en español", "", ES_START, FILL.format(name="borrador_es"), ES_END, "",
        "## 7. Propuesta en inglés (lista para pegar)", "", EN_START, FILL.format(name="propuesta_en"), EN_END, "",
    ]
    if screening:
        parts += ["## 8. Preguntas de filtro del cliente", "", screening, "", FILL.format(name="respuestas_en"), ""]
    parts += [
        "## 9. Antes de enviar", "",
        "- [ ] El hook va primero y el nombre no sale en la primera oración",
        "- [ ] Un solo proyecto análogo real, con datos",
        "- [ ] Fases con nombre, tiempo y costo (nunca un total suelto)",
        "- [ ] Una sola pregunta, al final",
        "- [ ] Adjuntos que pide el cliente listos",
        f"- [ ] Enviar desde: {ident.label}",
        "",
    ]
    return "\n".join(parts)


def write_brief(sj: ScoredJob, cfg: Config, out_dir: str | Path, day: str | None = None) -> Path:
    path = brief_path(sj, out_dir, day)
    if path.exists():
        return path                      # never overwrite a draft someone is working on
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(sj, cfg), encoding="utf-8")
    return path


def read_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body


def section(text: str, start: str, end: str) -> str | None:
    if start not in text or end not in text:
        return None
    return text.split(start, 1)[1].split(end, 1)[0].strip()
