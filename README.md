# MONEY FLOW — data pipeline

Auto-updating macro regime engine. GitHub Actions fetches FRED/CFTC data,
computes the regime, and commits six JSON files that the frontend renders.
**Zero manual data entry, ever.**

## How the auto-update works

| Trigger | Cadence | What happens |
|---|---|---|
| `update.yml` | Every 30 min, weekdays 12:00–22:30 UTC (≈8:00–18:30 ET) | Fetch FRED → recompute regime/dials/scenarios/flows/evidence/calendar → commit **only if something changed** |
| `update.yml` (overnight) | 03:15 UTC | Catch-up run |
| `cot.yml` | Fridays 20:45 UTC | Full build including the weekly CFTC COT pull |

So when CPI drops at 8:30 ET: BLS publishes → FRED ingests (typically within
the hour) → the next 30-min run picks it up → dials, verdict, regime needle,
narrative, and scorecard all recompute → commit → GitHub Pages redeploys.
Your site reflects the print roughly 30–90 minutes after release, untouched
by human hands. Runs where nothing changed commit nothing.

## One-time setup (~15 minutes)

1. **Create the repo** — push this folder to GitHub (public repo = free
   unlimited Actions minutes).
2. **FRED API key** — free at https://fred.stlouisfed.org/docs/api/api_key.html
   → repo Settings → Secrets and variables → Actions → New secret →
   name `FRED_API_KEY`.
3. **Enable Pages** — Settings → Pages → deploy from branch → `main`, root.
   The frontend lives in `site/`, data in `data/` — the page fetches
   `../data/*.json` relative, no CORS, no keys in the browser.
4. **Actions permissions** — Settings → Actions → General → Workflow
   permissions → "Read and write" (the bot commits data).
5. **First run** — Actions tab → `update-data` → Run workflow. Confirm six
   files appear in `data/`.
6. **Validate the brain** — locally:
   `FRED_API_KEY=xxx python -m pipeline.build --backtest 2000-01 2026-08`
   Eyeball `data/history.json` against reality (2008, 2020, 2022). Tune
   `pipeline/config.py` thresholds if needed; `tests/` must stay green.

## Local development

```bash
pip install -r requirements.txt
python -m pipeline.build --mock        # writes mock/ + mock/alt (no network)
FRED_API_KEY=xxx python -m pipeline.build            # full live build
FRED_API_KEY=xxx python -m pipeline.build --no-cot   # skip COT (weekday mode)
python -m pytest tests/ -q
```

## Layout

```
pipeline/config.py        # ALL tunables: series IDs, weights, thresholds, decks
pipeline/fetch_fred.py    # FRED client + cache + transforms
pipeline/fetch_cot.py     # CFTC Socrata COT
pipeline/fetch_prices.py  # ZQ Fed-funds futures -> implied hike/hold/cut odds
pipeline/regime_engine.py # five voters -> regime probabilities (+ backtest)
pipeline/narrative.py     # Jarvis-voice templates, verdict, scorecard, calendar
pipeline/build.py         # orchestrator; writes data/*.json only on change
pipeline/fomc_dates.json  # the ONE yearly manual touch — verify each December
pipeline/overview.py      # Layer 1: the plain-English payload
pipeline/ledger.py        # append-only record of what was claimed (hash-chained)
pipeline/scoring.py       # resolves claims vs persistence + naive baselines
pipeline/weekly_report.py # the Sunday report
mock/, mock/alt/          # PEAK + RECOVERY states for frontend dev
data/                     # live output (committed by the bot)
content/                  # lessons, glossary, framework.md (static)
ledger/                   # snapshots/events/divergences/health/scores (JSONL)
reports/weekly/           # generated Sunday reports
site/                     # Claude Design frontend goes here
tests/                    # schema contract + engine golden states
```

## The site

`site/index.html` is the Claude Design v2 build. It reads **live** data from
`../data/` by default. Two QA modes are permanent:

| URL | Reads |
|---|---|
| `site/index.html` | `data/` — live |
| `site/index.html?data=mock` | `mock/` — the PEAK state |
| `site/index.html?data=alt` | `mock/alt/` — the RECOVERY state |

The mock-swap test is the frontend's definition of done: `?data=alt` must
re-render everything — mood CAUTIOUS→CLEARING, arrows flipped, simulator
hold→cut, an `AGAINST MAP ✗` visible, lesson live-boxes showing different
numbers — with zero code edits.

One constant controls all of it, near the top of the page script:

```js
const DATA_SETS = { live: 'data/', mock: 'mock/', alt: 'mock/alt/' };
const DEFAULT_DATA_SET = 'live';
```

`site/legacy.html` is the previous placeholder, kept for rollback.

## Feedback loop

Two issue templates, both one tap from mobile:

| Template | Label | For |
|---|---|---|
| Confusion note | `confusion` | a line you read and didn't follow — a defect in the writing |
| Calibration note | `calibration` | the engine's read disagreeing with yours |

Layer 1 carries a quiet **"Something unclear?"** link that opens the confusion
form with the title prefilled to today's date and the current mood, e.g.
`confusion: CAUTIOUS — 2026-08-23`. That date joins straight to the ledger
snapshot for the day, so a note can always be traced back to exactly what the
site was claiming when it confused you. No backend — it is a plain link.

The Sunday report's section 6 gathers both labels, listed separately, because
they call for different fixes: a confusion note is usually a template edit in
`config.py`, not an engine change.

## Being judged

`ledger/snapshots.jsonl` records one line per market day: the full claim state
plus the raw input vintage that produced it, stamped with `engine_version` and
a `config_hash`. Lines are hash-chained, so editing history breaks CI.

`pipeline/scoring.py` resolves those claims at +21 and +63 trading days using
the same flat bands as the Evidence scorecard, and reports every figure as a
triple — **engine vs persistence vs naive**, with n. Nothing renders below
`MIN_SAMPLE_N`. See `CONTRIBUTING.md` for the change protocol.

## Failure policy

- A single series failing → last cached value is used, block marked
  `"stale": true`; the frontend dims it. The site degrades, never dies.
- Schema test failing → the commit is aborted; yesterday's data keeps
  serving; Actions emails you.
- ZQ futures unavailable → `market_pricing: null`, `pricing_stale: true`,
  default scenario falls back to the dials' verdict.

## Ops (the do-almost-nothing loop)

- **Yearly (December):** update `pipeline/fomc_dates.json` from the Fed's
  published calendar.
- **On failure email:** re-run the workflow; investigate only if it repeats.
- **Disagree with the needle?** Don't hot-patch. Tune `config.py`, keep
  `tests/` green, re-run the backtest, ship.

## Frontend contract

Six files, `schema_version: 1`, shapes enforced by `tests/test_schemas.py`.
The definition of done for the Claude Design build: pointing it at `mock/alt/`
instead of `mock/` re-renders everything correctly (needle → RECOVERY,
verdict → DOVISH, flows reverse, default scenario → CUT) with zero code edits.
