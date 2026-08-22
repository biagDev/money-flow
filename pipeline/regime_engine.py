"""Regime engine: five transparent voters -> regime probabilities.

Every voter takes the data dict (pandas Series) and an `asof` timestamp,
slices history up to asof, and returns:
    (vote: {regime: weight summing to 1}, evidence: str)
This makes historical replay (projection momentum + backtest) free.
"""
from __future__ import annotations

import pandas as pd

from . import config
from .fetch_fred import yoy, diff_days, last

T = config.THRESHOLDS
R = config.REGIMES


def _cut(s: pd.Series | None, asof: pd.Timestamp) -> pd.Series | None:
    if s is None:
        return None
    s = s.dropna()
    s = s[s.index <= asof]
    return s if len(s) else None


def _norm(v: dict) -> dict:
    tot = sum(v.values()) or 1.0
    return {k: round(v.get(k, 0.0) / tot, 4) for k in R}


# ---- voters --------------------------------------------------------------
def vote_inflation(d, asof):
    pce = _cut(d.get("pce"), asof)
    if pce is None or len(pce) < 15:
        return _norm({r: 0.25 for r in R}), "no data"
    y = yoy(pce).dropna()
    level = float(y.iloc[-1])
    mom = diff_days(y, 92) or 0.0
    rising = mom > T["inflation_momentum"]
    falling = mom < -T["inflation_momentum"]
    above = level > T["inflation_target"]
    hot = level > T["inflation_hot"]
    if above and rising:
        # decisively hot AND accelerating is a late-cycle signature, not growth:
        # withhold the expansion share that a merely-above-target print gets.
        v = {"peak": 0.85, "expansion": 0.15} if hot else {"peak": 0.7, "expansion": 0.3}
    elif above and falling:
        v = {"peak": 0.4, "contraction": 0.4, "recovery": 0.2}
    elif above:  # above, flat
        v = {"peak": 0.55, "expansion": 0.45}
    elif falling:  # below target, falling
        v = {"contraction": 0.5, "recovery": 0.5}
    elif rising:   # below target, rising
        v = {"recovery": 0.5, "expansion": 0.5}
    else:
        v = {"expansion": 0.6, "recovery": 0.4}
    ev = f"PCE {level:.1f}% YoY, {mom:+.2f}pp/3mo"
    return _norm(v), ev


def vote_employment(d, asof):
    u = _cut(d.get("unrate"), asof)
    if u is None or len(u) < 15:
        return _norm({r: 0.25 for r in R}), "no data"
    avg3 = float(u.iloc[-3:].mean())
    low12 = float(u.iloc[-12:].min())
    sahm = avg3 - low12
    if sahm >= T["sahm_trigger"]:
        v = {"contraction": 0.8, "recovery": 0.2}
    elif sahm >= T["sahm_warning"]:
        v = {"peak": 0.5, "contraction": 0.5}
    else:
        v = {"expansion": 0.6, "peak": 0.4}
    ev = f"UNRATE {float(u.iloc[-1]):.1f}%, Sahm gap {sahm:+.2f}pp"
    return _norm(v), ev


def vote_fed_stance(d, asof, priced: dict | None = None):
    """Direction of policy: last two target changes + (optionally) market pricing."""
    t = _cut(d.get("fed_target_upper"), asof)
    if t is None or len(t) < 40:
        # DFEDTARU only begins Dec 2008 (before that the Fed set a single
        # target, not a range). Without this the voter is blind for all
        # pre-2009 history and sprays a flat 0.25 across every regime.
        t = _cut(d.get("fed_funds"), asof)
        if t is not None:
            t = t.round(2)
    if t is None or len(t) < 40:
        return _norm({r: 0.25 for r in R}), "no data"
    changes = t[t.diff().fillna(0) != 0].diff().dropna()
    if not len(changes):
        return _norm({"expansion": 0.3, "peak": 0.3,
                      "contraction": 0.2, "recovery": 0.2}), "on hold"
    days_since = (asof - changes.index[-1]).days
    # a long-past move no longer implies a direction — without this a cut can
    # still vote "recovery" years later (687 days stale in Feb 2022).
    stale = days_since > T["fed_move_stale_days"]
    lastc = changes.iloc[-2:] if len(changes) >= 2 else changes
    hiking = (not stale) and len(lastc) > 0 and (lastc > 0).all()
    cutting = (not stale) and len(lastc) > 0 and (lastc < 0).all()
    # market pricing tilts a hold (and is never stale — it is forward-looking)
    p = priced or {}
    if hiking or p.get("hike", 0) > 0.5:
        v = {"peak": 0.7, "expansion": 0.3}
        ev = "hiking / priced to hike"
    elif cutting or p.get("cut", 0) > 0.5:
        # cutting into stress vs cutting into recovery — split by Sahm
        u = _cut(d.get("unrate"), asof)
        stressed = False
        if u is not None and len(u) >= 12:
            stressed = (float(u.iloc[-3:].mean()) - float(u.iloc[-12:].min())) >= T["sahm_warning"]
        v = {"contraction": 0.6, "recovery": 0.4} if stressed else {"recovery": 0.6, "expansion": 0.4}
        ev = "cutting / priced to cut"
    else:
        v = {"expansion": 0.3, "peak": 0.3, "contraction": 0.2, "recovery": 0.2}
        ev = "on hold (last move stale)" if stale else "on hold"
    ev += f" (last move {days_since}d ago)"
    return _norm(v), ev


