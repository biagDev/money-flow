"""Ledger integrity, scoring correctness, baselines, n-gating, and the report."""
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline import config, ledger as led, scoring, weekly_report as wr

ROOT = Path(__file__).parent.parent


# ---- fixtures -------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    (tmp_path / config.LEDGER_DIR).mkdir()
    return tmp_path


def _snapshot(day, needle="expansion", prob=0.52, assets=None, source="test"):
    assets = assets or [
        {"asset": "stocks", "expected": "up", "actual": "up", "agree": True},
        {"asset": "gold", "expected": "up", "actual": "down", "agree": False},
        {"asset": "dollar", "expected": "down", "actual": "down", "agree": True},
        {"asset": "bonds", "expected": "up", "actual": "up", "agree": True},
    ]
    return {
        "day": day, "source": source, "engine_version": "test",
        "config_hash": "deadbeef", "schema_version": 1,
        "claim": {"needle": needle,
                  "probabilities": {needle: prob, "peak": 1 - prob},
                  "projection": "recovery", "mood": "CAUTIOUS",
                  "assets": assets, "verdict_bias": "neutral",
                  "market_pricing": None, "pricing_stale": True,
                  "scorecard": {"confirmed": 2, "total": 4, "rows": []}},
        "inputs": {},
    }


def _series(start, n, step, freq="B"):
    idx = pd.date_range(start=start, periods=n, freq=freq)
    return pd.Series([100.0 + i * step for i in range(n)], index=idx)


# ---- hash chain -----------------------------------------------------------
def test_chain_starts_at_genesis_and_links_forward(store):
    a = led.append("snapshots", {"day": "2026-01-01"}, store)
    b = led.append("snapshots", {"day": "2026-01-02"}, store)
    assert a["prev_hash"] == led.GENESIS
    assert b["prev_hash"] == led.line_hash(a)
    ok, msg = led.verify_chain("snapshots", store)
    assert ok, msg


def test_editing_a_historical_line_breaks_the_chain(store):
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        led.append("snapshots", {"day": day, "needle": "expansion"}, store)
    ok, _ = led.verify_chain("snapshots", store)
    assert ok

    # quietly improve the record, exactly the thing the chain exists to catch
    p = store / config.LEDGER_DIR / "snapshots.jsonl"
    lines = p.read_text().splitlines()
    doctored = json.loads(lines[0])
    doctored["needle"] = "peak"
    lines[0] = led.canonical(doctored)
    p.write_text("\n".join(lines) + "\n")

    ok, msg = led.verify_chain("snapshots", store)
    assert not ok
    assert "line 2" in msg and "edited" in msg


def test_every_shipped_stream_parses_and_verifies():
    """Runs against the real ledger in the repo, so CI catches a bad edit."""
    if not led.ledger_dir().exists():
        pytest.skip("no ledger yet")
    for stream in config.LEDGER_FILES:
        p = led.ledger_dir() / config.LEDGER_FILES[stream]
        if not p.exists():
            continue
        for i, raw in enumerate(p.read_text().splitlines(), 1):
            if raw.strip():
                json.loads(raw)          # every line must parse
        ok, msg = led.verify_chain(stream)
        assert ok, msg


def test_config_hash_is_stable_and_sensitive():
    first = led.config_hash()
    assert first == led.config_hash()
    original = config.THRESHOLDS["inflation_target"]
    try:
        config.THRESHOLDS["inflation_target"] = original + 1
        assert led.config_hash() != first, "a tunable change must move the hash"
    finally:
        config.THRESHOLDS["inflation_target"] = original
    assert led.config_hash() == first


# ---- snapshots ------------------------------------------------------------
def test_two_same_day_builds_write_one_snapshot(store):
    snap = _snapshot("2026-08-22")
    assert led.write_snapshot(snap, store) is not None
    assert led.write_snapshot(snap, store) is None
    assert len(led.read_lines("snapshots", store)) == 1


