"""Curriculum shape, the index, and slot resolution against both mock states."""
import json
from pathlib import Path

import pytest
from jsonschema import validate

from pipeline import lessons

ROOT = Path(__file__).parent.parent
LESSON_DIR = ROOT / "content" / "lessons"
EXPECTED_COUNT = 14

SLOT_SCHEMA = {
    "type": "object",
    "required": ["file", "path"],
    "properties": {
        "file": {"type": "string", "minLength": 1},
        "path": {"type": "string", "minLength": 1},
        "round": {"type": "integer", "minimum": 0, "maximum": 4},
        "map": {"enum": ["updown_word", "percent", "longshort_word"]},
    },
}
LESSON_SCHEMA = {
    "type": "object",
    "required": ["id", "slug", "title", "hook", "metaphor", "body", "live",
                 "caveat", "see_it"],
    "properties": {
        "id": {"type": "integer", "minimum": 1, "maximum": EXPECTED_COUNT},
        "slug": {"type": "string", "pattern": "^[a-z0-9-]+$"},
        "title": {"type": "string", "minLength": 1},
        "hook": {"type": "string", "minLength": 1},
        "metaphor": {"type": "string", "minLength": 1},
        "body": {"type": "array", "minItems": 3, "maxItems": 6,
                 "items": {"type": "string", "minLength": 1}},
        "caveat": {"type": "string", "minLength": 1},
        "live": {
            "type": "object", "required": ["template", "slots"],
            "properties": {
                "template": {"type": "string", "minLength": 1},
                "slots": {"type": "object", "minProperties": 1,
                          "additionalProperties": SLOT_SCHEMA},
            },
        },
        "see_it": {"type": "object", "required": ["module", "anchor"]},
    },
}


def _lesson_paths():
    return sorted(LESSON_DIR.glob("lesson-*.json"))


def _load_state(dirname):
    d = ROOT / dirname
    return {p.name: json.loads(p.read_text()) for p in d.glob("*.json")}


STATES = {"mock": _load_state("mock"), "mock/alt": _load_state("mock/alt")}


# ---- shape ----------------------------------------------------------------
def test_exactly_fourteen_lessons():
    assert len(_lesson_paths()) == EXPECTED_COUNT


@pytest.mark.parametrize("path", _lesson_paths(), ids=lambda p: p.stem)
def test_lesson_schema(path):
    validate(json.loads(path.read_text()), LESSON_SCHEMA)


def test_ids_are_unique_contiguous_and_match_filenames():
    ids = []
    for p in _lesson_paths():
        les = json.loads(p.read_text())
        assert p.stem == f"lesson-{les['id']:02d}", (p.name, les["id"])
        ids.append(les["id"])
    assert sorted(ids) == list(range(1, EXPECTED_COUNT + 1))


def test_slugs_are_unique():
    slugs = [json.loads(p.read_text())["slug"] for p in _lesson_paths()]
    assert len(set(slugs)) == len(slugs)


def test_index_matches_the_lessons_on_disk():
    idx = json.loads((LESSON_DIR / "index.json").read_text())
    assert idx["count"] == EXPECTED_COUNT
    assert [l["id"] for l in idx["lessons"]] == list(range(1, EXPECTED_COUNT + 1)), \
        "index must be in curriculum order"
    on_disk = {json.loads(p.read_text())["id"]: json.loads(p.read_text())
               for p in _lesson_paths()}
    for entry in idx["lessons"]:
        les = on_disk[entry["id"]]
        for field in ("slug", "title", "hook"):
            assert entry[field] == les[field], (entry["id"], field)


def test_every_asset_and_lesson_reference_points_somewhere_real():
    from pipeline import config
    ids = {json.loads(p.read_text())["id"] for p in _lesson_paths()}
    for asset, lesson_id in config.ASSET_LESSON.items():
        assert lesson_id in ids, (asset, lesson_id)
    for event, lesson_id in config.EVENT_LESSON.items():
        assert lesson_id in ids, (event, lesson_id)
    assert config.EVENT_LESSON_DEFAULT in ids


