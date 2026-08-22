"""Two complete mock states for frontend development.

mock/      -> PEAK_STATE      (hawkish, inflation rising, gold soft)
mock/alt/  -> RECOVERY_STATE  (dovish, cuts priced, gold running)

Swapping the frontend between these two must re-render everything correctly
with zero code edits — that's the integration test for the design.
"""
import math

from . import config

NOW = "2026-08-14T10:10:00Z"


def _watch(cls, stakes, why, setup, loud, odds=None):
    """A mock `watch` object built from the REAL config branch table.

    Fixtures are composed from config.EVENT_BRANCH_MAPS rather than pasted, so
    labels and asset maps can never drift from what the pipeline ships. `loud`
    names the branch keys tagged "forces repricing" — flipping that set is what
    makes mock/alt a genuine re-render test of the watch card.
    """
    branches = {}
    for key, b in config.EVENT_BRANCH_MAPS[cls].items():
        entry = {"label": b["label"], "implies": b["implies"],
                 "pricing_effect": "forces repricing" if key in loud else "confirms pricing",
                 "assets": dict(b["assets"])}
        if odds and key in odds:
            entry["market_odds"] = odds[key]
        branches[key] = entry
    return {"stakes": stakes, "stakes_why": why, "setup": setup, "branches": branches}


def _overview(mood_label, needle, actual, bullets, next_big, changed=None):
    """Mock Layer-1 payload composed from the REAL config tables.

    Expectations come from config.REGIME_EXPECTATIONS and why-lines from
    config.OVERVIEW_ASSET_WHY, so a mock can never assert a direction the
    pipeline would not. Only `actual` is authored, which is what lets a state
    carry a deliberate agree: false card.
    """
    exp = config.REGIME_EXPECTATIONS[needle]
    family = config.REGIME_FAMILY[needle]
    assets = []
    for asset in config.OVERVIEW_ASSET_ORDER:
        want = config.DIRECTION_WORDS[exp[config.OVERVIEW_ASSET_KEYS[asset]]]
        got = actual[asset]
        assets.append({
            "asset": asset, "expected": want, "actual": got,
            "agree": want == got,
            "why": config.OVERVIEW_ASSET_WHY[(asset, want, family)],
            "lesson": config.ASSET_LESSON[asset],
        })
    out = {"as_of": NOW, "stale": False,
           "mood": {"label": mood_label, "line": config.MOOD_LINES[mood_label]},
           "assets": assets, "bullets": bullets, "next_big_date": next_big}
    if changed:
        out["changed"] = changed
    return out


def _resolution(cls, branch, as_mapped, detail):
    b = config.EVENT_BRANCH_MAPS[cls][branch]
    return {"branch": branch, "branch_label": b["label"], "as_mapped": as_mapped,
            "note": config.WATCHLIST_RESOLUTION_NOTE.format(label=b["label"], detail=detail)}


def _wave(n, lo, hi, phase=0.0, noise=0.03):
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        v = lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * (t * 1.5 + phase)))
        v *= 1 + noise * math.sin(i * 2.7)
        out.append(round(v, 2))
    return out


def _trend(n, start, end, noise=0.02):
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        v = start + (end - start) * t
        v *= 1 + noise * math.sin(i * 1.9)
        out.append(round(v, 2))
    return out


