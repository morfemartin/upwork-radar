"""Normalized data models. Everything downstream of `ingest` works on these."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Client(BaseModel):
    country: str | None = None
    payment_verified: bool | None = None
    rating: float | None = None          # score freelancers gave the client (0-5)
    total_reviews: int | None = None
    total_spent: float | None = None     # USD lifetime
    jobs_posted: int | None = None
    hires: int | None = None             # jobs_with_hires (from `get`)
    hire_rate: float | None = None       # 0-100 (from `get`)
    feedback: list[str] = Field(default_factory=list)  # reviews freelancers left this client (personalization)


class Activity(BaseModel):
    proposals: int | None = None         # exact count when the plan exposes it
    proposals_tier: str | None = None    # "Fewer than 5", "5 to 10", ... when it does not
    invited_to_interview: int = 0
    invites_sent: int = 0
    hired: int = 0
    offered: int = 0


class Job(BaseModel):
    id: str
    url: str | None = None
    title: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    job_type: Literal["fixed", "hourly", "unknown"] = "unknown"
    budget_fixed: float | None = None
    rate_min: float | None = None
    rate_max: float | None = None
    duration: str | None = None          # e.g. "Less than 1 month"
    workload: str | None = None
    experience_level: str | None = None
    published: datetime | None = None
    connects_cost: int | None = None
    applied: bool = False
    screening_questions: list[str] = Field(default_factory=list)
    client: Client = Field(default_factory=Client)
    activity: Activity = Field(default_factory=Activity)
    has_details: bool = False            # True once a `get` response was merged in

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}\n{' '.join(self.skills)}"


class LaneHit(BaseModel):
    lane: str
    strength: float                      # 0-1
    terms: list[str]


class Factor(BaseModel):
    name: str
    value: float                         # 0-1
    weight: float
    note: str = ""


class IdentityOption(BaseModel):
    identity: str
    score: float
    probability: float
    reason: str


class ScoredJob(BaseModel):
    job: Job
    knockouts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    lanes: list[LaneHit] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)     # H1..H5 concept flags
    factors: list[Factor] = Field(default_factory=list)
    score: float = 0.0                   # 0-100, identity-adjusted
    probability: float = 0.0             # estimated P(hire), identity-adjusted
    expected_pay: float | None = None
    expected_value: float | None = None
    identity: str | None = None
    identity_options: list[IdentityOption] = Field(default_factory=list)
    assignee: str | None = None          # who gets tagged in Slack
    analog_id: str | None = None         # best portfolio match
    mode: Literal["fast", "full"] = "fast"
    hook_suggestion: str | None = None
    passes: bool = False

    @property
    def primary_lane(self) -> str | None:
        return self.lanes[0].lane if self.lanes else None
