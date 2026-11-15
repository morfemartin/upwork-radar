import json
import shutil

from typer.testing import CliRunner

from radar.cli import app
from radar.outcome import record, report
from radar.state import State

from .conftest import ROOT

runner = CliRunner()
CFG = str(ROOT / "examples" / "config")


def _run_dir(tmp_path):
    run = tmp_path / "inbox" / "r1"
    shutil.copytree(ROOT / "tests" / "fixtures" / "raw", run / "raw")
    return run


def test_full_cli_pipeline(tmp_path, monkeypatch):
    # freeze "now" so fixture jobs are fresh
    import radar.filters as filters
    from .conftest import NOW
    monkeypatch.setattr(filters, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))

    run = _run_dir(tmp_path)
    state = str(tmp_path / "state" / "seen.json")
    out = tmp_path / "proposals"
    assert runner.invoke(app, ["ingest", str(run)]).exit_code == 0
    r = runner.invoke(app, ["shortlist", str(run), "-c", CFG, "--state", state])
    assert r.exit_code == 0 and "1003" in json.loads(r.stdout.strip().splitlines()[-1])
    r = runner.invoke(app, ["score", str(run), "-c", CFG, "--state", state])
    assert r.exit_code == 0 and "1 pasan" in r.stdout
    r = runner.invoke(app, ["brief", str(run), "--out", str(out), "-c", CFG])
    assert r.exit_code == 0
    briefs = json.loads((run / "briefs.json").read_text())
    assert list(briefs) == ["1001"]
    r = runner.invoke(app, ["lint", briefs["1001"], "-c", CFG, "--state", state])
    assert r.exit_code == 1               # unfilled draft
    r = runner.invoke(app, ["notify", str(run), "-c", CFG, "--state", state, "--dry-run"])
    assert r.exit_code == 0 and "revisión manual" in r.stdout and "@Sam" in r.stdout


def test_notify_marks_seen_once(tmp_path, monkeypatch):
    import radar.cli as cli
    import radar.filters as filters
    from .conftest import NOW
    monkeypatch.setattr(filters, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    posted = []
    monkeypatch.setattr(cli, "post", lambda msg: posted.append(msg))

    run = _run_dir(tmp_path)
    state = str(tmp_path / "seen.json")
    for cmd in (["ingest", str(run)], ["score", str(run), "-c", CFG, "--state", state],
                ["brief", str(run), "--out", str(tmp_path / "p"), "-c", CFG]):
        assert runner.invoke(app, cmd).exit_code == 0
    assert runner.invoke(app, ["notify", str(run), "-c", CFG, "--state", state]).exit_code == 0
    assert runner.invoke(app, ["notify", str(run), "-c", CFG, "--state", state]).exit_code == 0
    assert len(posted) == 1
    assert State(state).seen["1001"]["notified"] is True


def test_outcomes_report(tmp_path):
    path = tmp_path / "o.csv"
    record(path, "1", "sent", score=72, probability=0.2)
    record(path, "1", "won", score=72, probability=0.2)
    record(path, "2", "lost", score=75, probability=0.25)
    rep = report(path)
    assert rep["70-79"]["sent"] == 2 and rep["70-79"]["won"] == 1 and rep["70-79"]["actual"] == 0.5