def test_snapshot_only_written_in_the_final_slot(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.delenv("LEDGER_FORCE_SNAPSHOT", raising=False)
    hour = config.LEDGER_FINAL_SLOT_UTC_HOUR
    assert led.is_final_slot(datetime(2026, 8, 24, hour, 30, tzinfo=timezone.utc))
    assert not led.is_final_slot(datetime(2026, 8, 24, hour - 1, 30, tzinfo=timezone.utc))
    # Saturday, even at the right hour
    assert not led.is_final_slot(datetime(2026, 8, 22, hour, 30, tzinfo=timezone.utc))


def test_a_ledger_failure_never_raises_into_the_build(store, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(led, "build_snapshot", boom)
    monkeypatch.setenv("LEDGER_FORCE_SNAPSHOT", "1")
    out = led.record_build("2026-08-22", {}, {}, {}, {}, {}, {}, {}, root=store)
    assert out["snapshot"] is False
    assert out["errors"], "the failure must be recorded, not swallowed silently"
    assert led.read_lines("health", store), "and it must land in health.jsonl"


# ---- divergences ----------------------------------------------------------
def test_divergence_logs_transitions_not_standing_state(store):
    def snap(day, gold_agree, status):
        s = _snapshot(day)
        s["claim"]["assets"][1]["agree"] = gold_agree
        s["claim"]["scorecard"]["rows"] = [{"says": "Gold up", "status": status}]
        return s

    led.write_snapshot(snap("2026-08-20", True, "confirmed"), store)
    d1 = snap("2026-08-21", False, "diverging")
    led.write_snapshot(d1, store)
    assert led.record_divergences(d1, store) == 2       # both flipped

    d2 = snap("2026-08-22", False, "diverging")         # still bad, but not NEW
    led.write_snapshot(d2, store)
    assert led.record_divergences(d2, store) == 0


# ---- scoring: known paths, known answers ---------------------------------
def test_forward_move_counts_trading_days_not_calendar_days():
    s = _series("2026-01-01", 100, 1.0)          # business days only
    move, end = scoring.forward_move(s, "2026-01-05", 21, "spx")
    start_val = float(s[s.index <= pd.Timestamp("2026-01-05")].iloc[-1])
    pos = s.index.get_loc(s[s.index <= pd.Timestamp("2026-01-05")].index[-1])
    assert end == str(s.index[pos + 21].date())
    assert move == pytest.approx((float(s.iloc[pos + 21]) / start_val - 1) * 100, rel=1e-6)


def test_unresolvable_claim_returns_none_rather_than_guessing():
    s = _series("2026-01-01", 10, 1.0)
    assert scoring.forward_move(s, "2026-01-05", 63, "spx") is None


def test_scoring_hits_and_misses_on_a_known_price_path(store):
    """Rising stocks, falling gold: engine called stocks up (hit) and gold up
    (miss). Persistence called stocks up (hit) and gold down (hit)."""
    led.write_snapshot(_snapshot("2026-01-05"), store)
    d = {"spx": _series("2026-01-01", 200, 1.0),      # clearly up
         "gold": _series("2026-01-01", 200, -1.0),    # clearly down
         "dxy_proxy": _series("2026-01-01", 200, -0.5),
         "y10": pd.Series([4.0 + i * 0.01 for i in range(200)],
                          index=pd.date_range("2026-01-01", periods=200, freq="B"))}
    out = scoring.run(d, root=store)
    rows = {(r["asset"], r["horizon"]): r for r in led.read_lines("scores", store)}

    stocks = rows[("stocks", "h21")]
    assert stocks["outcome"] == "up"
    assert stocks["engine_hit"] is True
    assert stocks["persistence_hit"] is True
    assert stocks["naive_hit"] is True                 # always-up, and it rose

    gold = rows[("gold", "h21")]
    assert gold["outcome"] == "down"
    assert gold["engine_hit"] is False                 # engine expected up
    assert gold["persistence_hit"] is True             # trailing move was down
    assert gold["naive"] is None                       # always-up is stocks-only
    assert out["new"] == len(rows)


def test_scoring_is_idempotent(store):
    led.write_snapshot(_snapshot("2026-01-05"), store)
    d = {"spx": _series("2026-01-01", 200, 1.0)}
    first = scoring.run(d, root=store)["new"]
    second = scoring.run(d, root=store)["new"]
    assert first > 0 and second == 0


def test_scoring_uses_the_scorecard_bands_not_its_own():
    """A move inside the flat band must resolve sideways, at whatever the
    scorecard's band happens to be — never a hardcoded threshold here."""
    band = config.SCORECARD_FLAT_BAND["spx"]
    assert scoring.direction_of("spx", band * 0.5) == "sideways"
    assert scoring.direction_of("spx", band * 2) == "up"
    assert scoring.direction_of("spx", -band * 2) == "down"


# ---- baselines and gating -------------------------------------------------
def test_accuracy_cell_is_always_a_triple_with_n():
    rows = [{"engine_hit": True, "persistence_hit": False, "naive_hit": True}] * 25
    cell = scoring.accuracy_cell(rows)
    assert cell["n"] == 25 and cell["sufficient"]
    assert cell["engine"] == 100.0 and cell["persistence"] == 0.0
    assert cell["coin_flip"] == 50.0


def test_a_cell_with_n_below_the_minimum_is_withheld_not_shrunk():
    rows = [{"engine_hit": True, "persistence_hit": True, "naive_hit": True}] * (
        config.MIN_SAMPLE_N - 1)
    cell = scoring.accuracy_cell(rows)
    assert cell["n"] == config.MIN_SAMPLE_N - 1
    assert cell["sufficient"] is False
    assert "engine" not in cell, "a rate must not be readable below the gate"
    assert "insufficient" in cell["note"]


def test_n_equals_the_minimum_is_sufficient():
    rows = [{"engine_hit": True, "persistence_hit": True, "naive_hit": None}
            ] * config.MIN_SAMPLE_N
    cell = scoring.accuracy_cell(rows)
    assert cell["sufficient"] and cell["engine"] == 100.0
    assert cell["naive"] is None            # no naive baseline for this type


def test_calibration_cells_gate_at_the_same_n():
    snaps = [_snapshot(f"2026-01-{i:02d}", prob=0.60) for i in range(1, 6)]
    scores = [{"kind": "asset_direction", "horizon": "h63",
               "day": s["day"], "engine_hit": True} for s in snaps]
    cells = scoring.calibration(scores, snaps)
    bucket = next(c for c in cells if c["bucket"] == "0.55-0.70")
    assert bucket["n"] == 5 and not bucket["sufficient"]
    assert "observed" not in bucket


# ---- projections ----------------------------------------------------------
def test_projection_resolves_when_the_needle_changes():
    snaps = [_snapshot("2026-01-01", needle="expansion"),
             _snapshot("2026-02-01", needle="recovery")]
    out = scoring.resolve_projection_claims(snaps)
    assert len(out) == 1
    assert out[0]["engine"] == "recovery" and out[0]["outcome"] == "recovery"
    assert out[0]["engine_hit"] is True


def test_projection_expires_unresolved_after_the_window():
    snaps = [_snapshot("2026-01-01", needle="expansion"),
             _snapshot("2026-09-01", needle="expansion")]
    out = scoring.resolve_projection_claims(snaps)
    assert len(out) == 1
    assert out[0]["expired"] is True and out[0]["engine_hit"] is False


# ---- the weekly report ----------------------------------------------------
def test_report_renders_from_a_synthetic_ledger(store):
    led.write_snapshot(_snapshot("2026-01-05"), store)
    d = {"spx": _series("2026-01-01", 200, 1.0)}
    track = scoring.run(d, root=store)["track_record"]
    rep = wr.build(track, root=store)
    md = wr.render_markdown(rep)
    for heading in ("## 1. Headline", "## 2. Resolutions", "## 3. Divergence",
                    "## 4. Version ledger", "## 5. Reliability",
                    "## 6. Open calibration", "## 7. Suggested review"):
        assert heading in md, heading
    assert "insufficient" in md, "small samples must be visibly withheld"


def test_report_never_prints_a_rate_without_n_and_baselines():
    """The rule, enforced on the rendered markdown: any row showing a
    percentage must also show a sample size."""
    cell = {"n": 25, "sufficient": True, "engine": 61.0,
            "persistence": 64.0, "naive": 70.0}
    line = wr._cell_line("stocks · h21", cell)
    assert "61.0%" in line and "64.0%" in line and "70.0%" in line and "| 25 |" in line
    withheld = wr._cell_line("stocks · h63", {"n": 3, "sufficient": False})
    assert "%" not in withheld and "insufficient" in withheld


def test_review_section_stays_quiet_on_noise():
    below = {"by_asset": {"stocks": {"h21": {
        "n": config.MIN_SAMPLE_N, "sufficient": True,
        "engine": 60.0, "persistence": 70.0}}}}      # 10pp gap, under the line
    assert wr.review_items(below) == []

    over = {"by_asset": {"stocks": {"h21": {
        "n": config.MIN_SAMPLE_N, "sufficient": True,
        "engine": 50.0, "persistence": 70.0}}}}      # 20pp gap
    items = wr.review_items(over)
    assert len(items) == 1 and "trailing by 20.0pp" in items[0]


def test_review_ignores_a_big_gap_with_a_small_sample():
    noisy = {"by_asset": {"stocks": {"h21": {
        "n": 4, "sufficient": False, "engine_withheld": 25.0,
        "persistence_withheld": 100.0}}}}
    assert wr.review_items(noisy) == []


def test_calibration_issue_fetch_degrades_to_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise OSError("gh not installed")
    monkeypatch.setattr(wr.subprocess, "run", boom)
    issues, err = wr.open_calibration_issues()
    assert issues == [] and err
