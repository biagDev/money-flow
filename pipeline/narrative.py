"""Narrative generator, verdict logic, scorecard, calendar. Deterministic."""
from __future__ import annotations

import pandas as pd

from . import config
from .fetch_fred import yoy, diff_days, pct_change_days, last

WATCH = {
    "expansion":  "stocks ▲, gold ▲, dollar ▼",
    "peak":       "yields ▲, dollar ▲, gold ▼",
    "contraction":"bonds ▲ (yields ▼), stocks ▼, dollar ▲ short-term",
    "recovery":   "gold ▲, stocks bottoming, dollar ▼",
}
REGIME_TITLE = {"expansion": "EXPANSION", "peak": "PEAK",
                "contraction": "CONTRACTION", "recovery": "RECOVERY"}


def _infl_desc(pce_yoy_val: float | None, mom: float | None) -> str:
    if pce_yoy_val is None:
        return "Inflation data unavailable"
    mo = config.THRESHOLDS["inflation_momentum"]
    dir_ = "rising" if (mom or 0) > mo else "falling" if (mom or 0) < -mo else "holding"
    rel = "above" if pce_yoy_val > config.THRESHOLDS["inflation_target"] else "below"
    return f"Inflation is {dir_} at {pce_yoy_val:.1f}% ({rel} the 2% target)"


def _emp_desc(unrate_val: float | None, sahm: float | None,
              payroll: tuple[str, float] | None = None) -> str:
    if unrate_val is None:
        return "employment data unavailable"
    if (sahm or 0) >= config.THRESHOLDS["sahm_trigger"]:
        return f"unemployment is breaking higher at {unrate_val:.1f}%"
    if (sahm or 0) >= config.THRESHOLDS["sahm_warning"]:
        return f"unemployment is creeping up from its lows ({unrate_val:.1f}%)"
    # The Sahm gap lags payrolls. Saying "no stress" while the employment voter
    # has already moved on softening payrolls would contradict the scorecard.
    if payroll and payroll[0] in config.EMPLOYMENT_PAYROLL_DESC:
        return config.EMPLOYMENT_PAYROLL_DESC[payroll[0]].format(
            unrate=unrate_val, p3=payroll[1])
    return f"unemployment holds near {unrate_val:.1f}% with no stress"


def fed_bias(infl_above: bool, infl_rising: bool, sahm: float) -> str:
    if sahm >= config.THRESHOLDS["sahm_trigger"]:
        return "dovish"
    if infl_above and infl_rising:
        return "hawkish"
    if infl_above:
        return "hawkish-leaning"
    if sahm >= config.THRESHOLDS["sahm_warning"]:
        return "dovish-leaning"
    return "neutral"


def narrative(regime: str, infl: str, emp: str, bias: str) -> str:
    return (f"{infl} while {emp} — the market is pricing a {bias} Fed, "
            f"which historically marks the {REGIME_TITLE[regime]} phase. "
            f"Watch: {WATCH[regime]}.")


# ---- scorecard ------------------------------------------------------------
def _dir_of(value: float | None, flat_band: float) -> str:
    if value is None:
        return "na"
    if abs(value) < flat_band:
        return "flat"
    return "up" if value > 0 else "down"


def asset_moves(d: dict) -> dict:
    """The 3-month moves for the four assets.

    SINGLE SOURCE OF TRUTH. The Evidence scorecard and the Layer-1 overview
    both read this. Computing them twice with different windows or bands is
    how Layer 1 would start contradicting the scorecard, so it must not be
    reimplemented anywhere.
    """
    y10 = d.get("y10")
    return {
        "y10_bp": (diff_days(y10, 92) or 0) * 100 if y10 is not None else None,
        "dxy": pct_change_days(d.get("dxy_proxy"), 92) if d.get("dxy_proxy") is not None else None,
        "gold": pct_change_days(d.get("gold"), 92) if d.get("gold") is not None else None,
        "spx": pct_change_days(d.get("spx"), 92) if d.get("spx") is not None else None,
    }