PEAK_STATE = {
    "regime": {
        "as_of": NOW, "stale": False,
        "probabilities": {"expansion": 0.25, "peak": 0.55, "contraction": 0.15, "recovery": 0.05},
        "needle": "peak", "projection": "contraction", "projection_basis": "momentum",
        "in_regime_since": "2026-03-01",
        "narrative": ("Inflation is rising at 2.9% (above the 2% target) while unemployment "
                      "holds near 4.1% with no stress — the market is pricing a hawkish Fed, "
                      "which historically marks the PEAK phase. Watch: yields ▲, dollar ▲, gold ▼."),
        "scores": [
            {"input": "inflation", "value": "PCE 2.9% YoY, +0.40pp/3mo", "vote": "peak", "weight": 0.30,
             "distribution": {"expansion": 0.3, "peak": 0.7, "contraction": 0.0, "recovery": 0.0}},
            {"input": "employment", "value": "UNRATE 4.1%, Sahm gap +0.07pp", "vote": "expansion", "weight": 0.25,
             "distribution": {"expansion": 0.6, "peak": 0.4, "contraction": 0.0, "recovery": 0.0}},
            {"input": "fed_stance", "value": "on hold, priced 27% hike (last move 210d ago)", "vote": "peak", "weight": 0.20,
             "distribution": {"expansion": 0.3, "peak": 0.3, "contraction": 0.2, "recovery": 0.2}},
            {"input": "yield_curve", "value": "10Y−3M +0.78pp, −0.12pp/3mo (flattening)", "vote": "peak", "weight": 0.15,
             "distribution": {"expansion": 0.4, "peak": 0.6, "contraction": 0.0, "recovery": 0.0}},
            {"input": "liquidity", "value": "WALCL −2.1%/6mo (contracting, QT-side)", "vote": "peak", "weight": 0.10,
             "distribution": {"expansion": 0.0, "peak": 0.6, "contraction": 0.4, "recovery": 0.0}},
        ],
    },
    "dials": {
        "as_of": NOW,
        "inflation": {"pce_yoy": 2.9, "cpi_yoy": 3.1, "target": 2.0, "trend_3mo": 0.4,
                      "direction": "rising",
                      "sub": {"ppi_yoy": 2.2, "breakeven_5y": 2.45,
                              "oil": {"last": 96.2, "spark": _trend(30, 78, 96)}}},
        "employment": {"unrate": 4.1, "direction": "stable",
                       "sub": {"nfp": {"actual": 187}, "claims_4wk": 231, "jolts": 7.9}},
        "verdict": {"bias": "hawkish", "lines": [
            {"dial": "inflation", "reading": "Inflation is rising at 2.9% (above the 2% target)",
             "implication": "argues HIKE/HOLD"},
            {"dial": "employment", "reading": "unemployment holds near 4.1% with no stress",
             "implication": "gives the Fed room to be hawkish"},
        ]},
    },
    "scenarios": {
        "as_of": NOW,
        "market_pricing": {"hike": 0.27, "hold": 0.68, "cut": 0.05},
        "pricing_stale": False, "next_fomc": "2026-09-16", "default": "hold",
        "decks": {
            "hike": [
                {"asset": "bonds", "label": "Bond yields", "dir": "up",
                 "why": "New debt must pay more; the short end jumps hardest.", "current_3mo": "+38bp"},
                {"asset": "dollar", "label": "US Dollar", "dir": "up",
                 "why": "Banks park cash where risk-free yield is highest.", "current_3mo": "+2.1%"},
                {"asset": "gold", "label": "Gold", "dir": "down",
                 "why": "Real yields rise — bonds out-compete gold as the inflation hedge.", "current_3mo": "-4.2%"},
                {"asset": "stocks", "label": "Stocks", "dir": "caution",
                 "why": "Can grind higher until something breaks; watch the curve.", "current_3mo": "+1.8%"},
                {"asset": "curve", "label": "Yield curve", "dir": "flatten",
                 "why": "Overnight-rate pressure on the short end — the historic recession precursor.", "current_3mo": "-0.12pp"},
            ],
            "cut": [
                {"asset": "bonds", "label": "Bond yields", "dir": "down",
                 "why": "Cheaper money; existing bonds rally as yields fall.", "current_3mo": "+38bp"},
                {"asset": "dollar", "label": "US Dollar", "dir": "down",
                 "why": "Yield advantage evaporates; capital hunts returns elsewhere.", "current_3mo": "+2.1%"},
                {"asset": "gold", "label": "Gold", "dir": "up",
                 "why": "Real yields fall — gold wins the safe-haven contest.", "current_3mo": "-4.2%"},
                {"asset": "stocks", "label": "Stocks", "dir": "up",
                 "why": "Cheap credit → borrowing → earnings → risk appetite (once the reason for cutting passes).", "current_3mo": "+1.8%"},
                {"asset": "curve", "label": "Yield curve", "dir": "steepen",
                 "why": "Short end drops first; steepening after inversion is the classic recession confirmation.", "current_3mo": "-0.12pp"},
            ],
            "hold": [
                {"asset": "bonds", "label": "Bond yields", "dir": "drift",
                 "why": "Direction inherits from the expectation trend, not the meeting.", "current_3mo": "+38bp"},
                {"asset": "dollar", "label": "US Dollar", "dir": "drift",
                 "why": "Follows the next expected move — watch the two dials.", "current_3mo": "+2.1%"},
                {"asset": "gold", "label": "Gold", "dir": "drift",
                 "why": "Tracks real-yield expectations while the Fed waits.", "current_3mo": "-4.2%"},
                {"asset": "stocks", "label": "Stocks", "dir": "up",
                 "why": "Structural upward skew persists absent a shock.", "current_3mo": "+1.8%"},
                {"asset": "curve", "label": "Yield curve", "dir": "drift",
                 "why": "Shape set by which move markets price next.", "current_3mo": "-0.12pp"},
            ],
        },
    },
    "flows": {
        "as_of": NOW, "regime": "peak",
        "nodes": [
            {"asset": "bonds", "price": 4.52, "trend_3mo": 38, "trend_unit": "bp",
             "spark": _trend(120, 4.14, 4.52), "stale": False,
             "driver": "The market everything else keys off. Driver: Fed expectations."},
            {"asset": "dollar", "price": 121.4, "trend_3mo": 2.1, "trend_unit": "%",
             "spark": _trend(120, 118.9, 121.4), "stale": False,
             "driver": "Driver: bond yield differentials vs other currencies. ~90% of forex is this."},
            {"asset": "gold", "price": 3892.4, "trend_3mo": -4.2, "trend_unit": "%",
             "spark": _trend(120, 4063, 3892), "stale": False,
             "driver": "Driver: REAL yields (yield − inflation). Bonds are its competitor, not war headlines."},
            {"asset": "stocks", "price": 6852.3, "trend_3mo": 1.8, "trend_unit": "%",
             "spark": _wave(120, 6600, 6900, 0.2), "stale": False,
             "driver": "Driver: risk appetite + liquidity. Printed money tends to end up here."},
        ],
        "edges": [
            {"from": "gold", "to": "dollar", "strength": 0.7},
            {"from": "gold", "to": "bonds", "strength": 0.5},
            {"from": "stocks", "to": "dollar", "strength": 0.3},
        ],
    },
    "evidence": {
        "as_of": NOW,
        "curve": {
            "today": [{"m": "3M", "y": 3.74}, {"m": "2Y", "y": 3.98}, {"m": "5Y", "y": 4.21},
                      {"m": "10Y", "y": 4.52}, {"m": "30Y", "y": 4.97}],
            "6mo_ago": [{"m": "3M", "y": 3.71}, {"m": "2Y", "y": 3.85}, {"m": "5Y", "y": 4.05},
                        {"m": "10Y", "y": 4.31}, {"m": "30Y", "y": 4.80}],
            "1yr_ago": [{"m": "3M", "y": 4.35}, {"m": "2Y", "y": 4.10}, {"m": "5Y", "y": 4.02},
                        {"m": "10Y", "y": 4.18}, {"m": "30Y", "y": 4.55}],
            "spread_10y3m": {"series": _wave(260, -0.8, 1.2, 0.6),
                             "recessions": [["2020-02-01", "2020-04-01"]],
                             "status": "flattening",
                             "caveat": "~12 historical episodes; lag ranges months to ~2 years. Warning light, not a timer."}},
        "real_yields_gold": {
            "real_5y": _trend(260, 1.1, 1.9), "gold": _wave(260, 2600, 4100, 0.75),
            "corr_12mo": -0.71,
            "confirm": {"expected": "gold down", "actual": "-4.2%/3mo", "status": "confirmed"}},
        "cot": [
            {"market": "gold", "net": _wave(104, 120000, 260000, 0.7, 0.05),
             "dates": [], "current": 168400, "pctile_3yr": 42, "wow_delta": -12403,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "dxy", "net": _wave(104, -8000, 22000, 0.3, 0.05),
             "dates": [], "current": 18200, "pctile_3yr": 87, "wow_delta": 2140,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "spx", "net": _wave(104, -120000, 60000, 0.5, 0.05),
             "dates": [], "current": -31000, "pctile_3yr": 38, "wow_delta": -8800,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "tnote10", "net": _wave(104, -450000, -120000, 0.4, 0.05),
             "dates": [], "current": -287000, "pctile_3yr": 55, "wow_delta": 15600,
             "tuesday": "2026-08-11", "stale": False},
        ],
        "cot_caveat": "Published Friday for Tuesday positions — context, not a trigger.",
        "scorecard": {"rows": [
            {"says": "Yields up", "doing": "10Y +38bp / 3mo", "status": "confirmed"},
            {"says": "Dollar up", "doing": "DXY +2.1% / 3mo", "status": "confirmed"},
            {"says": "Gold down", "doing": "Gold -4.2% / 3mo", "status": "confirmed"},
            {"says": "Stocks flat", "doing": "SPX +1.8% / 3mo", "status": "confirmed"},
            {"says": "Smart money (gold COT) down", "doing": "net reducing w/w", "status": "confirmed"},
        ], "confirmed": 5, "total": 5},
    },
    "overview": _overview(
        "CAUTIOUS", "peak",
        # stocks disagree on purpose: the regime expects a stall, they are rising
        actual={"stocks": "up", "gold": "down", "dollar": "up", "bonds": "up"},
        bullets=["Prices: rising about 4.4% a year. The Fed wants 2%.",
                 "Jobs: hiring is steady at about +180K a month.",
                 "Next big date: Inflation report on Aug 20."],
        next_big={"date": "2026-08-20", "event": "Inflation report", "lesson": 5},
        changed={"recent": True,
                 "line": "The prices picture cooled this month. The mood is now cautious."}),
    "calendar": {
        "as_of": NOW,
        "next_catalyst": {"date": "2026-08-20", "event": "CPI"},
        "upcoming": [
            {"date": "2026-08-20", "event": "CPI", "feeds": "inflation",
             "hint": "Hot print → strengthens hike case → dollar ▲ gold ▼",
             "watch": _watch(
                 "inflation", "high",
                 "A plausible 0.2pp move flips the inflation voter from peak to "
                 "contraction — the heaviest single input to the needle can change here.",
                 "CPI runs 4.4% YoY against the 2.0% target and is rising at +0.310pp/3mo, "
                 "with the Fed priced 68% to hike / 32% to hold — this print decides "
                 "whether the hawkish case holds.",
                 loud={"b"})},
            {"date": "2026-08-21", "event": "Jobless Claims", "feeds": "employment",
             "hint": "Weak print → strengthens cut case → gold ▲ dollar ▼",
             "watch": _watch(
                 "employment", "low",
                 "Neither branch can move a voter off its current read.",
                 "Unemployment holds at 3.8% with a Sahm gap of +0.10pp, with the Fed "
                 "priced 68% to hike / 32% to hold — this print decides whether the "
                 "hawkish case keeps its room.",
                 loud={"b"})},
            {"date": "2026-08-28", "event": "PCE (Personal Income & Outlays)", "feeds": "inflation",
             "hint": "Hot print → strengthens hike case → dollar ▲ gold ▼",
             "watch": _watch(
                 "inflation", "medium",
                 "The inflation voter currently reads peak while the needle sits at peak "
                 "— this print feeds the contested dial without being able to flip it.",
                 "PCE runs 4.1% YoY against the 2.0% target and is rising at +0.280pp/3mo, "
                 "with the Fed priced 68% to hike / 32% to hold — this print decides "
                 "whether the hawkish case holds.",
                 loud={"b"})},
            {"date": "2026-09-04", "event": "Employment Situation (NFP)", "feeds": "employment",
             "hint": "Weak print → strengthens cut case → gold ▲ dollar ▼",
             "watch": _watch(
                 "employment", "high",
                 "A plausible 100K move flips the employment voter from peak to "
                 "contraction — the heaviest single input to the needle can change here.",
                 "Unemployment holds at 3.8% with a Sahm gap of +0.10pp, with the Fed "
                 "priced 68% to hike / 32% to hold — this print decides whether the "
                 "hawkish case keeps its room.",
                 loud={"b"})},
            {"date": "2026-09-16", "event": "FOMC", "feeds": "both",
             "hint": "The decision itself — expectations already moved the money",
             "highlight": True,
             "watch": _watch(
                 "fomc", "high",
                 "The decision itself — the one scheduled event that can move the policy "
                 "rate, and the whole curve prices off it.",
                 "The decision itself, with the Fed priced 68% to hike / 32% to hold, "
                 "with the regime needle at peak — expectations have already moved the money.",
                 loud={"cut"}, odds={"hike": 0.68, "hold": 0.32, "cut": 0.0})},
        ],
        "recent": [
            {"reference_month": "2026-07-01", "event": "CPI",
             "reactions": {"dxy_48h": 0.4, "gold_48h": -0.8, "spx_48h": -0.3},
             "resolution": _resolution("inflation", "a", True,
                                       "dollar ▲, gold ▼ as mapped")},
            {"reference_month": "2026-07-01", "event": "Employment Situation (NFP)",
             "reactions": {"dxy_48h": -0.2, "gold_48h": 0.5, "spx_48h": 0.6},
             "resolution": _resolution("employment", "b", True,
                                       "dollar ▼, gold ▲ as mapped")},
        ],
    },
}


