"""Regime engine unit tests on synthetic macro states.

Each test constructs series that unambiguously represent a regime and asserts
the needle lands there. These are the guardrails: tuning config.py must keep
them green. (Live golden-date backtests get added after the first real
`--backtest` run — see README step 6.)
"""
import numpy as np
import pandas as pd
import pytest

from pipeline import regime_engine as eng

ASOF = pd.Timestamp("2026-08-01")


def _monthly(vals, end=ASOF):
    idx = pd.date_range(end=end, periods=len(vals), freq="MS")
    return pd.Series(vals, index=idx, dtype=float)


def _daily(vals, end=ASOF):
    idx = pd.date_range(end=end, periods=len(vals), freq="D")
    return pd.Series(vals, index=idx, dtype=float)


def _weekly(vals, end=ASOF):
    idx = pd.date_range(end=end, periods=len(vals), freq="7D")
    return pd.Series(vals, index=idx, dtype=float)


def make_state(*, pce_yoy_path, unrate_path, target_path, spread_path, walcl_path):
    """Build a data dict from intent-level paths."""
    # PCE index whose YoY equals the requested path (approx): build cumulatively
    yoy = np.array(pce_yoy_path) / 100.0
    idx_vals = [100.0] * 12
    for y in yoy:
        idx_vals.append(idx_vals[-12] * (1 + y))
    return {
        "pce": _monthly(idx_vals),
        "unrate": _monthly(unrate_path),
        "fed_target_upper": _daily(target_path),
        "spread_10y3m": _daily(spread_path),
        "walcl": _weekly(walcl_path),
    }


def test_peak_state():
    """Hot rising inflation, tight labor, hiking, flattening curve, QT."""
    d = make_state(
        pce_yoy_path=[2.0 + 0.08 * i for i in range(36)],          # 2.0 -> 4.8, rising
        unrate_path=[4.0] * 36,                                     # no stress
        target_path=[3.0] * 300 + [3.25] * 200 + [3.5] * 230,       # two hikes
        spread_path=list(np.linspace(1.5, 0.2, 730)),               # flattening
        walcl_path=list(np.linspace(8000, 7500, 156)),              # QT
    )
    r = eng.compute(d, ASOF)
    assert r["needle"] == "peak", r["probabilities"]


def test_contraction_state():
    """Sahm triggered, curve steepening after inversion, cuts starting."""
    d = make_state(
        pce_yoy_path=[4.0 - 0.06 * i for i in range(36)],           # falling inflation
        unrate_path=[3.5] * 24 + [3.6, 3.7, 3.9, 4.0, 4.1, 4.2,
                                  4.3, 4.4, 4.5, 4.6, 4.7, 4.8],    # breaking higher
        target_path=[5.5] * 400 + [5.25] * 200 + [5.0] * 130,       # two cuts
        spread_path=list(np.linspace(0.5, -0.9, 400)) + list(np.linspace(-0.9, 0.4, 330)),
        walcl_path=list(np.linspace(8000, 7700, 156)),
    )
    r = eng.compute(d, ASOF)
    assert r["needle"] in ("contraction", "recovery"), r["probabilities"]
    assert r["probabilities"]["contraction"] > r["probabilities"]["peak"]


def test_recovery_state():
    """Low/rising-from-below inflation, cuts done, QE, steep curve."""
    d = make_state(
        pce_yoy_path=[0.8 + 0.03 * i for i in range(36)],           # below target, rising
        unrate_path=[6.5 - 0.05 * i for i in range(36)],            # healing but off lows... keep gap small
        target_path=[0.25] * 730,                                   # on hold at floor
        spread_path=list(np.linspace(0.3, 2.0, 730)),               # steep, no recent inversion
        walcl_path=list(np.linspace(7000, 8500, 156)),              # QE
    )
    r = eng.compute(d, ASOF)
    assert r["needle"] in ("recovery", "expansion"), r["probabilities"]


def test_expansion_state():
    """At-target-ish inflation, tight labor, normal steep curve, mild QE."""
    d = make_state(
        pce_yoy_path=[1.8] * 36,
        unrate_path=[3.8] * 36,
        target_path=[2.0] * 730,
        spread_path=[1.6] * 730,
        walcl_path=list(np.linspace(8000, 8100, 156)),
    )
    r = eng.compute(d, ASOF)
    assert r["needle"] == "expansion", r["probabilities"]


def test_votes_are_distributions():
    d = make_state(pce_yoy_path=[2.5] * 36, unrate_path=[4.0] * 36,
                   target_path=[3.0] * 730, spread_path=[1.0] * 730,
                   walcl_path=[8000.0] * 156)
    r = eng.compute(d, ASOF)
    for s in r["scores"]:
        assert abs(sum(s["distribution"].values()) - 1.0) < 1e-6
    assert abs(sum(r["probabilities"].values()) - 1.0) < 1e-6


def test_missing_data_degrades_gracefully():
    r = eng.compute({}, ASOF)
    assert set(r["probabilities"]) == {"expansion", "peak", "contraction", "recovery"}
    assert abs(sum(r["probabilities"].values()) - 1.0) < 1e-6
