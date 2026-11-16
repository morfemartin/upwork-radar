"""Factor scoring and probability estimate.

score_base = 100 * sum(w_i * f_i) / sum(w_i)            (every f_i in 0..1)
P(hire)    = sigmoid(bias + slope * score/100)           (heuristic until calibrated)
EV         = P * expected_pay - connects_cost * connect_value

Identity routing (route.py) then scales the score by how credible each sending
identity is in the job's lane.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from .config import Config
from .filters import age_hours, knockouts
from .lanes import classify, flags, matched
from .models import Factor, Job, LaneHit, ScoredJob
from .route import route

_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.MULTILINE)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def proposals_value(job: Job, cfg: Config) -> tuple[float, str]:
    n = job.activity.proposals
    if n is None and job.activity.proposals_tier:
        tier = job.activity.proposals_tier.lower()
        n = {"fewer than 5": 2, "5 to 10": 7, "10 to 15": 12, "15 to 20": 17, "20 to 50": 35, "50+": 60}.get(tier)
    if n is None:
        return 0.5, "propuestas desconocidas"
    for b in cfg.weights.competition_buckets:
        if b.max is None or n < b.max:
            return b.value, f"{n} propuestas"
    return 0.0, f"{n} propuestas"


def f_client(job: Job, cfg: Config) -> tuple[float, str]:
    c = job.client
    tier = cfg.countries.tier(c.country)
    parts = [0.35 * tier / 3]
    parts.append(0.15 if c.payment_verified else 0.0)
    parts.append(0.20 * (min(c.hire_rate, 100) / 100 if c.hire_rate is not None else 0.4))
    spent = c.total_spent or 0
    parts.append(0.15 * min(1.0, math.log10(spent + 1) / 5))          # $100k -> 1.0
    if c.rating is not None and (c.total_reviews or 0) > 0:
        parts.append(0.10 * max(0.0, min(1.0, (c.rating - 4.0))))
        parts.append(0.05)
    note = f"{c.country or '?'} (tier {tier}), gasto ${spent:,.0f}, hire rate {c.hire_rate if c.hire_rate is not None else '?'}%"
    return round(sum(parts), 3), note


def f_competition(job: Job, cfg: Config, now: datetime | None) -> tuple[float, str]:
    v, note = proposals_value(job, cfg)
    v -= min(0.3, 0.1 * job.activity.invited_to_interview)
    age = age_hours(job, now)
    if age is not None:
        if age < 6:
            v += 0.1
        elif age > 48:
            v -= 0.2
        note += f", {age:.0f} h de publicado"
    return max(0.0, min(1.0, v)), note


def best_analog(job: Job, lanes: list[LaneHit], cfg: Config,
                identity: str | None = None) -> tuple[float, str | None]:
    """Portfolio alignment: overlap between a piece's lanes/tags and the job text.

    With `identity`, only pieces that identity may cite are considered.
    """
    text = job.text.lower()
    lane_strength = {h.lane: h.strength for h in lanes}
    best, best_id = 0.0, None
    for item in cfg.portfolio.items:
        if identity and item.identities and identity not in item.identities:
            continue
        lane_part = max((lane_strength.get(l, 0.0) for l in item.lanes), default=0.0)
        tag_hits = len(matched(item.tags, text))
        tag_part = min(1.0, tag_hits / 3)
        v = 0.5 * lane_part + 0.5 * tag_part
        if not item.uploaded:
            v *= cfg.portfolio.not_uploaded_factor
        if v > best:
            best, best_id = v, item.id
    return round(best, 3), best_id


def f_combo(lanes: list[LaneHit]) -> tuple[float, str]:
    n = len(lanes)
    v = {0: 0.0, 1: 0.4, 2: 0.8}.get(n, 1.0)
    return v, f"{n} arista(s): {', '.join(h.lane for h in lanes)}" if lanes else "ninguna arista"


def expected_pay(job: Job, cfg: Config) -> float | None:
    if job.budget_fixed and job.budget_fixed > 1:
        return job.budget_fixed
    rate = job.rate_max or job.rate_min
    if rate:
        hours = cfg.weights.duration_hours.get(job.duration or "", cfg.weights.duration_hours.get("default", 30))
        return rate * hours
    return None


def f_pay_size(job: Job, cfg: Config) -> tuple[float, str, float | None]:
    pay = expected_pay(job, cfg)
    if pay is None:
        return 0.3, "presupuesto no indicado", None
    ref = cfg.weights.pay_reference
    v = max(0.0, min(1.0, math.log10(max(pay, 1)) / math.log10(ref)))
    return round(v, 3), f"pago esperado ~${pay:,.0f}", pay


def f_pay_speed(job: Job, cfg: Config) -> tuple[float, str]:
    v, notes = 0.2, []
    if job.job_type == "fixed":
        v += 0.3
        notes.append("precio fijo")
    if (job.duration or "").lower().startswith("less than 1 month"):
        v += 0.3
        notes.append("< 1 mes")
    if len(_LIST_ITEM.findall(job.description)) >= 3:
        v += 0.2
        notes.append("entregables claros")
    if matched(["planning ahead", "launch date is confirmed", "gather quotes", "not ready yet"], job.description.lower()):
        v -= 0.4
        notes.append("arranque diferido")
    return max(0.0, min(1.0, v)), ", ".join(notes) or "sin señales de cobro rápido"


def f_specificity(job: Job) -> tuple[float, str]:
    n = len(job.description)
    items = len(_LIST_ITEM.findall(job.description))
    v = min(1.0, n / 1500) * 0.7 + min(1.0, items / 5) * 0.3
    return round(v, 3), f"{n} caracteres, {items} ítems"


def decide_mode(job: Job, lanes: list[LaneHit], cfg: Config) -> str:
    text = job.text.lower()
    if len(job.description) >= cfg.weights.full_mode_min_chars:
        return "full"
    if len(lanes) >= 2 or matched(cfg.lanes.full_mode_terms, text):
        return "full"
    return "fast"


def suggest_hook(flag_list: list[str], lanes: list[LaneHit], analog_fit: float) -> str:
    if "H5" in flag_list:
        return "C"                       # emotional mirror
    if analog_fit >= 0.75:
        return "D"                       # image / curiosity on a strong analog
    lane = lanes[0].lane if lanes else ""
    if lane in ("branding", "web"):
        return "A"                       # conceptual statement
    if lane in ("motion_ui", "techpack"):
        return "B"                       # reframe the problem
    return "E"


def score_job(job: Job, cfg: Config, now: datetime | None = None) -> ScoredJob:
    lanes = classify(job, cfg.lanes)
    ko, warn = knockouts(job, lanes, cfg, now)
    fl = flags(job, cfg.lanes)
    w = cfg.weights.weights

    fit, analog_id = best_analog(job, lanes, cfg)
    if job.activity.proposals is not None and job.activity.proposals >= cfg.weights.crowded_proposals \
            and fit < cfg.weights.crowded_min_fit:
        ko.append(f"{job.activity.proposals} propuestas y el encaje no es casi perfecto")

    v_client, n_client = f_client(job, cfg)
    v_comp, n_comp = f_competition(job, cfg, now)
    v_combo, n_combo = f_combo(lanes)
    v_size, n_size, pay = f_pay_size(job, cfg)
    v_speed, n_speed = f_pay_speed(job, cfg)
    v_spec, n_spec = f_specificity(job)
    v_lane = cfg.lanes.lanes[lanes[0].lane].priority if lanes else 0.0

    factors = [
        Factor(name="client", value=v_client, weight=w["client"], note=n_client),
        Factor(name="competition", value=v_comp, weight=w["competition"], note=n_comp),
        Factor(name="portfolio_fit", value=fit, weight=w["portfolio_fit"], note=f"análogo: {analog_id}"),
        Factor(name="skill_combo", value=v_combo, weight=w["skill_combo"], note=n_combo),
        Factor(name="pay_size", value=v_size, weight=w["pay_size"], note=n_size),
        Factor(name="pay_speed", value=v_speed, weight=w["pay_speed"], note=n_speed),
        Factor(name="specificity", value=v_spec, weight=w["specificity"], note=n_spec),
        Factor(name="lane_priority", value=v_lane, weight=w["lane_priority"],
               note=lanes[0].lane if lanes else "-"),
    ]
    total_w = sum(f.weight for f in factors)
    base = 100 * sum(f.value * f.weight for f in factors) / total_w

    sj = ScoredJob(job=job, knockouts=ko, warnings=warn, lanes=lanes, flags=fl, factors=factors,
                   expected_pay=pay, analog_id=analog_id,
                   mode=decide_mode(job, lanes, cfg), hook_suggestion=suggest_hook(fl, lanes, fit))
    route(sj, base, cfg)
    own_fit, own_analog = best_analog(job, lanes, cfg, identity=sj.identity)
    if own_analog != analog_id:
        sj.analog_id = own_analog
        if fit - own_fit > 0.2:
            sj.warnings.append(f"el mejor análogo ({analog_id}) no lo puede citar {sj.identity}")
    sj.probability = round(sigmoid(cfg.weights.bias + cfg.weights.slope * sj.score / 100), 4)
    if pay is not None:
        cost = (job.connects_cost or 16) * cfg.weights.connect_value_usd
        sj.expected_value = round(sj.probability * pay - cost, 2)
    sj.passes = (not ko and sj.score >= cfg.weights.notify_threshold
                 and (job.has_details or not cfg.weights.require_details))
    return sj


def score_all(jobs: list[Job], cfg: Config, now: datetime | None = None) -> list[ScoredJob]:
    scored = [score_job(j, cfg, now) for j in jobs]
    scored.sort(key=lambda s: (not s.passes, bool(s.knockouts), -s.score))
    return scored
