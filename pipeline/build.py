"""MONEY FLOW pipeline orchestrator.

    python -m pipeline.build              # live build -> data/
    python -m pipeline.build --mock       # write mock/ + mock/alt/ (no network)
    python -m pipeline.build --backtest 2000-01 2026-08   # regime history

Live mode writes a JSON file only when its content hash changed, so the
Actions job can commit nothing when nothing new was published.
"""
from __future__ import annotations

import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from . import regime_engine as eng
from .fetch_fred import (fetch_all, fetch_release_dates, yoy, mom_delta,
                         pct_change_days, diff_days, last, spark)
from .fetch_cot import build_cot
from .fetch_prices import implied_fed_odds, gold_series
from . import narrative as nar
from . import watchlist as wl

T = config.THRESHOLDS

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
FOMC_FILE = ROOT / "pipeline" / "fomc_dates.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_if_changed(path: Path, obj: dict) -> bool:
    obj["schema_version"] = config.SCHEMA_VERSION
    payload = json.dumps(obj, indent=1, allow_nan=False)
    new_hash = hashlib.sha256(
        json.dumps({k: v for k, v in obj.items() if k != "as_of"},
                   sort_keys=True, allow_nan=False).encode()).hexdigest()
    if path.exists():
        try:
            old = json.loads(path.read_text())
            old_hash = hashlib.sha256(
                json.dumps({k: v for k, v in old.items() if k != "as_of"},
                           sort_keys=True, allow_nan=False).encode()).hexdigest()
            if old_hash == new_hash:
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return True


def next_fomc(fomc_dates: list[str]) -> str | None:
    today = str(pd.Timestamp.now(tz="UTC").date())
    fut = [f for f in sorted(fomc_dates) if f >= today]
    return fut[0] if fut else None