def vote_yield_curve(d, asof):
    sp = _cut(d.get("spread_10y3m"), asof)
    if sp is None or len(sp) < 70:
        return _norm({r: 0.25 for r in R}), "no data"
    level = float(sp.iloc[-1])
    slope3 = diff_days(sp, 92) or 0.0
    inverted_recently = float(sp.iloc[-260:].min()) < 0 if len(sp) >= 260 else level < 0
    if level < 0:
        v = {"peak": 0.7, "contraction": 0.3}
        state = "inverted"
    elif inverted_recently and slope3 > T["curve_steepen_3mo"]:
        v = {"contraction": 0.8, "recovery": 0.2}
        state = "steepening post-inversion"
    elif level < T["curve_flat"]:
        v = {"expansion": 0.4, "peak": 0.6}
        state = "flattening"
    else:
        v = {"expansion": 0.7, "recovery": 0.3}
        state = "normal"
    return _norm(v), f"10Y−3M {level:+.2f}pp, {slope3:+.2f}pp/3mo ({state})"


def vote_liquidity(d, asof):
    w = _cut(d.get("walcl"), asof)
    if w is None or len(w) < 30:
        return _norm({r: 0.25 for r in R}), "no data"
    chg6 = ((float(w.iloc[-1]) / float(w[w.index <= asof - pd.Timedelta(days=182)].iloc[-1])) - 1) * 100 \
        if len(w[w.index <= asof - pd.Timedelta(days=182)]) else 0.0
    if chg6 > T["walcl_6mo_pct"]:
        v = {"recovery": 0.5, "expansion": 0.5}
        state = "expanding (QE-side)"
    else:
        v = {"peak": 0.6, "contraction": 0.4}
        state = "contracting (QT-side)"
    return _norm(v), f"WALCL {chg6:+.1f}%/6mo ({state})"


VOTERS = {
    "inflation": vote_inflation,
    "employment": vote_employment,
    "fed_stance": vote_fed_stance,
    "yield_curve": vote_yield_curve,
    "liquidity": vote_liquidity,
}


# ---- engine --------------------------------------------------------------
def compute(d: dict, asof: pd.Timestamp | None = None,
            priced: dict | None = None) -> dict:
    asof = asof or pd.Timestamp.utcnow().tz_localize(None)
    probs = {r: 0.0 for r in R}
    scores = []
    for name, fn in VOTERS.items():
        vote, ev = fn(d, asof, priced) if name == "fed_stance" else fn(d, asof)
        w = config.WEIGHTS[name]
        for r in R:
            probs[r] += w * vote[r]
        scores.append({
            "input": name, "value": ev,
            "vote": max(vote, key=vote.get), "weight": w,
            "distribution": vote,
        })
    tot = sum(probs.values()) or 1.0
    probs = {r: round(p / tot, 4) for r, p in probs.items()}
    needle = max(probs, key=probs.get)
    return {"probabilities": probs, "needle": needle, "scores": scores}


def projection(d: dict, current: dict, priced: dict | None = None) -> str:
    """Regime whose probability momentum is strongest over the lag window."""
    now = pd.Timestamp.utcnow().tz_localize(None)
    lags = config.THRESHOLDS["projection_lags_months"]
    oldest = compute(d, now - pd.DateOffset(months=max(lags)), priced)
    momentum = {r: current["probabilities"][r] - oldest["probabilities"][r] for r in R}
    # exclude the current needle; project toward the fastest-growing alternative
    alt = {r: m for r, m in momentum.items() if r != current["needle"]}
    best = max(alt, key=alt.get)
    return best if alt[best] > 0.02 else current["needle"]


def in_regime_since(d: dict, current_needle: str, priced: dict | None = None,
                    max_back_months: int = 60) -> str:
    now = pd.Timestamp.utcnow().tz_localize(None)
    since = now
    for m in range(1, max_back_months + 1):
        t = now - pd.DateOffset(months=m)
        if compute(d, t, priced)["needle"] != current_needle:
            break
        since = t
    return str(since.date().replace(day=1))


def backtest(d: dict, start: str, end: str) -> pd.DataFrame:
    """Monthly regime series for validation / the time-machine feature."""
    dates = pd.date_range(start, end, freq="MS")
    rows = []
    for t in dates:
        r = compute(d, t)
        rows.append({"date": str(t.date()), "needle": r["needle"], **r["probabilities"]})
    return pd.DataFrame(rows)
