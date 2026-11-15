"""Command line interface. Every step reads and writes plain files in a run directory:

  inbox/<run>/raw/*.json      raw Upwork MCP responses saved by the fetch agent
  inbox/<run>/jobs.json       normalized jobs              (radar ingest)
  inbox/<run>/shortlist.json  ids worth a `get` call       (radar shortlist)
  inbox/<run>/scored.json     scored + routed jobs         (radar score)
  inbox/<run>/briefs.json     job id -> brief path         (radar brief)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import outcome as outcome_mod
from .brief import read_front_matter, write_brief
from .config import load_config
from .ingest import ingest_dir
from .lint import lint_file
from .models import Job, ScoredJob
from .notify import build_message, post
from .score import score_all
from .state import State

app = typer.Typer(add_completion=False, help="Deterministic Upwork triage and proposal pipeline.")

ConfigOpt = typer.Option(os.environ.get("RADAR_CONFIG", "config"), "--config", "-c", help="Config directory")
StateOpt = typer.Option(os.environ.get("RADAR_STATE", "state/seen.json"), "--state", help="State file")


def _jobs(run: Path) -> list[Job]:
    return [Job(**j) for j in json.loads((run / "jobs.json").read_text(encoding="utf-8"))]


def _scored(run: Path) -> list[ScoredJob]:
    return [ScoredJob(**s) for s in json.loads((run / "scored.json").read_text(encoding="utf-8"))]


def _dump(path: Path, items) -> None:
    path.write_text(json.dumps([i.model_dump(mode="json") for i in items], indent=2, ensure_ascii=False),
                    encoding="utf-8")


def _table(scored: list[ScoredJob], limit: int = 40) -> None:
    for s in scored[:limit]:
        mark = "PASS" if s.passes else ("KO  " if s.knockouts else "low ")
        why = "; ".join(s.knockouts) if s.knockouts else f"{s.primary_lane} → {s.identity} @{s.assignee}"
        typer.echo(f"{mark} {s.score:5.1f}  P{s.probability:5.1%}  {s.job.id}  {s.job.title[:60]:60}  {why}")


@app.command("new-run")
def new_run(inbox: str = typer.Option("inbox", help="Inbox directory")) -> None:
    """Create inbox/<UTC timestamp>/raw and print its run directory."""
    run = Path(inbox) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (run / "raw").mkdir(parents=True, exist_ok=True)
    typer.echo(str(run))


@app.command()
def searches(config: str = ConfigOpt) -> None:
    """Print the searches the fetch agent must run, as JSON."""
    typer.echo(json.dumps(load_config(config).searches, indent=2, ensure_ascii=False))


@app.command()
def ingest(run: Path) -> None:
    """Normalize raw MCP responses in RUN/raw into RUN/jobs.json."""
    jobs = ingest_dir(run / "raw")
    _dump(run / "jobs.json", jobs)
    typer.echo(f"{len(jobs)} jobs ({sum(j.has_details for j in jobs)} con detalle)")


@app.command()
def shortlist(run: Path, config: str = ConfigOpt, state: str = StateOpt,
              margin: float = typer.Option(15.0, help="Points below threshold still worth a `get`")) -> None:
    """List job ids that deserve a find_jobs `get` (not seen, no knockouts, near threshold)."""
    cfg = load_config(config)
    st = State(state)
    scored = score_all(_jobs(run), cfg)
    ids = [s.job.id for s in scored
           if not st.is_seen(s.job.id) and not s.knockouts and not s.job.has_details
           and s.score >= cfg.weights.notify_threshold - margin]
    (run / "shortlist.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
    typer.echo(json.dumps(ids))


@app.command()
def score(run: Path, config: str = ConfigOpt, state: str = StateOpt) -> None:
    """Score and route RUN/jobs.json into RUN/scored.json."""
    cfg = load_config(config)
    st = State(state)
    scored = [s for s in score_all(_jobs(run), cfg) if not st.is_seen(s.job.id)]
    _dump(run / "scored.json", scored)
    _table(scored)
    typer.echo(f"\n{sum(s.passes for s in scored)} pasan el umbral de {cfg.weights.notify_threshold:g}")


@app.command()
def brief(run: Path, out: Path = typer.Option(Path("proposals"), help="Proposals directory"),
          config: str = ConfigOpt) -> None:
    """Write a Markdown brief for every passing job; print the paths."""
    cfg = load_config(config)
    paths = {}
    for s in _scored(run):
        if s.passes:
            paths[s.job.id] = str(write_brief(s, cfg, out))
    (run / "briefs.json").write_text(json.dumps(paths, indent=2), encoding="utf-8")
    for p in paths.values():
        typer.echo(p)


@app.command()
def lint(paths: list[Path], config: str = ConfigOpt, state: str = StateOpt) -> None:
    """Check drafted briefs against the proposal rules. Exit code 1 on any error."""
    cfg = load_config(config)
    hooks = State(state).hooks_today()
    bad = 0
    for p in paths:
        r = lint_file(p, cfg, hooks)
        typer.echo(f"{'OK ' if r.ok else 'ERR'} {p}")
        for e in r.errors:
            typer.echo(f"    error: {e}")
        for w in r.warnings:
            typer.echo(f"    aviso: {w}")
        bad += not r.ok
    raise typer.Exit(1 if bad else 0)


@app.command()
def notify(run: Path, config: str = ConfigOpt, state: str = StateOpt,
           base_url: str = typer.Option("", envvar="RADAR_BRIEF_BASE_URL",
                                        help="URL prefix for brief links, e.g. https://github.com/o/r/blob/main"),
           dry_run: bool = typer.Option(False, "--dry-run", help="Print messages instead of posting")) -> None:
    """Post every brief of RUN to Slack, mark jobs as seen, record hook types."""
    cfg = load_config(config)
    st = State(state)
    briefs = json.loads((run / "briefs.json").read_text(encoding="utf-8")) if (run / "briefs.json").exists() else {}
    by_id = {s.job.id: s for s in _scored(run)}
    sent = 0
    for job_id, path in briefs.items():
        if st.is_seen(job_id) or job_id not in by_id:
            continue
        sj = by_id[job_id]
        r = lint_file(path, cfg, st.hooks_today())
        fm, _ = read_front_matter(Path(path).read_text(encoding="utf-8"))
        url = f"{base_url.rstrip('/')}/{path}" if base_url else None
        msg = build_message(sj, cfg, url, r)
        if dry_run:
            typer.echo(msg["text"] + "\n---")
        else:
            post(msg)
            st.mark(job_id, notified=True, score=sj.score, probability=sj.probability, lane=sj.primary_lane,
                    identity=sj.identity, assignee=sj.assignee, lint_ok=r.ok, brief=path)
            if fm.get("hook_type"):
                st.use_hook(fm["hook_type"])
        sent += 1
    # jobs scored but not passing are remembered too, so they are not re-scored forever
    if not dry_run:
        for s in by_id.values():
            if not s.passes and not st.is_seen(s.job.id) and s.job.has_details:
                st.mark(s.job.id, notified=False, score=s.score, knockouts=s.knockouts)
        st.save()
    typer.echo(f"{sent} notificaciones {'(dry-run)' if dry_run else 'enviadas'}")


@app.command()
def run(run_dir: Path, config: str = ConfigOpt, state: str = StateOpt) -> None:
    """Dry pipeline for local checks: ingest + score + table, no Slack."""
    ingest(run_dir)
    score(run_dir, config, state)


@app.command("outcome")
def outcome_cmd(job_id: str, result: str = typer.Argument(..., help="|".join(outcome_mod.OUTCOMES)),
                note: str = "", state: str = StateOpt,
                path: str = typer.Option("state/outcomes.csv", help="Outcomes CSV")) -> None:
    """Record what happened with a proposal (used to calibrate the weights)."""
    info = State(state).seen.get(job_id, {})
    outcome_mod.record(path, job_id, result, identity=info.get("identity", ""), lane=info.get("lane", ""),
                       score=info.get("score"), probability=info.get("probability"), note=note)
    typer.echo(f"{job_id}: {result}")


@app.command()
def report(path: str = typer.Option("state/outcomes.csv", help="Outcomes CSV")) -> None:
    """Predicted vs actual hire rate by score bucket."""
    data = outcome_mod.report(path)
    if not data:
        typer.echo("Sin resultados todavía.")
    for bucket, s in data.items():
        typer.echo(f"{bucket:>7}: enviadas {s['sent']:3}  entrevistas {s['interview']:3}  ganadas {s['won']:3}  "
                   f"predicho {s['predicted']:.0%}  real {s['actual']:.0%}")


if __name__ == "__main__":
    app()
