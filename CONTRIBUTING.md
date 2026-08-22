# Contributing to MONEY FLOW

One rule sits above the others: **the site's job is to be trustworthy, not to
be right.** Stale-but-verified beats fresh-but-unchecked. Everything below
follows from that.

## The change protocol

Every engine or config change follows the same five steps, in order. No step
is optional and none of them can be done later.

1. **Hypothesis.** Write down what you think is wrong and what you expect the
   change to do — *before* you edit. "The employment voter is blind to
   payrolls, so it should read peak rather than expansion when hiring rolls
   over." A change without a stated expectation cannot be judged afterwards.
2. **Tests green.** The full suite, not a subset. New behaviour needs a test
   that fails without the change.
3. **Backtest clean.** Re-run `--backtest 2000-01 <current>` and compare the
   four reference windows (2008 recession, 2020 COVID, the 2020-21 rebound,
   the 2022 hiking cycle). State how many months changed. A change that moves
   hundreds of months is a different engine, not a fix.
4. **Bump `ENGINE_VERSION`.** In `pipeline/config.py`. The ledger stamps it on
   every snapshot, so claims made under different versions stay separable.
   Add a `CHANGELOG.md` entry using the template there.
5. **Judge at n≥20.** Do not declare the change good because the backtest
   improved. The ledger will tell you at `MIN_SAMPLE_N` resolved claims,
   against persistence and naive baselines. Until then it is a hypothesis
   that passed its tests.

## Things that are not negotiable

- **No accuracy figure without its baselines and its n.** Anywhere. A hit rate
  with no comparison is marketing.
- **Never edit a historical ledger line.** The hash chain will catch it and CI
  will fail. If a line is wrong, append a correction.
- **Never synthesise a claim the site did not make.** The backfill only
  reconstructs from committed `data/` states. A thin ledger is honest; a
  padded one is worthless.
- **No threshold in a logic file.** All tunables live in `pipeline/config.py`.
- **Data flows pipeline → content, one way.** Lessons read shipped JSON.
  Pipeline code must never read `content/` to make a decision.
- **Curve-fitting is a bug.** If a change only works by widening a threshold
  to fit the windows you happen to be checking, say so and don't ship it.

## Voice rules (simple mode)

Sentences of 15 words or fewer, one idea each. No jargon without an instant
plain definition. Rounded numbers in prose. Direction always explicit — up,
down, or sideways. `tests/test_voice.py` enforces what it can.

## Layout

```
pipeline/       the engine and the builders
content/        static teaching material (lessons, glossary, framework.md)
ledger/         append-only record of what was claimed (hash-chained)
reports/weekly/ Sunday reports
data/           what the bot commits every 30 minutes
mock/, mock/alt/ two complete states for frontend development
```
