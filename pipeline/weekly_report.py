"""The Sunday report: what the engine claimed, what resolved, what to review.

Seven sections, in the order a reader should meet them. The two disciplines
that matter here:

  * No accuracy figure appears without its baselines and its n. Below
    config.MIN_SAMPLE_N a cell renders as "insufficient", never as a small
    number, because a 3-of-5 hit rate printed as "60%" is a lie told with
    arithmetic.
  * The review section stays SILENT unless a claim type trails persistence by
    config.REVIEW_TRIGGER_PP with a real sample behind it. A report that nags
    every week on noise gets ignored within a month, and then it is worth
    nothing on the week it finally matters.

    python -m pipeline.weekly_report            # writes reports/weekly/YYYY-Www.*
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from . import ledger as led

ROOT = Path(__file__).parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def week_id(day: pd.Timestamp | None = None) -> str:
    day = day or pd.Timestamp.now(tz="UTC").tz_localize(None)
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _cell_line(name: str, cell: dict) -> str:
    """One row of an accuracy table — or an honest refusal to render one."""
    if not cell.get("sufficient"):
        return f"| {name} | — | — | — | {cell.get('n', 0)} | insufficient (need {config.MIN_SAMPLE_N}) |"
    eng, per = cell.get("engine"), cell.get("persistence")
    naive = cell.get("naive")
    edge = "—" if (eng is None or per is None) else f"{eng - per:+.1f}pp"
    return (f"| {name} | {eng}% | {per}% | "
            f"{'—' if naive is None else str(naive) + '%'} | {cell['n']} | {edge} |")


# ---- section 6: open calibration issues ----------------------------------
def open_issues(label: str) -> tuple[list[dict], str | None]:
    """Open issues for one label. Degrades to 'unavailable', never fails the report."""
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--label", label, "--state", "open",
             "--json", "number,title,createdAt,labels", "--limit", "50"],
            capture_output=True, text=True, timeout=45, cwd=str(ROOT))
        if out.returncode != 0:
            return [], (out.stderr.strip().splitlines() or ["gh call failed"])[-1]
        return json.loads(out.stdout or "[]"), None
    except Exception as exc:
        return [], repr(exc)


def open_feedback() -> tuple[dict, dict]:
    """{label: [issues]}, {label: error}. One call per label so a single
    failing label cannot hide the others."""
    found, errors = {}, {}
    for label in config.FEEDBACK_LABELS:
        items, err = open_issues(label)
        found[label] = items
        if err:
            errors[label] = err
    return found, errors


# ---- section 7: suggested review items -----------------------------------
def review_items(track: dict) -> list[str]:
    """Only fires on a real, sustained shortfall. Otherwise says nothing."""
    items = []
    for asset, horizons in (track.get("by_asset") or {}).items():
        for horizon, cell in horizons.items():
            if not cell.get("sufficient"):
                continue
            eng, per = cell.get("engine"), cell.get("persistence")
            if eng is None or per is None:
                continue
            if eng < per - config.REVIEW_TRIGGER_PP:
                items.append(
                    f"`{asset}` at {horizon}: engine {eng}% vs persistence "
                    f"{per}% (n={cell['n']}) — trailing by "
                    f"{per - eng:.1f}pp, past the {config.REVIEW_TRIGGER_PP}pp "
                    f"review line.")
    return items


# ---- the report ----------------------------------------------------------
def build(track: dict, root: Path | None = None) -> dict:
    root = root or ROOT
    snapshots = led.read_lines("snapshots", root)
    scores = led.read_lines("scores", root)
    events = led.read_lines("events", root)
    divergences = led.read_lines("divergences", root)
    health = led.read_lines("health", root)
    feedback, feedback_errors = open_feedback()

    versions = {}
    for snap in snapshots:
        key = (snap.get("engine_version"), (snap.get("config_hash") or "")[:12])
        versions.setdefault(key, []).append(snap["day"])

    chains = {}
    for stream in ("snapshots", "events", "divergences", "health", "scores"):
        ok, msg = led.verify_chain(stream, root)
        chains[stream] = {"ok": ok, "detail": msg}

    return {
        "week": week_id(),
        "generated": _now(),
        "schema_version": config.SCHEMA_VERSION,
        "engine_version": config.ENGINE_VERSION,
        "config_hash": led.config_hash(),
        "headline": track.get("overall", {}),
        "by_asset": track.get("by_asset", {}),
        "calibration": track.get("calibration", []),
        "counts": {"snapshots": len(snapshots), "scores": len(scores),
                   "events": len(events), "divergences": len(divergences),
                   "health": len(health)},
        "resolutions": [e for e in events if e.get("phase") == "resolution"][-10:],
        "divergences": divergences[-10:],
        "versions": [{"engine_version": v, "config_hash": c,
                      "days": len(days), "first": min(days), "last": max(days)}
                     for (v, c), days in sorted(versions.items())],
        "reliability": {"chains": chains, "health_recent": health[-10:]},
        "open_feedback": feedback,
        "open_feedback_errors": feedback_errors,
        "review_items": review_items(track),
    }


def render_markdown(rep: dict) -> str:
    L = [f"# MONEY FLOW — weekly report {rep['week']}", "",
         f"Generated {rep['generated']} · engine `{rep['engine_version']}` · "
         f"config `{rep['config_hash'][:12]}`", "",
         "> Every accuracy figure below is shown against two baselines and its "
         "sample size. Cells under "
         f"n={config.MIN_SAMPLE_N} are withheld rather than rounded — a hit "
         "rate from a handful of claims is noise wearing a percentage sign.",
         ""]

    L += ["## 1. Headline", "",
          "| Horizon | Engine | Persistence | Always-up | n | Edge |",
          "|---|---|---|---|---|---|"]
    for horizon, cell in (rep["headline"] or {}).items():
        L.append(_cell_line(horizon, cell))
    if not rep["headline"]:
        L.append("| — | — | — | — | 0 | no claims resolved yet |")
    L += ["", "### By asset", "",
          "| Asset · horizon | Engine | Persistence | Always-up | n | Edge |",
          "|---|---|---|---|---|---|"]
    if rep["by_asset"]:
        for asset, horizons in sorted(rep["by_asset"].items()):
            for horizon, cell in sorted(horizons.items()):
                L.append(_cell_line(f"{asset} · {horizon}", cell))
    else:
        L.append("| — | — | — | — | 0 | nothing resolvable yet |")

    L += ["", "## 2. Resolutions this week", ""]
    if rep["resolutions"]:
        L += ["| Event | Reference | Branch | As mapped |", "|---|---|---|---|"]
        for e in rep["resolutions"]:
            L.append(f"| {e.get('event')} | {e.get('date')} | "
                     f"{e.get('branch')} | {'yes' if e.get('as_mapped') else 'no'} |")
    else:
        L.append("Nothing resolved this week.")

    L += ["", "## 3. Divergence digest", ""]
    if rep["divergences"]:
        L += ["| Day | Kind | Subject | Transition |", "|---|---|---|---|"]
        for dv in rep["divergences"]:
            L.append(f"| {dv.get('day')} | {dv.get('kind')} | "
                     f"{dv.get('subject')} | {dv.get('from')} → {dv.get('to')} |")
    else:
        L.append("No new divergences. (A row already diverging is not a new "
                 "divergence — only transitions are logged.)")

    L += ["", "## 4. Version ledger", "",
          "| Engine | Config hash | Days | First | Last |", "|---|---|---|---|---|"]
    for v in rep["versions"]:
        L.append(f"| {v['engine_version']} | `{v['config_hash']}` | {v['days']} | "
                 f"{v['first']} | {v['last']} |")
    if not rep["versions"]:
        L.append("| — | — | 0 | — | — |")
    L += ["", "A config-hash change means later claims are not strictly "
          "comparable with earlier ones. That is the point of recording it."]

    L += ["", "## 5. Reliability", "",
          "| Stream | Chain | Detail |", "|---|---|---|"]
    for stream, st in rep["reliability"]["chains"].items():
        L.append(f"| {stream} | {'intact' if st['ok'] else 'BROKEN'} | {st['detail']} |")
    counts = rep["counts"]
    L += ["", f"Ledger holds {counts['snapshots']} snapshot(s), "
          f"{counts['scores']} resolved claim(s), {counts['events']} event "
          f"record(s), {counts['health']} health record(s)."]
    if rep["reliability"]["health_recent"]:
        L += ["", "Recent health entries:", ""]
        for h in rep["reliability"]["health_recent"]:
            L.append(f"- `{h.get('ts')}` **{h.get('kind')}** {h.get('source')}"
                     f"{' — ' + h['detail'] if h.get('detail') else ''}")

    L += ["", "## 6. Open feedback notes", ""]
    feedback = rep.get("open_feedback") or {}
    errors = rep.get("open_feedback_errors") or {}
    titles = {"confusion": "Confusion — a line that did not land",
              "calibration": "Calibration — a disagreement with the read"}
    total = sum(len(v) for v in feedback.values())
    if errors and not total:
        L.append("Unavailable — could not reach GitHub ("
                 + "; ".join(f"`{k}`: {v}" for k, v in errors.items())
                 + "). The report is otherwise complete.")
    else:
        for label in config.FEEDBACK_LABELS:
            items = feedback.get(label) or []
            L += [f"**{titles.get(label, label)}** ({len(items)} open)", ""]
            if label in errors:
                L += [f"- unavailable: `{errors[label]}`", ""]
                continue
            if not items:
                L += ["- none open", ""]
                continue
            for i in items:
                L.append(f"- #{i['number']} {i['title']} ({i['createdAt'][:10]})")
            L.append("")
        if feedback.get("confusion"):
            L.append("Confusion notes are writing defects. They are usually a "
                     "template edit in `config.py`, not an engine change.")

    L += ["", "## 7. Suggested review", ""]
    if rep["review_items"]:
        L += [f"- {item}" for item in rep["review_items"]]
    else:
        L.append(f"Nothing to review. No claim type trails persistence by "
                 f"{config.REVIEW_TRIGGER_PP}pp at n≥{config.MIN_SAMPLE_N}. "
                 f"This section stays quiet on purpose — a report that flags "
                 f"something every week stops being read.")

    L += ["", "## Calibration", "",
          "| Needle probability | Observed | Expected | n |", "|---|---|---|---|"]
    for cell in rep["calibration"]:
        if cell.get("sufficient"):
            L.append(f"| {cell['bucket']} | {cell['observed']}% | "
                     f"{cell['expected']}% | {cell['n']} |")
        else:
            L.append(f"| {cell['bucket']} | — | — | {cell['n']} (insufficient) |")
    L.append("")
    return "\n".join(L)


def write(rep: dict, root: Path | None = None) -> tuple[Path, Path]:
    root = root or ROOT
    out_dir = root / config.WEEKLY_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{rep['week']}.md"
    js = out_dir / f"{rep['week']}.json"
    md.write_text(render_markdown(rep))
    js.write_text(json.dumps(rep, indent=1) + "\n")
    return md, js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track-record", default="data/track_record.json")
    args = ap.parse_args()
    tr_path = ROOT / args.track_record
    track = json.loads(tr_path.read_text()) if tr_path.exists() else {}
    rep = build(track)
    md, js = write(rep)
    print(f"[weekly] wrote {md.relative_to(ROOT)} and {js.relative_to(ROOT)}")
    print(f"[weekly] snapshots={rep['counts']['snapshots']} "
          f"scores={rep['counts']['scores']} "
          f"review_items={len(rep['review_items'])}")


if __name__ == "__main__":
    main()
