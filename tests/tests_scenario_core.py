"""
Scenario-core tests (rewrite).

Two kinds of check:
  1. CLS HAND-CALC ORACLE — literal expected values computed independently by hand
     from the CLS fixture (tests_archive/stage4_state_cls).  This is the B7
     independent check: it proves the code implements the intended formulas, not
     merely that it reproduces its own prior output.
  2. RECONCILIATION INVARIANTS — structural guards that must hold BY CONSTRUCTION
     on every ticker (CLS + the 4 archive sentinels).  If any needs a clamp to
     hold, the model is wrong.

Run: pytest tests_scenario_core.py
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from run_methodology_math import run_methodology_math
from compute_methodology_v2 import (
    scenario_growth, scenario_margin, pe_bands, joint_probabilities,
)

_ARCHIVE = pathlib.Path(__file__).resolve().parent / "archive"
_DIRS = {
    "CLS":  _ARCHIVE / "stage4_state_cls",
    "AVGO": _ARCHIVE / "stage4_state",
    "NVDA": _ARCHIVE / "stage4_state_nvda",
    "KO":   _ARCHIVE / "stage4_state_ko",
    "ARLO": _ARCHIVE / "stage4_state_arlo",
}
_ALL = list(_DIRS)


def _load(ticker: str) -> tuple[dict, dict]:
    d = _DIRS[ticker]
    baseline = json.loads((d / "layer1_baseline.json").read_text())
    pass1 = json.loads((d / "layer2_pass1.json").read_text())
    assert baseline.get("ticker") == ticker
    return pass1, baseline


def _math(ticker: str) -> dict:
    p, b = _load(ticker)
    return run_methodology_math(p, b)


# ── 1. CLS HAND-CALC ORACLE ──────────────────────────────────────────────────
# Independently hand-computed from the fixture (base_growth capped at 0.40 —
# MAX_BASE_GROWTH raised from 0.35; forward-rebased segment revenue, rev-at-risk-
# weighted margins, peer-anchored P/E with quality_adj = 0.40/0.3122 = 1.2812,
# RERATE_PREMIUM 0.125 / DERATE_DISCOUNT 0.15 (halved), no franchise bear floor).
#
# Hand derivation of the two anchor numbers (peer_median_pe=21.25, peer_g=0.3122,
# segs CCS=8.2@0.45 / ATS=4.2@0.05, gbar=3.90/12.4=0.314516, tax=0.21,
# shares_proj=0.11497):
#   base rev  = 8.2·(1+0.40·1.4308)^2 + 4.2·(1+0.40·0.1590)^2 = 20.2716+4.7511 = 25.0227
#   base mgn  = (0.095·1.0+0.09·0.4+0.075·0.4)/1.8 = 0.161/1.8 = 0.089444
#   base EPS  = 25.0227 · 0.089444 · 0.79 / 0.11497 = 15.38
#   base P/E  = 21.25 · 1.2812 = 27.23   (bull=27.226·1.125=30.63, bear=27.226·0.85=23.14)
#   base tgt  = 15.3791 · 27.23 = 418.77

CLS_EXPECTED = {
    "base_growth":  0.40,
    "eps":   {"bull": 18.97,  "base": 15.38,  "bear": 7.85},
    "pe":    {"bull": 30.63,  "base": 27.23,  "bear": 23.14},
    "price": {"bull": 581.20, "base": 418.77, "bear": 181.62},
    "joint": {"bull": 0.2667, "base": 0.4833, "bear": 0.25},
    "ev": 402.80,
    "base_case_return": 0.1241,
    "recommendation": "WATCH",
}


def test_cls_hand_calc_oracle():
    m = _math("CLS")
    assert m["base_growth"] == pytest.approx(CLS_EXPECTED["base_growth"], abs=1e-9)
    for s in ("bull", "base", "bear"):
        assert m["scenario_eps"][s]   == pytest.approx(CLS_EXPECTED["eps"][s],   abs=0.01), f"eps {s}"
        assert m["pe_points"][s]      == pytest.approx(CLS_EXPECTED["pe"][s],    abs=0.01), f"pe {s}"
        assert m["price_target"][s]   == pytest.approx(CLS_EXPECTED["price"][s], abs=0.05), f"price {s}"
        assert m["joint_probs"][s]    == pytest.approx(CLS_EXPECTED["joint"][s], abs=0.001), f"joint {s}"
    assert m["expected_value"]   == pytest.approx(CLS_EXPECTED["ev"], abs=0.05)
    assert m["base_case_return"] == pytest.approx(CLS_EXPECTED["base_case_return"], abs=0.001)
    assert m["recommendation"]   == CLS_EXPECTED["recommendation"]


def test_cls_is_not_a_franchise_no_bear_floor():
    """CLS: high ROE but thin (12%) gross margin ⇒ franchise_quality False ⇒ the
    bear P/E is a pure peer-derate (≈16.7×), NOT floored at 25×."""
    _, b = _load("CLS")
    assert b["franchise_quality"] is False
    m = _math("CLS")
    assert m["pe_points"]["bear"] < 25.0
    assert any("no 25× bear P/E floor" in line for line in m["calibration_log"])


def test_cls_bull_not_3x_base():
    """The original bug: bull EPS was ~3× base with no economic link.  Now bull
    and base share a revenue basis, so the ratio is economically modest."""
    m = _math("CLS")
    ratio = m["scenario_eps"]["bull"] / m["scenario_eps"]["base"]
    assert 1.1 < ratio < 1.8, f"bull/base EPS ratio {ratio:.2f} implausible"


def test_cls_reverse_dcf_flagged_unstable():
    """CLS FCF yield ~1.1% (<2%) ⇒ implied CAGR flagged unstable, not printed raw."""
    m = _math("CLS")
    assert m["reverse_dcf_unstable"] is True
    assert isinstance(m["implied_fcf_cagr"], float)
    # whole-percent rounding: never a 6-decimal artifact
    assert round(m["implied_fcf_cagr"], 2) == m["implied_fcf_cagr"]


# ── 2. RECONCILIATION INVARIANTS (all tickers) ───────────────────────────────

@pytest.mark.parametrize("ticker", _ALL)
def test_price_hierarchy_holds_without_clamp(ticker):
    """bull_mid > base_mid > bear_mid must hold BY CONSTRUCTION."""
    m = _math(ticker)
    pt = m["price_target"]
    assert pt["bull"] > pt["base"] > pt["bear"], f"{ticker}: {pt}"
    # no calibration_log entry ever forces the hierarchy (no clamp-on-clamp)
    assert not any("hierarchy" in line.lower() and "cap" in line.lower()
                   for line in m["calibration_log"])


@pytest.mark.parametrize("ticker", _ALL)
def test_ev_single_source_of_truth(ticker):
    """The headline EV must equal Σ joint_prob × price_mid recomputed from the
    same fields — no second EV can diverge."""
    m = _math(ticker)
    jp, pt = m["joint_probs"], m["price_target"]
    recomputed = round(sum(jp[s] * pt[s] for s in ("bull", "base", "bear")), 2)
    assert abs(m["expected_value"] - recomputed) < 0.02, f"{ticker}: {m['expected_value']} vs {recomputed}"


@pytest.mark.parametrize("ticker", _ALL)
def test_joint_probs_sum_to_one(ticker):
    m = _math(ticker)
    assert abs(sum(m["joint_probs"].values()) - 1.0) < 0.001


@pytest.mark.parametrize("ticker", _ALL)
def test_joint_probs_track_driver_direction(ticker):
    """No hidden skew: the joint distribution's lean matches the driver-average
    lean (a bull-leaning driver set cannot produce a bear-heavy joint)."""
    p, _ = _load(ticker)
    dp = joint_probabilities(
        {k: v for k, v in __import__("compute_methodology_v2")
              .driver_outcome_probabilities(p.get("events", [])).items()}
    )
    m = _math(ticker)
    # argmax of joint equals argmax of the transparent mean (identical by design)
    assert max(m["joint_probs"], key=m["joint_probs"].get) == max(dp, key=dp.get)


@pytest.mark.parametrize("ticker", _ALL)
def test_segment_table_reconciles_with_scenario_revenue(ticker):
    """When a segment table exists, its per-scenario totals equal the EPS chain's
    scenario_revenue (single revenue basis)."""
    m = _math(ticker)
    ssr = m.get("scenario_segment_revenue")
    if not ssr:
        pytest.skip(f"{ticker}: no segment table")
    for s in ("bull", "base", "bear"):
        seg_sum = round(sum(row[s] for row in ssr["segments"]), 4)
        assert seg_sum == pytest.approx(m["scenario_revenue"][s], abs=0.01), f"{ticker} {s}"


# ── 3. Unit tests for the new pure functions ─────────────────────────────────

def test_scenario_growth_bear_may_contract():
    """No lower floor: heavy bear revenue-at-risk can drive growth negative."""
    events = [{"driver": "C", "outcome": "bear", "probability": 0.5,
               "revenue_at_risk_low": 8.0, "revenue_at_risk_high": 12.0}]
    g = scenario_growth(0.05, 10.0, events, "bear", horizon=2)
    assert g < 0.0, f"bear growth {g} should be able to go negative"


def test_scenario_growth_upper_clamped():
    g = scenario_growth(0.35, 100.0, [], "bull", horizon=2)
    from compute import MAX_SCENARIO_GROWTH
    assert g <= MAX_SCENARIO_GROWTH + 1e-9


def test_pe_bands_no_peer_fallback_bounded():
    pe = pe_bands(0.50, franchise_quality=False, peer_median_pe=None)
    from compute import NO_PEER_PE_MAX, BULL_PE_CEILING
    assert pe["source"] == "no_peer_fallback"
    assert pe["base"] <= NO_PEER_PE_MAX
    assert pe["bull"] <= BULL_PE_CEILING


def test_pe_bands_franchise_gets_bear_floor():
    pe = pe_bands(0.20, franchise_quality=True, peer_median_pe=30.0, peer_median_growth=0.20)
    assert pe["bear"] >= 25.0


def test_pe_bands_non_franchise_no_floor():
    pe = pe_bands(0.20, franchise_quality=False, peer_median_pe=22.0, peer_median_growth=0.20)
    assert pe["bear"] < 25.0


def test_pe_bands_low_multiple_franchise_floor_suppressed():
    """A low-multiple franchise (base_pe < 25) must NOT get the 25× bear floor —
    that would invert bear > bull.  Hierarchy must hold."""
    pe = pe_bands(0.05, franchise_quality=True, peer_median_pe=None)  # no peers → low base_pe
    assert pe["base"] < 25.0
    assert pe["bull"] > pe["base"] > pe["bear"], pe


def test_joint_probabilities_no_multiplier_inversion():
    """A bull-leaning driver set stays bull-leaning (the old 3.0/4.5 multipliers
    inverted this into bear-heavy)."""
    driver_probs = {"A": {"bull": 0.6, "base": 0.3, "bear": 0.1}}
    jp = joint_probabilities(driver_probs)
    assert jp["bull"] > jp["bear"]
    assert jp == {"bull": 0.6, "base": 0.3, "bear": 0.1}


def test_scenario_margin_weighted_by_rev_at_risk():
    events = [
        {"outcome": "bull", "op_margin_to_apply": 0.20, "revenue_at_risk_low": 1.0, "revenue_at_risk_high": 3.0},
        {"outcome": "bull", "op_margin_to_apply": 0.10, "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 2.0},
    ]
    m = scenario_margin(0.15, events, "bull")
    # weights 2.0 and 1.0 -> (0.20*2 + 0.10*1)/3 = 0.1667
    assert m == pytest.approx(0.16667, abs=1e-4)
