"""Contract enforcement: every shipped JSON must validate. Runs in CI before
any commit — broken JSON never reaches the site."""
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import validate

ROOT = Path(__file__).parent.parent
REGIMES = ["expansion", "peak", "contraction", "recovery"]

SCHEMAS = {
    "regime": {
        "type": "object",
        "required": ["as_of", "probabilities", "needle", "projection",
                     "in_regime_since", "narrative", "scores"],
        "properties": {
            "needle": {"enum": REGIMES},
            "projection": {"enum": REGIMES},
            "probabilities": {
                "type": "object", "required": REGIMES,
                "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "scores": {"type": "array", "minItems": 5, "items": {
                "type": "object",
                "required": ["input", "value", "vote", "weight"],
            }},
        },
    },
    "dials": {
        "type": "object",
        "required": ["as_of", "inflation", "employment", "verdict"],
        "properties": {
            "inflation": {"type": "object", "required": ["target", "direction", "sub"]},
            "employment": {"type": "object", "required": ["direction", "sub"]},
            "verdict": {"type": "object", "required": ["bias", "lines"]},
        },
    },
    "scenarios": {
        "type": "object",
        "required": ["as_of", "default", "decks"],
        "properties": {
            "default": {"enum": ["hike", "hold", "cut"]},
            "decks": {"type": "object", "required": ["hike", "hold", "cut"],
                      "additionalProperties": {"type": "array", "minItems": 5, "items": {
                          "type": "object",
                          "required": ["asset", "label", "dir", "why", "current_3mo"]}}},
        },
    },
    "flows": {
        "type": "object",
        "required": ["as_of", "regime", "nodes", "edges"],
        "properties": {
            "regime": {"enum": REGIMES},
            "nodes": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
                "type": "object", "required": ["asset", "driver", "spark"]}},
            "edges": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["from", "to", "strength"]}},
        },
    },
    "evidence": {
        "type": "object",
        "required": ["as_of", "curve", "real_yields_gold", "cot", "scorecard"],
        "properties": {
            "curve": {"type": "object", "required": ["today", "spread_10y3m"]},
            "scorecard": {"type": "object", "required": ["rows", "confirmed", "total"]},
        },
    },
    "calendar": {
        "type": "object",
        "required": ["as_of", "upcoming", "recent"],
        "properties": {
            # next_catalyst is additive: absent is valid, present must be shaped
            "next_catalyst": {"type": "object", "required": ["date", "event"]},
            "upcoming": {"type": "array", "items": {
                "type": "object", "required": ["date", "event", "feeds", "hint"]}},
        },
    },
}

# The watch object is additive — validated only where it appears, so the
# pre-watchlist frontend contract keeps passing untouched.
ASSET_MAP_SCHEMA = {
    "type": "object",
    "required": ["bonds", "dollar", "gold", "stocks"],
    "additionalProperties": {"type": "string"},
}
BRANCH_SCHEMA = {
    "type": "object",
    "required": ["label", "implies", "pricing_effect", "assets"],
    "properties": {
        "label": {"type": "string", "minLength": 1},
        "implies": {"type": "string", "minLength": 1},
        "pricing_effect": {"enum": ["confirms pricing", "forces repricing"]},
        "assets": ASSET_MAP_SCHEMA,
        "market_odds": {"type": "number", "minimum": 0, "maximum": 1},
    },
}
WATCH_SCHEMA = {
    "type": "object",
    "required": ["stakes", "stakes_why", "setup", "branches"],
    "properties": {
        "stakes": {"enum": ["high", "medium", "low"]},
        "stakes_why": {"type": "string", "minLength": 1},
        "setup": {"type": "string", "minLength": 1},
        "branches": {"type": "object", "minProperties": 2,
                     "additionalProperties": BRANCH_SCHEMA},
    },
}
RESOLUTION_SCHEMA = {
    "type": "object",
    "required": ["branch", "branch_label", "as_mapped", "note"],
    "properties": {
        "branch": {"type": "string", "minLength": 1},
        "branch_label": {"type": "string", "minLength": 1},
        "as_mapped": {"type": "boolean"},
        "note": {"type": "string", "minLength": 1},
    },
}


