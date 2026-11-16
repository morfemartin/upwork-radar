"""Turn raw Upwork MCP responses (find_jobs search / get) into normalized Jobs.

The fetch agent only has to save tool responses verbatim as JSON files; all parsing
is done here so it is deterministic and tested.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .models import Activity, Client, Job

_UNTRUSTED = re.compile(r"</?untrusted_participant_content>")
_MONEY = re.compile(r"\d[\d,]*\.?\d*")


def clean(text: Any) -> str:
    if text is None:
        return ""
    return _UNTRUSTED.sub("", str(text)).strip()


def money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _MONEY.search(str(value))
    return float(m.group().replace(",", "")) if m else None


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _budget(raw: str | None, job_type: str) -> tuple[float | None, float | None, float | None]:
    """Return (fixed, rate_min, rate_max) from strings like '500.00' or '20.00–50.00/hr'."""
    if not raw:
        return None, None, None
    nums = [float(n.replace(",", "")) for n in _MONEY.findall(raw)]
    if "/hr" in raw or job_type == "hourly":
        if len(nums) >= 2:
            return None, nums[0], nums[1]
        if nums:
            return (None, nums[0], None) if "+" in raw else (None, None, nums[0])
        return None, None, None
    return (nums[0] if nums else None), None, None


def from_search_row(row: dict) -> Job:
    job_type = (row.get("job_type") or "unknown").lower()
    if job_type not in ("fixed", "hourly"):
        job_type = "unknown"
    fixed, rmin, rmax = _budget(row.get("budget"), job_type)
    c = row.get("client") or {}
    act = row.get("job_activity") or {}
    return Job(
        id=str(row["id"]),
        url=(row.get("url") or "").split("?")[0] or None,
        title=clean(row.get("title")),
        description=clean(row.get("description") or row.get("description_snippet")),
        skills=list(row.get("skills") or []),
        job_type=job_type,
        budget_fixed=fixed,
        rate_min=rmin,
        rate_max=rmax,
        duration=row.get("duration"),
        workload=row.get("engagement") or row.get("workload"),
        experience_level=row.get("experience_level"),
        published=_date(row.get("published_date") or row.get("created_date")),
        applied=bool(row.get("applied", False)),
        client=Client(
            country=c.get("country"),
            payment_verified=(c.get("verification_status") == "VERIFIED") if "verification_status" in c else None,
            rating=c.get("rating"),
            total_reviews=c.get("total_reviews"),
            total_spent=money(c.get("total_spent")),
            jobs_posted=c.get("total_posted_jobs"),
        ),
        activity=Activity(
            proposals=row.get("proposal_count"),
            proposals_tier=row.get("proposals_tier"),
            invited_to_interview=act.get("invited_to_interview") or 0,
            invites_sent=act.get("invites_sent") or 0,
            hired=act.get("total_hired") or 0,
            offered=act.get("total_offered") or 0,
        ),
    )


def merge_get(job: Job, detail: dict) -> Job:
    """Merge a find_jobs `get` response into a Job built from a search row."""
    posting = ((detail.get("data") or {}).get("marketplaceJobPosting")) or {}
    rec = detail.get("client_record") or {}
    j = job.model_copy(deep=True)
    content = posting.get("content") or {}
    if content.get("description"):
        j.description = clean(content["description"])
    terms = posting.get("contractTerms") or {}
    fixed_terms = terms.get("fixedPriceContractTerms") or {}
    if fixed_terms.get("amount"):
        j.budget_fixed = money(fixed_terms["amount"].get("rawValue"))
        j.job_type = "fixed"
    country = ((posting.get("clientCompanyPublic") or {}).get("country") or {}).get("name")
    if country:
        j.client.country = country
    if rec:
        j.client.hires = rec.get("jobs_with_hires", j.client.hires)
        j.client.hire_rate = rec.get("hire_rate_percent", j.client.hire_rate)
        j.client.total_spent = money(rec.get("spend_total")) if rec.get("spend_total") else j.client.total_spent
        j.client.jobs_posted = rec.get("jobs_posted", j.client.jobs_posted)
        if rec.get("feedback_score") is not None:
            j.client.rating = rec["feedback_score"]
            j.client.total_reviews = rec.get("feedback_count", j.client.total_reviews)
    ja = ((posting.get("activityStat") or {}).get("jobActivity")) or {}
    if ja:
        j.activity.invited_to_interview = ja.get("totalInvitedToInterview") or 0
        j.activity.invites_sent = ja.get("invitesSent") or 0
        j.activity.hired = ja.get("totalHired") or 0
        j.activity.offered = ja.get("totalOffered") or 0
    if detail.get("connects_cost") is not None:
        j.connects_cost = int(detail["connects_cost"])
    j.applied = bool(detail.get("applied", j.applied))
    j.screening_questions = [clean(q) for q in detail.get("screening_questions") or []]
    for fb in detail.get("client_feedback") or []:
        name = fb.get("freelancer_name") or fb.get("client_name")
        if name:
            j.client.feedback_names.append(clean(name))
    j.has_details = True
    return j


def _detail_id(detail: dict) -> str | None:
    posting = ((detail.get("data") or {}).get("marketplaceJobPosting")) or {}
    return str(posting["id"]) if posting.get("id") else None


def ingest_payloads(payloads: Iterable[dict]) -> list[Job]:
    """Accept any mix of search responses and get responses; return deduped Jobs."""
    jobs: dict[str, Job] = {}
    details: list[dict] = []
    for p in payloads:
        if "jobs" in p:
            for row in p["jobs"]:
                job = from_search_row(row)
                jobs.setdefault(job.id, job)
        elif _detail_id(p):
            details.append(p)
    for d in details:
        jid = _detail_id(d)
        if jid in jobs:
            jobs[jid] = merge_get(jobs[jid], d)
    return list(jobs.values())


def failed_files(raw_dir: str | Path) -> list[tuple[str, str, float | None]]:
    """Raw files that hold an error instead of data: (file, error_code, retry_after_seconds)."""
    out = []
    for f in sorted(Path(raw_dir).glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            out.append((f.name, "INVALID_JSON", None))
            continue
        if isinstance(data, dict) and data.get("status") == "error":
            out.append((f.name, str(data.get("error_code", "ERROR")), data.get("retry_after_seconds")))
    return out


def ingest_dir(raw_dir: str | Path) -> list[Job]:
    files = sorted(Path(raw_dir).glob("*.json"))
    payloads = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        payloads.extend(data if isinstance(data, list) else [data])
    return ingest_payloads(payloads)
