"""Slack notification through an incoming webhook (no SDK, no API cost)."""

from __future__ import annotations

import json
import os
import urllib.request

from .config import Config
from .lint import LintResult
from .models import ScoredJob


def build_message(sj: ScoredJob, cfg: Config, brief_url: str | None, lint: LintResult | None) -> dict:
    person = cfg.profiles.people[sj.assignee]
    ident = next(i for i in cfg.profiles.identities if i.id == sj.identity)
    mention = f"<@{person.slack_id}>" if person.slack_id else f"@{person.name}"
    j = sj.job
    budget = f"${j.budget_fixed:,.0f} fijo" if j.budget_fixed else (
        f"${j.rate_min or '?'}–{j.rate_max or '?'}/h" if (j.rate_min or j.rate_max) else "sin presupuesto")
    status = "✅ lista para revisar" if lint and lint.ok else "⚠️ revisión manual"
    lines = [
        f"{mention} *{sj.score:.0f}/100* · P {sj.probability:.0%} · {sj.primary_lane} · {status}",
        f"*<{j.url}|{j.title}>*",
        f"{j.client.country or '?'} · {budget} · {j.activity.proposals if j.activity.proposals is not None else j.activity.proposals_tier} propuestas · "
        f"gasto cliente ${j.client.total_spent or 0:,.0f} · hire rate {j.client.hire_rate if j.client.hire_rate is not None else '?'}%",
        f"Enviar desde: *{ident.label}* · modo {sj.mode} · análogo `{sj.analog_id}`",
    ]
    if sj.warnings:
        lines.append("Alertas: " + "; ".join(sj.warnings))
    if lint and not lint.ok:
        lines.append("Lint: " + "; ".join(lint.errors[:4]))
    if brief_url:
        lines.append(f"<{brief_url}|Abrir el MD de la propuesta>")
    text = "\n".join(lines)
    return {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}


def post(payload: dict, webhook_url: str | None = None, timeout: float = 15.0) -> None:
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Slack returned {resp.status}")