# ------------------------------------------------------------------ live build
def build_live(out_dir: Path, do_cot: bool = True) -> None:
    d = fetch_all()
    if "gold" not in d:          # FRED retired its gold series -> price vendor
        g = gold_series()
        if g is not None:
            d["gold"] = g
    now = _now_iso()
    fomc = json.loads(FOMC_FILE.read_text())["dates"] if FOMC_FILE.exists() else []
    nf = next_fomc(fomc)

    eff = last(d.get("fed_funds")) or last(d.get("fed_target_upper")) or 0.0
    priced = implied_fed_odds(nf, eff) if nf else None

    # --- regime ---
    core = eng.compute(d, priced=priced)
    proj = eng.projection(d, core, priced)
    since = eng.in_regime_since(d, core["needle"], priced)

    pce_y = yoy(d["pce"]).dropna() if "pce" in d else pd.Series(dtype=float)
    pce_now = float(pce_y.iloc[-1]) if len(pce_y) else None
    pce_mom = diff_days(pce_y, 92) if len(pce_y) else None
    u = d.get("unrate")
    unrate_now = last(u)
    sahm = (float(u.iloc[-3:].mean()) - float(u.iloc[-12:].min())) if u is not None and len(u) >= 12 else 0.0
    infl_desc = nar._infl_desc(pce_now, pce_mom)
    emp_desc = nar._emp_desc(unrate_now, sahm, eng.payroll_state(d))
    bias = nar.fed_bias(bool(pce_now and pce_now > T["inflation_target"]),
                        bool(pce_mom and pce_mom > T["inflation_momentum"]), sahm)

    regime = {
        "as_of": now, "stale": False,
        "probabilities": core["probabilities"],
        "needle": core["needle"], "projection": proj,
        "projection_basis": "momentum",
        "in_regime_since": since,
        "narrative": nar.narrative(core["needle"], infl_desc, emp_desc, bias),
        "scores": core["scores"],
    }

    # --- dials ---
    cpi_y = yoy(d["cpi"]).dropna() if "cpi" in d else pd.Series(dtype=float)
    ppi_y = yoy(d["ppi"]).dropna() if "ppi" in d else pd.Series(dtype=float)
    nfp = mom_delta(d["payems"]).dropna() if "payems" in d else pd.Series(dtype=float)
    claims = d.get("claims")
    dials = {
        "as_of": now,
        "inflation": {
            "pce_yoy": round(pce_now, 2) if pce_now is not None else None,
            "cpi_yoy": round(float(cpi_y.iloc[-1]), 2) if len(cpi_y) else None,
            "target": config.THRESHOLDS["inflation_target"],
            "trend_3mo": round(pce_mom, 2) if pce_mom is not None else None,
            "direction": ("rising" if (pce_mom or 0) > T["inflation_momentum"]
                          else "falling" if (pce_mom or 0) < -T["inflation_momentum"]
                          else "flat"),
            "sub": {
                "ppi_yoy": round(float(ppi_y.iloc[-1]), 2) if len(ppi_y) else None,
                "breakeven_5y": last(d.get("breakeven_5y")),
                "oil": {"last": last(d.get("oil")),
                        "spark": spark(d["oil"], 30, days=180) if "oil" in d else []},
            },
        },
        "employment": {
            "unrate": unrate_now,
            "direction": ("stressed" if sahm >= T["sahm_trigger"]
                          else "softening" if sahm >= T["sahm_warning"] else "stable"),
            "sub": {
                "nfp": {"actual": int(nfp.iloc[-1]) if len(nfp) else None},
                "claims_4wk": round(float(claims.iloc[-4:].mean()) / 1000, 0)
                    if claims is not None and len(claims) >= 4 else None,
                "jolts": round(last(d.get("jolts")) / 1000, 1) if last(d.get("jolts")) else None,
            },
        },
        "verdict": {
            "bias": bias,
            "lines": [
                {"dial": "inflation", "reading": infl_desc,
                 "implication": ("argues HIKE/HOLD" if (pce_now or 0) > T["inflation_target"]
                                 else "argues CUT/HOLD")},
                {"dial": "employment", "reading": emp_desc,
                 "implication": ("forces the Fed dovish" if sahm >= T["sahm_trigger"]
                                 else "gives the Fed room to be hawkish")},
            ],
        },
    }

    # --- scenarios ---
    trends = {
        "bonds": f"{(diff_days(d['y10'], 92) or 0) * 100:+.0f}bp" if "y10" in d else "n/a",
        "dollar": f"{pct_change_days(d['dxy_proxy'], 92) or 0:+.1f}%" if "dxy_proxy" in d else "n/a",
        "gold": f"{pct_change_days(d['gold'], 92) or 0:+.1f}%" if "gold" in d else "n/a",
        "stocks": f"{pct_change_days(d['spx'], 92) or 0:+.1f}%" if "spx" in d else "n/a",
        "curve": f"{(diff_days(d['spread_10y3m'], 92) or 0):+.2f}pp" if "spread_10y3m" in d else "n/a",
    }
    decks = {k: [{**card, "current_3mo": trends[card["asset"]]} for card in deck]
             for k, deck in config.SCENARIO_DECKS.items()}
    default = max(priced, key=lambda k: priced[k] if k in ("hike", "hold", "cut") else -1) \
        if priced else ("hike" if bias.startswith("hawkish") else
                        "cut" if bias.startswith("dovish") else "hold")
    scenarios = {"as_of": now,
                 "market_pricing": ({k: priced[k] for k in ("hike", "hold", "cut")}
                                    if priced else None),
                 "pricing_stale": priced is None,
                 "next_fomc": nf, "default": default, "decks": decks}

    # --- flows ---
    nodes = []
    for asset, key in (("bonds", "y10"), ("dollar", "dxy_proxy"),
                       ("gold", "gold"), ("stocks", "spx")):
        s = d.get(key)
        t3 = (diff_days(s, 92) or 0) * 100 if asset == "bonds" and s is not None \
            else pct_change_days(s, 92) if s is not None else None
        nodes.append({
            "asset": asset,
            "price": last(s),
            "trend_3mo": round(t3, 2) if t3 is not None else None,
            "trend_unit": "bp" if asset == "bonds" else "%",
            "spark": spark(s, 120, days=185) if s is not None else [],
            "driver": config.ASSET_DRIVERS[asset],
            "stale": bool(getattr(s, "attrs", {}).get("stale")) if s is not None else True,
        })
    flows = {"as_of": now, "regime": core["needle"],
             "nodes": nodes,
             "edges": [{"from": a, "to": b, "strength": st}
                       for a, b, st in config.REGIME_FLOWS[core["needle"]]]}

    # --- evidence ---
    def curve_points(asof_offset_days: int = 0):
        pts = []
        for label, key in (("3M", "y3m"), ("2Y", "y2"), ("5Y", "y5"),
                           ("10Y", "y10"), ("30Y", "y30")):
            s = d.get(key)
            if s is None:
                continue
            s = s.dropna()
            if asof_offset_days:
                s = s[s.index <= s.index[-1] - pd.Timedelta(days=asof_offset_days)]
            if len(s):
                pts.append({"m": label, "y": round(float(s.iloc[-1]), 2)})
        return pts

    sp = d.get("spread_10y3m")
    rec = d.get("recessions")
    rec_bands = []
    if rec is not None:
        r = rec.dropna()
        in_rec, start = False, None
        for dt, v in r.items():
            if v == 1 and not in_rec:
                in_rec, start = True, dt
            elif v == 0 and in_rec:
                in_rec = False
                rec_bands.append([str(start.date()), str(dt.date())])
    sp_level = last(sp)
    sp_slope = diff_days(sp, 92) if sp is not None else None
    inverted_recent = bool(sp is not None and len(sp.dropna()) >= 260
                           and float(sp.dropna().iloc[-260:].min()) < 0)
    curve_status = ("inverted" if (sp_level or 1) < 0 else
                    "steepening_post_inversion"
                    if inverted_recent and (sp_slope or 0) > T["curve_steepen_3mo"] else
                    "flattening" if (sp_level or 1) < T["curve_flat"] else "normal")

    cot = build_cot() if do_cot else _load_prev_cot(out_dir)
    real5, gold = d.get("real_5y"), d.get("gold")
    corr = None
    if real5 is not None and gold is not None:
        j = pd.concat([real5.dropna(), gold.dropna()], axis=1).dropna()
        j = j[j.index >= j.index[-1] - pd.Timedelta(days=365)]
        if len(j) > 30:
            corr = round(float(j.corr().iloc[0, 1]), 2)
    gold_3mo = pct_change_days(gold, 92) if gold is not None else None
    exp_gold = config.REGIME_EXPECTATIONS[core["needle"]]["gold"]
    evidence = {
        "as_of": now,
        "curve": {"today": curve_points(), "6mo_ago": curve_points(182),
                  "1yr_ago": curve_points(365),
                  "spread_10y3m": {
                      "series": spark(sp, 260, days=365 * 5) if sp is not None else [],
                      "recessions": rec_bands[-6:],
                      "status": curve_status,
                      "caveat": ("~12 historical episodes; lag ranges months to "
                                 "~2 years. Warning light, not a timer.")}},
        "real_yields_gold": {
            "real_5y": spark(real5, 260, days=365 * 5) if real5 is not None else [],
            "gold": spark(gold, 260, days=365 * 5) if gold is not None else [],
            "corr_12mo": corr,
            "confirm": {"expected": f"gold {exp_gold}",
                        "actual": f"{gold_3mo:+.1f}%/3mo" if gold_3mo is not None else "no data",
                        "status": ("confirmed" if gold_3mo is not None and
                                   ((exp_gold == "down" and gold_3mo < 0) or
                                    (exp_gold == "up" and gold_3mo > 0) or
                                    exp_gold == "flat")
                                   else "diverging" if gold_3mo is not None else "na")}},
        "cot": cot,
        "cot_caveat": "Published Friday for Tuesday positions — context, not a trigger.",
        "scorecard": nar.scorecard(core["needle"], d, cot),
    }

    # --- calendar ---
    rel = {}
    for name, rid in config.FRED_RELEASES.items():
        try:
            rel[name] = fetch_release_dates(rid, config.CALENDAR_LOOKAHEAD_DAYS)
        except Exception as e:
            print(f"[calendar] {name}: {e}")
            rel[name] = []
    calendar = {"as_of": now, **nar.build_calendar(rel, fomc, d)}

    # --- watchlist (purely additive: unknown events keep their current shape) ---
    regime_state = {"needle": core["needle"], "bias": bias,
                    "unrate": unrate_now, "sahm": sahm}
    for e in calendar.get("upcoming", []):
        watch = wl.branch_for_event(e.get("event", ""), e.get("feeds", ""),
                                    d, regime_state, priced)
        if watch:
            e["watch"] = watch
    catalyst = wl.next_catalyst(calendar.get("upcoming", []))
    if catalyst:
        calendar["next_catalyst"] = catalyst
    for e in calendar.get("recent", []):
        try:
            at = pd.Timestamp(e["reference_month"])
        except Exception:
            continue
        res = wl.resolve_event(e.get("event", ""), d, at, e.get("reactions"))
        if res:
            e["resolution"] = res

    changed = []
    for fname, obj in (("regime", regime), ("dials", dials), ("scenarios", scenarios),
                       ("flows", flows), ("evidence", evidence), ("calendar", calendar)):
        if _write_if_changed(out_dir / f"{fname}.json", obj):
            changed.append(fname)
    print(f"[build] changed: {changed or 'nothing'}")


def _load_prev_cot(out_dir: Path) -> list[dict]:
    p = out_dir / "evidence.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("cot", [])
        except Exception:
            pass
    return []


# ------------------------------------------------------------------ mock build
def build_mock(root: Path) -> None:
    from .mockdata import PEAK_STATE, RECOVERY_STATE
    for target, state in ((root / "mock", PEAK_STATE), (root / "mock" / "alt", RECOVERY_STATE)):
        target.mkdir(parents=True, exist_ok=True)
        for name, obj in state.items():
            _write_if_changed(target / f"{name}.json", json.loads(json.dumps(obj)))
    print("[build] mock + mock/alt written")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--no-cot", action="store_true",
                    help="skip live COT fetch (reuse previous)")
    ap.add_argument("--backtest", nargs=2, metavar=("START", "END"))
    args = ap.parse_args()

    if args.mock:
        build_mock(ROOT)
        return
    if args.backtest:
        d = fetch_all(start="1985-01-01")
        df = eng.backtest(d, args.backtest[0], args.backtest[1])
        out = DATA / "history.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(df.to_json(orient="records"))
        print(df.groupby("needle").size())
        return
    build_live(DATA, do_cot=not args.no_cot)


if __name__ == "__main__":
    main()
