"""Event watchlist: turns the release schedule into a forward-looking view.

Every upcoming release carries what is at stake given the current regime, the
two branches the print can take, what each branch implies for the four assets,
and which branch would actually force a repricing. After the print lands, the
event resolves against the reactions the pipeline already measures.

Deterministic end to end — templates plus rules over state the pipeline already
computes. No external calls, no LLM, no manual entry. Every branch label, asset
direction, threshold and sentence template lives in config.py; this module only
composes them, and every step degrades to None rather than guessing.
"""
from __future__ import annotations

import pandas as pd

from . import config
from . import regime_engine as eng
from .fetch_fred import yoy, mom_delta, diff_days

T = config.THRESHOLDS


# ---- helpers -------------------------------------------------------------
def _event_class(event: str) -> str | None:
    return config.EVENT_CLASSES.get(event)


def _pricing_tilt(priced: dict | None, bias: str | None, needle: str | None) -> str:
    """Which way policy expectations currently lean: hawkish / dovish / neutral.

    Prefers live market pricing, falls back to the dials' verdict bias, then to
    the regime's own lean — so a branch can always be scored even with the ZQ
    feed down.
    """
    if priced:
        hike, cut = priced.get("hike", 0.0), priced.get("cut", 0.0)
        if hike > cut:
            return "hawkish"
        if cut > hike:
            return "dovish"
    if bias:
        if bias.startswith("hawkish"):
            return "hawkish"
        if bias.startswith("dovish"):
            return "dovish"
    return config.REGIME_FED_LEAN.get(needle or "", "neutral")


def _pricing_effect(fed_direction: str, tilt: str, priced: dict | None) -> str:
    """A branch that contradicts what is currently priced forces a repricing."""
    if fed_direction == "neutral":
        # a "hold" only confirms when hold is actually the modal priced outcome
        if priced and max(("hike", "hold", "cut"),
                          key=lambda k: priced.get(k, 0.0)) == "hold":
            return "confirms pricing"
        return "confirms pricing" if not priced else "forces repricing"
    return "confirms pricing" if fed_direction == tilt else "forces repricing"


def _shift_yoy(s: pd.Series | None, delta_pp: float) -> pd.Series | None:
    """Copy of an index series whose latest YoY reading moves by delta_pp."""
    if s is None:
        return None
    s = s.dropna()
    if len(s) < 13:
        return None
    base = float(s.iloc[-13])
    if base == 0:
        return None
    cur_yoy = (float(s.iloc[-1]) / base - 1.0) * 100.0
    out = s.copy()
    out.iloc[-1] = base * (1.0 + (cur_yoy + delta_pp) / 100.0)
    return out


def _shift_level(s: pd.Series | None, delta: float) -> pd.Series | None:
    """Copy of a level series with its latest observation shifted by delta."""
    if s is None:
        return None
    s = s.dropna()
    if not len(s):
        return None
    out = s.copy()
    out.iloc[-1] = float(out.iloc[-1]) + delta
    return out


def _vote_of(voter: str, d: dict, asof: pd.Timestamp) -> str | None:
    fn = eng.VOTERS.get(voter)
    if fn is None:
        return None
    try:
        vote, _ = fn(d, asof)
    except Exception:
        return None
    return max(vote, key=vote.get)


