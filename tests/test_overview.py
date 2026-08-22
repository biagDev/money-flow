"""Layer 1: schema, mood mapping, and the Layer-1 vs scorecard consistency rule."""
import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import validate

from pipeline import config, narrative as nar, overview as ov, regime_engine as eng

ROOT = Path(__file__).parent.parent
ASOF = pd.Timestamp("2026-08-01")

OVERVIEW_SCHEMA = {
    "type": "object",
    "required": ["as_of", "mood", "assets", "bullets", "next_big_date"],
    "properties": {
        "stale": {"type": "boolean"},
        "mood": {
            "type": "object", "required": ["label", "line"],
            "properties": {
                "label": {"enum": ["SUNNY", "CAUTIOUS", "STORMY", "CLEARING"]},
                "line": {"type": "string", "minLength": 1},
            },
        },
        "assets": {
            "type": "array", "minItems": 4, "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["asset", "expected", "actual", "agree", "why", "lesson"],
                "properties": {
                    "asset": {"enum": ["stocks", "gold", "dollar", "bonds"]},
                    "expected": {"enum": ["up", "down", "sideways"]},
                    "actual": {"enum": ["up", "down", "sideways"]},
                    "agree": {"type": "boolean"},
                    "why": {"type": "string", "minLength": 1},
                    "lesson": {"type": "integer", "minimum": 1, "maximum": 14},
                },
            },
        },
        "bullets": {"type": "array", "minItems": 2, "maxItems": 4,
                    "items": {"type": "string", "minLength": 1}},
        "next_big_date": {
            "type": ["object", "null"],
            "required": ["date", "event", "lesson"],
        },
        "changed": {
            "type": "object", "required": ["recent", "line"],
            "properties": {"recent": {"type": "boolean"},
                           "line": {"type": "string", "minLength": 1}},
        },
    },
}


def _dirs():
    return [d for d in (ROOT / "data", ROOT / "mock", ROOT / "mock" / "alt")
            if (d / "overview.json").exists()]


def _overviews():
    for d in _dirs():
        yield d, json.loads((d / "overview.json").read_text())


# ---- schema ---------------------------------------------------------------
def test_overview_schema():
    assert _dirs(), "no overview.json anywhere — run the builder first"
    for d, o in _overviews():
        validate(o, OVERVIEW_SCHEMA)


def test_agree_flag_is_never_a_lie():
    for d, o in _overviews():
        for a in o["assets"]:
            assert a["agree"] == (a["expected"] == a["actual"]), (d, a)


def test_every_asset_appears_exactly_once():
    for d, o in _overviews():
        names = [a["asset"] for a in o["assets"]]
        assert sorted(names) == ["bonds", "dollar", "gold", "stocks"], (d, names)


def test_next_big_date_is_referenced_by_a_bullet():
    for d, o in _overviews():
        nbd = o.get("next_big_date")
        if not nbd:
            continue
        assert any("Next big date" in b for b in o["bullets"]), d


# ---- mood mapping ---------------------------------------------------------
@pytest.mark.parametrize("needle,bias,pce,sahm,want", [
    ("expansion",   "neutral",         1.8, 0.0,  "SUNNY"),
    ("expansion",   "hawkish-leaning", 3.7, 0.1,  "CAUTIOUS"),
    ("peak",        "hawkish",         4.4, 0.1,  "CAUTIOUS"),
    ("contraction", "dovish",          1.5, 0.6,  "STORMY"),
    ("recovery",    "dovish",          1.6, 0.3,  "CLEARING"),
    # a triggered Sahm gap outranks a calm-looking needle
    ("expansion",   "neutral",         1.8, 0.9,  "STORMY"),
])
def test_mood_mapping(needle, bias, pce, sahm, want):
    assert ov.mood_for(needle, bias, pce, sahm)["label"] == want


def test_mood_always_returns_a_known_label():
    m = ov.mood_for("not-a-regime", None, None, None)
    assert m["label"] in config.MOOD_LINES
    assert m["line"]


