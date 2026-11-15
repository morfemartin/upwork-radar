"""Pick the sending identity and the person tagged in Slack."""

from __future__ import annotations

import math

from .config import Config
from .models import IdentityOption, ScoredJob


def _strength(identity, lanes) -> float:
    """Credibility of an identity for this job: weighted by lane strength."""
    if not lanes:
        return identity.default_strength
    num = sum(h.strength * identity.lane_strength.get(h.lane, identity.default_strength) for h in lanes)
    den = sum(h.strength for h in lanes)
    return num / den if den else identity.default_strength


def route(sj: ScoredJob, base_score: float, cfg: Config) -> None:
    p = cfg.profiles
    w = cfg.weights
    options: list[IdentityOption] = []
    for ident in p.identities:
        s = _strength(ident, sj.lanes)
        score = base_score * (p.identity_floor + (1 - p.identity_floor) * s)
        prob = 1 / (1 + math.exp(-(w.bias + w.slope * score / 100)))
        options.append(IdentityOption(identity=ident.id, score=round(score, 1), probability=round(prob, 4),
                                      reason=f"credibilidad {s:.2f} en {sj.primary_lane or '-'}"))
    pref = {i.id: i.preference for i in p.identities}
    # best score wins; within 1 point the preferred identity wins
    options.sort(key=lambda o: (-round(o.score), pref[o.identity]))
    sj.identity_options = options
    best = options[0]
    sj.identity = best.identity
    sj.score = best.score

    ident = next(i for i in p.identities if i.id == best.identity)
    lane = sj.primary_lane
    sj.assignee = p.lane_assignee.get(lane, None) if lane else None
    if sj.assignee is None:
        sj.assignee = ident.sender if ident.sender in p.lane_assignee.values() else p.default_assignee
