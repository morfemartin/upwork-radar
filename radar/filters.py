"""Hard knockouts and warnings. A knocked-out job never reaches Slack."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Config
from .lanes import global_negative, matched
from .models import Job, LaneHit


def age_hours(job: Job, now: datetime | None = None) -> float | None:
    if not job.published:
        return None
    now = now or datetime.now(timezone.utc)
    pub = job.published if job.published.tzinfo else job.published.replace(tzinfo=timezone.utc)
    return (now - pub).total_seconds() / 3600


def knockouts(job: Job, lanes: list[LaneHit], cfg: Config, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Return (knockouts, warnings). Reasons are short Spanish strings for the Slack report."""
    ko: list[str] = []
    warn: list[str] = []
    w = cfg.weights
    c = job.client
    text = job.text.lower()

    if job.applied:
        ko.append("ya aplicamos a este job")
    if cfg.countries.is_banned(c.country):
        ko.append(f"país descartado ({c.country})")
    if not lanes:
        ko.append("fuera de nuestras aristas")
    neg, neg_terms = global_negative(job, cfg.lanes)
    if neg_terms and (not lanes or neg >= cfg.lanes.saturation * lanes[0].strength):
        ko.append(f"no es trabajo creativo ({', '.join(neg_terms[:3])})")
    presence = matched(cfg.lanes.physical_presence, text)
    if presence:
        ko.append(f"requiere presencia física ({presence[0]})")
    lang = matched(cfg.lanes.language_required, text)
    if lang:
        ko.append(f"pide un idioma que no hablamos ({lang[0]})")
    if lanes:
        crit = matched(cfg.lanes.lanes[lanes[0].lane].critical_missing, text)
        if crit:
            ko.append(f"pide una skill que no tenemos ({crit[0]})")
    if lanes:
        floor = cfg.lanes.lanes[lanes[0].lane].min_budget
        if floor and job.budget_fixed and 1 < job.budget_fixed < floor / 2:
            ko.append(f"presupuesto ${job.budget_fixed:,.0f} muy bajo para {lanes[0].lane} (mínimo ${floor:,.0f})")
        elif floor and job.budget_fixed and 1 < job.budget_fixed < floor:
            warn.append(f"presupuesto ${job.budget_fixed:,.0f} bajo para {lanes[0].lane} (mínimo ${floor:,.0f}): proponer fases")
        minor = matched(cfg.lanes.lanes[lanes[0].lane].minor_missing, text)
        if minor:
            warn.append(f"pide una herramienta que no usamos ({minor[0]})")
    if matched(cfg.lanes.deferred_start, text):
        warn.append("todavía no arranca: solo está cotizando")
    if job.activity.hired > 0 or job.activity.offered > 0:
        ko.append("ya contrató u ofertó a alguien")
    if c.payment_verified is False:
        ko.append("pago no verificado")
    if c.hire_rate is not None and c.hire_rate == 0 and (c.jobs_posted or 0) >= 3:
        ko.append(f"hire rate 0% con {c.jobs_posted} jobs publicados")
    age = age_hours(job, now)
    if age is not None and age > w.max_age_hours:
        ko.append(f"publicado hace {age:.0f} h")

    if c.payment_verified is None:
        warn.append("no sabemos si el pago está verificado")
    if not c.jobs_posted or c.jobs_posted <= 1:
        warn.append("cliente nuevo, sin historial")
    if not job.has_details:
        warn.append("sin detalle del cliente (falta `get`)")
    if job.activity.invited_to_interview > 0:
        warn.append(f"ya entrevista a {job.activity.invited_to_interview}")
    if c.rating is not None and c.rating < 4.3 and (c.total_reviews or 0) >= 3:
        warn.append(f"rating del cliente bajo ({c.rating})")
    return ko, warn
