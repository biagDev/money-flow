"""Voice lint: simple mode must stay readable, and jargon must stay out.

Layer 1 and the lessons are the only strings a beginner reads unaided. The
PRO layer (voter distributions, COT percentiles, exact spreads) is exempt —
it is allowed to be technical, which is the whole point of the depth toggle.
"""
import json
from pathlib import Path

import pytest

from pipeline import config

ROOT = Path(__file__).parent.parent
LESSON_DIR = ROOT / "content" / "lessons"
LIMIT = config.VOICE_MAX_CHARS


def _overview_files():
    return [p for p in (ROOT / "data" / "overview.json",
                        ROOT / "mock" / "overview.json",
                        ROOT / "mock" / "alt" / "overview.json") if p.exists()]


def _lesson_files():
    return sorted(LESSON_DIR.glob("lesson-*.json"))


def _overview_strings(o):
    yield "mood.line", o["mood"]["line"]
    for a in o["assets"]:
        yield f"why[{a['asset']}]", a["why"]
    for i, b in enumerate(o["bullets"]):
        yield f"bullet[{i}]", b
    if "changed" in o:
        yield "changed.line", o["changed"]["line"]


def _reader_strings(lesson):
    yield "hook", lesson["hook"]
    yield "metaphor", lesson["metaphor"]
    yield "caveat", lesson["caveat"]
    for i, line in enumerate(lesson["body"]):
        yield f"body[{i}]", line


# ---- length ---------------------------------------------------------------
def test_overview_strings_are_short():
    assert _overview_files(), "no overview.json to lint"
    for p in _overview_files():
        o = json.loads(p.read_text())
        for name, text in _overview_strings(o):
            assert len(text) <= LIMIT, f"{p.name} {name}: {len(text)} chars — {text}"


def test_lesson_body_lines_are_short():
    for p in _lesson_files():
        les = json.loads(p.read_text())
        for i, line in enumerate(les["body"]):
            assert len(line) <= LIMIT, f"{p.name} body[{i}]: {len(line)} chars"


# ---- jargon ---------------------------------------------------------------
def _find_jargon(text):
    low = text.lower()
    return [j for j in config.BANNED_JARGON if j in low]


def test_no_banned_jargon_in_overview():
    for p in _overview_files():
        o = json.loads(p.read_text())
        for name, text in _overview_strings(o):
            assert not _find_jargon(text), f"{p.name} {name}: {_find_jargon(text)}"


def test_no_banned_jargon_in_lesson_reader_text():
    for p in _lesson_files():
        les = json.loads(p.read_text())
        for name, text in _reader_strings(les):
            assert not _find_jargon(text), f"{p.name} {name}: {_find_jargon(text)}"


def test_glossary_is_exempt_because_defining_jargon_is_its_job():
    """Guard against someone 'fixing' the glossary to satisfy the linter."""
    terms = json.loads((ROOT / "content" / "glossary.json").read_text())["terms"]
    names = {t["term"].lower() for t in terms}
    for word in ("hawkish", "dovish", "basis point"):
        assert word in names, f"glossary lost its definition of '{word}'"


def test_config_templates_are_clean_at_the_source():
    """Lint the table, not just today's render — an unreached template with
    jargon in it is a bug waiting for the regime to change."""
    for key, text in config.OVERVIEW_ASSET_WHY.items():
        assert not _find_jargon(text), (key, text)
        assert len(text) <= LIMIT, (key, len(text))
    for label, text in config.MOOD_LINES.items():
        assert not _find_jargon(text), (label, text)
        assert len(text) <= LIMIT, (label, len(text))


# ---- structure ------------------------------------------------------------
@pytest.mark.parametrize("path", _lesson_files(), ids=lambda p: p.stem)
def test_lesson_has_exactly_one_honest_caveat(path):
    les = json.loads(path.read_text())
    assert isinstance(les["caveat"], str) and les["caveat"].strip()
    assert 3 <= len(les["body"]) <= 6, len(les["body"])
    assert "?" in les["hook"], "the hook must ask a real question"


def test_flagged_overstatements_carry_their_caveat():
    """Where the source material overstates, the lesson must say so."""
    def caveat(n):
        return json.loads((LESSON_DIR / f"lesson-{n:02d}.json").read_text())["caveat"].lower()

    inversion = caveat(7)
    assert "12" in inversion and "two years" in inversion, \
        "lesson 7 must carry the inversion sample-size and lag caveat"
    cot = caveat(14)
    assert "tuesday" in cot and ("friday" in cot or "published" in cot), \
        "lesson 14 must carry the COT reporting-lag caveat"
    vix = caveat(11)
    assert "expire" in vix or "replaced" in vix, \
        "lesson 11 must carry the VIX roll-cost caveat"


# ---- why-lines describe tendencies, never today ---------------------------
def test_why_lines_never_assert_present_tense_direction():
    """A why-line is keyed on the regime's EXPECTED direction, while the card's
    `actual` is live. "The dollar is falling" next to actual: sideways is Layer 1
    contradicting itself — a consistency failure that lives in wording, so the
    data-level consistency test cannot catch it. Lint the wording instead.
    """
    offenders = []
    for key, text in config.OVERVIEW_ASSET_WHY.items():
        low = text.lower()
        for phrase in config.BANNED_PRESENT_TENSE:
            if phrase in low:
                offenders.append((key, phrase, text))
    assert not offenders, (
        "why-lines must describe what usually happens, not today's move:\n"
        + "\n".join(f"  {k}: '{p}' in {t!r}" for k, p, t in offenders))


def test_every_why_line_hedges_to_a_tendency():
    missing = [(k, t) for k, t in config.OVERVIEW_ASSET_WHY.items()
               if not any(w in t.lower() for w in config.REQUIRED_TENDENCY_WORDS)]
    assert not missing, (
        "every why-line needs a tendency word (usually / tends to / can keep):\n"
        + "\n".join(f"  {k}: {t!r}" for k, t in missing))


def test_shipped_why_lines_obey_the_same_rule():
    """Belt and braces: lint what actually shipped, not only the table."""
    for p in _overview_files():
        o = json.loads(p.read_text())
        for a in o["assets"]:
            low = a["why"].lower()
            hits = [ph for ph in config.BANNED_PRESENT_TENSE if ph in low]
            assert not hits, f"{p.name} {a['asset']}: {hits} in {a['why']!r}"
