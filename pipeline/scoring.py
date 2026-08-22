"""Resolve what the ledger claimed, against baselines that make it meaningful.

An accuracy number on its own is close to worthless. "The engine called stocks
right 61% of the time" means nothing until you know that simply assuming the
last three months continue would have scored 64%, or that stocks rose in 70% of
those windows anyway. So every figure this module emits is a TRIPLE —

    engine · persistence · naive        (with n)

— and nothing is emitted at all below config.MIN_SAMPLE_N. A cell with n=19 is
rendered "insufficient", not rendered small.

Direction claims resolve at +21 and +63 TRADING days, measured on the same
price series and through the same flat bands the Evidence scorecard uses
(narrative.asset_moves / move_direction). The bands are imported, never
restated, for the same reason Layer 1 imports them: two definitions of "up"
is how a track record starts flattering itself.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from . import ledger as led
from . import narrative as nar

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# asset -> (series key in the data dict, move key used by the flat bands)
ASSET_SERIES = {"stocks": ("spx", "spx"), "gold": ("gold", "gold"),
                "dollar": ("dxy_proxy", "dxy"), "bonds": ("y10", "y10_bp")}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- forward moves -------------------------------------------------------
def forward_move(series: pd.Series | None, start: str, n_trading: int,
                 move_key: str) -> tuple[float, str] | None:
    """(move, end_date) n TRADING days after `start`, in the scorecard's units.

    Trading days are the series' own observations, so holidays and weekends
    fall out naturally rather than being approximated from calendar days.
    """
    if series is None:
        return None
    s = series.dropna()
    if s.empty:
        return None
    at = pd.Timestamp(start)
    past = s[s.index <= at]
    if past.empty:
        return None
    start_pos = s.index.get_loc(past.index[-1])
    end_pos = start_pos + n_trading
    if end_pos >= len(s):
        return None                      # not resolvable yet — say so, never guess
    a, b = float(s.iloc[start_pos]), float(s.iloc[end_pos])
    move = (b - a) * 100.0 if move_key == "y10_bp" else (b / a - 1.0) * 100.0
    return move, str(s.index[end_pos].date())


def direction_of(move_key: str, move: float) -> str:
    """The scorecard's own banding, imported rather than restated."""
    return config.DIRECTION_WORDS[nar.move_direction(move_key, move)]


# ---- one claim -----------------------------------------------------------
def resolve_asset_claim(snapshot: dict, asset_row: dict, d: dict,
                        horizon_name: str, n_trading: int) -> dict | None:
    asset = asset_row.get("asset")
    spec = ASSET_SERIES.get(asset)
    if spec is None:
        return None
    series_key, move_key = spec
    fwd = forward_move(d.get(series_key), snapshot["day"], n_trading, move_key)
    if fwd is None:
        return None
    move, end_day = fwd
    outcome = direction_of(move_key, move)

    engine = asset_row.get("expected")
    persistence = asset_row.get("actual")       # trailing 3-mo direction at claim time
    naive = "up" if asset == "stocks" else None  # always-up only defined for stocks

    return {
        "ts": _now(), "kind": "asset_direction", "asset": asset,
        "day": snapshot["day"], "horizon": horizon_name,
        "trading_days": n_trading, "resolved_on": end_day,
        "engine_version": snapshot.get("engine_version"),
        "config_hash": snapshot.get("config_hash"),
        "source": snapshot.get("source"),
        "move": round(move, 3), "outcome": outcome,
        "engine": engine, "engine_hit": engine == outcome,
        "persistence": persistence,
        "persistence_hit": (None if persistence is None
                            else persistence == outcome),
        "naive": naive,
        "naive_hit": (None if naive is None else naive == outcome),
    }


def resolve_projection_claims(snapshots: list[dict]) -> list[dict]:
    """A projection resolves when the needle changes, or expires at 6 months."""
    out = []
    for i, snap in enumerate(snapshots):
        claim = snap.get("claim") or {}
        projected = claim.get("projection")
        needle = claim.get("needle")
        if not projected or projected == needle:
            continue                     # "no change expected" is not a claim
        start = pd.Timestamp(snap["day"])
        expiry = start + pd.DateOffset(months=config.PROJECTION_EXPIRY_MONTHS)
        for later in snapshots[i + 1:]:
            lday = pd.Timestamp(later["day"])
            lneedle = (later.get("claim") or {}).get("needle")
            if lneedle and lneedle != needle:
                out.append({
                    "ts": _now(), "kind": "projection", "day": snap["day"],
                    "resolved_on": later["day"], "from_needle": needle,
                    "engine": projected, "outcome": lneedle,
                    "engine_hit": projected == lneedle,
                    "engine_version": snap.get("engine_version"),
                    "config_hash": snap.get("config_hash"),
                    "source": snap.get("source"),
                })
                break
            if lday > expiry:
                out.append({
                    "ts": _now(), "kind": "projection", "day": snap["day"],
                    "resolved_on": later["day"], "from_needle": needle,
                    "engine": projected, "outcome": "no_change",
                    "engine_hit": False, "expired": True,
                    "engine_version": snap.get("engine_version"),
                    "config_hash": snap.get("config_hash"),
                    "source": snap.get("source"),
                })
                break
    return out


# ---- aggregation ---------------------------------------------------------
def _rate(hits: list) -> float | None:
    vals = [h for h in hits if h is not None]
    return round(100.0 * sum(1 for h in vals if h) / len(vals), 1) if vals else None


