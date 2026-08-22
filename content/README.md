# content/ — static teaching material

Ships as plain files in the repo and is served straight off GitHub Pages.
Nothing here is generated at build time, and nothing here needs the pipeline
to run. The frontend fetches these directly.

```
content/
  lessons/index.json      the 14 lessons in curriculum order (id, slug, title, hook)
  lessons/lesson-NN.json  one lesson each
  glossary.json           ~44 terms, one plain sentence each
  framework.md            source text for lesson authoring (see "Provenance")
```

## Lesson shape

```jsonc
{
  "id": 9, "slug": "gold-vs-real-yields",
  "title": "...",           // the lesson name
  "hook": "...",            // a real question, asked the way a beginner would
  "metaphor": "...",        // one concrete image
  "body": ["...", "..."],   // 3-6 short lines, one idea each
  "live": { "template": "... {slot} ...", "slots": { ... } },
  "caveat": "...",          // exactly one, and it must be honest
  "see_it": {"module": "evidence", "anchor": "real_yields_gold"}
}
```

## Slot grammar

Slots keep the lesson evergreen while the example stays today's. Each slot
names a shipped JSON file and a path into it.

```jsonc
"real_5y": {"file": "evidence.json", "path": "real_yields_gold.real_5y[-1]", "round": 1}
```

Path steps:

| Form | Meaning |
|---|---|
| `a.b.c` | walk objects by key |
| `arr[0]` | index |
| `arr[-1]` | last element |
| `arr[key=value]` | first element whose `key` equals `value` |
| `arr.length` | number of elements |
| `a.$b` | resolve `b` from the same file's root, then use it as the key |

Modifiers, applied in this order:

| Key | Effect |
|---|---|
| `map` | `updown_word` → up/down/sideways by sign · `percent` → ×100 · `longshort_word` → "betting on higher/lower prices" |
| `round` | decimals; `0` yields an integer |

`updown_word` is **sign-based**, deliberately unlike the Evidence scorecard,
which uses flat bands from `config.SCORECARD_FLAT_BAND`. A lesson says which
way a number leans; the scorecard judges whether a move was big enough to
count. Do not conflate them.

## Resolver contract

`pipeline/lessons.py` is the reference implementation and the spec the
frontend resolver must match. A slot that cannot be resolved yields `None`,
and the renderer substitutes `—` rather than raising: a missing number must
never take the page down. `tests/test_lessons.py` proves every slot in all 14
lessons resolves against both mock states.

## Voice rules

Every string a reader sees in simple mode:

- Sentences of 15 words or fewer, one idea each.
- No jargon without an instant plain definition. "The Fed may raise rates",
  never "hawkish tilt".
- Rounded numbers in prose: "about 4%", "roughly +20K jobs a month".
- "usually" and "tends to" — never "may potentially possibly".
- Direction is always explicit: up, down, or sideways. Never just "mixed".

`tests/test_voice.py` enforces the length limit and a banned-jargon list
(`config.BANNED_JARGON`). The glossary is exempt, because defining those
words is its job.

## Provenance

Lesson concepts, metaphors and the curriculum order come from the v2
blueprint. Caveats that correct an overstatement are sourced from the
pipeline's own data contract where one exists, so the lesson and the module
say the same thing:

All 14 lessons were reconciled against `content/framework.md` on 2026-08-22.
Part 12 of that document ("What to Trust, and What to Check Yourself") flags
five places where the source material states things more confidently than the
evidence supports. Each one is carried by the matching lesson's caveat:

| framework.md flags | Lesson | How the caveat carries it |
|---|---|---|
| "Every inversion caused a recession" | 7 | ~12 episodes, lag months to nearly two years, "a warning light, not a stopwatch" |
| "90% of money moves because of macro" | 8 | "Rate gaps explain most currency moves, not all" — the figure is never quoted |
| "Gold and real yields are mathematical" | 9 | "a strong pattern, not a law" + the central-bank-buying decoupling |
| The VIX "always" reverts | 11 | roll costs: contracts "expire and must be replaced", so "a floor does not make it safe" |
| "Follow the smart money" via COT | 14 | "covers a wide mix of firms" + Friday-for-Tuesday lag, "context, never a trigger" |

Other caveats trace to specific sections rather than to a flagged
overstatement: lesson 3 to Part 3 (5-7 year short-term debt cycle), lesson 4
to Part 4 (markets have priced recessions that never arrived), lesson 10 to
Part 7 (cap-weighted indexes).

One-way dependency: **data flows pipeline → content**. Lessons read shipped
JSON through slots; pipeline code must never read `content/` to make a
decision.
