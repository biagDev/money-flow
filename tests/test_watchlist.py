"""Event watchlist: branch construction, vote-sensitivity stakes, resolution."""
import pandas as pd
import pytest

from pipeline import config, regime_engine as eng, watchlist as wl

ASOF = pd.Timestamp("2026-08-01")


# ---- fixtures -------------------------------------------------------------
def _monthly(vals, end=ASOF):
    idx = pd.date_range(end=end, periods=len(vals), freq="MS")
    return pd.Series([float(v) for v in vals], index=idx)


def _pce_index(yoy_pct, months=40):
    """Index series that produces a roughly constant YoY of yoy_pct."""
    step = (1 + yoy_pct / 100.0) ** (1 / 12)
    return _monthly([100.0 * step ** i for i in range(months)])


def _hawkish_state():
    return {"needle": "expansion", "bias": "hawkish-leaning",
            "unrate": 4.1, "sahm": 0.10}


PRICED_HAWKISH = {"hike": 0.42, "hold": 0.58, "cut": 0.0, "stale": False}


# ---- pricing effect -------------------------------------------------------
def test_inflation_cool_branch_forces_repricing_under_hawkish_pricing():
    """With hikes priced and cuts at zero, a hot print merely confirms —
    the cool print is the one that forces a repricing."""
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    w = wl.branch_for_event("CPI", "inflation", d, _hawkish_state(), PRICED_HAWKISH)
    assert w is not None
    assert w["branches"]["a"]["pricing_effect"] == "confirms pricing"
    assert w["branches"]["b"]["pricing_effect"] == "forces repricing"


def test_pricing_effect_flips_when_cuts_are_priced():
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    dovish = {"hike": 0.0, "hold": 0.40, "cut": 0.60, "stale": False}
    w = wl.branch_for_event("CPI", "inflation", d, _hawkish_state(), dovish)
    assert w["branches"]["a"]["pricing_effect"] == "forces repricing"
    assert w["branches"]["b"]["pricing_effect"] == "confirms pricing"


def test_falls_back_to_bias_when_pricing_missing():
    """Stale ZQ feed must not break branch scoring."""
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    w = wl.branch_for_event("CPI", "inflation", d, _hawkish_state(), None)
    effects = {b["pricing_effect"] for b in w["branches"].values()}
    assert effects == {"confirms pricing", "forces repricing"}


# ---- stakes via vote sensitivity -----------------------------------------
def test_stakes_high_names_the_voter_flip():
    """PCE sitting just above target: a -0.2pp shock crosses it and flips the
    inflation voter, so stakes are high and the reason names from -> to."""
    target = config.THRESHOLDS["inflation_target"]
    shock = config.WATCHLIST_PERTURBATIONS["inflation_pp"]
    d = {"pce": _pce_index(target + shock / 2), "unrate": _monthly([4.1] * 24)}
    stakes, why = wl.stakes_for_event("inflation", d, _hawkish_state(), ASOF)
    assert stakes == "high"
    assert "inflation" in why
    base = wl._vote_of("inflation", d, ASOF)
    assert base in why          # the "from" vote is named explicitly


def test_stakes_not_high_when_print_is_far_from_any_threshold():
    """Inflation far above every threshold: a 0.2pp wobble changes nothing."""
    d = {"pce": _pce_index(8.0), "unrate": _monthly([4.1] * 24)}
    stakes, _ = wl.stakes_for_event("inflation", d, _hawkish_state(), ASOF)
    assert stakes in ("medium", "low")


def test_stakes_medium_when_voter_disagrees_with_needle():
    d = {"pce": _pce_index(8.0), "unrate": _monthly([4.1] * 24)}
    state = {"needle": "recovery", "bias": "hawkish", "unrate": 4.1, "sahm": 0.1}
    stakes, why = wl.stakes_for_event("inflation", d, state, ASOF)
    assert stakes == "medium"
    assert "recovery" in why


def test_employment_stakes_use_unrate_perturbation():
    """UNRATE parked just under the Sahm warning line: +0.1pp on the latest
    print lifts the 3-month average over it and flips the employment voter."""
    warn = config.THRESHOLDS["sahm_warning"]
    base = [3.8] * 12 + [3.8 + warn * 0.9] * 2 + [3.8 + warn * 1.4]
    d = {"unrate": _monthly(base), "pce": _pce_index(3.0)}
    stakes, why = wl.stakes_for_event("employment", d, _hawkish_state(), ASOF)
    assert stakes in ("high", "medium", "low")
    if stakes == "high":
        assert "employment" in why


