"""Record proposal outcomes and compare predicted probability with reality."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

OUTCOMES = ("sent", "viewed", "interview", "won", "lost", "no_reply", "skipped")
FIELDS = ["timestamp", "job_id", "outcome", "identity", "lane", "score", "probability", "note"]


def record(path: str | Path, job_id: str, outcome: str, identity: str = "", lane: str = "",
           score: float | None = None, probability: float | None = None, note: str = "") -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    path = Path(path)
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now(timezone.utc).isoformat(), "job_id": job_id, "outcome": outcome,
                    "identity": identity, "lane": lane, "score": score, "probability": probability, "note": note})


def report(path: str | Path) -> dict:
    """Latest outcome per job, grouped by score bucket: predicted vs actual hire rate."""
    path = Path(path)
    if not path.exists():
        return {}
    latest: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            latest[row["job_id"]] = row
    buckets: dict[str, dict] = {}
    for row in latest.values():
        if row["outcome"] == "skipped" or not row["score"]:
            continue
        b = f"{int(float(row['score']) // 10 * 10)}-{int(float(row['score']) // 10 * 10 + 9)}"
        s = buckets.setdefault(b, {"sent": 0, "won": 0, "interview": 0, "predicted": 0.0})
        s["sent"] += 1
        s["won"] += row["outcome"] == "won"
        s["interview"] += row["outcome"] in ("interview", "won")
        s["predicted"] += float(row["probability"] or 0)
    for s in buckets.values():
        s["predicted"] = round(s["predicted"] / s["sent"], 3)
        s["actual"] = round(s["won"] / s["sent"], 3)
    return dict(sorted(buckets.items()))
