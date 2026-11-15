"""Persistent state: jobs already notified and hook types used per day."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {}
        self.seen: dict[str, dict] = data.get("seen", {})
        self.hooks: dict[str, list[str]] = data.get("hooks", {})

    def is_seen(self, job_id: str) -> bool:
        return job_id in self.seen

    def mark(self, job_id: str, **info) -> None:
        entry = self.seen.setdefault(job_id, {"first_seen": datetime.now(timezone.utc).isoformat()})
        entry.update(info)

    def hooks_today(self, day: date | None = None) -> list[str]:
        return self.hooks.get((day or date.today()).isoformat(), [])

    def use_hook(self, hook: str, day: date | None = None) -> None:
        self.hooks.setdefault((day or date.today()).isoformat(), []).append(hook)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # keep only the last 14 days of hook history
        keep = sorted(self.hooks)[-14:]
        self.hooks = {k: self.hooks[k] for k in keep}
        self.path.write_text(json.dumps({"seen": self.seen, "hooks": self.hooks}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