def move_direction(key: str, value: float | None) -> str:
    """up | down | flat, using the scorecard's own flat bands."""
    return _dir_of(value, config.SCORECARD_FLAT_BAND.get(key, 0.0))


def scorecard(regime: str, d: dict, cot: list[dict]) -> dict:
    exp = config.REGIME_EXPECTATIONS[regime]
    band = config.SCORECARD_FLAT_BAND
    moves = asset_moves(d)
    gold_cot = next((c for c in cot if c["market"] == "gold"), None)
    moves["cot_gold"] = float(gold_cot["wow_delta"]) if gold_cot else None

    labels = {"y10_bp": "Yields", "dxy": "Dollar", "gold": "Gold",
              "spx": "Stocks", "cot_gold": "Smart money (gold COT)"}
    fmt = {"y10_bp": lambda v: f"10Y {v:+.0f}bp / 3mo",
           "dxy":    lambda v: f"DXY {v:+.1f}% / 3mo",
           "gold":   lambda v: f"Gold {v:+.1f}% / 3mo",
           "spx":    lambda v: f"SPX {v:+.1f}% / 3mo",
           "cot_gold": lambda v: f"net {'adding' if v > 0 else 'reducing'} w/w"}
    rows, confirmed, total = [], 0, 0
    for k, want in exp.items():
        v = moves.get(k)
        got = _dir_of(v, band.get(k, 0.0)) if k != "cot_gold" else \
            ("up" if (v or 0) > 0 else "down" if (v or 0) < 0 else "flat")
        if v is None:
            status = "na"
        elif want == "flat":
            status = "confirmed" if got in ("flat", "up") else "diverging"
        else:
            status = "confirmed" if got == want else ("neutral" if got == "flat" else "diverging")
        if status != "na":
            total += 1
            confirmed += status == "confirmed"
        rows.append({"says": f"{labels[k]} {want}",
                     "doing": fmt[k](v) if v is not None else "no data",
                     "status": status})
    return {"rows": rows, "confirmed": confirmed, "total": total}


# ---- calendar ---------------------------------------------------------------
def build_calendar(release_dates: dict[str, list[str]],
                   fomc_dates: list[str], d: dict) -> dict:
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    upcoming = []
    for name, dates in release_dates.items():
        feeds = config.RELEASE_FEEDS.get(name, "both")
        for dt in dates:
            upcoming.append({"date": dt, "event": name, "feeds": feeds,
                             "hint": config.RELEASE_HINTS[feeds]})
    for f in fomc_dates:
        fd = pd.Timestamp(f)
        if today <= fd <= today + pd.Timedelta(days=config.CALENDAR_LOOKAHEAD_DAYS):
            upcoming.append({"date": f, "event": "FOMC", "feeds": "both",
                             "hint": "The decision itself — expectations already moved the money",
                             "highlight": True})
    upcoming.sort(key=lambda x: x["date"])

    recent = []
    for name, series_key in (("CPI", "cpi"), ("Employment Situation (NFP)", "payems"),
                             ("PCE (Personal Income & Outlays)", "pce")):
        s = d.get(series_key)
        if s is None or len(s) < 2:
            continue
        obs_date = s.dropna().index[-1]
        if (today - obs_date).days > config.CALENDAR_LOOKBACK_DAYS + 45:
            continue
        recent.append({"reference_month": str(obs_date.date()), "event": name,
                       "reactions": _reactions(d, obs_date)})
    return {"upcoming": upcoming, "recent": recent}


def _reactions(d: dict, around: pd.Timestamp) -> dict:
    out = {}
    for k, key in (("dxy_48h", "dxy_proxy"), ("gold_48h", "gold"), ("spx_48h", "spx")):
        s = d.get(key)
        if s is None:
            continue
        s = s.dropna()
        before = s[s.index <= around]
        after = s[s.index >= around + pd.Timedelta(days=2)]
        if len(before) and len(after):
            out[k] = round((float(after.iloc[0]) / float(before.iloc[-1]) - 1) * 100, 2)
    return out