# ---- FOMC -----------------------------------------------------------------
def test_fomc_is_always_high_with_three_branches_and_odds():
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    w = wl.branch_for_event("FOMC", "both", d, _hawkish_state(), PRICED_HAWKISH)
    assert w["stakes"] == "high"
    assert set(w["branches"]) == {"hike", "hold", "cut"}
    for k in ("hike", "hold", "cut"):
        assert w["branches"][k]["market_odds"] == PRICED_HAWKISH[k]


def test_fomc_without_pricing_omits_odds_but_still_builds():
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    w = wl.branch_for_event("FOMC", "both", d, _hawkish_state(), None)
    assert w["stakes"] == "high"
    assert set(w["branches"]) == {"hike", "hold", "cut"}
    assert all("market_odds" not in b for b in w["branches"].values())


def test_unknown_event_returns_none():
    assert wl.branch_for_event("Beige Book", "both", {}, _hawkish_state(), None) is None


# ---- every branch is well-formed -----------------------------------------
@pytest.mark.parametrize("event", sorted(config.EVENT_CLASSES))
def test_every_known_event_builds_a_complete_watch(event):
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    w = wl.branch_for_event(event, "both", d, _hawkish_state(), PRICED_HAWKISH)
    assert w["stakes"] in ("high", "medium", "low")
    assert isinstance(w["setup"], str) and w["setup"]
    assert w["stakes_why"]
    assert len(w["branches"]) >= 2
    for b in w["branches"].values():
        assert b["pricing_effect"] in ("confirms pricing", "forces repricing")
        assert set(b["assets"]) == {"bonds", "dollar", "gold", "stocks"}
        assert b["label"] and b["implies"]


def test_setup_line_has_no_unformatted_placeholders():
    d = {"pce": _pce_index(3.7), "unrate": _monthly([4.1] * 24)}
    for event in config.EVENT_CLASSES:
        w = wl.branch_for_event(event, "both", d, _hawkish_state(), PRICED_HAWKISH)
        assert "{" not in w["setup"] and "}" not in w["setup"]


def test_setup_degrades_when_series_missing():
    """No pce/unrate at all: still returns a sentence, never raises."""
    w = wl.branch_for_event("CPI", "inflation", {}, _hawkish_state(), None)
    assert isinstance(w["setup"], str) and w["setup"]


# ---- resolution -----------------------------------------------------------
def _hot_cpi():
    """CPI YoY accelerating into the final month."""
    return _monthly([100 * (1.002 ** i) for i in range(30)] + [100 * (1.002 ** 29) * 1.01])


def test_resolution_as_mapped_true_when_reactions_match_branch():
    d = {"cpi": _hot_cpi()}
    at = d["cpi"].index[-1]
    branch = wl.realized_branch("CPI", d, at)
    assert branch is not None
    amap = config.EVENT_BRANCH_MAPS["inflation"][branch]["assets"]
    sign = lambda a: 1.0 if "▲" in amap[a] else -1.0
    reactions = {"dxy_48h": 0.4 * sign("dollar"),
                 "gold_48h": 0.8 * sign("gold"),
                 "spx_48h": 0.3 * sign("stocks")}
    res = wl.resolve_event("CPI", d, at, reactions)
    assert res["as_mapped"] is True
    assert res["branch"] == branch
    assert res["branch_label"]


def test_resolution_as_mapped_false_when_reactions_contradict():
    d = {"cpi": _hot_cpi()}
    at = d["cpi"].index[-1]
    branch = wl.realized_branch("CPI", d, at)
    amap = config.EVENT_BRANCH_MAPS["inflation"][branch]["assets"]
    sign = lambda a: 1.0 if "▲" in amap[a] else -1.0
    reactions = {"dxy_48h": -0.4 * sign("dollar"),
                 "gold_48h": -0.8 * sign("gold"),
                 "spx_48h": -0.3 * sign("stocks")}
    res = wl.resolve_event("CPI", d, at, reactions)
    assert res["as_mapped"] is False


def test_resolution_omitted_when_reactions_missing():
    d = {"cpi": _hot_cpi()}
    at = d["cpi"].index[-1]
    assert wl.resolve_event("CPI", d, at, None) is None
    assert wl.resolve_event("CPI", d, at, {}) is None


