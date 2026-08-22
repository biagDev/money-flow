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
        "properties": {"upcoming": {"type": "array", "items": {
            "type": "object", "required": ["date", "event", "feeds", "hint"]}}},
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
