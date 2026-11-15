"""Lane classification and concept flags, driven entirely by lanes.yaml."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import LanesConfig
from .models import Job, LaneHit


@lru_cache(maxsize=4096)
def _pattern(term: str) -> re.Pattern:
    # whole-word, case-insensitive, tolerant to plural "s"/"es" and to - / space variants
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip().lower()) if p]
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<![a-z0-9]){body}(?:e?s)?(?![a-z0-9])", re.IGNORECASE)


def has(term: str, text: str) -> bool:
    return bool(_pattern(term).search(text))


def matched(terms: dict[str, float] | list[str], text: str) -> list[str]:
    keys = terms.keys() if isinstance(terms, dict) else terms
    return [t for t in keys if has(t, text)]


def _weighted(terms: dict[str, float], title: str, body: str, title_mult: float) -> tuple[float, list[str]]:
    total, hits = 0.0, []
    for term, w in terms.items():
        if has(term, title):
            total += w * title_mult
            hits.append(term)
        elif has(term, body):
            total += w
            hits.append(term)
    return total, hits


def classify(job: Job, cfg: LanesConfig) -> list[LaneHit]:
    """Return lanes over `min_strength`, strongest first."""
    title = job.title.lower()
    body = f"{job.description}\n{' '.join(job.skills)}".lower()
    out: list[LaneHit] = []
    for name, lane in cfg.lanes.items():
        pos, hits = _weighted(lane.terms, title, body, cfg.title_multiplier)
        neg, _ = _weighted(lane.negative, title, body, cfg.title_multiplier)
        strength = max(0.0, min(1.0, (pos - neg) / cfg.saturation))
        if strength >= cfg.min_strength:
            out.append(LaneHit(lane=name, strength=round(strength, 3), terms=hits))
    out.sort(key=lambda h: (-h.strength, -cfg.lanes[h.lane].priority))
    return out


def global_negative(job: Job, cfg: LanesConfig) -> tuple[float, list[str]]:
    return _weighted(cfg.negative_global, job.title.lower(), job.description.lower(), cfg.title_multiplier)


def flags(job: Job, cfg: LanesConfig) -> list[str]:
    text = job.text.lower()
    return sorted(f for f, terms in cfg.flags.items() if matched(terms, text))