def accuracy_cell(rows: list[dict]) -> dict:
    """A triple plus n, gated. Never a bare percentage."""
    n = len(rows)
    cell = {
        "n": n,
        "sufficient": n >= config.MIN_SAMPLE_N,
        "engine": _rate([r.get("engine_hit") for r in rows]),
        "persistence": _rate([r.get("persistence_hit") for r in rows]),
        "naive": _rate([r.get("naive_hit") for r in rows]),
        "coin_flip": 50.0,
    }
    if not cell["sufficient"]:
        # keep the counts, withhold the rates: an n=19 number invites belief
        cell["note"] = (f"insufficient sample: {n} of "
                        f"{config.MIN_SAMPLE_N} needed")
        for k in ("engine", "persistence", "naive"):
            cell[f"{k}_withheld"] = cell.pop(k)
    return cell


def calibration(scores: list[dict], snapshots: list[dict]) -> list[dict]:
    """Did a 55%-confidence call behave like a 55% call?

    Bucketed on the needle's own probability; the outcome is whether the four
    assets mostly did what that regime expects over +63 trading days.
    """
    by_day = {s["day"]: s for s in snapshots}
    per_day: dict[str, list[bool]] = {}
    for row in scores:
        if row.get("kind") != "asset_direction" or row.get("horizon") != "h63":
            continue
        per_day.setdefault(row["day"], []).append(bool(row.get("engine_hit")))

    out = []
    for lo, hi in config.CALIBRATION_BUCKETS:
        days = []
        for day, hits in per_day.items():
            snap = by_day.get(day)
            if not snap:
                continue
            claim = snap.get("claim") or {}
            probs = claim.get("probabilities") or {}
            p = probs.get(claim.get("needle"))
            if p is None or not (lo <= p < hi):
                continue
            days.append(sum(hits) > len(hits) / 2.0)   # mostly behaved as expected
        cell = {"bucket": f"{lo:.2f}-{hi:.2f}", "n": len(days),
                "sufficient": len(days) >= config.MIN_SAMPLE_N}
        if cell["sufficient"]:
            cell["observed"] = round(100.0 * sum(days) / len(days), 1)
            cell["expected"] = round(100.0 * (lo + min(hi, 1.0)) / 2.0, 1)
        else:
            cell["note"] = f"insufficient sample: {len(days)} of {config.MIN_SAMPLE_N}"
        out.append(cell)
    return out


def aggregate(scores: list[dict], snapshots: list[dict]) -> dict:
    by_asset_horizon = {}
    for row in scores:
        if row.get("kind") != "asset_direction":
            continue
        by_asset_horizon.setdefault((row["asset"], row["horizon"]), []).append(row)

    assets = {}
    for (asset, horizon), rows in sorted(by_asset_horizon.items()):
        assets.setdefault(asset, {})[horizon] = accuracy_cell(rows)

    overall = {}
    for horizon in config.SCORING_HORIZONS:
        rows = [r for r in scores
                if r.get("kind") == "asset_direction" and r.get("horizon") == horizon]
        overall[horizon] = accuracy_cell(rows)

    projections = [r for r in scores if r.get("kind") == "projection"]
    return {
        "as_of": _now(),
        "schema_version": config.SCHEMA_VERSION,
        "engine_version": config.ENGINE_VERSION,
        "config_hash": led.config_hash(),
        "min_sample_n": config.MIN_SAMPLE_N,
        "note": ("Every accuracy figure is engine vs persistence vs naive, with n. "
                 "Cells below the minimum sample are withheld, not shrunk."),
        "snapshots": len(snapshots),
        "resolved_claims": len(scores),
        "overall": overall,
        "by_asset": assets,
        "projections": accuracy_cell(projections) if projections else
                       {"n": 0, "sufficient": False,
                        "note": "no projection claims resolved yet"},
        "calibration": calibration(scores, snapshots),
    }


# ---- the pass ------------------------------------------------------------
def _already(root: Path | None) -> set:
    keys = set()
    for row in led.read_lines("scores", root):
        if row.get("kind") == "asset_direction":
            keys.add((row["day"], row["asset"], row["horizon"]))
        elif row.get("kind") == "projection":
            keys.add((row["day"], "projection", "-"))
    return keys


def run(d: dict, root: Path | None = None, write: bool = True) -> dict:
    """Resolve everything newly resolvable; append to scores.jsonl."""
    root = root or ROOT
    snapshots = sorted(led.read_lines("snapshots", root), key=lambda s: s["day"])
    seen = _already(root)
    fresh = []

    for snap in snapshots:
        for row in (snap.get("claim") or {}).get("assets") or []:
            for hname, n in config.SCORING_HORIZONS.items():
                if (snap["day"], row.get("asset"), hname) in seen:
                    continue
                res = resolve_asset_claim(snap, row, d, hname, n)
                if res:
                    fresh.append(res)

    for row in resolve_projection_claims(snapshots):
        if (row["day"], "projection", "-") not in seen:
            fresh.append(row)

    if write:
        for row in fresh:
            led.append("scores", row, root)

    all_scores = led.read_lines("scores", root) if write else fresh
    agg = aggregate(all_scores, snapshots)
    if write:
        out = (root / "data" / "track_record.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(agg, indent=1) + "\n")
    return {"new": len(fresh), "total": len(all_scores), "track_record": agg}


def main():
    from .fetch_fred import fetch_all
    from .fetch_prices import gold_series
    d = fetch_all()
    if "gold" not in d:
        g = gold_series()
        if g is not None:
            d["gold"] = g
    summary = run(d)
    print(f"[scoring] resolved {summary['new']} new claims "
          f"({summary['total']} total)")
    tr = summary["track_record"]
    for horizon, cell in tr["overall"].items():
        if cell["sufficient"]:
            print(f"[scoring] {horizon}: engine {cell['engine']}% vs "
                  f"persistence {cell['persistence']}% (n={cell['n']})")
        else:
            print(f"[scoring] {horizon}: {cell['note']}")


if __name__ == "__main__":
    main()