def _dirs():
    out = []
    for d in (ROOT / "data", ROOT / "mock", ROOT / "mock" / "alt"):
        if d.exists() and any(d.glob("*.json")):
            out.append(d)
    return out


@pytest.mark.parametrize("name", list(SCHEMAS))
def test_schema(name):
    dirs = _dirs()
    assert dirs, "no data/ or mock/ output found — run the builder first"
    for d in dirs:
        p = d / f"{name}.json"
        if not p.exists():
            continue
        obj = json.loads(p.read_text())
        validate(obj, SCHEMAS[name])


def test_probabilities_sum_to_one():
    for d in _dirs():
        p = d / "regime.json"
        if p.exists():
            probs = json.loads(p.read_text())["probabilities"]
            assert abs(sum(probs.values()) - 1.0) < 0.02, f"{d}: probs sum {sum(probs.values())}"


def test_fomc_dates_present_and_future():
    """The one hand-maintained input. Its absence is silent: the build still
    succeeds but next_fomc goes None, so scenarios ship market_pricing: null
    and the FOMC calendar entries disappear. Fail loudly instead."""
    p = ROOT / "pipeline" / "fomc_dates.json"
    assert p.exists(), ("fomc_dates.json missing — scenarios pricing and FOMC "
                        "calendar entries silently degrade")
    dates = json.loads(p.read_text())["dates"]
    assert any(d >= str(date.today()) for d in dates), \
        "no future FOMC dates — file needs its yearly update"


# ---- event watchlist (additive schema) ------------------------------------
def _calendars():
    for d in _dirs():
        p = d / "calendar.json"
        if p.exists():
            yield d, json.loads(p.read_text())


def test_watch_objects_validate_where_present():
    for d, cal in _calendars():
        for entry in cal.get("upcoming", []):
            if "watch" in entry:
                validate(entry["watch"], WATCH_SCHEMA)


def test_next_catalyst_present_when_any_watch_exists():
    for d, cal in _calendars():
        has_watch = any("watch" in e for e in cal.get("upcoming", []))
        if not has_watch:
            continue
        assert "next_catalyst" in cal, f"{d}: watch entries exist but no next_catalyst"
        nc = cal["next_catalyst"]
        assert any(e["date"] == nc["date"] and e["event"] == nc["event"]
                   for e in cal["upcoming"]), f"{d}: next_catalyst not in upcoming"


def test_next_catalyst_points_at_the_highest_available_stakes():
    """It must never name a medium event while a high one is on the board."""
    for d, cal in _calendars():
        nc = cal.get("next_catalyst")
        if not nc:
            continue
        stakes = {(e["date"], e["event"]): (e.get("watch") or {}).get("stakes")
                  for e in cal["upcoming"] if "watch" in e}
        chosen = stakes.get((nc["date"], nc["event"]))
        if chosen == "medium":
            assert "high" not in stakes.values(), \
                f"{d}: next_catalyst is medium but a high-stakes event exists"


def test_resolutions_validate_where_present():
    for d, cal in _calendars():
        for entry in cal.get("recent", []):
            if "resolution" in entry:
                validate(entry["resolution"], RESOLUTION_SCHEMA)
                assert entry.get("reactions"), \
                    f"{d}: resolution present without reactions to score"


def test_watchlist_is_purely_additive():
    """Every pre-existing upcoming/recent field must survive untouched."""
    for d, cal in _calendars():
        for e in cal.get("upcoming", []):
            for k in ("date", "event", "feeds", "hint"):
                assert k in e, f"{d}: upcoming entry lost '{k}'"
        for e in cal.get("recent", []):
            for k in ("reference_month", "event", "reactions"):
                assert k in e, f"{d}: recent entry lost '{k}'"