# ---------- opposite state: dovish RECOVERY -------------------------------
RECOVERY_STATE = {
    "regime": {
        "as_of": NOW, "stale": False,
        "probabilities": {"expansion": 0.18, "peak": 0.05, "contraction": 0.17, "recovery": 0.60},
        "needle": "recovery", "projection": "expansion", "projection_basis": "momentum",
        "in_regime_since": "2026-05-01",
        "narrative": ("Inflation is falling at 1.6% (below the 2% target) while unemployment "
                      "is creeping up from its lows (4.7%) — the market is pricing a dovish Fed, "
                      "which historically marks the RECOVERY phase. Watch: gold ▲, stocks bottoming, dollar ▼."),
        "scores": [
            {"input": "inflation", "value": "PCE 1.6% YoY, −0.35pp/3mo", "vote": "contraction", "weight": 0.30,
             "distribution": {"expansion": 0.0, "peak": 0.0, "contraction": 0.5, "recovery": 0.5}},
            {"input": "employment", "value": "UNRATE 4.7%, Sahm gap +0.43pp", "vote": "peak", "weight": 0.25,
             "distribution": {"expansion": 0.0, "peak": 0.5, "contraction": 0.5, "recovery": 0.0}},
            {"input": "fed_stance", "value": "cutting / priced to cut", "vote": "recovery", "weight": 0.20,
             "distribution": {"expansion": 0.0, "peak": 0.0, "contraction": 0.4, "recovery": 0.6}},
            {"input": "yield_curve", "value": "10Y−3M +0.95pp, +0.44pp/3mo (steepening post-inversion)", "vote": "contraction", "weight": 0.15,
             "distribution": {"expansion": 0.0, "peak": 0.0, "contraction": 0.8, "recovery": 0.2}},
            {"input": "liquidity", "value": "WALCL +3.4%/6mo (expanding, QE-side)", "vote": "recovery", "weight": 0.10,
             "distribution": {"expansion": 0.5, "peak": 0.0, "contraction": 0.0, "recovery": 0.5}},
        ],
    },
    "dials": {
        "as_of": NOW,
        "inflation": {"pce_yoy": 1.6, "cpi_yoy": 1.9, "target": 2.0, "trend_3mo": -0.35,
                      "direction": "falling",
                      "sub": {"ppi_yoy": 0.8, "breakeven_5y": 1.95,
                              "oil": {"last": 61.4, "spark": _trend(30, 84, 61)}}},
        "employment": {"unrate": 4.7, "direction": "softening",
                       "sub": {"nfp": {"actual": 42}, "claims_4wk": 268, "jolts": 6.8}},
        "verdict": {"bias": "dovish", "lines": [
            {"dial": "inflation", "reading": "Inflation is falling at 1.6% (below the 2% target)",
             "implication": "argues CUT/HOLD"},
            {"dial": "employment", "reading": "unemployment is creeping up from its lows (4.7%)",
             "implication": "forces the Fed dovish"},
        ]},
    },
    "scenarios": {
        "as_of": NOW,
        "market_pricing": {"hike": 0.02, "hold": 0.24, "cut": 0.74},
        "pricing_stale": False, "next_fomc": "2026-09-16", "default": "cut",
        "decks": PEAK_STATE["scenarios"]["decks"],  # same framework constants
    },
    "flows": {
        "as_of": NOW, "regime": "recovery",
        "nodes": [
            {"asset": "bonds", "price": 3.61, "trend_3mo": -47, "trend_unit": "bp",
             "spark": _trend(120, 4.08, 3.61), "stale": False,
             "driver": "The market everything else keys off. Driver: Fed expectations."},
            {"asset": "dollar", "price": 114.2, "trend_3mo": -3.2, "trend_unit": "%",
             "spark": _trend(120, 118.0, 114.2), "stale": False,
             "driver": "Driver: bond yield differentials vs other currencies. ~90% of forex is this."},
            {"asset": "gold", "price": 4480.0, "trend_3mo": 9.6, "trend_unit": "%",
             "spark": _trend(120, 4087, 4480), "stale": False,
             "driver": "Driver: REAL yields (yield − inflation). Bonds are its competitor, not war headlines."},
            {"asset": "stocks", "price": 6120.5, "trend_3mo": 4.1, "trend_unit": "%",
             "spark": _wave(120, 5700, 6150, 0.85), "stale": False,
             "driver": "Driver: risk appetite + liquidity. Printed money tends to end up here."},
        ],
        "edges": [
            {"from": "dollar", "to": "gold", "strength": 0.8},
            {"from": "bonds", "to": "stocks", "strength": 0.7},
            {"from": "dollar", "to": "stocks", "strength": 0.5},
        ],
    },
    "evidence": {
        "as_of": NOW,
        "curve": {
            "today": [{"m": "3M", "y": 2.60}, {"m": "2Y", "y": 2.95}, {"m": "5Y", "y": 3.25},
                      {"m": "10Y", "y": 3.61}, {"m": "30Y", "y": 4.12}],
            "6mo_ago": [{"m": "3M", "y": 3.70}, {"m": "2Y", "y": 3.55}, {"m": "5Y", "y": 3.60},
                        {"m": "10Y", "y": 3.82}, {"m": "30Y", "y": 4.25}],
            "1yr_ago": [{"m": "3M", "y": 4.40}, {"m": "2Y", "y": 4.05}, {"m": "5Y", "y": 3.95},
                        {"m": "10Y", "y": 4.05}, {"m": "30Y", "y": 4.40}],
            "spread_10y3m": {"series": _wave(260, -1.0, 1.0, 0.25),
                             "recessions": [["2020-02-01", "2020-04-01"], ["2026-01-01", "2026-04-01"]],
                             "status": "steepening_post_inversion",
                             "caveat": "~12 historical episodes; lag ranges months to ~2 years. Warning light, not a timer."}},
        "real_yields_gold": {
            "real_5y": _trend(260, 2.0, 0.7), "gold": _trend(260, 3400, 4480),
            "corr_12mo": -0.83,
            "confirm": {"expected": "gold up", "actual": "+9.6%/3mo", "status": "confirmed"}},
        "cot": [
            {"market": "gold", "net": _trend(104, 130000, 310000, 0.04),
             "dates": [], "current": 306500, "pctile_3yr": 96, "wow_delta": 18200,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "dxy", "net": _trend(104, 21000, -14000, 0.04),
             "dates": [], "current": -13400, "pctile_3yr": 6, "wow_delta": -3100,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "spx", "net": _trend(104, -140000, 45000, 0.04),
             "dates": [], "current": 41800, "pctile_3yr": 78, "wow_delta": 9400,
             "tuesday": "2026-08-11", "stale": False},
            {"market": "tnote10", "net": _trend(104, -420000, -90000, 0.04),
             "dates": [], "current": -96000, "pctile_3yr": 91, "wow_delta": 22800,
             "tuesday": "2026-08-11", "stale": False},
        ],
        "cot_caveat": "Published Friday for Tuesday positions — context, not a trigger.",
        "scorecard": {"rows": [
            {"says": "Yields down", "doing": "10Y -47bp / 3mo", "status": "confirmed"},
            {"says": "Dollar down", "doing": "DXY -3.2% / 3mo", "status": "confirmed"},
            {"says": "Gold up", "doing": "Gold +9.6% / 3mo", "status": "confirmed"},
            {"says": "Stocks up", "doing": "SPX +4.1% / 3mo", "status": "confirmed"},
            {"says": "Smart money (gold COT) up", "doing": "net adding w/w", "status": "confirmed"},
        ], "confirmed": 5, "total": 5},
    },
    "overview": _overview(
        "CLEARING", "recovery",
        actual={"stocks": "up", "gold": "up", "dollar": "down", "bonds": "down"},
        bullets=["Prices: steady at about 1.6% a year. The Fed wants 2%.",
                 "Jobs: companies are cutting about 40K jobs a month.",
                 "Next big date: Jobs report on Sep 4."],
        next_big={"date": "2026-09-04", "event": "Jobs report", "lesson": 13},
        changed={"recent": True,
                 "line": "The Fed picture warmed this month. The mood is now clearing."}),
    # Deliberately NOT a reference to PEAK_STATE["calendar"]: with cuts priced
    # the loud branch flips to the hot/strong side, and one event resolves
    # AGAINST its map. Swapping mock/ -> mock/alt/ must re-render both.
    "calendar": {
        "as_of": NOW,
        "next_catalyst": {"date": "2026-09-04", "event": "Employment Situation (NFP)"},
        "upcoming": [
            {"date": "2026-08-20", "event": "CPI", "feeds": "inflation",
             "hint": "Hot print → strengthens hike case → dollar ▲ gold ▼",
             "watch": _watch(
                 "inflation", "medium",
                 "The inflation voter currently reads recovery while the needle sits at "
                 "recovery — this print feeds the contested dial without being able to flip it.",
                 "CPI runs 1.6% YoY against the 2.0% target and is falling at -0.220pp/3mo, "
                 "with the Fed priced 4% to hike / 26% to hold — this print decides "
                 "whether the dovish case holds.",
                 loud={"a"})},
            {"date": "2026-08-21", "event": "Jobless Claims", "feeds": "employment",
             "hint": "Weak print → strengthens cut case → gold ▲ dollar ▼",
             "watch": _watch(
                 "employment", "low",
                 "Neither branch can move a voter off its current read.",
                 "Unemployment holds at 5.4% with a Sahm gap of +0.45pp, with the Fed "
                 "priced 4% to hike / 26% to hold — this print decides whether the "
                 "dovish case keeps its room.",
                 loud={"a"})},
            {"date": "2026-08-28", "event": "PCE (Personal Income & Outlays)", "feeds": "inflation",
             "hint": "Hot print → strengthens hike case → dollar ▲ gold ▼",
             "watch": _watch(
                 "inflation", "low",
                 "Neither branch can move a voter off its current read.",
                 "PCE runs 1.7% YoY against the 2.0% target and is falling at -0.190pp/3mo, "
                 "with the Fed priced 4% to hike / 26% to hold — this print decides "
                 "whether the dovish case holds.",
                 loud={"a"})},
            {"date": "2026-09-04", "event": "Employment Situation (NFP)", "feeds": "employment",
             "hint": "Weak print → strengthens cut case → gold ▲ dollar ▼",
             "watch": _watch(
                 "employment", "high",
                 "A plausible 100K move flips the employment voter from contraction to "
                 "recovery — the heaviest single input to the needle can change here.",
                 "Unemployment holds at 5.4% with a Sahm gap of +0.45pp, with the Fed "
                 "priced 4% to hike / 26% to hold — this print decides whether the "
                 "dovish case keeps its room.",
                 loud={"a"})},
            {"date": "2026-09-16", "event": "FOMC", "feeds": "both",
             "hint": "The decision itself — expectations already moved the money",
             "highlight": True,
             "watch": _watch(
                 "fomc", "high",
                 "The decision itself — the one scheduled event that can move the policy "
                 "rate, and the whole curve prices off it.",
                 "The decision itself, with the Fed priced 4% to hike / 26% to hold, "
                 "with the regime needle at recovery — expectations have already moved the money.",
                 loud={"hike"}, odds={"hike": 0.04, "hold": 0.26, "cut": 0.70})},
        ],
        "recent": [
            {"reference_month": "2026-07-01", "event": "CPI",
             "reactions": {"dxy_48h": -0.5, "gold_48h": 1.2, "spx_48h": 0.9},
             "resolution": _resolution("inflation", "b", True,
                                       "dollar ▼, gold ▲, stocks ▲ as mapped")},
            {"reference_month": "2026-07-01", "event": "Employment Situation (NFP)",
             "reactions": {"dxy_48h": 0.3, "gold_48h": -0.4, "spx_48h": 0.2},
             "resolution": _resolution("employment", "b", False,
                                       "0 of 2 asset moves matched")},
        ],
    },
}
