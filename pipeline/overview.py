"""Layer 1: today, in plain English.

A fourth-grader should be able to read this module's output: money's overall
mood, four asset cards with a direction and a one-line why, a few bullets, and
the next big date.

Every string comes from a template table in config.py written to the voice
rules (<=15 words a sentence, one idea each, no unexplained jargon, rounded
numbers, explicit direction). Nothing here is authored inline, nothing is
computed twice: the asset directions come from narrative.asset_moves, the same
function the Evidence scorecard uses, so Layer 1 and the scorecard cannot
disagree about what an asset is doing.
"""
from __future__ import annotations

import pandas as pd

from . import config
from . import narrative as nar
from . import regime_engine as eng
from .fetch_fred import yoy, diff_days, last

T = config.THRESHOLDS


# ---- mood ----------------------------------------------------------------
def _facts(needle: str, bias: str | None, pce_now: float | None,
           sahm: float | None) -> dict:
    return {
        "needle": needle,
        "sahm_triggered": (sahm or 0.0) >= T["sahm_trigger"],
        "bias_hawkish": bool(bias and bias.startswith("hawkish")),
        "bias_dovish": bool(bias and bias.startswith("dovish")),
        "inflation_above_target": bool(pce_now is not None
                                       and pce_now > T["inflation_target"]),
    }


def mood_for(needle: str, bias: str | None, pce_now: float | None,
             sahm: float | None) -> dict:
    """First matching rule in config.MOOD_RULES wins; worst weather first."""
    facts = _facts(needle, bias, pce_now, sahm)
    for rule in config.MOOD_RULES:
        when = rule["when"]
        ok = True
        for key, want in when.items():
            got = facts.get(key)
            if isinstance(want, list):
                if got not in want:
                    ok = False
                    break
            elif got != want:
                ok = False
                break
        if ok:
            label = rule["mood"]
            return {"label": label, "line": config.MOOD_LINES[label]}
    return {"label": config.MOOD_FALLBACK,
            "line": config.MOOD_LINES[config.MOOD_FALLBACK]}


# ---- assets --------------------------------------------------------------
def asset_rows(needle: str, d: dict) -> list[dict]:
    """One card per asset: what the regime expects, what it is actually doing."""
    expectations = config.REGIME_EXPECTATIONS.get(needle, {})
    family = config.REGIME_FAMILY.get(needle, "growing")
    moves = nar.asset_moves(d)          # shared with the scorecard, never re-derived
    rows = []
    for asset in config.OVERVIEW_ASSET_ORDER:
        key = config.OVERVIEW_ASSET_KEYS[asset]
        expected = config.DIRECTION_WORDS.get(expectations.get(key, "flat"), "sideways")
        value = moves.get(key)
        actual = (config.DIRECTION_WORDS[nar.move_direction(key, value)]
                  if value is not None else "sideways")
        why = config.OVERVIEW_ASSET_WHY.get((asset, expected, family))
        if why is None:                 # never ship a blank card
            why = config.OVERVIEW_ASSET_WHY.get((asset, "sideways", family), "")
        rows.append({
            "asset": asset,
            "expected": expected,
            "actual": actual,
            "agree": expected == actual,
            "why": why,
            "lesson": config.ASSET_LESSON[asset],
        })
    return rows


# ---- bullets -------------------------------------------------------------
def _price_bullet(pce_now: float | None, pce_mom: float | None) -> str:
    if pce_now is None:
        return config.OVERVIEW_BULLETS["prices_min"]
    mom = pce_mom or 0.0
    key = ("up" if mom > T["inflation_momentum"]
           else "down" if mom < -T["inflation_momentum"] else "flat")
    if key == "flat":       # "holding near about 3.7%" does not read as English
        return config.OVERVIEW_BULLETS["prices_flat"].format(
            level=pce_now, target=T["inflation_target"])
    return config.OVERVIEW_BULLETS["prices"].format(
        word=config.PRICE_DIRECTION_WORDS[key], level=pce_now,
        target=T["inflation_target"])


