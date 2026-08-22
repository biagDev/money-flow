"""Seed the ledger from what the site ACTUALLY published, and nothing else.

Walks the git history of data/*.json and reconstructs one snapshot per commit
that carried a complete claim state. Lines are marked "source": "backfill" so
no later reader mistakes a reconstruction for a live recording.

The rule this module exists to respect: never synthesize a claim for a day the
site did not assert one. If data/ entered git history four days ago, the
backfill is four lines. A thin honest ledger is the correct output; padding it
would defeat the entire purpose of keeping one.

    python -m pipeline.backfill            # dry run, prints what it would add
    python -m pipeline.backfill --write
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import config
from . import ledger as led

ROOT = Path(__file__).parent.parent
NEEDED = ("regime.json", "overview.json", "dials.json",
          "scenarios.json", "evidence.json")


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def commits_touching_data() -> list[tuple[str, str]]:
    """[(sha, iso-date)] oldest first, for commits that changed data/."""
    out = _git("log", "--reverse", "--format=%H %cI", "--", "data/")
    rows = []
    for line in out.splitlines():
        sha, _, when = line.partition(" ")
        if sha:
            rows.append((sha, when[:10]))
    return rows


def file_at(sha: str, path: str) -> dict | None:
    try:
        return json.loads(_git("show", f"{sha}:{path}"))
    except Exception:
        return None


def reconstruct(sha: str, day: str) -> dict | None:
    """A snapshot from one commit, or None when the state is incomplete."""
    files = {name: file_at(sha, f"data/{name}") for name in NEEDED}
    if any(files[name] is None for name in NEEDED):
        return None
    regime, overview = files["regime.json"], files["overview.json"]
    dials, scenarios = files["dials.json"], files["scenarios.json"]
    evidence = files["evidence.json"]

    # The input vintage is only partly recoverable from shipped JSON. Record
    # what the files actually contain and leave the rest null rather than
    # back-computing numbers the site never published.
    infl = dials.get("inflation") or {}
    emp = dials.get("employment") or {}
    curve = ((evidence.get("curve") or {}).get("spread_10y3m") or {})
    series = curve.get("series") or []
    real = ((evidence.get("real_yields_gold") or {}).get("real_5y") or [])
    inputs = {
        "pce_yoy": infl.get("pce_yoy"),
        "pce_mom3": infl.get("trend_3mo"),
        "unrate": emp.get("unrate"),
        "sahm_gap": None,
        "payems_3mo": None,
        "spread_10y3m": series[-1] if series else None,
        "spread_slope_3mo": None,
        "walcl_6mo": None,
        "real_5y": real[-1] if real else None,
    }
    snap = led.build_snapshot(day, regime, overview, dials, scenarios,
                              evidence, inputs, source="backfill")
    snap["commit"] = sha[:12]
    return snap


def run(write: bool = False) -> dict:
    seen = {rec["day"] for rec in led.read_lines("snapshots")}
    added, skipped_incomplete, skipped_dupe = [], [], []
    for sha, day in commits_touching_data():
        if day in seen:
            skipped_dupe.append((sha[:8], day))
            continue
        snap = reconstruct(sha, day)
        if snap is None:
            skipped_incomplete.append((sha[:8], day))
            continue
        seen.add(day)
        added.append(snap)

    if write:
        # oldest first so the hash chain reads chronologically
        existing = led.read_lines("snapshots")
        if existing:
            # a live line already exists; backfill must not be spliced before it
            newest_live = max(r["day"] for r in existing)
            added = [s for s in added if s["day"] > newest_live]
        for snap in added:
            led.append("snapshots", snap)
    return {"added": added, "incomplete": skipped_incomplete,
            "duplicate": skipped_dupe}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    res = run(write=args.write)
    print(f"[backfill] commits touching data/: "
          f"{len(res['added']) + len(res['incomplete']) + len(res['duplicate'])}")
    print(f"[backfill] reconstructable snapshots: {len(res['added'])}")
    for snap in res["added"]:
        claim = snap["claim"]
        print(f"    {snap['day']}  {snap['commit']}  needle={claim['needle']}  "
              f"mood={claim['mood']}")
    if res["incomplete"]:
        print(f"[backfill] skipped {len(res['incomplete'])} commit(s) with an "
              f"incomplete claim state (no overview.json yet):")
        for sha, day in res["incomplete"]:
            print(f"    {day}  {sha}")
    if res["duplicate"]:
        print(f"[backfill] skipped {len(res['duplicate'])} day(s) already in "
              f"the ledger")
    if not args.write:
        print("[backfill] dry run — pass --write to append")


if __name__ == "__main__":
    main()
