# Changelog

Every engine or config change gets an entry. The point is not release notes —
it is that a future reader can tell whether an accuracy shift came from the
world or from us editing the rules. `ENGINE_VERSION` in `pipeline/config.py`
and the `config_hash` on every ledger snapshot tie entries to claims.

## Template

```markdown
## [x.y.z] — YYYY-MM-DD

**Hypothesis.** What we believed was wrong, and what we expected to change.

**Change.** What was actually edited, in one or two lines.

**Tests.** Full suite N passed. New tests: which behaviour they pin.

**Backtest.** Months changed: N of M. Reference windows:
2008 recession X% · 2020 COVID X% · 2020-21 rebound X% · 2022 hikes X%

**Judged.** Pending — revisit at n>=20 resolved claims. (Later: the triple.)
```

---

## [2.0.0] — 2026-08-22

**Hypothesis.** The site could report a regime but not be held to it. Without
a record of what was claimed and when, "is the engine any good?" could only be
answered from memory, and memory grades generously.

**Change.** Added the accuracy ledger (`pipeline/ledger.py`), the resolution
pass (`pipeline/scoring.py`), the Sunday report (`pipeline/weekly_report.py`)
and honest backfill (`pipeline/backfill.py`). Snapshots are hash-chained and
append-only. Every accuracy figure is a triple — engine vs persistence vs
naive — gated at n>=20.

**Tests.** Full suite 175 passed. New: hash-chain integrity including a
doctored-line case, scoring against known price paths, baseline computation,
n-gating at exactly 19 and 20, same-day dedupe, report rendering.

**Backtest.** Unchanged — this release touches no voter. Reference windows
hold at 2008 79% · 2020 100% · rebound 86% · 2022 94%.

**Judged.** Pending. Day one of the record is 2026-08-22; the first
meaningful cell needs 20 resolved claims at +21 trading days.

---

## [1.x] — 2026-08-22 (pre-ledger, reconstructed)

Shipped before the changelog existed, recorded here for continuity.

- Live-data fixes: FRED retired its gold series and Stooq began serving a
  bot-challenge; both gold and ZQ fed-funds futures moved to the price vendor.
- `vote_fed_stance` was blind before Dec 2008 (DFEDTARU does not exist
  earlier) and had no recency decay (a 687-day-old cut still voted
  "recovery"). Both fixed. 2008 74%→79%, 2022 69%→95%.
- `vote_employment` blended with payrolls momentum, as weakness evidence only.
  An earlier cut let firm payrolls vote expansion and erased the recovery
  regime from the 2020-21 rebound; the backtest caught it.
- Event watchlist, then v2 Layer 1 plus the 14-lesson curriculum.