# ---- stakes --------------------------------------------------------------
def stakes_for_event(event_class: str, d: dict, regime_state: dict,
                     asof: pd.Timestamp | None = None) -> tuple[str, str]:
    """(stakes, stakes_why) from VOTE SENSITIVITY, not assertion.

    Perturb the input the event actually moves, re-run that voter, and see
    whether a plausible print changes its argmax. A flip is HIGH and the reason
    names it. Otherwise MEDIUM when the event feeds a dial whose voter already
    disagrees with the needle, else LOW.
    """
    if event_class == "fomc":
        return "high", config.WATCHLIST_STAKES_WHY["high_fomc"]

    spec = config.EVENT_SENSITIVITY.get(event_class)
    needle = regime_state.get("needle")
    if not spec:
        return "low", config.WATCHLIST_STAKES_WHY["low"]

    asof = asof or pd.Timestamp.now(tz="UTC").tz_localize(None)
    voter, key = spec["voter"], spec["series"]
    base_vote = _vote_of(voter, d, asof)
    if base_vote is None:
        return "low", config.WATCHLIST_STAKES_WHY["low"]

    shock = config.WATCHLIST_PERTURBATIONS[spec["shock"]]
    shifter = _shift_yoy if event_class == "inflation" else _shift_level
    for delta in (shock, -shock):
        moved = shifter(d.get(key), delta)
        if moved is None:
            continue
        probe = dict(d)
        probe[key] = moved
        alt = _vote_of(voter, probe, asof)
        if alt is not None and alt != base_vote:
            return "high", config.WATCHLIST_STAKES_WHY["high"].format(
                shock=f"{abs(shock):.1f}pp", voter=voter, frm=base_vote, to=alt)

    if needle and base_vote != needle:
        return "medium", config.WATCHLIST_STAKES_WHY["medium"].format(
            voter=voter, vote=base_vote, needle=needle)
    return "low", config.WATCHLIST_STAKES_WHY["low"]


# ---- setup line ----------------------------------------------------------
def _pricing_clause(priced: dict | None) -> str:
    if not priced:
        return ""
    try:
        return config.WATCHLIST_PRICING_CLAUSE.format(
            hike=priced["hike"] * 100, hold=priced["hold"] * 100)
    except Exception:
        return ""


def _setup_line(event: str, event_class: str, d: dict,
                regime_state: dict, priced: dict | None) -> str:
    """One sentence in narrative.py's voice, citing live values only."""
    pricing = _pricing_clause(priced)
    needle = regime_state.get("needle") or "—"
    bias = regime_state.get("bias") or "current"
    # every field the *_min fallbacks may reference must be present here,
    # or the degraded path raises instead of degrading
    fields = {"pricing": pricing, "needle": needle, "bias": bias,
              "metric": event.split(" (")[0] or event}
    try:
        if event_class == "inflation":
            skey = config.EVENT_TREND_SERIES.get(event)
            y = yoy(d[skey]).dropna()
            level = float(y.iloc[-1])
            mom = diff_days(y, 92)
            if mom is None:
                raise ValueError("no momentum")
            direction = ("rising" if mom > T["inflation_momentum"]
                         else "falling" if mom < -T["inflation_momentum"] else "flat")
            return config.WATCHLIST_SETUP["inflation"].format(
                level=level, target=T["inflation_target"],
                direction=direction, mom=mom, **fields)
        if event_class == "employment":
            unrate = regime_state.get("unrate")
            sahm = regime_state.get("sahm")
            if unrate is None or sahm is None:
                raise ValueError("no employment state")
            return config.WATCHLIST_SETUP["employment"].format(
                unrate=unrate, sahm=sahm, **fields)
        if event_class == "fomc":
            return config.WATCHLIST_SETUP["fomc"].format(**fields)
        return config.WATCHLIST_SETUP["growth"].format(**fields)
    except Exception:
        pass
    try:
        return config.WATCHLIST_SETUP.get(
            f"{event_class}_min", config.WATCHLIST_SETUP["growth_min"]).format(**fields)
    except Exception:                      # never let a template kill the build
        return f"{fields['metric']} lands into a {needle} read."


# ---- the watch object ----------------------------------------------------
def branch_for_event(event: str, feeds: str, d: dict,
                     regime_state: dict, priced: dict | None) -> dict | None:
    """The `watch` object for one upcoming event, or None if unrecognised.

    Unknown events return None so the caller can leave their entry untouched —
    the schema change stays purely additive.
    """
    cls = _event_class(event)
    branch_cfg = config.EVENT_BRANCH_MAPS.get(cls or "")
    if not branch_cfg:
        return None

    tilt = _pricing_tilt(priced, regime_state.get("bias"), regime_state.get("needle"))
    stakes, why = stakes_for_event(cls, d, regime_state)

    branches = {}
    for key, b in branch_cfg.items():
        entry = {
            "label": b["label"],
            "implies": b["implies"],
            "pricing_effect": _pricing_effect(b["fed_direction"], tilt, priced),
            "assets": dict(b["assets"]),
        }
        if cls == "fomc" and priced and key in priced:
            entry["market_odds"] = priced[key]
        branches[key] = entry

    return {
        "stakes": stakes,
        "stakes_why": why,
        "setup": _setup_line(event, cls, d, regime_state, priced),
        "branches": branches,
    }