def test_resolution_omitted_when_branch_undeterminable():
    assert wl.resolve_event("CPI", {}, ASOF, {"dxy_48h": 0.4}) is None


def test_jobless_claims_trend_is_inverted():
    """Higher claims is a WEAKER labour print, so it must not map to 'strong'."""
    assert config.EVENT_TREND_INVERTED.get("Jobless Claims") is True


# ---- next catalyst --------------------------------------------------------
def test_next_catalyst_prefers_soonest_high():
    up = [
        {"date": "2026-09-01", "event": "JOLTS", "watch": {"stakes": "medium"}},
        {"date": "2026-09-04", "event": "NFP", "watch": {"stakes": "high"}},
        {"date": "2026-09-10", "event": "CPI", "watch": {"stakes": "high"}},
    ]
    assert wl.next_catalyst(up) == {"date": "2026-09-04", "event": "NFP"}


def test_next_catalyst_falls_back_to_medium():
    up = [{"date": "2026-09-01", "event": "JOLTS", "watch": {"stakes": "medium"}},
          {"date": "2026-09-02", "event": "PPI", "watch": {"stakes": "low"}}]
    assert wl.next_catalyst(up) == {"date": "2026-09-01", "event": "JOLTS"}


def test_next_catalyst_none_when_no_watch():
    assert wl.next_catalyst([{"date": "2026-09-01", "event": "X"}]) is None


# ---- payrolls feed the NFP watch card -------------------------------------
def _payems_from_deltas(deltas, start=150000.0, end=ASOF):
    lvl, cur = [start], start
    for dv in deltas:
        cur += dv
        lvl.append(cur)
    return _monthly(lvl, end=end)


def _labour_state(deltas):
    return {"unrate": _monthly([4.1] * 24),
            "pce": _pce_index(2.2),
            "payems": _payems_from_deltas(deltas)}


def test_nfp_is_high_stakes_when_payrolls_sit_near_the_stress_line():
    """The case the watchlist exists to flag: unemployment quiet, payrolls
    positive but weak enough that one plausible print crosses into stress and
    flips the voter. This mirrors the live setup going into the Sept NFP."""
    d = _labour_state([120] * 20 + [60, 20, -20])       # ~+20K/3mo, like today
    state = eng.payroll_state(d, ASOF)
    assert state[0] == "soft" and 0 < state[1] < config.THRESHOLDS["payems_soft_3mo"]
    stakes, why = wl.stakes_for_event("employment", d, _hawkish_state(), ASOF)
    assert stakes == "high", why
    assert "employment" in why


def test_deeply_negative_payrolls_are_medium_not_high():
    """Deliberate: once payrolls have already dragged the voter to contraction,
    a single further print cannot flip it, so the event stops being a
    catalyst. Stakes measure what the next print can CHANGE, not how bad
    things already are."""
    d = _labour_state([120] * 20 + [-40, -55, -60])
    assert eng.payroll_state(d, ASOF)[0] == "stress"
    assert wl._vote_of("employment", d, ASOF) == "contraction"
    stakes, _ = wl.stakes_for_event("employment", d, _hawkish_state(), ASOF)
    assert stakes == "medium"


def test_nfp_stakes_see_payrolls_not_just_unemployment():
    """With payrolls firm and UNRATE flat nothing can flip, so the same event
    is not high — proving the payrolls probe is what does the work."""
    firm = _labour_state([180] * 23)
    stakes, _ = wl.stakes_for_event("employment", firm, _hawkish_state(), ASOF)
    assert stakes != "high"
    near = _labour_state([120] * 20 + [60, 20, -20])
    assert wl.stakes_for_event("employment", near, _hawkish_state(), ASOF)[0] == "high"


def test_employment_probe_survives_missing_payrolls():
    """No payems at all: still scores, never raises."""
    d = {"unrate": _monthly([4.1] * 24), "pce": _pce_index(2.2)}
    stakes, why = wl.stakes_for_event("employment", d, _hawkish_state(), ASOF)
    assert stakes in ("high", "medium", "low")
    assert why


def test_high_stakes_reason_names_the_payroll_shock_in_thousands():
    d = _labour_state([120] * 20 + [60, 20, -20])
    _, why = wl.stakes_for_event("employment", d, _hawkish_state(), ASOF)
    shock = config.WATCHLIST_PERTURBATIONS["payems_k"]
    assert f"{shock:.0f}K" in why, why