# ---- slot resolution ------------------------------------------------------
@pytest.mark.parametrize("state", sorted(STATES))
@pytest.mark.parametrize("path", _lesson_paths(), ids=lambda p: p.stem)
def test_every_slot_resolves_against_both_mock_states(path, state):
    les = json.loads(path.read_text())
    out = lessons.resolve_lesson(les, STATES[state])
    assert not out["missing"], f"{path.stem} in {state}: unresolved {out['missing']}"
    assert "{" not in out["text"] and "}" not in out["text"]


def test_lesson_nine_resolves_to_a_real_sentence():
    les = json.loads((LESSON_DIR / "lesson-09.json").read_text())
    out = lessons.resolve_lesson(les, STATES["mock"])
    assert "seesaw" in out["text"]
    assert out["values"]["gold_dir"] in ("up", "down", "sideways")


# ---- the resolver grammar -------------------------------------------------
def test_path_grammar():
    root = {
        "a": {"b": [1, 2, 3]},
        "nodes": [{"asset": "gold", "trend_3mo": -1.5},
                  {"asset": "stocks", "trend_3mo": 3.0}],
        "needle": "peak",
        "probabilities": {"peak": 0.55, "expansion": 0.25},
    }
    assert lessons.resolve_path(root, "a.b[0]") == 1
    assert lessons.resolve_path(root, "a.b[-1]") == 3
    assert lessons.resolve_path(root, "a.b.length") == 3
    assert lessons.resolve_path(root, "nodes[asset=gold].trend_3mo") == -1.5
    assert lessons.resolve_path(root, "probabilities.$needle") == 0.55
    assert lessons.resolve_path(root, "nodes[asset=nope].trend_3mo") is None
    assert lessons.resolve_path(root, "a.b[99]") is None
    assert lessons.resolve_path(root, "missing.entirely") is None


def test_maps_and_rounding():
    files = {"f.json": {"v": -1.234, "p": 0.4237, "n": 5}}
    assert lessons.resolve_slot({"file": "f.json", "path": "v",
                                 "map": "updown_word"}, files) == "down"
    assert lessons.resolve_slot({"file": "f.json", "path": "v",
                                 "round": 1}, files) == -1.2
    assert lessons.resolve_slot({"file": "f.json", "path": "p",
                                 "map": "percent", "round": 0}, files) == 42
    assert lessons.resolve_slot({"file": "f.json", "path": "n",
                                 "map": "longshort_word"},
                                files) == "betting on higher prices"


def test_missing_slot_degrades_to_a_dash_not_an_exception():
    les = {"live": {"template": "value is {x}.",
                    "slots": {"x": {"file": "nope.json", "path": "a"}}}}
    out = lessons.resolve_lesson(les, {})
    assert out["missing"] == ["x"]
    assert out["text"] == "value is —."


# ---- glossary -------------------------------------------------------------
def test_glossary_shape_and_lesson_links():
    g = json.loads((ROOT / "content" / "glossary.json").read_text())
    terms = g["terms"]
    assert g["count"] == len(terms) >= 40
    assert len({t["term"] for t in terms}) == len(terms), "duplicate term"
    ids = {json.loads(p.read_text())["id"] for p in _lesson_paths()}
    for t in terms:
        assert t["plain"].strip(), t["term"]
        assert t["plain"][0].isupper(), f"{t['term']}: definition must be a sentence"
        if "lesson" in t:
            assert t["lesson"] in ids, (t["term"], t["lesson"])


def test_glossary_covers_the_required_vocabulary():
    g = json.loads((ROOT / "content" / "glossary.json").read_text())
    have = {t["term"].lower() for t in g["terms"]}
    required = ["yield", "bond", "the fed", "interest rate", "inflation", "pce",
                "cpi", "unemployment rate", "jobs report", "yield curve",
                "inversion", "real yield", "basis point", "spread", "safe haven",
                "risk appetite", "qe", "qt", "cot", "smart money", "regime",
                "recession", "fomc", "vix", "dollar index", "s&p 500",
                "hawkish", "dovish", "priced in"]
    missing = [r for r in required if r not in have]
    assert not missing, f"glossary missing: {missing}"