def _jobs_bullet(d: dict, unrate: float | None) -> str | None:
    pay = eng.payroll_state(d)
    if pay is not None:
        state, p3 = pay
        if state == "stress":
            return config.OVERVIEW_BULLETS["jobs_stress"].format(p3=abs(p3))
        return config.OVERVIEW_BULLETS[f"jobs_{state}"].format(p3=p3)
    if unrate is not None:
        return config.OVERVIEW_BULLETS["jobs_unrate"].format(unrate=unrate)
    # say so plainly rather than pad the card or drop below the 2-bullet contract
    return config.OVERVIEW_BULLETS["jobs_min"]


def friendly_event(event: str) -> str:
    return config.EVENT_FRIENDLY_NAMES.get(event, event)


def _friendly_date(date_str: str) -> str:
    try:
        return pd.Timestamp(date_str).strftime("%b %-d")
    except Exception:
        return date_str


def next_big_date(calendar: dict) -> dict | None:
    """The catalyst the watchlist already picked, renamed for humans."""
    nc = (calendar or {}).get("next_catalyst")
    if not nc:
        upcoming = sorted((calendar or {}).get("upcoming", []),
                          key=lambda e: e.get("date", ""))
        if not upcoming:
            return None
        nc = {"date": upcoming[0]["date"], "event": upcoming[0]["event"]}
    return {"date": nc["date"],
            "event": friendly_event(nc["event"]).capitalize(),
            "lesson": config.EVENT_LESSON.get(nc["event"],
                                              config.EVENT_LESSON_DEFAULT)}


# ---- what changed --------------------------------------------------------
def what_changed(d: dict, core: dict, since: str | None, mood_label: str,
                 priced: dict | None = None) -> dict | None:
    """Present only when something actually moved recently.

    Two triggers: the regime itself is young, or a voter's argmax differs from
    its argmax a month ago (the engine already supports historical replay).
    """
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    mood = mood_label.lower()

    # a voter that flipped in the last month is the more specific story
    try:
        prev = eng.compute(d, now - pd.DateOffset(months=1), priced)
        prev_votes = {s["input"]: s["vote"] for s in prev["scores"]}
        for s in core["scores"]:
            was = prev_votes.get(s["input"])
            nowv = s["vote"]
            if was and was != nowv:
                verb = config.CHANGE_VERBS.get(
                    (config.REGIME_FAMILY.get(was), config.REGIME_FAMILY.get(nowv)),
                    config.CHANGE_VERB_DEFAULT)
                topic = config.VOTER_TOPIC.get(s["input"], s["input"])
                return {"recent": True,
                        "line": config.OVERVIEW_CHANGED["voter"].format(
                            topic=topic, verb=verb, mood=mood)}
    except Exception:
        pass

    if since:
        try:
            age = (now - pd.Timestamp(since)).days
            if 0 <= age <= config.OVERVIEW_CHANGED_DAYS:
                return {"recent": True,
                        "line": config.OVERVIEW_CHANGED["regime"].format(
                            word=config.REGIME_PLAIN_WORDS.get(core["needle"],
                                                               core["needle"]),
                            mood=mood)}
        except Exception:
            pass
    return None


# ---- the payload ---------------------------------------------------------
def build_overview(d: dict, core: dict, calendar: dict, *, now: str,
                   bias: str | None, pce_now: float | None,
                   pce_mom: float | None, unrate: float | None,
                   sahm: float | None, since: str | None,
                   priced: dict | None = None) -> dict:
    needle = core["needle"]
    mood = mood_for(needle, bias, pce_now, sahm)

    bullets = [_price_bullet(pce_now, pce_mom)]
    jobs = _jobs_bullet(d, unrate)
    if jobs:
        bullets.append(jobs)
    nbd = next_big_date(calendar)
    if nbd:
        bullets.append(config.OVERVIEW_BULLETS["next_date"].format(
            event=nbd["event"], date=_friendly_date(nbd["date"])))

    out = {
        "as_of": now,
        "stale": False,
        "mood": mood,
        "assets": asset_rows(needle, d),
        "bullets": bullets[:4],
        "next_big_date": nbd,
    }
    changed = what_changed(d, core, since, mood["label"], priced)
    if changed:                      # present only when true
        out["changed"] = changed
    return out
