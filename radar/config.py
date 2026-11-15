"""Load and validate the YAML config directory.

A config directory holds:
  lanes.yaml      lane dictionaries (terms, negatives, critical missing skills, concept flags)
  countries.yaml  country tiers and banned list
  weights.yaml    factor weights, logistic bias, thresholds, buckets
  profiles.yaml   sending identities, people and routing rules
  portfolio.yaml  real portfolio pieces (the only source analogs can come from)
  searches.yaml   searches the fetch agent runs (not used by the scorer itself)
  rules.yaml      proposal lint rules (word limits, banned phrases)
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LaneConfig(BaseModel):
    label: str
    priority: float = Field(ge=0, le=1)
    terms: dict[str, float]
    negative: dict[str, float] = Field(default_factory=dict)
    critical_missing: list[str] = Field(default_factory=list)


class LanesConfig(BaseModel):
    saturation: float = 8.0              # sum of term weights that maps to strength 1.0
    min_strength: float = 0.25           # below this a lane does not count
    title_multiplier: float = 2.0
    lanes: dict[str, LaneConfig]
    negative_global: dict[str, float] = Field(default_factory=dict)
    physical_presence: list[str] = Field(default_factory=list)
    flags: dict[str, list[str]] = Field(default_factory=dict)   # H1..H5
    full_mode_terms: list[str] = Field(default_factory=list)


class CountriesConfig(BaseModel):
    tiers: dict[int, list[str]]
    banned: list[str]
    aliases: dict[str, str] = Field(default_factory=dict)

    def normalize(self, country: str | None) -> str | None:
        if not country:
            return None
        return self.aliases.get(country, country)

    def tier(self, country: str | None) -> int:
        c = self.normalize(country)
        for t, names in self.tiers.items():
            if c in names:
                return int(t)
        return 0

    def is_banned(self, country: str | None) -> bool:
        return self.normalize(country) in self.banned


class Bucket(BaseModel):
    max: float | None                    # upper bound (exclusive); None = open
    value: float


class WeightsConfig(BaseModel):
    weights: dict[str, float]
    bias: float = -3.0                   # logistic intercept
    slope: float = 5.0                   # logistic slope on the 0-1 weighted mean
    notify_threshold: float = 60.0       # 0-100 score needed to reach Slack
    max_age_hours: float = 72.0
    crowded_proposals: int = 50
    crowded_min_fit: float = 0.85
    competition_buckets: list[Bucket]
    duration_hours: dict[str, float]
    pay_reference: float = 3000.0        # USD that maps pay_size to 1.0
    connect_value_usd: float = 0.15
    full_mode_min_chars: int = 1200


class Identity(BaseModel):
    id: str
    label: str
    sender: str                          # person key in `people`
    via: str                             # "freelancer" | "agency"
    preference: int                      # 1 = most preferred
    lane_strength: dict[str, float]      # 0-1 credibility per lane (reviews + portfolio)
    default_strength: float = 0.3


class Person(BaseModel):
    name: str
    slack_id: str = ""


class ProfilesConfig(BaseModel):
    identities: list[Identity]
    people: dict[str, Person]
    lane_assignee: dict[str, str] = Field(default_factory=dict)  # lane -> person
    default_assignee: str
    identity_floor: float = 0.6          # score multiplier floor: floor + (1-floor) * strength


class PortfolioItem(BaseModel):
    id: str
    name: str
    lanes: list[str]
    tags: list[str]
    problem: str
    phrase_en: str
    uploaded: bool = True
    identities: list[str] = Field(default_factory=list)  # empty = any identity may cite it


class PortfolioConfig(BaseModel):
    items: list[PortfolioItem]
    not_uploaded_factor: float = 0.75

    def get(self, item_id: str) -> PortfolioItem | None:
        return next((i for i in self.items if i.id == item_id), None)


class RulesConfig(BaseModel):
    fast_words: tuple[int, int] = (80, 180)
    full_words: tuple[int, int] = (400, 700)
    banned_phrases: list[str] = Field(default_factory=list)
    name_tokens: list[str] = Field(default_factory=list)   # must not appear in first sentence
    hook_types: list[str] = Field(default_factory=lambda: ["A", "B", "C", "D", "E"])


class Config(BaseModel):
    lanes: LanesConfig
    countries: CountriesConfig
    weights: WeightsConfig
    profiles: ProfilesConfig
    portfolio: PortfolioConfig
    rules: RulesConfig
    searches: dict = Field(default_factory=dict)
    root: Path | None = None


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(root: str | Path) -> Config:
    root = Path(root)
    required = ["lanes", "countries", "weights", "profiles", "portfolio", "rules"]
    missing = [n for n in required if not (root / f"{n}.yaml").exists()]
    if missing:
        raise FileNotFoundError(f"config dir {root} is missing: {', '.join(m + '.yaml' for m in missing)}")
    data = {n: _load(root / f"{n}.yaml") for n in required}
    searches = _load(root / "searches.yaml") if (root / "searches.yaml").exists() else {}
    cfg = Config(**data, searches=searches, root=root)
    _cross_check(cfg)
    return cfg


def _cross_check(cfg: Config) -> None:
    lanes = set(cfg.lanes.lanes)
    for item in cfg.portfolio.items:
        bad = set(item.lanes) - lanes
        if bad:
            raise ValueError(f"portfolio item {item.id} uses unknown lanes {sorted(bad)}")
    for ident in cfg.profiles.identities:
        bad = set(ident.lane_strength) - lanes
        if bad:
            raise ValueError(f"identity {ident.id} uses unknown lanes {sorted(bad)}")
        if ident.sender not in cfg.profiles.people:
            raise ValueError(f"identity {ident.id} sender {ident.sender!r} not in people")
    for lane, person in cfg.profiles.lane_assignee.items():
        if lane not in lanes or person not in cfg.profiles.people:
            raise ValueError(f"lane_assignee {lane}->{person} references unknown lane or person")
    if cfg.profiles.default_assignee not in cfg.profiles.people:
        raise ValueError("default_assignee not in people")
    ids = [i.id for i in cfg.portfolio.items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate portfolio ids")