# ---- resolution ----------------------------------------------------------
def _dir_sign(text: str) -> int:
    if "▲" in text:
        return 1
    if "▼" in text:
        return -1
    return 0


def _accelerating(y: pd.Series, at: pd.Timestamp) -> bool | None:
    """Did the latest reading accelerate against its own 3-month momentum?"""
    y = y.dropna()
    y = y[y.index <= at]
    if len(y) < 5:
        return None
    latest = float(y.iloc[-1]) - float(y.iloc[-2])
    prior = (float(y.iloc[-2]) - float(y.iloc[-5])) / 3.0
    return latest > prior


def realized_branch(event: str, d: dict, at: pd.Timestamp) -> str | None:
    """Which branch the print actually took — same trend-relative rule."""
    cls = _event_class(event)
    skey = config.EVENT_TREND_SERIES.get(event)
    s = d.get(skey) if skey else None
    if s is None or cls is None:
        return None
    if cls == "inflation":
        acc = _accelerating(yoy(s), at)
    elif cls == "employment":
        nfp = mom_delta(s).dropna()
        nfp = nfp[nfp.index <= at]
        if len(nfp) < 4:
            return None
        acc = float(nfp.iloc[-1]) > float(nfp.iloc[-4:-1].mean())
    else:
        return None
    if acc is None:
        return None
    if config.EVENT_TREND_INVERTED.get(event):
        acc = not acc          # higher claims = weaker, not stronger
    return "a" if acc else "b"


def resolve_event(event: str, d: dict, at: pd.Timestamp,
                  reactions: dict | None) -> dict | None:
    """Close the loop: which branch happened, and did assets react as mapped.

    Returns None — never a guess — when the branch cannot be determined or
    there are no reactions to score against.
    """
    cls = _event_class(event)
    branch_cfg = config.EVENT_BRANCH_MAPS.get(cls or "")
    if not branch_cfg or not reactions:
        return None
    key = realized_branch(event, d, at)
    if key is None or key not in branch_cfg:
        return None

    b = branch_cfg[key]
    matches, mismatches, hits = 0, 0, []
    for asset, react_key in config.WATCHLIST_REACTION_MAP.items():
        want = _dir_sign(b["assets"].get(asset, ""))
        got_val = reactions.get(react_key)
        if want == 0 or got_val is None:
            continue
        got = 1 if got_val > 0 else -1 if got_val < 0 else 0
        if got == 0:
            continue
        if got == want:
            matches += 1
            hits.append(f"{asset} {'▲' if got > 0 else '▼'}")
        else:
            mismatches += 1
    if matches + mismatches == 0:
        return None

    as_mapped = matches > mismatches
    detail = (", ".join(hits) + " as mapped") if as_mapped else \
        f"{matches} of {matches + mismatches} asset moves matched"
    return {
        "branch": key,
        "branch_label": b["label"],
        "as_mapped": as_mapped,
        "note": config.WATCHLIST_RESOLUTION_NOTE.format(label=b["label"], detail=detail),
    }


# ---- next catalyst -------------------------------------------------------
def next_catalyst(upcoming: list[dict]) -> dict | None:
    """Soonest HIGH-stakes event; falls back to the soonest MEDIUM."""
    for level in ("high", "medium"):
        for e in sorted(upcoming, key=lambda x: x.get("date", "")):
            if (e.get("watch") or {}).get("stakes") == level:
                return {"date": e["date"], "event": e["event"]}
    return None
