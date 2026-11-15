# upwork-radar

Deterministic job triage and proposal pipeline for small creative studios on Upwork.

An agent (Codex, Claude, or a person) fetches job postings with the official Upwork MCP
connector and saves the raw responses. Everything after that is plain, tested Python:

```
raw MCP responses ─► ingest ─► shortlist ─► score + route ─► brief ─► (agent drafts) ─► lint ─► notify
                                  │                                                    │
                     ids worth a `get` call                              Slack webhook + seen state
```

- **Score**: knockouts first (banned country, unverified payment, wrong lane, missing critical skill,
  already hired, stale, crowded), then eight 0–1 factors: client quality, competition, portfolio
  alignment, skill combination, pay size, pay speed, brief specificity and lane priority.
  The weighted mean (0–100) maps to an estimated hire probability through a logistic curve,
  and to an expected value (`P × pay − connects`).
- **Route**: each sending identity (freelancer profile, agency, team members) has a credibility per
  lane. The job goes to the identity with the best adjusted score; near-ties go to the preferred one.
  A lane → person map decides who gets tagged in Slack.
- **Brief**: a Markdown file per job with every fact filled in by code and marked blocks for the
  drafting agent (Spanish summary, strategy, Spanish draft, English proposal).
- **Lint**: proposal rules checked mechanically: hook first and no self-introduction in the first
  sentence, exactly one question at the end, word limits per mode, priced phases in full mode,
  analog must be a real portfolio id, banned phrases, unfilled placeholders.
- **Calibrate**: `radar outcome <job> won|lost|...` and `radar report` compare predicted probability
  with real results per score bucket, so the weights can be tuned with evidence.

No paid APIs. No scraping. Nothing is ever submitted automatically: a person sends every proposal.

## Install

```bash
uv venv && uv pip install -e ".[dev]"
pytest
```

## Use

All configuration lives in a directory of YAML files (see [`examples/config`](examples/config)):
`lanes`, `countries`, `weights`, `profiles`, `portfolio`, `rules`, `searches`.

```bash
export RADAR_CONFIG=config RADAR_STATE=state/seen.json
RUN=$(radar new-run)                 # inbox/<timestamp>/raw
# agent saves find_jobs responses into $RUN/raw/*.json
radar ingest $RUN
radar shortlist $RUN                 # ids that deserve a find_jobs `get`
# agent saves the `get` responses into $RUN/raw/ too
radar ingest $RUN && radar score $RUN
radar brief $RUN --out proposals     # one Markdown brief per passing job
# agent fills the FILL blocks
radar lint proposals/2026-11-15/*.md
SLACK_WEBHOOK_URL=... radar notify $RUN --base-url https://github.com/<you>/<private-repo>/blob/main
```

`radar run <dir>` does ingest + score with no side effects, for local checks.

## Layout

| Module | Role |
|---|---|
| `radar/ingest.py` | Parses raw `find_jobs` search and `get` responses into `Job` models |
| `radar/lanes.py` | Lane classification and concept flags from weighted term dictionaries |
| `radar/filters.py` | Knockouts and warnings |
| `radar/score.py` | Factors, score, probability, expected value, mode and hook suggestion |
| `radar/route.py` | Sending identity and Slack assignee |
| `radar/brief.py` | Markdown brief rendering |
| `radar/lint.py` | Proposal rule checks |
| `radar/notify.py` | Slack incoming-webhook message |
| `radar/state.py` / `outcome.py` | Seen jobs, hook rotation, outcomes and calibration report |

## License

MIT