# ---- THE consistency rule -------------------------------------------------
def test_layer1_and_scorecard_never_disagree():
    """The hard rule: if Layer 1 and the Evidence scorecard could ever say an
    asset is doing different things, the build must fail here rather than ship
    the contradiction. Both must read narrative.asset_moves with the same bands.
    """
    for d, o in _overviews():
        ev_path = d / "evidence.json"
        rg_path = d / "regime.json"
        if not (ev_path.exists() and rg_path.exists()):
            continue
        rows = json.loads(ev_path.read_text())["scorecard"]["rows"]
        needle = json.loads(rg_path.read_text())["needle"]
        exp = config.REGIME_EXPECTATIONS[needle]

        # scorecard rows are "<Label> <want>"; recover want per asset
        label_to_asset = {"Yields": "bonds", "Dollar": "dollar",
                          "Gold": "gold", "Stocks": "stocks"}
        want_by_asset = {}
        for row in rows:
            for label, asset in label_to_asset.items():
                if row["says"].startswith(label + " "):
                    want_by_asset[asset] = row["says"][len(label) + 1:]
        for a in o["assets"]:
            want = want_by_asset.get(a["asset"])
            if want is None:
                continue
            expect_word = config.DIRECTION_WORDS[want]
            assert a["expected"] == expect_word, (
                d, a["asset"], a["expected"], want)
            # and Layer 1's expectation must come from the same table
            assert config.DIRECTION_WORDS[
                exp[config.OVERVIEW_ASSET_KEYS[a["asset"]]]] == a["expected"]


def test_asset_moves_is_the_only_source_of_directions():
    """Both readers must produce identical directions from identical inputs."""
    idx = pd.date_range(end=ASOF, periods=400, freq="D")
    d = {
        "y10": pd.Series([4.0 + i * 0.002 for i in range(400)], index=idx),
        "dxy_proxy": pd.Series([100.0 + i * 0.02 for i in range(400)], index=idx),
        "gold": pd.Series([4000.0 - i * 0.5 for i in range(400)], index=idx),
        "spx": pd.Series([5000.0 + i * 2.0 for i in range(400)], index=idx),
    }
    moves = nar.asset_moves(d)
    rows = ov.asset_rows("peak", d)
    for row in rows:
        key = config.OVERVIEW_ASSET_KEYS[row["asset"]]
        expected_word = config.DIRECTION_WORDS[nar.move_direction(key, moves[key])]
        assert row["actual"] == expected_word, row


# ---- degradation ----------------------------------------------------------
def test_overview_survives_a_totally_empty_data_dict():
    core = eng.compute({}, ASOF)
    out = ov.build_overview({}, core, {}, now="2026-08-01T00:00:00Z", bias=None,
                            pce_now=None, pce_mom=None, unrate=None, sahm=None,
                            since=None)
    validate(out, OVERVIEW_SCHEMA)
    assert len(out["assets"]) == 4
    assert all(a["why"] for a in out["assets"])


def test_why_line_exists_for_every_reachable_combination():
    """No regime can produce a blank card."""
    for needle in config.REGIMES:
        family = config.REGIME_FAMILY[needle]
        for asset, key in config.OVERVIEW_ASSET_KEYS.items():
            want = config.DIRECTION_WORDS[config.REGIME_EXPECTATIONS[needle][key]]
            assert (asset, want, family) in config.OVERVIEW_ASSET_WHY, \
                (needle, asset, want, family)


def test_mock_states_carry_opposite_moods_and_a_disagreement():
    """The design build's contract: swapping mock -> mock/alt must re-render."""
    peak = json.loads((ROOT / "mock" / "overview.json").read_text())
    rec = json.loads((ROOT / "mock" / "alt" / "overview.json").read_text())
    assert peak["mood"]["label"] != rec["mood"]["label"]
    disagreements = [a for s in (peak, rec) for a in s["assets"] if not a["agree"]]
    assert disagreements, "no agree:false card in either mock state to style"
