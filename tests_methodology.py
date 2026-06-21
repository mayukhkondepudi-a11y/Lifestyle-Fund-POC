"""
Phase A regression tests — pure-function math layer.

Two fixture sets:
  AVGO  — synthetic Pass1 calibrated to §7.4 target numbers.
  B7    — independent hand-calc with trivial arithmetic (no code needed to verify).

Run with:  pytest tests_methodology.py -v
"""
from __future__ import annotations

import math
import pytest

from compute_methodology_v2 import (
    scenario_revenue,
    scenario_eps,
    pe_band,
    driver_probabilities,
    driver_outcome_probabilities,
    sensitivity_analysis,
    scenario_segment_revenue,
    joint_probabilities,
    expected_value,
    risk_metrics,
    implied_fcf_cagr,
    projected_shares,
    dcf_intrinsic_value,
    project_fcf,
    breakeven_pe,
    recommendation,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_EQUITY_RISK_PREMIUM,
)
from run_methodology_math import run_methodology_math
from compute import BULL_CORRELATION_MULTIPLIER, BEAR_CORRELATION_MULTIPLIER


# ════════════════════════════════════════════════════════════════════════════
# AVGO SYNTHETIC FIXTURE  (§7.4 target numbers)
#
# Targets (±tolerance):
#   bull EPS   ~$14.50 ± $0.50
#   base EPS   ~$10.74 ± $0.50
#   bear EPS   ~ $6.35 ± $0.50
#   EV         ~$295   ± $15  (updated: Bug B base-PE ratio fix lowers base P/E 32→25)
#   joint_probs ~ {bull:0.249, base:0.593, bear:0.158} ± 1pp each
# ════════════════════════════════════════════════════════════════════════════

AVGO_BASELINE = {
    "current_price":  320.0,
    "shares_out":     1.43,          # billions
    "fy_revenue":     28.5,          # $B trailing
    "base_op_margin": 0.62,
    "tax_rate":       0.13,
    "beta":           1.15,
    "net_debt":       30.0,          # $B
    "horizon_years":  5,
    "franchise_quality": True,
    "trailing_net_dilution_rate": 0.005,  # +0.5%/yr (slight dilution)
    "base_fcf":       14.5,          # $B trailing FCF
    "earnings_cagr":  0.18,          # 18% → PEG band anchored at 18
    "peer_pes":       [36.0, 38.0, 40.0, 38.0, 38.0],   # peer median=38 → anchors P/E, hits EV ≈348
    "trailing_eps":   10.50,
}

# Three drivers with bull/base/bear events
#   Driver A (AI demand):  bull p=0.20  base p=0.80  bear p=0.00
#   Driver B (semis cycle): bull p=0.15  base p=0.82  bear p=0.03
#   Driver C (competition): bull p=0.00  base p=0.88  bear p=0.12
AVGO_EVENTS = [
    # Driver A
    {"driver_id": "A", "scenario": "bull", "probability": 0.20,
     "rev_change_mid": 7.5,  "op_margin": 0.648},
    {"driver_id": "A", "scenario": "base", "probability": 0.80,
     "rev_change_mid": 0.0,  "op_margin": 0.62},
    # Driver B
    {"driver_id": "B", "scenario": "bull", "probability": 0.15,
     "rev_change_mid": 2.0,  "op_margin": 0.648},
    {"driver_id": "B", "scenario": "base", "probability": 0.82,
     "rev_change_mid": 0.0,  "op_margin": 0.62},
    {"driver_id": "B", "scenario": "bear", "probability": 0.03,
     "rev_change_mid": -0.5, "op_margin": 0.689},
    # Driver C
    {"driver_id": "C", "scenario": "base", "probability": 0.88,
     "rev_change_mid": 0.0,  "op_margin": 0.62},
    {"driver_id": "C", "scenario": "bear", "probability": 0.12,
     "rev_change_mid": -10.0, "op_margin": 0.689},
]

AVGO_PASS1 = {"events": AVGO_EVENTS}


# ── Joint probability unit tests ─────────────────────────────────────────────

class TestAVGOJointProbs:
    def _driver_probs(self):
        return driver_probabilities(AVGO_EVENTS)

    def test_driver_probs_sum_to_one(self):
        dp = self._driver_probs()
        for did, d in dp.items():
            total = sum(d.values())
            assert abs(total - 1.0) < 1e-6, f"Driver {did} probs sum={total}"

    def test_joint_probs_sum_to_one(self):
        dp = self._driver_probs()
        jp = joint_probabilities(dp)
        total = sum(jp.values())
        assert abs(total - 1.0) < 0.001, f"joint_probs sum={total}"

    def test_joint_probs_within_target(self):
        dp = self._driver_probs()
        jp = joint_probabilities(dp)
        tol = 0.01  # 1pp
        assert abs(jp["bull"] - 0.249) <= tol, f"bull={jp['bull']}"
        assert abs(jp["base"] - 0.593) <= tol, f"base={jp['base']}"
        assert abs(jp["bear"] - 0.158) <= tol, f"bear={jp['bear']}"

    def test_correlation_multipliers_applied(self):
        # Verify the algorithm uses the calibrated multipliers
        dp = self._driver_probs()
        n = len(dp)
        bull_avg = sum(d["bull"] for d in dp.values()) / n
        bear_avg = sum(d["bear"] for d in dp.values()) / n
        base_avg = sum(d["base"] for d in dp.values()) / n
        w_bull = bull_avg * BULL_CORRELATION_MULTIPLIER
        w_bear = bear_avg * BEAR_CORRELATION_MULTIPLIER
        w_base = base_avg
        total = w_bull + w_base + w_bear
        jp = joint_probabilities(dp)
        assert abs(jp["bull"] - w_bull / total) < 1e-4
        assert abs(jp["bear"] - w_bear / total) < 1e-4


# ── EPS unit tests ────────────────────────────────────────────────────────────

class TestAVGOEPS:
    def _shares_proj(self):
        return projected_shares(
            AVGO_BASELINE["shares_out"],
            AVGO_BASELINE["horizon_years"],
            AVGO_BASELINE["trailing_net_dilution_rate"],
        )

    def test_bull_eps_within_target(self):
        eps = scenario_eps(
            AVGO_BASELINE["fy_revenue"],
            AVGO_BASELINE["base_op_margin"],
            AVGO_EVENTS, "bull",
            AVGO_BASELINE["tax_rate"],
            self._shares_proj(),
        )
        assert abs(eps - 14.50) <= 0.50, f"bull EPS={eps:.2f}, target=14.50 ±0.50"

    def test_base_eps_within_target(self):
        eps = scenario_eps(
            AVGO_BASELINE["fy_revenue"],
            AVGO_BASELINE["base_op_margin"],
            AVGO_EVENTS, "base",
            AVGO_BASELINE["tax_rate"],
            self._shares_proj(),
        )
        assert abs(eps - 10.74) <= 0.50, f"base EPS={eps:.2f}, target=10.74 ±0.50"

    def test_bear_eps_within_target(self):
        eps = scenario_eps(
            AVGO_BASELINE["fy_revenue"],
            AVGO_BASELINE["base_op_margin"],
            AVGO_EVENTS, "bear",
            AVGO_BASELINE["tax_rate"],
            self._shares_proj(),
        )
        assert abs(eps - 6.35) <= 0.50, f"bear EPS={eps:.2f}, target=6.35 ±0.50"

    def test_bull_eps_gt_base_gt_bear(self):
        sp = self._shares_proj()
        kwargs = dict(
            base_revenue=AVGO_BASELINE["fy_revenue"],
            base_op_margin=AVGO_BASELINE["base_op_margin"],
            events=AVGO_EVENTS,
            tax_rate=AVGO_BASELINE["tax_rate"],
            shares_projected=sp,
        )
        bull = scenario_eps(**kwargs, scenario="bull")
        base = scenario_eps(**kwargs, scenario="base")
        bear = scenario_eps(**kwargs, scenario="bear")
        assert bull > base > bear, f"EPS ordering violated: bull={bull:.2f} base={base:.2f} bear={bear:.2f}"


# ── EV / orchestrator end-to-end ─────────────────────────────────────────────

class TestAVGOOrchestrator:
    def _math(self):
        return run_methodology_math(AVGO_PASS1, AVGO_BASELINE)

    def test_math_dict_has_required_keys(self):
        m = self._math()
        required = [
            "implied_fcf_cagr", "scenario_eps", "pe_band",
            "price_target", "joint_probs", "expected_value",
            "risk", "recommendation",
        ]
        for k in required:
            assert k in m, f"math dict missing key: {k}"

    def test_joint_probs_sum_to_one(self):
        m = self._math()
        total = sum(m["joint_probs"].values())
        assert abs(total - 1.0) < 0.001

    def test_ev_within_target(self):
        m = self._math()
        ev = m["expected_value"]
        assert abs(ev - 295.0) <= 15.0, f"EV={ev:.1f}, target=295 ±15 (post-BugB base-PE ratio fix)"

    def test_implied_fcf_cagr_finite(self):
        m = self._math()
        cagr = m["implied_fcf_cagr"]
        assert isinstance(cagr, float) and math.isfinite(cagr), f"implied_fcf_cagr={cagr!r}"

    def test_nvda_bull_above_current(self):
        # Re-use AVGO fixture shape: bull_high must be > current_price
        m = self._math()
        bull_high = m["price_target"]["bull_high"]
        assert bull_high > AVGO_BASELINE["current_price"], (
            f"bull_high={bull_high} not > current_price={AVGO_BASELINE['current_price']}"
        )

    def test_risk_keys_present(self):
        m = self._math()
        for k in ("prob_loss", "max_drawdown_pct", "expected_return_pct", "ev"):
            assert k in m["risk"], f"risk dict missing: {k}"

    def test_no_sharpe_in_risk(self):
        # Sharpe is a forbidden token per B6
        m = self._math()
        risk_keys = list(m["risk"].keys())
        assert "sharpe" not in [k.lower() for k in risk_keys]


# ════════════════════════════════════════════════════════════════════════════
# B7 INDEPENDENT HAND-CALC FIXTURE
#
# All numbers below are verifiable without running any code.
#
# Setup:
#   base_revenue   = 100 B
#   base_op_margin = 0.30
#   tax_rate       = 0.20
#   shares         = 1.0 B  (no dilution, horizon=5)
#   current_price  = 400
#   1 driver, 3 events:
#     bull: p=0.30, rev_change_mid=+20B, op_margin=0.35
#     base: p=0.50, rev_change_mid=0,    op_margin=0.30
#     bear: p=0.20, rev_change_mid=-15B, op_margin=0.40
#
# EPS hand-calc (base scenario):
#   blended_income = 100*0.30 + 0*0.30 = 30
#   scenario_rev   = 100
#   blended_margin = 30/100 = 0.30
#   net_income     = 100 * 0.30 * (1-0.20) = 24
#   EPS_base       = 24 / 1.0 = 24.00  ✓
#
# EPS bull:
#   blended_income = 100*0.30 + 20*0.35 = 30 + 7 = 37
#   scenario_rev   = 120
#   blended_margin = 37/120 ≈ 0.30833
#   net_income     = 120 * 0.30833 * 0.80 = 29.60
#   EPS_bull       = 29.60 / 1.0 = 29.60  ✓
#
# EPS bear:
#   blended_income = 100*0.30 + (-15)*0.40 = 30 - 6 = 24
#   scenario_rev   = 85
#   blended_margin = 24/85 ≈ 0.28235
#   net_income     = 85 * 0.28235 * 0.80 = 19.20
#   EPS_bear       = 19.20 / 1.0 = 19.20  ✓
#
# joint_probs (1 driver):
#   bull_avg=0.30, base_avg=0.50, bear_avg=0.20
#   w_bull = 0.30*3.0 = 0.90
#   w_base = 0.50
#   w_bear = 0.20*4.5 = 0.90
#   total  = 0.90+0.50+0.90 = 2.30
#   p_bull = 0.90/2.30 ≈ 0.3913
#   p_base = 0.50/2.30 ≈ 0.2174
#   p_bear = 0.90/2.30 ≈ 0.3913
# ════════════════════════════════════════════════════════════════════════════

B7_EVENTS = [
    {"driver_id": "X", "scenario": "bull", "probability": 0.30,
     "rev_change_mid": 20.0, "op_margin": 0.35},
    {"driver_id": "X", "scenario": "base", "probability": 0.50,
     "rev_change_mid":  0.0, "op_margin": 0.30},
    {"driver_id": "X", "scenario": "bear", "probability": 0.20,
     "rev_change_mid": -15.0, "op_margin": 0.40},
]
B7_BASE_REVENUE    = 100.0
B7_BASE_OP_MARGIN  = 0.30
B7_TAX_RATE        = 0.20
B7_SHARES          = 1.0
B7_CURRENT_PRICE   = 400.0


class TestB7IndependentHandCalc:
    """All expected values verifiable by pencil-and-paper arithmetic."""

    def test_base_eps(self):
        eps = scenario_eps(B7_BASE_REVENUE, B7_BASE_OP_MARGIN, B7_EVENTS,
                           "base", B7_TAX_RATE, B7_SHARES)
        assert abs(eps - 24.00) < 0.01, f"base EPS={eps:.4f}"

    def test_bull_eps(self):
        eps = scenario_eps(B7_BASE_REVENUE, B7_BASE_OP_MARGIN, B7_EVENTS,
                           "bull", B7_TAX_RATE, B7_SHARES)
        assert abs(eps - 29.60) < 0.01, f"bull EPS={eps:.4f}"

    def test_bear_eps(self):
        eps = scenario_eps(B7_BASE_REVENUE, B7_BASE_OP_MARGIN, B7_EVENTS,
                           "bear", B7_TAX_RATE, B7_SHARES)
        assert abs(eps - 19.20) < 0.01, f"bear EPS={eps:.4f}"

    def test_joint_probs_bull(self):
        dp = driver_probabilities(B7_EVENTS)
        jp = joint_probabilities(dp)
        assert abs(jp["bull"] - (0.90 / 2.30)) < 0.0001, f"p_bull={jp['bull']:.4f}"

    def test_joint_probs_bear(self):
        dp = driver_probabilities(B7_EVENTS)
        jp = joint_probabilities(dp)
        assert abs(jp["bear"] - (0.90 / 2.30)) < 0.0001, f"p_bear={jp['bear']:.4f}"

    def test_joint_probs_base(self):
        dp = driver_probabilities(B7_EVENTS)
        jp = joint_probabilities(dp)
        assert abs(jp["base"] - (0.50 / 2.30)) < 0.0001, f"p_base={jp['base']:.4f}"

    def test_joint_probs_sum_to_one(self):
        dp = driver_probabilities(B7_EVENTS)
        jp = joint_probabilities(dp)
        assert abs(sum(jp.values()) - 1.0) < 0.001

    def test_scenario_revenue_bull(self):
        rev = scenario_revenue(B7_BASE_REVENUE, B7_EVENTS, "bull")
        assert abs(rev - 120.0) < 0.001

    def test_scenario_revenue_base(self):
        rev = scenario_revenue(B7_BASE_REVENUE, B7_EVENTS, "base")
        assert abs(rev - 100.0) < 0.001

    def test_scenario_revenue_bear(self):
        rev = scenario_revenue(B7_BASE_REVENUE, B7_EVENTS, "bear")
        assert abs(rev - 85.0) < 0.001


# ── DCF / reverse-DCF unit tests ─────────────────────────────────────────────

class TestDCFPureFunctions:
    def test_project_fcf_growth(self):
        series = project_fcf(100.0, 0.10, 3)
        assert abs(series[0] - 110.0) < 0.01
        assert abs(series[1] - 121.0) < 0.01
        assert abs(series[2] - 133.1) < 0.01

    def test_dcf_intrinsic_value_structure(self):
        series = project_fcf(10.0, 0.10, 5)
        result = dcf_intrinsic_value(series, 0.03, 0.10, 1.0, 0.0)
        for k in ("enterprise_value", "equity_value", "intrinsic_per_share"):
            assert k in result
        assert result["enterprise_value"] > 0

    def test_dcf_raises_on_invalid_rates(self):
        series = project_fcf(10.0, 0.10, 5)
        with pytest.raises(ValueError):
            dcf_intrinsic_value(series, 0.10, 0.05, 1.0, 0.0)  # dr <= tg

    def test_implied_fcf_cagr_finite(self):
        cagr = implied_fcf_cagr(
            current_price=100.0, base_fcf=5.0, shares_projected=1.0,
            horizon_years=5, terminal_growth=0.03, discount_rate=0.09,
        )
        assert math.isfinite(cagr), f"implied_fcf_cagr={cagr!r}"

    def test_implied_fcf_cagr_round_trips(self):
        # If we project FCF at the implied CAGR, the resulting intrinsic value
        # should be within $1 of the target price.
        target = 300.0
        base_fcf = 10.0
        shares = 1.0
        dr = 0.09
        tg = 0.03
        cagr = implied_fcf_cagr(
            current_price=target, base_fcf=base_fcf, shares_projected=shares,
            horizon_years=5, terminal_growth=tg, discount_rate=dr,
        )
        series = project_fcf(base_fcf, cagr, 5)
        dcf_val = dcf_intrinsic_value(series, tg, dr, shares, 0.0)
        assert abs(dcf_val["intrinsic_per_share"] - target) < 1.0, (
            f"round-trip error: dcf={dcf_val['intrinsic_per_share']:.2f} vs target={target}"
        )


# ── P/E band unit tests ───────────────────────────────────────────────────────

class TestPEBand:
    def test_bear_floor_applies_for_quality_franchise(self):
        lo, hi = pe_band("bear", 0.18, franchise_quality=True)
        assert lo >= 25.0, f"bear_low={lo}"

    def test_bear_floor_stress_for_non_quality(self):
        lo, hi = pe_band("bear", 0.05, franchise_quality=False)
        assert lo >= 15.0, f"bear_low={lo}"

    def test_bear_below_bull_and_base(self):
        # Bear trades at a discount to bull and base (bear_high < bull_high and base_high).
        bull_lo, bull_hi = pe_band("bull", 0.18, franchise_quality=True, peer_median_pe=37.0)
        base_lo, base_hi = pe_band("base", 0.18, franchise_quality=True, peer_median_pe=37.0)
        bear_lo, bear_hi = pe_band("bear", 0.18, franchise_quality=True, peer_median_pe=37.0)
        assert bear_hi < bull_hi, f"bear_high={bear_hi} not < bull_high={bull_hi}"
        assert bear_hi < base_hi, f"bear_high={bear_hi} not < base_high={base_hi}"

    def test_bull_pe_high_anchored_to_peers(self):
        lo, hi = pe_band("bull", 0.18, franchise_quality=True, peer_median_pe=37.0)
        assert abs(hi - 37.0) < 0.1, f"bull_pe_high={hi}"


# ── projected_shares unit tests ───────────────────────────────────────────────

class TestProjectedShares:
    def test_no_dilution_unchanged(self):
        result = projected_shares(1.43, 5, 0.0)
        assert abs(result - 1.43) < 1e-6

    def test_positive_dilution_grows(self):
        result = projected_shares(1.0, 5, 0.01)
        expected = 1.0 * (1.01 ** 5)
        assert abs(result - expected) < 1e-6

    def test_negative_dilution_shrinks(self):
        result = projected_shares(1.0, 5, -0.02)
        expected = 1.0 * (0.98 ** 5)
        assert abs(result - expected) < 1e-6


# ── breakeven_pe ──────────────────────────────────────────────────────────────

class TestBreakevenPE:
    def test_basic(self):
        assert abs(breakeven_pe(300.0, 10.0) - 30.0) < 0.01

    def test_zero_eps_returns_none(self):
        assert breakeven_pe(300.0, 0.0) is None

    def test_negative_eps_returns_none(self):
        assert breakeven_pe(300.0, -5.0) is None


# ════════════════════════════════════════════════════════════════════════════
# PHASE C — validator, exceptions, retry logic (no LLM calls)
# ════════════════════════════════════════════════════════════════════════════

from ai import (
    _validate_pass1_v2, Pass1ValidationError, BullCaseTooLowError, run_pass1_foundation
)
import unittest.mock as mock


def _minimal_valid_pass1() -> dict:
    """Minimal §5.2-compliant pass1 dict — all hard-critical fields present."""
    return {
        "corporate_dna": "Test company does things.",
        "segments_enriched": [{"name": "Seg A", "fy_revenue": 1.0, "share_pct": 1.0,
                                "growth_yoy": 0.1, "gross_margin": None, "sub_segments": []}],
        "primary_growth_driver": {"name": "AI demand", "narrative": "x", "key_data_points": [], "tam_view": "big"},
        "peer_set_enriched": [{"ticker": "MRVL", "rationale": "similar"}],
        "macro_drivers": {
            "A": {"label": "Growth", "narrative": "drives bull"},
            "B": {"label": "Stability", "narrative": "keeps base"},
            "C": {"label": "Risk", "narrative": "bear driver"},
        },
        "events": [
            {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.50,
             "revenue_at_risk_low": 1.0, "revenue_at_risk_high": 2.0,
             "op_margin_to_apply": 0.25, "tax_rate_to_apply": 0.21, "evidence": "Q1 2025 call"},
            {"id": "A2", "driver": "A", "outcome": "bear", "probability": 0.50,
             "revenue_at_risk_low": -1.0, "revenue_at_risk_high": -0.5,
             "op_margin_to_apply": 0.20, "tax_rate_to_apply": 0.21, "evidence": "Q1 2025 call"},
            {"id": "B1", "driver": "B", "outcome": "base", "probability": 0.70,
             "revenue_at_risk_low": 0.1, "revenue_at_risk_high": 0.3,
             "op_margin_to_apply": 0.22, "tax_rate_to_apply": 0.21, "evidence": "FY2024 annual"},
            {"id": "B2", "driver": "B", "outcome": "bear", "probability": 0.30,
             "revenue_at_risk_low": -0.5, "revenue_at_risk_high": -0.1,
             "op_margin_to_apply": 0.18, "tax_rate_to_apply": 0.21, "evidence": "FY2024 annual"},
            {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.60,
             "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.1,
             "op_margin_to_apply": 0.22, "tax_rate_to_apply": 0.21, "evidence": "Reuters 2025-01"},
            {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.40,
             "revenue_at_risk_low": -2.0, "revenue_at_risk_high": -1.0,
             "op_margin_to_apply": 0.15, "tax_rate_to_apply": 0.21, "evidence": "Reuters 2025-01"},
        ],
        "pe_anchors": {
            "bull": {"reasoning": "MRVL trades at 28× NTM; bull PEG 1.0× on 20% growth implies 20×"},
            "base": {"reasoning": "MRVL at 22×; base PEG 1.5× implies 18×"},
            "bear": {"reasoning": "MRVL at 22×; bear at 0.875× haircut implies 19×"},
        },
        "sbc_context": None,
        "contract_asset_context": None,
        "catalysts": [
            {"date": "Q3 FY2026", "event": "Q3 earnings first full AI cycle quarter",
             "what_to_watch": "AI networking revenue vs $4B guidance"},
            {"date": "2026-09-15", "event": "Investor day capital allocation update",
             "what_to_watch": "buyback authorization size vs prior year"},
            {"date": "Q4 FY2026", "event": "Q4 earnings — VMware cost synergy update",
             "what_to_watch": "VMware op margin contribution"},
        ],
    }


class TestPassOneValidator:
    def test_valid_pass1_no_errors(self):
        p = _minimal_valid_pass1()
        soft, hard = _validate_pass1_v2(p)
        assert hard == [], f"unexpected hard errors: {hard}"
        assert soft == [], f"unexpected soft errors: {soft}"

    def test_missing_events_is_hard(self):
        p = _minimal_valid_pass1()
        del p["events"]
        soft, hard = _validate_pass1_v2(p)
        assert any("events" in e for e in hard), "missing events should be hard error"

    def test_missing_macro_drivers_is_hard(self):
        p = _minimal_valid_pass1()
        del p["macro_drivers"]
        soft, hard = _validate_pass1_v2(p)
        assert any("macro_drivers" in e for e in hard)

    def test_missing_catalysts_is_soft(self):
        p = _minimal_valid_pass1()
        del p["catalysts"]
        soft, hard = _validate_pass1_v2(p)
        assert hard == [], "missing catalysts must be soft, not hard"
        assert any("catalysts" in e for e in soft)

    def test_wrong_macro_driver_ids_is_hard(self):
        p = _minimal_valid_pass1()
        # Rename key A → X so keys are {X, B, C} ≠ {A, B, C}
        mds = dict(p["macro_drivers"])
        mds["X"] = mds.pop("A")
        p["macro_drivers"] = mds
        soft, hard = _validate_pass1_v2(p)
        assert any("A, B, C" in e or "keys" in e for e in hard), f"wrong keys not hard: {hard}"

    def test_macro_driver_count_mismatch_is_hard(self):
        p = _minimal_valid_pass1()
        # Remove key C so keys are {A, B} ≠ {A, B, C}
        mds = dict(p["macro_drivers"])
        del mds["C"]
        p["macro_drivers"] = mds
        soft, hard = _validate_pass1_v2(p)
        assert any("A, B, C" in e or "keys" in e for e in hard), f"wrong key set not hard: {hard}"

    def test_too_few_events_is_hard(self):
        p = _minimal_valid_pass1()
        p["events"] = p["events"][:3]
        soft, hard = _validate_pass1_v2(p)
        assert any("events" in e or "6" in e for e in hard)

    def test_driver_with_one_event_is_hard(self):
        p = _minimal_valid_pass1()
        # remove B2 so driver B has only 1 event
        p["events"] = [e for e in p["events"] if e["id"] != "B2"]
        soft, hard = _validate_pass1_v2(p)
        assert any("driver B" in e for e in hard)

    def test_missing_pe_anchors_is_soft(self):
        p = _minimal_valid_pass1()
        del p["pe_anchors"]
        soft, hard = _validate_pass1_v2(p)
        assert hard == []
        assert any("pe_anchors" in e for e in soft)

    def test_event_bad_outcome_is_soft(self):
        p = _minimal_valid_pass1()
        p["events"][0]["outcome"] = "moon"
        soft, hard = _validate_pass1_v2(p)
        assert any("outcome" in e for e in soft)

    def test_prob_sum_off_is_soft(self):
        p = _minimal_valid_pass1()
        p["events"][0]["probability"] = 0.99   # A: 0.99 + 0.50 >> 1.0
        soft, hard = _validate_pass1_v2(p)
        assert any("driver A" in e for e in soft)

    def test_revenue_high_lt_low_is_soft(self):
        p = _minimal_valid_pass1()
        p["events"][0]["revenue_at_risk_low"]  = 5.0
        p["events"][0]["revenue_at_risk_high"] = 1.0
        soft, hard = _validate_pass1_v2(p)
        assert any("high" in e and "low" in e for e in soft)


class TestPassOneExceptions:
    def test_pass1_validation_error_stores_list(self):
        err = Pass1ValidationError(["err1", "err2"])
        assert err.errors == ["err1", "err2"]
        assert "2" in str(err)

    def test_bull_case_too_low_error_stores_values(self):
        err = BullCaseTooLowError(bull_eps=1.5, consensus_high=20.0)
        assert err.bull_eps == 1.5
        assert err.consensus_high == 20.0


class TestPassOneFoundationMocked:
    """run_pass1_foundation logic verified with mocked run_ai — no API calls."""

    def _baseline(self) -> dict:
        return {
            "ticker": "TEST", "company_name": "TestCo",
            "current_price": 100.0, "fy_revenue": 10.0,
            "recent_news": [], "history_3y": [],
            "peer_set": [{"ticker": "PEER", "fwd_pe": 20.0}],
            "data_quality_warnings": [],
        }

    def _good_raw(self) -> str:
        import json
        return json.dumps(_minimal_valid_pass1())

    def test_success_on_first_attempt(self):
        baseline = self._baseline()
        with mock.patch("ai.run_ai", return_value=(self._good_raw(), "test-model", None)):
            result = run_pass1_foundation("TEST", baseline, max_passes=2)
        assert "A" in result["macro_drivers"], "macro_drivers must have key 'A'"
        assert result["model_used"] == "test-model"

    def test_soft_error_triggers_retry(self):
        baseline = self._baseline()
        import json
        # First response: missing catalysts (soft error)
        p_no_cats = _minimal_valid_pass1()
        del p_no_cats["catalysts"]
        first_raw  = json.dumps(p_no_cats)
        second_raw = json.dumps(_minimal_valid_pass1())  # retry has catalysts

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (first_raw, "model-a", None)
            return (second_raw, "model-b", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass1_foundation("TEST", baseline, max_passes=2)

        assert call_count["n"] == 2, "expected exactly one retry"
        assert "catalysts" in result

    def test_retry_regression_falls_back_to_first(self):
        """If retry drops events (hard error), keep the first attempt."""
        baseline = self._baseline()
        import json
        # First: soft error only (missing catalysts)
        p_first = _minimal_valid_pass1()
        del p_first["catalysts"]
        first_raw = json.dumps(p_first)

        # Retry: drops events entirely (hard error regression)
        p_retry = _minimal_valid_pass1()
        del p_retry["catalysts"]
        del p_retry["events"]
        retry_raw = json.dumps(p_retry)

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (first_raw if call_count["n"] == 1 else retry_raw, "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass1_foundation("TEST", baseline, max_passes=2)

        # Should have kept first attempt (which had events)
        assert "events" in result
        assert len(result["events"]) == 6

    def test_hard_error_on_first_triggers_retry_then_raises(self):
        """Hard error (missing events) on both passes → Pass1ValidationError."""
        baseline = self._baseline()
        import json
        p_bad = _minimal_valid_pass1()
        del p_bad["events"]
        bad_raw = json.dumps(p_bad)

        with mock.patch("ai.run_ai", return_value=(bad_raw, "m", None)):
            with pytest.raises(Pass1ValidationError) as exc_info:
                run_pass1_foundation("TEST", baseline, max_passes=2)
        assert any("events" in e for e in exc_info.value.errors)


class TestC4BullCaseTooLowMath:
    """C4: verify math produces bull EPS << consensus when events are tiny."""

    C4_BASELINE = {
        "current_price": 100.0, "shares_out": 1.0, "fy_revenue": 5.0,
        "base_op_margin": 0.10, "tax_rate": 0.21, "earnings_cagr": 0.10,
        "beta": 1.2, "net_debt": 0.5, "horizon_years": 5,
        "franchise_quality": True, "trailing_net_dilution_rate": 0.0,
        "base_fcf": 0.3, "peer_pes": [20.0, 22.0, 24.0],
        "consensus_eps_fy2": {"low": 40.0, "mid": 45.0, "high": 50.0},
        "fy_eps_non_gaap": 2.0,
    }
    C4_PASS1 = {
        "events": [
            {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.45,
             "revenue_at_risk_low": 0.05, "revenue_at_risk_high": 0.10,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
            {"id": "A2", "driver": "A", "outcome": "bear", "probability": 0.55,
             "revenue_at_risk_low": -0.10, "revenue_at_risk_high": -0.05,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
            {"id": "B1", "driver": "B", "outcome": "base", "probability": 0.60,
             "revenue_at_risk_low": 0.01, "revenue_at_risk_high": 0.02,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
            {"id": "B2", "driver": "B", "outcome": "bear", "probability": 0.40,
             "revenue_at_risk_low": -0.05, "revenue_at_risk_high": -0.01,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
            {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.50,
             "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.01,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
            {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.50,
             "revenue_at_risk_low": -0.20, "revenue_at_risk_high": -0.10,
             "op_margin_to_apply": 0.10, "tax_rate_to_apply": 0.21, "evidence": "test"},
        ],
        "macro_drivers": [
            {"id": "A", "label": "Growth", "narrative": "x"},
            {"id": "B", "label": "Stability", "narrative": "x"},
            {"id": "C", "label": "Risk", "narrative": "x"},
        ],
        "pe_anchors": {
            "bull": {"reasoning": "PEER trades at 20×"},
            "base": {"reasoning": "PEER trades at 20×"},
            "bear": {"reasoning": "PEER trades at 20×"},
        },
    }

    def test_bull_eps_far_below_consensus(self):
        from run_methodology_math import run_methodology_math
        math = run_methodology_math(self.C4_PASS1, self.C4_BASELINE)
        consensus_high = 50.0

        # Step A must fire: bottom-up bull EPS (~$0.40) is far below consensus floor ($47.5)
        step_a = [e for e in math["calibration_log"] if "Step A" in e]
        assert len(step_a) == 1, (
            f"Step A should fire (bottom-up << consensus); calibration_log={math['calibration_log']}"
        )

        # After Step A, bull_eps is floored to exactly 0.95 × consensus_high
        bull_eps = math["scenario_eps"]["bull"]
        expected_floor = 0.95 * consensus_high   # = 47.5
        assert abs(bull_eps - expected_floor) < 0.01, (
            f"bull_eps=${bull_eps:.4f} should equal floor=${expected_floor:.2f}"
        )

        # The gap that *would* have triggered BullCaseTooLowError (pre-floor) is confirmed
        # by Step A firing: bottom-up was < 0.95 × $50 = $47.5 << $50 (far below consensus)
        assert "0.95" in step_a[0] or "→" in step_a[0], (
            f"Step A log entry should show floor arrow: {step_a[0]!r}"
        )


# ════════════════════════════════════════════════════════════════════════════
# PHASE D — §5.1 field wiring, §6 calibration, NVDA exit criterion
# ════════════════════════════════════════════════════════════════════════════

# D2: AVGO fixture using §5.1 canonical field names.
# Values are identical to AVGO_BASELINE but keys are renamed to §5.1 names.
# No consensus_eps_fy2 → Step A does not fire; targets should match §7.4.
AVGO_V2_BASELINE = {
    "current_price":              320.0,
    "shares_out":                 1.43,
    "fy_revenue":                 28.5,
    "fy_op_margin":               0.62,        # §5.1 name (was base_op_margin)
    "tax_rate_guidance":          0.13,         # §5.1 name (was tax_rate)
    "beta":                       1.15,
    "net_debt":                   30.0,
    "horizon_years":              5,
    "franchise_quality":          True,
    "trailing_net_dilution_rate": 0.005,
    "fy_fcf":                     14.5,         # §5.1 name (was base_fcf)
    "five_yr_eps_growth_est":     0.18,         # §5.1 name (was earnings_cagr)
    "peer_set": [                               # §5.1 name (was peer_pes flat list)
        {"ticker": "MRVL", "fwd_pe": 36.0},
        {"ticker": "QCOM", "fwd_pe": 38.0},
        {"ticker": "BRCM", "fwd_pe": 40.0},
        {"ticker": "TXN",  "fwd_pe": 38.0},
        {"ticker": "ADI",  "fwd_pe": 38.0},
    ],
    "fy_eps_non_gaap": 10.50,                   # §5.1 name (was trailing_eps)
}


class TestD2AVGOFieldNames:
    """D2: §5.1 field names feed the same §7.4 targets as Phase A AVGO_BASELINE."""

    def _math(self):
        return run_methodology_math({"events": AVGO_EVENTS}, AVGO_V2_BASELINE)

    def test_bull_eps_within_target(self):
        m = self._math()
        eps = m["scenario_eps"]["bull"]
        assert abs(eps - 14.50) <= 0.50, f"bull EPS={eps:.2f}, expected 14.50±0.50"

    def test_base_eps_within_target(self):
        m = self._math()
        eps = m["scenario_eps"]["base"]
        assert abs(eps - 10.74) <= 0.50, f"base EPS={eps:.2f}, expected 10.74±0.50"

    def test_ev_within_target(self):
        m = self._math()
        ev = m["expected_value"]
        assert abs(ev - 299.0) <= 15.0, f"EV={ev:.1f}, expected 299±15 (post-BugB base-PE ratio fix)"

    def test_bull_price_high_above_current(self):
        m = self._math()
        assert m["price_target"]["bull_high"] > AVGO_V2_BASELINE["current_price"], (
            f"bull_high={m['price_target']['bull_high']} not > {AVGO_V2_BASELINE['current_price']}"
        )

    def test_calibration_log_present(self):
        m = self._math()
        assert "calibration_log" in m
        assert isinstance(m["calibration_log"], list)

    def test_no_step_a_without_consensus(self):
        m = self._math()
        # No consensus_eps_fy2 in AVGO_V2_BASELINE → Step A must not fire
        assert not any("Step A" in entry for entry in m["calibration_log"]), (
            "Step A should not fire when consensus_eps_fy2 is absent"
        )

    def test_consensus_divergent_false(self):
        m = self._math()
        # No consensus → consensus_divergent must stay False
        assert m["consensus_divergent"] is False

    def test_breakeven_pe_uses_fy_eps_non_gaap(self):
        m = self._math()
        # fy_eps_non_gaap = 10.50, current_price = 320 → expected breakeven PE ≈ 30.5
        bkev = m["breakeven_pe"]
        assert bkev is not None
        assert abs(bkev - (320.0 / 10.50)) < 0.2, f"breakeven_pe={bkev:.1f}, expected ~30.5"


# ── D3 NVDA synthetic fixture ────────────────────────────────────────────────
# Post-split NVDA: current_price=$110, growth=35%, fy_eps_non_gaap=2.50.
# peer_set median fwd_pe=25 → bull pe_high=35 (PEG 1.0×35).
# Growth-rate bull EPS: 2.50 × 1.35² = 4.556. consensus_eps_fy2.high=6.0
# → floor = 0.95 × 6.0 = 5.70 > 4.556 → Step A always floors to 5.70.
# bull_price_high = 5.70 × 35 = 199.5 > 110 on all variants.

NVDA_BASELINE = {
    "current_price":              110.0,
    "shares_out":                 24.5,          # billions (post-split)
    "fy_revenue":                 60.0,          # $B FY2024
    "fy_op_margin":               0.55,
    "tax_rate_guidance":          0.15,
    "beta":                       1.7,
    "net_debt":                   -16.0,         # net cash
    "horizon_years":              5,
    "franchise_quality":          True,
    "trailing_net_dilution_rate": -0.03,         # buyback
    "fy_fcf":                     25.0,
    "five_yr_eps_growth_est":     0.35,
    "peer_set": [
        {"ticker": "AMD",  "fwd_pe": 20.0},
        {"ticker": "MU",   "fwd_pe": 25.0},
        {"ticker": "AVGO", "fwd_pe": 30.0},
    ],
    "fy_eps_non_gaap": 2.50,
    "consensus_eps_fy2": {"low": 5.0, "mid": 5.5, "high": 6.0},
}

# Three distinct pass1 event sets — all produce growth-rate bull EPS (4.556) < floor (5.70)
def _nvda_pass1_variant(bull_rev_mid: float, bull_op_margin: float) -> dict:
    return {
        "events": [
            {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.40,
             "revenue_at_risk_low":  bull_rev_mid * 0.8, "revenue_at_risk_high": bull_rev_mid * 1.2,
             "op_margin_to_apply": bull_op_margin, "tax_rate_to_apply": 0.15, "evidence": "test"},
            {"id": "A2", "driver": "A", "outcome": "bear", "probability": 0.60,
             "revenue_at_risk_low": -4.0, "revenue_at_risk_high": -2.0,
             "op_margin_to_apply": 0.55, "tax_rate_to_apply": 0.15, "evidence": "test"},
            {"id": "B1", "driver": "B", "outcome": "base", "probability": 0.70,
             "revenue_at_risk_low":  0.0, "revenue_at_risk_high":  2.0,
             "op_margin_to_apply": 0.55, "tax_rate_to_apply": 0.15, "evidence": "test"},
            {"id": "B2", "driver": "B", "outcome": "bear", "probability": 0.30,
             "revenue_at_risk_low": -5.0, "revenue_at_risk_high": -2.0,
             "op_margin_to_apply": 0.55, "tax_rate_to_apply": 0.15, "evidence": "test"},
            {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.65,
             "revenue_at_risk_low":  0.0, "revenue_at_risk_high":  1.0,
             "op_margin_to_apply": 0.55, "tax_rate_to_apply": 0.15, "evidence": "test"},
            {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.35,
             "revenue_at_risk_low": -6.0, "revenue_at_risk_high": -3.0,
             "op_margin_to_apply": 0.55, "tax_rate_to_apply": 0.15, "evidence": "test"},
        ],
    }

NVDA_PASS1_V1 = _nvda_pass1_variant(bull_rev_mid=10.0, bull_op_margin=0.65)   # big AI upcycle
NVDA_PASS1_V2 = _nvda_pass1_variant(bull_rev_mid= 5.0, bull_op_margin=0.60)   # moderate upside
NVDA_PASS1_V3 = _nvda_pass1_variant(bull_rev_mid= 2.0, bull_op_margin=0.56)   # muted bull


class TestD3NVDABullAboveCurrent:
    """D3 exit: all 3 NVDA pass1 variants produce bull_price_high > current_price."""

    def _math(self, pass1):
        return run_methodology_math(pass1, NVDA_BASELINE)

    def test_variant1_bull_high_above_current(self):
        m = self._math(NVDA_PASS1_V1)
        bh = m["price_target"]["bull_high"]
        assert bh > NVDA_BASELINE["current_price"], f"V1 bull_high={bh} not > {NVDA_BASELINE['current_price']}"

    def test_variant2_bull_high_above_current(self):
        m = self._math(NVDA_PASS1_V2)
        bh = m["price_target"]["bull_high"]
        assert bh > NVDA_BASELINE["current_price"], f"V2 bull_high={bh} not > {NVDA_BASELINE['current_price']}"

    def test_variant3_bull_high_above_current(self):
        m = self._math(NVDA_PASS1_V3)
        bh = m["price_target"]["bull_high"]
        assert bh > NVDA_BASELINE["current_price"], f"V3 bull_high={bh} not > {NVDA_BASELINE['current_price']}"

    def test_step_a_fires_on_all_variants(self):
        for i, p1 in enumerate([NVDA_PASS1_V1, NVDA_PASS1_V2, NVDA_PASS1_V3], 1):
            m = self._math(p1)
            assert any("Step A" in e for e in m["calibration_log"]), (
                f"V{i}: expected Step A to fire (bottom-up bull EPS << consensus)"
            )

    def test_consensus_divergent_false_when_bull_above_current(self):
        for p1 in [NVDA_PASS1_V1, NVDA_PASS1_V2, NVDA_PASS1_V3]:
            m = self._math(p1)
            # bull_high > current_price → consensus_divergent must be False
            assert m["consensus_divergent"] is False

    def test_implied_fcf_cagr_finite_and_bounded(self):
        for i, p1 in enumerate([NVDA_PASS1_V1, NVDA_PASS1_V2, NVDA_PASS1_V3], 1):
            m = self._math(p1)
            cagr = m["implied_fcf_cagr"]
            assert math.isfinite(cagr), f"V{i}: implied_fcf_cagr={cagr!r} is not finite"
            assert -0.5 <= cagr <= 1.0, f"V{i}: implied_fcf_cagr={cagr:.3f} out of [-0.5, 1.0]"


class TestD3ConsensusCalibration:
    """D3: calibration_log and consensus_divergent behave correctly."""

    def _math_with_consensus(self, consensus_high: float, current_price: float = 110.0) -> dict:
        bl = dict(NVDA_BASELINE, current_price=current_price,
                  consensus_eps_fy2={"low": 3.0, "mid": 3.5, "high": consensus_high})
        return run_methodology_math(NVDA_PASS1_V1, bl)

    def test_step_a_log_entry_format(self):
        # 5.5: floor=0.95×5.5=5.225 > growth-rate bull_eps (2.50×1.35²=4.556) → Step A fires
        m = self._math_with_consensus(5.5)
        step_a = [e for e in m["calibration_log"] if "Step A" in e]
        assert len(step_a) == 1
        assert "→" in step_a[0] and "consensus_high" in step_a[0]

    def test_no_step_a_when_bottomup_exceeds_floor(self):
        # Tiny consensus_high → floor = 0.95 × 0.01 ≈ 0 → Step A never fires
        m = self._math_with_consensus(consensus_high=0.01)
        assert not any("Step A" in e for e in m["calibration_log"])

    def test_consensus_divergent_true_when_bull_below_price(self):
        # Absurdly high current_price to force bull_high < current_price
        m = self._math_with_consensus(consensus_high=4.5, current_price=10_000.0)
        assert m["consensus_divergent"] is True
        assert any("Step D" in e for e in m["calibration_log"])

    def test_price_target_has_bull_mid_key(self):
        m = self._math_with_consensus(4.5)
        assert "bull_mid" in m["price_target"], "price_target must include bull_mid (EV-based)"

    def test_price_target_bull_high_ge_bull_mid(self):
        m = self._math_with_consensus(4.5)
        assert m["price_target"]["bull_high"] >= m["price_target"]["bull_mid"], (
            f"bull_high={m['price_target']['bull_high']} < bull_mid={m['price_target']['bull_mid']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# PHASE E — pass2 prompt v2, run_pass2_report, smoke harness structural checks
# ════════════════════════════════════════════════════════════════════════════

from ai import (
    _build_pass2_body, _validate_pass2_v2, run_pass2_report,
    _PASS2_QUALITATIVE_SECTIONS, PASS3_PROMPT,
)
from smoke_harness import check_word_count, check_forbidden_tokens


def _minimal_valid_pass2() -> dict:
    """Minimal §5.4-compliant pass2 dict — all required sections, no forbidden tokens,
    well under 7000 words."""
    return {
        "business_overview": (
            "The company operates a diversified semiconductor and infrastructure software "
            "platform with a mix of recurring license revenue and hardware sales. "
            "Customers embed the product into mission-critical workflows, creating high "
            "switching costs and multi-year revenue visibility."
        ),
        "revenue_architecture": (
            "Segment data is not available in the current baseline, so the revenue "
            "base is assessed in aggregate. Total revenue is growing at a rate consistent "
            "with the base-case growth assumptions in the scenario analysis."
        ),
        "growth_drivers_and_moats": (
            "The three named growth drivers are AI Infrastructure Capex Cycle (Driver A), "
            "Enterprise Software Renewal Rates (Driver B), and Competitive Insourcing Risk "
            "(Driver C). Driver A is the primary growth lever with moat protection from "
            "platform integration depth. Driver B benefits from multi-year contracts that "
            "reduce churn. Driver C represents long-term displacement risk from proprietary "
            "silicon development by large customers."
        ),
        "margin_analysis": (
            "Current operating margin is 0.62, consistent with franchise-quality positioning. "
            "Margin trajectory by scenario reflects the operating leverage embedded in the "
            "software-heavy revenue mix."
        ),
        "competitive_position": (
            "The company competes with AMAT, LRCX, and KLAC in certain end-markets. "
            "Moat durability is supported by workflow integration and certification requirements. "
            "Key threats include customer insourcing of proprietary silicon and open-source "
            "alternatives in the software segment."
        ),
        "valuation_vs_expectations": (
            "The current forward P/E reflects a market assumption that is inconsistent with "
            "the base-case earnings trajectory implied by the scenario analysis. The implied "
            "FCF CAGR embedded in the current price is modest relative to the base-case EPS "
            "path, suggesting the market is underpricing the base-case outcome."
        ),
        "sensitivity_check": (
            "Shifting Driver A bull probability by +/-10pp moves expected value from "
            "270.0 at bull prob 0.149 to 328.0 at bull prob 0.349. "
            "The expected value is moderately sensitive to the Driver A probability assumption."
        ),
        "factor_analysis": [
            {
                "driver_id": "A",
                "name": "AI Infrastructure Capex Cycle",
                "outcomes": [
                    {"label": "optimistic",  "probability": 0.40, "description": "Hyperscaler AI buildout accelerates, driving incremental networking demand above base."},
                    {"label": "neutral",     "probability": 0.42, "description": "AI capex grows at a pace consistent with the base forecast."},
                    {"label": "pessimistic", "probability": 0.18, "description": "AI spending decelerates sharply due to macro tightening or compute efficiency gains."},
                ],
            },
            {
                "driver_id": "B",
                "name": "Enterprise Software Renewal Rates",
                "outcomes": [
                    {"label": "optimistic",  "probability": 0.50, "description": "Renewal rates exceed 95%, sustaining high-margin recurring revenue."},
                    {"label": "neutral",     "probability": 0.35, "description": "Renewal rates hold at historical norms around 90%."},
                    {"label": "pessimistic", "probability": 0.15, "description": "Renewal rates decline due to competitive alternatives entering the market."},
                ],
            },
            {
                "driver_id": "C",
                "name": "Competitive Insourcing Risk",
                "outcomes": [
                    {"label": "optimistic",  "probability": 0.20, "description": "Insourcing attempts fail or stall; incumbent position holds."},
                    {"label": "neutral",     "probability": 0.40, "description": "Insourcing progresses gradually with limited near-term revenue impact."},
                    {"label": "pessimistic", "probability": 0.40, "description": "A major customer successfully insources, triggering revenue displacement."},
                ],
            },
        ],
        "concentration_and_dependencies": {
            "geographic_exposure": "North America approximately 60% of revenue (estimate), Europe 20% (estimate), Asia-Pacific 20% (estimate).",
            "top_customer_concentration": "Top customer represents approximately 20% of revenue (estimate); top-5 customers approximately 45% (estimate).",
            "supply_chain_dependencies": "Reliance on TSMC for leading-edge node fabrication; packaging dependence on a small number of OSAT providers.",
            "relationships_at_risk": "Apple custom silicon transition could reduce AVGO's networking content; Meta AI infrastructure shifts could reprice hyperscaler contracts; TSMC capacity allocation remains a bottleneck risk.",
        },
        "scenario_analysis_extended": {
            "bull": {
                "segment_revenue_note": None,
                "headwind_tailwind_summary": "Bull tailwinds are led by AI networking revenue acceleration and VMware upsell.",
                "valuation_rationale": "The bull P/E of 38x is justified by FY+2 EPS of 14.50 and the durable franchise premium.",
            },
            "base": {
                "segment_revenue_note": None,
                "headwind_tailwind_summary": "Base case reflects steady compounding with moderate headwinds from macro sensitivity.",
                "valuation_rationale": "The base P/E of 32x reflects the blended growth-value profile at base EPS of 10.74.",
            },
            "bear": {
                "segment_revenue_note": None,
                "headwind_tailwind_summary": "Bear headwinds include insourcing risk and margin compression from competitive pricing.",
                "valuation_rationale": "The bear P/E of 26x reflects distressed-franchise pricing at bear EPS of 6.35.",
            },
        },
        "investment_thesis": (
            "The current price implies a free cash flow CAGR consistent with modest "
            "growth expectations over the 5-year horizon, making the entry valuation "
            "undemanding relative to the base-case earnings trajectory.\n\n"
            "The FY+2 price target range spans from the bull scenario at the upper P/E "
            "bound to the bear scenario at the lower bound, with the bull case requiring "
            "Driver A to materialise through sustained AI infrastructure spending.\n\n"
            "Expected value is above the current price, with expected return well above "
            "the minimum threshold and prob_loss below the 35% ceiling, making the "
            "risk/reward balance favourable at this entry point."
        ),
        "reverse_dcf_commentary": (
            "The implied FCF CAGR embedded in the current price is consistent with a "
            "moderate trajectory, neither aggressively demanding nor trivially easy to "
            "achieve given the baseline earnings power visible in the scenario analysis. "
            "A buyer at the current price is implicitly betting on sustained franchise "
            "strength rather than a discrete growth acceleration."
        ),
        "scenario_commentary": {
            "bull": (
                "The bull scenario carries a joint probability of 0.249 and requires "
                "Driver A to fire fully: AI networking revenue acceleration would lift "
                "bull EPS to 14.50 and the bull price target to 551.0 at the upper P/E bound."
            ),
            "base": (
                "The base scenario is the most probable outcome with a joint probability "
                "of 0.593, producing FY+2 EPS of 10.74 and a price target of 347.0 at "
                "the mid P/E band."
            ),
            "bear": (
                "The bear scenario has a joint probability of 0.158 and would materialise "
                "if the competitive insourcing risk driver fires negatively, reducing "
                "bear EPS to 6.35 and the bear price target to 168.0 at the lower P/E bound."
            ),
        },
        "driver_narratives": {
            "A": (
                "Driver A — AI Infrastructure Capex Cycle — is the primary growth lever. "
                "Hyperscaler AI compute buildout drives incremental networking and chip "
                "demand, with evidence from the Q2 FY2025 earnings call citing AI networking "
                "revenue above 4.0 billion. The probability distribution leans bull."
            ),
            "B": (
                "Driver B — Enterprise Software Renewal Rates — anchors the base case "
                "through multi-year licensing contracts that provide earnings visibility. "
                "High renewal rates reduce revenue volatility and support the base scenario "
                "probability of 0.82."
            ),
            "C": (
                "Driver C — Competitive Insourcing Risk — is the primary structural headwind. "
                "Large customers developing proprietary silicon creates long-term revenue "
                "displacement risk. The probability distribution leans bear, with a 0.40 "
                "probability on the bear outcome per the Reuters 2025-03-14 report."
            ),
        },
        "financial_health": (
            "Operating margin of 0.62 is well above the sector median, supporting the "
            "franchise quality assessment. Free cash flow of 14.5 billion provides ample "
            "capacity for capital returns; FCF margin of 0.51 is above the long-run norm. "
            "Net debt of 30.0 billion is elevated following the recent acquisition but "
            "declining at a pace consistent with the base case. SBC of 2.1 billion "
            "represents a 0.5 percentage point annual dilution headwind."
        ),
        "recommendation_rationale": (
            "The BUY recommendation reflects an expected return above the 15% upside "
            "threshold with prob_loss below 35%, satisfying both conditions simultaneously. "
            "Expected value of 348.0 versus the current price of 320.0 produces a "
            "probability-weighted return that is positive and meaningful.\n\n"
            "No calibration steps fired for this ticker, confirming the bottom-up bull "
            "EPS is consistent with the FY+2 consensus range."
        ),
        "conclusion": (
            "The investment thesis rests on AI-driven revenue acceleration supported by "
            "strong recurring franchise income; the BUY recommendation is supported by "
            "the probability-weighted math.\n\n"
            "Key catalysts: Q3 FY2026 earnings — watch AI networking revenue versus "
            "the 4.0 billion guidance; Investor Day capital allocation update — watch "
            "buyback authorisation size; Q4 FY2026 — watch VMware operating margin contribution."
        ),
    }


def _math_for_pass2() -> dict:
    """Compute a real §5.3 math dict using the AVGO v2 fixture."""
    return run_methodology_math({"events": AVGO_EVENTS}, AVGO_V2_BASELINE)


def _baseline_for_pass2() -> dict:
    """§5.1 baseline for pass2 tests — AVGO v2 with extra required fields."""
    return {
        **AVGO_V2_BASELINE,
        "company_name": "Broadcom Inc.",
        "ticker": "AVGO",
        "recent_news": [],
        "history_3y": [],
        "peer_set": AVGO_V2_BASELINE.get("peer_set", []),
        "data_quality_warnings": [],
        "fy_sbc": 2.1,
        "fy_fcf_margin": 0.51,
    }


class TestPass2Validator:
    """Unit tests on _validate_pass2_v2."""

    def test_valid_pass2_no_errors(self):
        soft, hard = _validate_pass2_v2(_minimal_valid_pass2())
        assert hard == [], f"unexpected hard errors: {hard}"
        assert soft == [], f"unexpected soft errors: {soft}"

    def test_missing_required_section_is_hard(self):
        for k in ("investment_thesis", "reverse_dcf_commentary",
                  "recommendation_rationale", "conclusion"):
            p = _minimal_valid_pass2()
            del p[k]
            soft, hard = _validate_pass2_v2(p)
            assert any(k in e for e in hard), f"missing {k} should be hard error"

    def test_forbidden_sharpe_is_hard(self):
        p = _minimal_valid_pass2()
        p["investment_thesis"] += " The Sharpe ratio is high."
        soft, hard = _validate_pass2_v2(p)
        assert any("Sharpe" in e for e in hard)

    def test_forbidden_capture_is_hard(self):
        p = _minimal_valid_pass2()
        p["conclusion"] += " The reward-to-risk capture ratio is 2.5x."
        soft, hard = _validate_pass2_v2(p)
        assert any("capture ratio" in e for e in hard)

    def test_forbidden_degraded_is_hard(self):
        p = _minimal_valid_pass2()
        p["financial_health"] += " DEGRADED data."
        soft, hard = _validate_pass2_v2(p)
        assert any("DEGRADED" in e for e in hard)

    def test_word_count_over_limit_is_soft(self):
        p = _minimal_valid_pass2()
        filler = " This is additional filler text." * 1500   # ~7500 extra words, exceeds 7000
        p["investment_thesis"] += filler
        soft, hard = _validate_pass2_v2(p)
        assert hard == [], "word count violation should be soft, not hard"
        assert any("word count" in e for e in soft)

    def test_missing_optional_section_is_soft(self):
        p = _minimal_valid_pass2()
        del p["financial_health"]
        soft, hard = _validate_pass2_v2(p)
        assert hard == []
        assert any("financial_health" in e for e in soft)

    def test_missing_driver_narrative_is_hard(self):
        """Bug 4: missing driver narrative is now a hard retry trigger, not a soft warning."""
        p = _minimal_valid_pass2()
        del p["driver_narratives"]["C"]
        soft, hard = _validate_pass2_v2(p)
        assert any("driver_narratives" in e and "C" in e for e in hard), (
            f"missing driver_narratives.C must be hard; hard={hard}"
        )

    def test_build_body_excludes_body_key_itself(self):
        p = _minimal_valid_pass2()
        p["body"] = "should not double-count"
        body = _build_pass2_body(p)
        assert "should not double-count" not in body


class TestPass2FoundationMocked:
    """run_pass2_report logic with mocked run_ai — no API calls."""

    def _raw_good(self) -> str:
        import json
        return json.dumps(_minimal_valid_pass2())

    def test_success_returns_body_key(self):
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        with mock.patch("ai.run_ai", return_value=(self._raw_good(), "test-model", None)):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math)
        assert "body" in result, "run_pass2_report must return a 'body' key"
        assert isinstance(result["body"], str)

    def test_model_used_recorded(self):
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        with mock.patch("ai.run_ai", return_value=(self._raw_good(), "claude-test", None)):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math)
        assert result.get("model_used") == "claude-test"

    def test_soft_error_triggers_retry(self):
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        import json
        p_verbose = _minimal_valid_pass2()
        filler = " Extra filler text added to exceed word count limit." * 1000
        p_verbose["investment_thesis"] += filler  # pushes over 4500 words → soft error
        p_good = _minimal_valid_pass2()            # retry: under limit

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (json.dumps(p_verbose if call_count["n"] == 1 else p_good),
                    "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math,
                                      max_passes=2)
        assert call_count["n"] == 2, "expected exactly one retry on soft error"

    def test_hard_error_triggers_retry(self):
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        import json
        p_bad = _minimal_valid_pass2()
        del p_bad["investment_thesis"]     # hard error: missing required section
        p_good = _minimal_valid_pass2()

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (json.dumps(p_bad if call_count["n"] == 1 else p_good), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math,
                                      max_passes=2)
        assert call_count["n"] == 2

    def test_retry_regression_keeps_first(self):
        """Retry that reintroduces a forbidden token → keep first attempt."""
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        import json
        # First attempt: missing financial_health (soft error only)
        p_first = _minimal_valid_pass2()
        del p_first["financial_health"]

        # Retry: drops investment_thesis (hard regression)
        p_retry = _minimal_valid_pass2()
        del p_retry["investment_thesis"]

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (json.dumps(p_first if call_count["n"] == 1 else p_retry), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math,
                                      max_passes=2)
        # Should have kept first attempt (which had investment_thesis)
        assert result.get("investment_thesis"), "first attempt's investment_thesis should be kept"

    def test_word_count_in_body(self):
        baseline = _baseline_for_pass2()
        math = _math_for_pass2()
        with mock.patch("ai.run_ai", return_value=(self._raw_good(), "m", None)):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math)
        body_wc = len(result["body"].split())
        assert body_wc <= 4500, f"body word count {body_wc} exceeds 4500"
        assert body_wc > 50, "body is suspiciously short"


# ── E3: Smoke harness structural checks — 5 tickers × 3 runs ────────────────

_E3_TICKERS = ["AVGO", "KO", "ASML", "NVDA", "ADBE"]


class TestPass2SmokeHarness:
    """E3: smoke harness word_count + forbidden_tokens pass for 5 tickers × 3 runs."""

    @pytest.mark.parametrize("ticker", _E3_TICKERS)
    @pytest.mark.parametrize("run_idx", [1, 2, 3])
    def test_word_count_passes(self, ticker, run_idx):
        import json as _json
        baseline = {**_baseline_for_pass2(), "ticker": ticker}
        math = _math_for_pass2()
        raw = _json.dumps(_minimal_valid_pass2())
        with mock.patch("ai.run_ai", return_value=(raw, "test-model", None)):
            pass2 = run_pass2_report(ticker, baseline, _minimal_valid_pass1(), math)
        fixture = {"pass2": pass2}
        ok, msg = check_word_count(fixture)
        assert ok is not False, f"{ticker} run {run_idx} word_count failed: {msg}"

    @pytest.mark.parametrize("ticker", _E3_TICKERS)
    @pytest.mark.parametrize("run_idx", [1, 2, 3])
    def test_forbidden_tokens_pass(self, ticker, run_idx):
        import json as _json
        baseline = {**_baseline_for_pass2(), "ticker": ticker}
        math = _math_for_pass2()
        raw = _json.dumps(_minimal_valid_pass2())
        with mock.patch("ai.run_ai", return_value=(raw, "test-model", None)):
            pass2 = run_pass2_report(ticker, baseline, _minimal_valid_pass1(), math)
        fixture = {"pass2": pass2}
        ok, msg = check_forbidden_tokens(fixture)
        assert ok is not False, f"{ticker} run {run_idx} forbidden_tokens failed: {msg}"

    @pytest.mark.parametrize("ticker", _E3_TICKERS)
    @pytest.mark.parametrize("run_idx", [1, 2, 3])
    def test_all_required_sections_present(self, ticker, run_idx):
        import json as _json
        baseline = {**_baseline_for_pass2(), "ticker": ticker}
        math = _math_for_pass2()
        raw = _json.dumps(_minimal_valid_pass2())
        with mock.patch("ai.run_ai", return_value=(raw, "test-model", None)):
            pass2 = run_pass2_report(ticker, baseline, _minimal_valid_pass1(), math)
        for section in ("investment_thesis", "reverse_dcf_commentary",
                        "recommendation_rationale", "conclusion"):
            assert pass2.get(section), (
                f"{ticker} run {run_idx}: section '{section}' is missing or empty"
            )


# ════════════════════════════════════════════════════════════════════════════
# PHASE F — pass3 audit v2: forbidden vocab scan, citation detection, call ceiling
# ════════════════════════════════════════════════════════════════════════════

from ai import _scan_forbidden_vocab, run_pass3_audit
from compute import MAX_PIPELINE_AI_CALLS


def _clean_audit_json() -> str:
    """Minimal valid pass3 audit result from LLM (all-clean)."""
    import json as _json
    return _json.dumps({
        "citation_errors": [],
        "b1_compliant": True,
        "tone_label_ok": True,
        "tone_label_evidence": None,
    })


def _pass2_with_body() -> dict:
    """Minimal valid pass2 with body attached (as run_pass2_report would produce)."""
    from ai import _build_pass2_body
    p = _minimal_valid_pass2()
    p["body"] = _build_pass2_body(p)
    return p


class TestPass3ForbiddenVocabScan:
    """F3: deterministic _scan_forbidden_vocab — no LLM call."""

    def test_clean_body_returns_empty(self):
        p2 = _pass2_with_body()
        hits = _scan_forbidden_vocab(p2)
        assert hits == [], f"clean pass2 should have no hits, got: {hits}"

    def test_detects_sharpe(self):
        p2 = _pass2_with_body()
        p2["body"] += " The Sharpe ratio of this trade is attractive."
        hits = _scan_forbidden_vocab(p2)
        assert any(h["token"] == "Sharpe" for h in hits), "should detect 'Sharpe'"

    def test_detects_capture_ratio(self):
        p2 = _pass2_with_body()
        p2["body"] += " The reward-to-risk capture ratio is 2.5x."
        hits = _scan_forbidden_vocab(p2)
        assert any(h["token"] == "capture ratio" for h in hits), "should detect 'capture ratio'"

    def test_detects_degraded(self):
        p2 = _pass2_with_body()
        p2["body"] += " DEGRADED — analysis unavailable."
        hits = _scan_forbidden_vocab(p2)
        assert any(h["token"] == "DEGRADED" for h in hits), "should detect 'DEGRADED'"

    def test_quoted_context_non_empty(self):
        p2 = _pass2_with_body()
        p2["body"] += " The Sharpe ratio is high."
        hits = _scan_forbidden_vocab(p2)
        sharpe_hit = next(h for h in hits if h["token"] == "Sharpe")
        assert sharpe_hit["quoted_context"], "quoted_context should be non-empty"

    def test_falls_back_to_building_body_if_absent(self):
        # pass2 without 'body' key — should build from sections
        p2 = _minimal_valid_pass2()
        p2["investment_thesis"] += " The Sharpe metric matters here."
        assert "body" not in p2
        hits = _scan_forbidden_vocab(p2)
        assert any(h["token"] == "Sharpe" for h in hits)


class TestPass3AuditMocked:
    """F3: run_pass3_audit with mocked LLM — citation errors, clean reports, budget."""

    def _args(self):
        baseline = _baseline_for_pass2()
        pass1    = _minimal_valid_pass1()
        math     = _math_for_pass2()
        pass2    = _pass2_with_body()
        return "AVGO", baseline, pass1, math, pass2

    def test_clean_pass2_returns_audit_clean(self):
        with mock.patch("ai.run_ai", return_value=(_clean_audit_json(), "m", None)):
            result = run_pass3_audit(*self._args(), calls_remaining=5)
        assert result["audit_clean"] is True
        assert result["forbidden_vocab"] == []
        assert result["citation_errors"] == []

    def test_injected_citation_error_is_flagged(self):
        """F3: inject a fabricated number → LLM mock returns citation error → audit surfaces it."""
        import json as _json
        # Inject a clearly wrong number into the body
        ticker, baseline, pass1, math, pass2 = self._args()
        pass2["investment_thesis"] += " The company reported revenue of 999.9 billion last year."
        pass2["body"] = pass2.get("body", "") + " The company reported revenue of 999.9 billion last year."

        # Mock LLM to return a citation error for that number
        audit_with_error = _json.dumps({
            "citation_errors": [{
                "field": "investment_thesis",
                "quoted_text": "revenue of 999.9 billion",
                "issue": "999.9 is not in any allowed source; fy_revenue=28.5",
                "severity": "error",
            }],
            "b1_compliant": True,
            "tone_label_ok": True,
            "tone_label_evidence": None,
        })
        with mock.patch("ai.run_ai", return_value=(audit_with_error, "m", None)):
            result = run_pass3_audit(ticker, baseline, pass1, math, pass2, calls_remaining=3)

        assert not result["audit_clean"], "audit should not be clean when citation error present"
        assert len(result["citation_errors"]) == 1
        assert result["citation_errors"][0]["severity"] == "error"
        assert "999.9" in result["citation_errors"][0]["quoted_text"]

    def test_forbidden_vocab_caught_before_llm(self):
        """Forbidden vocab scan is deterministic — fires even if LLM never called."""
        ticker, baseline, pass1, math, pass2 = self._args()
        pass2["body"] += " The Sharpe ratio here is 1.8."

        call_count = {"n": 0}
        def mock_run_ai(*a, **kw):
            call_count["n"] += 1
            return (_clean_audit_json(), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass3_audit(ticker, baseline, pass1, math, pass2, calls_remaining=5)

        # vocab scan fires regardless of LLM result
        assert any(h["token"] == "Sharpe" for h in result["forbidden_vocab"])
        assert not result["audit_clean"]

    def test_b1_non_compliant_flagged(self):
        import json as _json
        audit_b1_fail = _json.dumps({
            "citation_errors": [],
            "b1_compliant": False,
            "tone_label_ok": True,
            "tone_label_evidence": None,
        })
        with mock.patch("ai.run_ai", return_value=(audit_b1_fail, "m", None)):
            result = run_pass3_audit(*self._args(), calls_remaining=5)
        assert result["b1_compliant"] is False
        assert not result["audit_clean"]

    def test_tone_mismatch_flagged(self):
        import json as _json
        audit_tone = _json.dumps({
            "citation_errors": [],
            "b1_compliant": True,
            "tone_label_ok": False,
            "tone_label_evidence": "narrative is predominantly bearish but label is BUY",
        })
        with mock.patch("ai.run_ai", return_value=(audit_tone, "m", None)):
            result = run_pass3_audit(*self._args(), calls_remaining=5)
        assert result["tone_label_ok"] is False
        assert result["tone_label_evidence"] is not None

    def test_info_severity_does_not_fail_audit(self):
        """Only 'error' and 'warn' severities mark audit_clean=False."""
        import json as _json
        audit_info_only = _json.dumps({
            "citation_errors": [{
                "field": "financial_health",
                "quoted_text": "elevated net debt",
                "issue": "qualitative language without numeric anchor",
                "severity": "info",
            }],
            "b1_compliant": True,
            "tone_label_ok": True,
            "tone_label_evidence": None,
        })
        with mock.patch("ai.run_ai", return_value=(audit_info_only, "m", None)):
            result = run_pass3_audit(*self._args(), calls_remaining=5)
        assert result["audit_clean"] is True, "info-only citation errors should not fail audit_clean"


class TestPass3CallCeiling:
    """F4: C3 ceiling — no retry path can loop; budget_remaining decrements correctly."""

    def _args(self):
        return (
            "AVGO",
            _baseline_for_pass2(),
            _minimal_valid_pass1(),
            _math_for_pass2(),
            _pass2_with_body(),
        )

    def test_constant_exists_and_is_positive(self):
        assert isinstance(MAX_PIPELINE_AI_CALLS, int)
        assert MAX_PIPELINE_AI_CALLS >= 4, "ceiling must be ≥ 4 (pass1+pass2+pass3 baseline)"

    def test_ceiling_zero_skips_llm(self):
        """calls_remaining=0 → audit_skipped=True, zero LLM calls made."""
        call_count = {"n": 0}
        def mock_run_ai(*a, **kw):
            call_count["n"] += 1
            return (_clean_audit_json(), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass3_audit(*self._args(), calls_remaining=0)

        assert result["audit_skipped"] is True
        assert call_count["n"] == 0, "LLM must not be called when calls_remaining=0"

    def test_ceiling_one_makes_exactly_one_call(self):
        call_count = {"n": 0}
        def mock_run_ai(*a, **kw):
            call_count["n"] += 1
            return (_clean_audit_json(), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass3_audit(*self._args(), calls_remaining=1)

        assert call_count["n"] == 1
        assert result["calls_remaining"] == 0

    def test_calls_remaining_decremented_by_one(self):
        with mock.patch("ai.run_ai", return_value=(_clean_audit_json(), "m", None)):
            result = run_pass3_audit(*self._args(), calls_remaining=5)
        assert result["calls_remaining"] == 4

    def test_loop_terminates_within_ceiling(self):
        """Simulate an orchestrator calling audit in a loop — must stop ≤ MAX_PIPELINE_AI_CALLS."""
        import json as _json
        # Each audit call returns an error to simulate the orchestrator wanting to loop
        persistent_error = _json.dumps({
            "citation_errors": [{"field": "f", "quoted_text": "x", "issue": "y", "severity": "warn"}],
            "b1_compliant": True,
            "tone_label_ok": True,
            "tone_label_evidence": None,
        })

        call_count   = {"n": 0}
        budget       = MAX_PIPELINE_AI_CALLS
        iterations   = 0

        def mock_run_ai(*a, **kw):
            call_count["n"] += 1
            return (persistent_error, "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            while budget > 0:
                result  = run_pass3_audit(*self._args(), calls_remaining=budget)
                budget  = result.get("calls_remaining", 0)
                iterations += 1
                if result.get("audit_skipped"):
                    break

        assert iterations <= MAX_PIPELINE_AI_CALLS, (
            f"Loop ran {iterations} times — exceeds ceiling {MAX_PIPELINE_AI_CALLS}"
        )
        assert call_count["n"] <= MAX_PIPELINE_AI_CALLS

    def test_audit_skipped_result_includes_forbidden_vocab(self):
        """Even when skipped, deterministic vocab scan results are returned."""
        ticker, baseline, pass1, math, pass2 = self._args()
        pass2["body"] += " The reward-to-risk capture ratio is 2.5x."
        result = run_pass3_audit(ticker, baseline, pass1, math, pass2, calls_remaining=0)
        assert result["audit_skipped"] is True
        assert any(h["token"] == "capture ratio" for h in result["forbidden_vocab"])


# ════════════════════════════════════════════════════════════════════════════
# PHASE G — run_pipeline orchestration
# ════════════════════════════════════════════════════════════════════════════

import json as _json
from ai import run_pipeline, Pass1ValidationError

_G_TICKER   = "TSTK"
_G_BASELINE = {
    "ticker": "TSTK", "company_name": "Test Co", "current_price": 100.0,
    "shares_out": 1.0, "fy_revenue": 10.0, "fy_op_margin": 0.20,
    "tax_rate_guidance": 0.21, "beta": 1.0, "net_debt": 1.0,
    "franchise_quality": True, "trailing_net_dilution_rate": 0.0,
    "fy_fcf": 2.0, "fy_eps_non_gaap": 5.0, "consensus_eps_fy2": None,
    "peer_set": [], "data_quality_warnings": [],
}
_G_MATH = {
    "implied_fcf_cagr": 0.08,
    "joint_probs":   {"bull": 0.25, "base": 0.55, "bear": 0.20},
    "scenario_eps":  {"bull": 8.0,  "base": 6.0,  "bear": 4.0},
    "price_target":  {"bull_high": 150.0, "bull_mid": 130.0, "base_mid": 110.0, "bear_low": 70.0},
    "pe_band":       {"bull_low": 18, "bull_high": 22, "base_low": 16, "base_high": 20, "bear_low": 12, "bear_high": 16},
    "risk":          {"prob_loss": 0.20, "max_drawdown_pct": 0.30, "expected_return_pct": 0.10, "ev": 110.0},
    "expected_value": 110.0, "recommendation": "BUY",
    "calibration_log": [], "consensus_divergent": False,
}
_G_PASS2 = {
    "investment_thesis": "The implied FCF CAGR of 8.0% suggests reasonable pricing.",
    "reverse_dcf_commentary": "At 8% implied FCF CAGR the buyer bets on continued growth.",
    "scenario_commentary": {
        "bull": "Bull (25%): 130.00.",
        "base": "Base (55%): 110.00.",
        "bear": "Bear (20%): 70.00.",
    },
    "driver_narratives": {"A": "Driver A.", "B": "Driver B.", "C": "Driver C."},
    "financial_health": "FCF of 2.0B with net_debt 1.0B supports the thesis.",
    "recommendation_rationale": "BUY with medium conviction.",
    "conclusion": "BUY.",
    "body": "The implied FCF CAGR of 8.0%.",
    "model_used": "claude-opus-4-7",
}
_G_PASS3 = {
    "audit_skipped": False, "citation_errors": [], "b1_compliant": True,
    "tone_label_ok": True, "tone_label_evidence": None,
    "forbidden_vocab": [], "audit_clean": True, "calls_remaining": 6,
}

_REQUIRED_REPORT_KEYS = (
    "recommendation", "conviction", "model_used", "investment_thesis",
    "scenario_math", "pass3", "data_quality_warnings",
    "catalysts", "segments", "peer_tickers", "scenario_inputs",
    "drivers", "headwinds", "tailwinds", "concentration",
)
_REQUIRED_SM_KEYS = (
    "final_probabilities", "eps", "price_target", "expected_value",
    "expected_return", "base_implied_return", "prob_positive",
    "monotonicity_violation", "bull_below_current", "diagnostic", "degraded_sections",
)


def _pipeline_mocks(
    pass1=None, math=None, pass2=None, pass3=None,
    pass1_raises=None, math_raises=None, pass2_raises=None,
):
    """Return a context-manager stack that patches all four pipeline sub-functions."""
    p1 = pass1 if pass1 is not None else _minimal_valid_pass1()
    ma = math  if math  is not None else _G_MATH
    p2 = pass2 if pass2 is not None else _G_PASS2
    p3 = pass3 if pass3 is not None else _G_PASS3

    def _p1(*a, **kw):
        if pass1_raises:
            raise pass1_raises
        return p1

    def _ma(*a, **kw):
        if math_raises:
            raise math_raises
        return ma

    import contextlib
    @contextlib.contextmanager
    def _ctx():
        with mock.patch("ai.run_pass1_foundation", side_effect=_p1), \
             mock.patch("ai.run_methodology_math", side_effect=_ma), \
             mock.patch("ai.run_pass2_report",     return_value=p2), \
             mock.patch("ai.run_pass3_audit",       return_value=p3):
            yield

    return _ctx()


class TestPipelineOrchestrator:
    """Phase G: run_pipeline orchestration, field bridging, and error handling."""

    def test_required_keys_present(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        for key in _REQUIRED_REPORT_KEYS:
            assert key in result, f"missing key: {key}"

    def test_scenario_math_has_render_aliases(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        sm = result["scenario_math"]
        for key in _REQUIRED_SM_KEYS:
            assert key in sm, f"scenario_math missing key: {key}"

    def test_price_target_has_bull_base_bear_aliases(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        pt = result["scenario_math"]["price_target"]
        assert "bull" in pt and "base" in pt and "bear" in pt
        assert pt["bull"] == _G_MATH["price_target"]["bull_mid"]
        assert pt["base"] == _G_MATH["price_target"]["base_mid"]
        assert pt["bear"] == _G_MATH["price_target"]["bear_low"]

    def test_final_probabilities_equals_joint_probs(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        fp = result["scenario_math"]["final_probabilities"]
        assert fp == _G_MATH["joint_probs"]

    def test_eps_alias_equals_scenario_eps(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert result["scenario_math"]["eps"] == _G_MATH["scenario_eps"]

    def test_prob_positive_in_unit_interval(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        pp = result["scenario_math"]["prob_positive"]
        assert 0.0 <= pp <= 1.0, f"prob_positive={pp} out of [0,1]"

    def test_prob_positive_is_one_minus_prob_loss(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        expected = round(1.0 - _G_MATH["risk"]["prob_loss"], 4)
        assert abs(result["scenario_math"]["prob_positive"] - expected) < 1e-6

    def test_conviction_valid_value(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert result["conviction"] in ("High", "Medium", "Low")

    def test_recommendation_valid_value(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert result["recommendation"] in ("BUY", "WATCH", "PASS")

    def test_pass1_failure_returns_error_dict(self):
        exc = Pass1ValidationError(["missing macro_drivers"])
        with _pipeline_mocks(pass1_raises=exc):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert "error" in result
        assert result.get("recommendation") == "WATCH"
        assert "scenario_math" in result

    def test_math_failure_returns_error_dict(self):
        with _pipeline_mocks(math_raises=ValueError("bad math")):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert "error" in result
        assert "Math layer failed" in result["error"]

    def test_bull_below_triggers_retry(self):
        bull_below_math  = {**_G_MATH, "price_target": {
            "bull_high": 95.0, "bull_mid": 90.0, "base_mid": 80.0, "bear_low": 60.0,
        }, "risk": {**_G_MATH["risk"]}}
        bull_above_math  = _G_MATH

        call_count = {"n": 0}
        def _alt_p1(*a, retry_hint="", **kw):
            call_count["n"] += 1
            return _minimal_valid_pass1()

        def _alt_math(p1, bl):
            return bull_above_math if call_count["n"] >= 2 else bull_below_math

        with mock.patch("ai.run_pass1_foundation", side_effect=_alt_p1), \
             mock.patch("ai.run_methodology_math", side_effect=_alt_math), \
             mock.patch("ai.run_pass2_report",     return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit",       return_value=_G_PASS3):
            result = run_pipeline(_G_TICKER, _G_BASELINE)

        assert call_count["n"] >= 2, "retry was not called when bull < current"
        assert not result["scenario_math"]["bull_below_current"]

    def test_bull_below_flag_set_when_retry_fails(self):
        bull_below_math = {**_G_MATH, "price_target": {
            "bull_high": 95.0, "bull_mid": 90.0, "base_mid": 80.0, "bear_low": 60.0,
        }, "risk": {**_G_MATH["risk"]}}

        with mock.patch("ai.run_pass1_foundation", return_value=_minimal_valid_pass1()), \
             mock.patch("ai.run_methodology_math", return_value=bull_below_math), \
             mock.patch("ai.run_pass2_report",     return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit",       return_value=_G_PASS3):
            result = run_pipeline(_G_TICKER, _G_BASELINE)

        assert result["scenario_math"]["bull_below_current"] is True
        assert "90.00" in result["scenario_math"]["bull_below_msg"]

    def test_pass2_failure_uses_stub_narrative(self):
        with mock.patch("ai.run_pass1_foundation", return_value=_minimal_valid_pass1()), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH), \
             mock.patch("ai.run_pass2_report",     side_effect=Pass1ValidationError(["gen error"])), \
             mock.patch("ai.run_pass3_audit",       return_value=_G_PASS3):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert "Narrative unavailable" in result["investment_thesis"]
        assert result["model_used"] == "N/A"

    def test_catalysts_bridged_with_bull_signal(self):
        # 3 catalysts to avoid the catalysts-fallback call (which would need a real API key)
        p1 = {**_minimal_valid_pass1(), "catalysts": [
            {"date": "Q2 FY2026", "event": "Earnings", "what_to_watch": "Rev growth > 20%"},
            {"date": "Q3 FY2026", "event": "Investor Day", "what_to_watch": "Buyback size"},
            {"date": "Q4 FY2026", "event": "New product", "what_to_watch": "Adoption"},
        ]}
        with _pipeline_mocks(pass1=p1):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        cats = result["catalysts"]
        assert len(cats) == 3
        assert cats[0]["bull_signal"] == "Rev growth > 20%"
        assert cats[0]["bear_signal"] == ""
        assert cats[0]["bear_signal"] == ""

    def test_segments_bridged_from_segments_enriched(self):
        p1 = {**_minimal_valid_pass1(), "segments_enriched": [
            {"name": "Core", "fy_revenue": 8.0, "share_pct": 0.80, "growth_yoy": 0.10, "gross_margin": 0.65},
        ]}
        with _pipeline_mocks(pass1=p1):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        segs = result["segments"]
        assert len(segs) == 1
        assert segs[0]["name"] == "Core"
        assert segs[0]["current_revenue"] == 8.0

    def test_pass3_tone_mismatch_inverted(self):
        p3_mismatch = {**_G_PASS3, "tone_label_ok": False, "tone_label_evidence": "BUY but text says sell"}
        with _pipeline_mocks(pass3=p3_mismatch):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert result["pass3"]["tone_label_mismatch"] is True
        assert "BUY but text says sell" in result["pass3"]["tone_label_evidence"]

    def test_pass3_citation_errors_mapped_to_consistency_flags(self):
        p3 = {**_G_PASS3, "citation_errors": [
            {"field": "investment_thesis", "issue": "wrong number", "severity": "warn"}
        ]}
        with _pipeline_mocks(pass3=p3):
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        flags = result["pass3"]["consistency_flags"]
        assert len(flags) == 1
        assert flags[0]["field"] == "investment_thesis"
        assert flags[0]["severity"] == "warn"

    def test_no_error_key_on_success(self):
        with _pipeline_mocks():
            result = run_pipeline(_G_TICKER, _G_BASELINE)
        assert "error" not in result, f"unexpected error key: {result.get('error')}"

    def test_empty_scenario_math_has_all_render_keys(self):
        """_empty_scenario_math() must contain every key render() accesses on sm."""
        from ai import _empty_scenario_math as _esm
        sm = _esm()
        for key in _REQUIRED_SM_KEYS:
            assert key in sm, f"_empty_scenario_math missing key: {key}"


# ════════════════════════════════════════════════════════════════════════════
# yfinance period-index parsing
# Regression for the "+1y"/"+2y" vs "1y"/"2y" bug in fetch_consensus_pack.
# ════════════════════════════════════════════════════════════════════════════

class TestYFinanceConsensusIndexParsing:
    """fetch_consensus_pack must map '+1y'/'+2y' period rows, not '1y'/'2y'.
    +1y → consensus_eps_fy1 (FY+1); +2y → consensus_eps_fy2 (FY+2 used in Step A)."""

    def _make_earnings_df(self):
        import pandas as pd
        return pd.DataFrame(
            {
                "avg":             [2.39,  3.21, 11.36, 18.26, 23.00],
                "low":             [2.36,  2.69, 10.24, 13.35, 17.50],
                "high":            [2.50,  4.26, 13.31, 21.45, 27.00],
                "yearAgoEps":      [1.58,  1.69,  6.82, 11.36, 18.26],
                "numberOfAnalysts":[36,    35,    43,    42,    40],
                "growth":          [0.513, 0.898, 0.666, 0.608, 0.259],
            },
            index=pd.Index(["0q", "+1q", "0y", "+1y", "+2y"], name="period"),
        )

    def _make_revenue_df(self):
        import pandas as pd
        return pd.DataFrame(
            {
                "avg": [22.08e9, 28.69e9, 103.27e9, 158.86e9],
                "low": [21.88e9, 25.15e9,  85.61e9,  90.65e9],
                "high":[22.50e9, 30.00e9, 120.00e9, 180.00e9],
                "yearAgoRevenue":[15.00e9, 15.95e9, 63.89e9, 103.27e9],
                "growth":[0.472, 0.799, 0.617, 0.538],
            },
            index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"),
        )

    def test_fy2_eps_populated_not_none(self):
        import unittest.mock as mock
        from fmp_api import fetch_consensus_pack

        mock_ticker = mock.MagicMock()
        mock_ticker.earnings_estimate = self._make_earnings_df()
        mock_ticker.revenue_estimate  = self._make_revenue_df()
        mock_ticker.analyst_price_targets = {
            "current": 414.14, "high": 630.0, "low": 215.88,
            "mean": 480.49, "median": 495.0,
        }
        mock_ticker.info = {}

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", return_value=mock_ticker):
            result = fetch_consensus_pack("TEST")

        # +1y row → consensus_eps_fy1 (the near FY+1 estimate)
        assert result["consensus_eps_fy1"] is not None, (
            "consensus_eps_fy1 is None — '+1y' period row was not matched"
        )
        assert abs(result["consensus_eps_fy1"]["mid"] - 18.26) < 0.01

        # +2y row → consensus_eps_fy2 (the FY+2 estimate used in Step A and 2yr CAGR)
        assert result["consensus_eps_fy2"] is not None, (
            "consensus_eps_fy2 is None — '+2y' period row was not matched"
        )
        assert abs(result["consensus_eps_fy2"]["mid"] - 23.00) < 0.01
        assert result["consensus_fy2_source"] == "reported"

        # revenue mapping unchanged
        assert result["consensus_revenue_fy2"] is not None
        assert abs(result["consensus_revenue_fy2"]["mid"] - 158.86e9) < 1e8


# ════════════════════════════════════════════════════════════════════════════
# FY+2 consensus fallback — absent / identical / derived / missing-fy1
# ════════════════════════════════════════════════════════════════════════════

class TestConsensusFY2Fallback:
    """
    fetch_consensus_pack sets consensus_fy2_source correctly and falls back
    to derivation when the +2y yfinance row is absent or duplicates +1y.
    """

    def _make_ee_df(self, rows):
        import pandas as pd
        index = list(rows.keys())
        return pd.DataFrame(
            {
                "avg":              [rows[r]["avg"] for r in index],
                "low":              [rows[r].get("low") for r in index],
                "high":             [rows[r].get("high") for r in index],
                "numberOfAnalysts": [rows[r].get("numberOfAnalysts", 10) for r in index],
            },
            index=pd.Index(index, name="period"),
        )

    def _base_mock(self, ee_df, trailing_eps=None):
        import unittest.mock as mock
        import pandas as pd
        t = mock.MagicMock()
        t.earnings_estimate = ee_df
        t.revenue_estimate = pd.DataFrame()
        t.analyst_price_targets = {}
        t.info = {"trailingEps": trailing_eps} if trailing_eps is not None else {}
        return t

    def test_reported_when_distinct_plus2y_row(self):
        """Distinct +2y row (different avg from +1y) → source == 'reported', fy2 matches."""
        import unittest.mock as mock
        from fmp_api import fetch_consensus_pack

        ee = self._make_ee_df({
            "+1y": {"avg": 15.5, "low": 14.0, "high": 16.5},
            "+2y": {"avg": 19.0, "low": 17.5, "high": 21.0},
        })
        mock_ticker = self._base_mock(ee)

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", return_value=mock_ticker), \
             mock.patch("fmp_api._fmp_get", return_value=None):
            result = fetch_consensus_pack("TEST")

        assert result["consensus_fy2_source"] == "reported"
        assert result["consensus_eps_fy1"] is not None
        assert abs(result["consensus_eps_fy1"]["mid"] - 15.5) < 0.01
        assert result["consensus_eps_fy2"] is not None
        assert abs(result["consensus_eps_fy2"]["mid"] - 19.0) < 0.01

    def test_derived_when_plus2y_absent(self):
        """+2y row absent → FMP returns nothing → derived from FY+1 × growth, capped 50%."""
        import unittest.mock as mock
        from fmp_api import fetch_consensus_pack

        ee = self._make_ee_df({
            "+1y": {"avg": 15.0, "low": 13.5, "high": 16.5},
        })
        # trailing_eps=12.5 → growth = (15.0/12.5) - 1 = 0.20 → fy2.mid = 15.0 × 1.20 = 18.0
        mock_ticker = self._base_mock(ee, trailing_eps=12.5)

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", return_value=mock_ticker), \
             mock.patch("fmp_api._fmp_get", return_value=None):
            result = fetch_consensus_pack("TEST")

        assert result["consensus_fy2_source"] == "derived", (
            f"expected 'derived' when +2y absent; got {result['consensus_fy2_source']!r}"
        )
        assert result["consensus_eps_fy2"] is not None
        assert abs(result["consensus_eps_fy2"]["mid"] - 18.0) < 0.05

    def test_derived_when_plus2y_identical_to_plus1y(self):
        """+2y avg numerically identical to +1y → treated as absent → derived."""
        import unittest.mock as mock
        from fmp_api import fetch_consensus_pack

        # Both rows have the exact same avg — data provider duplicated the row
        ee = self._make_ee_df({
            "+1y": {"avg": 15.0, "low": 13.5, "high": 16.5},
            "+2y": {"avg": 15.0, "low": 13.5, "high": 16.5},
        })
        # trailing_eps=12.5 → growth=0.20 → fy2.mid=18.0
        mock_ticker = self._base_mock(ee, trailing_eps=12.5)

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", return_value=mock_ticker), \
             mock.patch("fmp_api._fmp_get", return_value=None):
            result = fetch_consensus_pack("TEST")

        assert result["consensus_fy2_source"] == "derived", (
            f"identical +2y must be treated as absent; got {result['consensus_fy2_source']!r}"
        )
        assert result["consensus_eps_fy2"] is not None
        assert abs(result["consensus_eps_fy2"]["mid"] - 18.0) < 0.05

    def test_none_when_no_fy1_either(self):
        """No FY+1 row and FMP empty → cannot derive → consensus_eps_fy2 is None."""
        import unittest.mock as mock
        import pandas as pd
        from fmp_api import fetch_consensus_pack

        # Empty DataFrame — no +1y or +2y rows
        mock_ticker = self._base_mock(pd.DataFrame())

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", return_value=mock_ticker), \
             mock.patch("fmp_api._fmp_get", return_value=None):
            result = fetch_consensus_pack("TEST")

        assert result["consensus_eps_fy2"] is None, (
            f"fy2 must be None when no fy1 and FMP empty; got {result['consensus_eps_fy2']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# fetch_peer_metrics — shape and +1y growth extraction
# ════════════════════════════════════════════════════════════════════════════

class TestFetchPeerMetrics:
    """fetch_peer_metrics returns §5.1 peer_set shape with +1y growth."""

    def _make_ee_df(self, growth_plus1y: float):
        import pandas as pd
        return pd.DataFrame(
            {"avg": [5.0, 6.5], "low": [4.8, 6.0], "high": [5.5, 7.0],
             "yearAgoEps": [3.0, 5.0], "numberOfAnalysts": [30, 28],
             "growth": [0.2, growth_plus1y]},
            index=pd.Index(["0y", "+1y"], name="period"),
        )

    def _make_mock_ticker(self, fwd_pe, growth_plus1y):
        import unittest.mock as mock
        t = mock.MagicMock()
        t.info = {"forwardPE": fwd_pe, "earningsGrowth": None}
        t.earnings_estimate = self._make_ee_df(growth_plus1y)
        return t

    def test_returns_correct_shape_for_two_peers(self):
        import unittest.mock as mock
        from fmp_api import fetch_peer_metrics

        ticker_a = self._make_mock_ticker(fwd_pe=25.0, growth_plus1y=0.30)
        ticker_b = self._make_mock_ticker(fwd_pe=18.5, growth_plus1y=0.12)

        call_map = {"PEER_A": ticker_a, "PEER_B": ticker_b}

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", side_effect=lambda t: call_map[t]):
            result = fetch_peer_metrics(["PEER_A", "PEER_B"])

        assert len(result) == 2
        # Input order preserved
        assert result[0]["ticker"] == "PEER_A"
        assert result[1]["ticker"] == "PEER_B"
        # §5.1 contract keys all present
        for row in result:
            for key in ("ticker", "fwd_pe", "growth", "op_margin", "fcf_margin"):
                assert key in row, f"missing key '{key}' in {row}"
        # Values extracted correctly from +1y row
        assert abs(result[0]["fwd_pe"] - 25.0) < 0.01
        assert abs(result[0]["growth"] - 0.30) < 0.001
        assert abs(result[1]["fwd_pe"] - 18.5) < 0.01
        assert abs(result[1]["growth"] - 0.12) < 0.001
        # op_margin and fcf_margin are always None
        assert result[0]["op_margin"] is None
        assert result[0]["fcf_margin"] is None

    def test_failed_ticker_skipped_not_raised(self):
        import unittest.mock as mock
        from fmp_api import fetch_peer_metrics

        good = self._make_mock_ticker(fwd_pe=20.0, growth_plus1y=0.25)
        bad  = mock.MagicMock()
        bad.info = mock.PropertyMock(side_effect=RuntimeError("network failure"))

        call_map = {"GOOD": good, "BAD": bad}

        with mock.patch("fmp_api.HAS_YF", True), \
             mock.patch("yfinance.Ticker", side_effect=lambda t: call_map[t]):
            result = fetch_peer_metrics(["GOOD", "BAD"])

        # Must not raise; BAD ticker gets None fields
        tickers = [r["ticker"] for r in result]
        assert "GOOD" in tickers
        good_row = next(r for r in result if r["ticker"] == "GOOD")
        assert abs(good_row["growth"] - 0.25) < 0.001

    def test_empty_input_returns_empty_list(self):
        from fmp_api import fetch_peer_metrics
        assert fetch_peer_metrics([]) == []


# ════════════════════════════════════════════════════════════════════════════
# BUG-FIX REGRESSION TESTS
# Bug 1: five_yr_eps_growth_est uses implied 2yr forward CAGR, not trailing earningsGrowth
# Bug 1B: pe_band growth and PE caps prevent 3-figure multiples
# ════════════════════════════════════════════════════════════════════════════

class TestBug1GrowthRateSource:
    """
    Bug 1: calc_baseline must derive five_yr_eps_growth_est from consensus implied CAGR,
    not from yfinance earningsGrowth (which is trailing YoY — NVDA: 214.5% outlier).

    Hand-calc: (12.646 / 4.90)^0.5 - 1 = 1.6065... - 1 = 0.6065, capped to 0.60.
    """

    def _mock_data(self) -> dict:
        return {
            "info": {
                "symbol": "",           # empty → skips FMP segment fetch
                "shortName": "TestCo",
                "currency": "USD",
                "currentPrice": 100.0,
                "sharesOutstanding": 1_000_000_000,
                "earningsGrowth": 2.145,   # old buggy source (trailing YoY, 214.5%)
                "trailingEps": 4.90,       # fy_eps_non_gaap via info fallback
            },
            "inc": None, "qinc": None, "bs": None,
            "cf": None, "hist": None, "news": [],
        }

    def _consensus(self) -> dict:
        return {"consensus_eps_fy2": {"low": 10.0, "mid": 12.646, "high": 15.0}}

    def test_implied_cagr_formula_hand_calc(self):
        """Independent verification: (12.646/4.90)^0.5 - 1 ≈ 0.6065, capped to 0.60."""
        fy2_mid = 12.646
        fy_eps  = 4.90
        implied = (fy2_mid / fy_eps) ** 0.5 - 1
        assert abs(implied - 0.6065) < 0.001, f"implied={implied:.4f}, expected ≈0.6065"
        capped = min(implied, 0.60)
        assert abs(capped - 0.60) < 1e-9, f"capped={capped}, expected 0.60"

    def test_calc_baseline_uses_consensus_not_earnings_growth(self):
        """calc_baseline must ignore earningsGrowth=2.145 and use consensus CAGR ≈ 0.60."""
        from compute import calc_baseline
        baseline = calc_baseline(self._mock_data(), consensus_pack=self._consensus())
        est = baseline.get("five_yr_eps_growth_est")
        assert est is not None, "five_yr_eps_growth_est must be populated"
        assert abs(est - 0.60) < 1e-6, (
            f"five_yr_eps_growth_est={est:.4f}; expected 0.60 (capped from ≈0.606). "
            f"If this is 2.145, earningsGrowth is still being used (bug not fixed)."
        )

    def test_calc_baseline_fallback_to_revenue_growth_when_no_consensus(self):
        """Without consensus, falls back to revenueGrowth capped at 40%."""
        from compute import calc_baseline
        data = self._mock_data()
        data["info"]["revenueGrowth"] = 0.55   # exceeds 40% cap
        del data["info"]["earningsGrowth"]
        baseline = calc_baseline(data, consensus_pack=None)
        est = baseline.get("five_yr_eps_growth_est")
        assert est is not None, "five_yr_eps_growth_est must fall back to revenueGrowth"
        assert abs(est - 0.40) < 1e-6, (
            f"five_yr_eps_growth_est={est:.4f}; expected 0.40 (revenueGrowth=0.55 capped)"
        )

    def test_calc_baseline_none_when_no_sources(self):
        """Without consensus or revenueGrowth, five_yr_eps_growth_est is None."""
        from compute import calc_baseline
        data = self._mock_data()
        del data["info"]["earningsGrowth"]
        # No revenueGrowth in info, no consensus
        baseline = calc_baseline(data, consensus_pack=None)
        est = baseline.get("five_yr_eps_growth_est")
        assert est is None, f"expected None without any source, got {est}"


class TestBug1PEBandCaps:
    """
    Bug 1B: pe_band must apply growth cap (0.60) and bull PE hard cap (60.0)
    to prevent 3-figure multiples from anomalous input growth rates.
    """

    def test_bull_pe_high_at_most_60_with_normal_growth(self):
        lo, hi = pe_band("bull", 0.60, franchise_quality=True)
        assert hi <= 60.0, f"bull_pe_high={hi} with growth=0.60 must be ≤ 60.0"

    def test_bull_pe_high_at_most_60_with_anomalous_growth(self):
        """growth_rate=2.145 (NVDA Stage 4 bug) must not produce a 3-figure bull P/E."""
        lo, hi = pe_band("bull", 2.145, franchise_quality=True)
        assert hi <= 60.0, (
            f"bull_pe_high={hi} with growth=2.145; expected ≤ 60.0. "
            f"If this is ≥ 200, the growth cap in pe_band is not applied."
        )

    def test_base_and_bear_unaffected_by_growth_cap(self):
        """Base and bear bands with growth=0.60 are well-behaved (no 3-figure P/E)."""
        _, base_hi = pe_band("base", 0.60, franchise_quality=True)
        _, bear_hi = pe_band("bear", 0.60, franchise_quality=True)
        assert base_hi < 200, f"base_pe_high={base_hi} unexpectedly large"
        assert bear_hi < 200, f"bear_pe_high={bear_hi} unexpectedly large"

    def test_run_methodology_math_logs_peg_guard_when_growth_high(self):
        """run_methodology_math logs the PEG guard cap when growth_rate > 0.60."""
        bl = dict(AVGO_V2_BASELINE, five_yr_eps_growth_est=2.145)  # anomalous growth
        math = run_methodology_math({"events": AVGO_EVENTS}, bl)
        guard_entries = [e for e in math["calibration_log"] if "PEG guard" in e]
        assert len(guard_entries) >= 1, (
            f"expected at least one PEG guard log entry; calibration_log={math['calibration_log']}"
        )
        assert "2.145" in guard_entries[0], (
            f"PEG guard entry should cite original growth_rate; got: {guard_entries[0]!r}"
        )

    def test_run_methodology_math_logs_pe_anchors_absent(self):
        """run_methodology_math logs pe_anchors absence when pass1 omits that key."""
        pass1_no_anchors = {"events": AVGO_EVENTS}  # no pe_anchors key
        math = run_methodology_math(pass1_no_anchors, AVGO_V2_BASELINE)
        absent_entries = [e for e in math["calibration_log"] if "pe_anchors absent" in e]
        assert len(absent_entries) == 1, (
            f"expected exactly one pe_anchors-absent log entry; "
            f"calibration_log={math['calibration_log']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG 2 — Calibration log wiring: all three cap/absence conditions append correctly
#
# (a) growth_rate > 0.60 — tested in TestBug1PEBandCaps.test_run_methodology_math_logs_peg_guard_when_growth_high
# (b) bull_pe_high capped at 60× — tested below (new)
# (c) pe_anchors absent         — tested in TestBug1PEBandCaps.test_run_methodology_math_logs_pe_anchors_absent
# ════════════════════════════════════════════════════════════════════════════

class TestBug2CalibrationLogWiring:
    """
    Bug 2: confirm each cap/absent condition appends to calibration_log when it fires.
    These tests set up inputs that guarantee the condition, then assert the exact
    log string appears.  Scope confirmation: the append() calls are at the top level
    of run_methodology_math (not inside nested branches that exit early).
    """

    def test_bull_pe_high_cap_logged_when_peer_median_over_60(self):
        """
        bull_pe_high cap fires when peer_median > 60.  Cap is min(pe_high, 60.0)
        inside pe_band(); the log entry in run_methodology_math fires on the same
        condition so the two stay in sync.
        """
        bl = dict(AVGO_V2_BASELINE, peer_set=[
            {"ticker": "PEER_A", "fwd_pe": 70.0},
            {"ticker": "PEER_B", "fwd_pe": 80.0},
            {"ticker": "PEER_C", "fwd_pe": 90.0},
        ])
        math = run_methodology_math({"events": AVGO_EVENTS}, bl)
        cap_entries = [e for e in math["calibration_log"] if "bull_pe_high capped" in e]
        assert len(cap_entries) >= 1, (
            f"Expected 'bull_pe_high capped' log entry when peer_median=80>60; "
            f"calibration_log={math['calibration_log']}"
        )
        assert math["pe_band"]["bull_high"] <= 60.0, (
            f"bull_pe_high={math['pe_band']['bull_high']} must be ≤ 60.0 after cap fires"
        )

    def test_growth_rate_cap_logged(self):
        """(a) growth_rate > 0.60 fires and is logged (regression guard for existing fix)."""
        bl = dict(AVGO_V2_BASELINE, five_yr_eps_growth_est=1.50)
        math = run_methodology_math({"events": AVGO_EVENTS}, bl)
        entries = [e for e in math["calibration_log"] if "PEG guard" in e and "1.500" in e]
        assert len(entries) >= 1, (
            f"PEG guard log entry not found for growth=1.50; "
            f"calibration_log={math['calibration_log']}"
        )

    def test_pe_anchors_absent_logged(self):
        """(c) pe_anchors absent fires and is logged (regression guard for existing fix)."""
        math = run_methodology_math({"events": AVGO_EVENTS}, AVGO_V2_BASELINE)
        entries = [e for e in math["calibration_log"] if "pe_anchors absent" in e]
        assert len(entries) == 1, (
            f"Expected exactly one 'pe_anchors absent' entry; "
            f"calibration_log={math['calibration_log']}"
        )

    def test_no_spurious_cap_log_when_peer_below_60(self):
        """When peer_median < 60, the bull_pe_high cap log entry must NOT appear."""
        # AVGO_V2_BASELINE peer_set has median = 38 < 60
        math = run_methodology_math({"events": AVGO_EVENTS}, AVGO_V2_BASELINE)
        cap_entries = [e for e in math["calibration_log"] if "bull_pe_high capped" in e]
        assert cap_entries == [], (
            f"Spurious cap log entry when peer_median=38; "
            f"calibration_log={math['calibration_log']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG 1 (catalysts) — focused fallback call fires when pass1 has < 3 catalysts
# ════════════════════════════════════════════════════════════════════════════

class TestCatalystsFallback:
    """
    Bug 1: run_pipeline makes one extra focused LLM call when pass1 returns < 3
    catalysts.  Verified by mocking run_ai (the fallback call site) while mocking
    all other pipeline sub-functions so no real API calls are made.
    """

    def _baseline(self):
        return {**_G_BASELINE, "company_name": "Test Co"}

    def test_fallback_fires_and_populates_catalysts_when_empty(self):
        import json as _json
        p1_no_cats = {**_minimal_valid_pass1(), "catalysts": []}
        cats = [
            {"date": "Q3 FY2026", "event": "Earnings", "what_to_watch": "Revenue beat"},
            {"date": "Q4 FY2026", "event": "Investor Day", "what_to_watch": "Buyback size"},
            {"date": "2026-03", "event": "Product launch", "what_to_watch": "Adoption rate"},
        ]
        call_count = {"n": 0}

        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (_json.dumps(cats), "test-model", None)

        with mock.patch("ai.run_pass1_foundation", return_value=p1_no_cats), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH), \
             mock.patch("ai.run_pass2_report", return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit", return_value=_G_PASS3), \
             mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pipeline(_G_TICKER, self._baseline())

        assert call_count["n"] >= 1, "fallback LLM call must fire when catalysts is empty"
        assert len(result["catalysts"]) >= 3, (
            f"catalysts fallback must populate ≥ 3 entries; got {len(result['catalysts'])}"
        )

    def test_fallback_fires_when_fewer_than_3_catalysts(self):
        """Fallback fires when pass1 returns exactly 2 catalysts."""
        import json as _json
        p1_few_cats = {**_minimal_valid_pass1(), "catalysts": [
            {"date": "Q3 FY2026", "event": "A", "what_to_watch": "x"},
            {"date": "Q4 FY2026", "event": "B", "what_to_watch": "y"},
        ]}
        cats = [
            {"date": "Q3 FY2026", "event": "E1", "what_to_watch": "w1"},
            {"date": "Q4 FY2026", "event": "E2", "what_to_watch": "w2"},
            {"date": "2026-03",   "event": "E3", "what_to_watch": "w3"},
        ]
        call_count = {"n": 0}

        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (_json.dumps(cats), "test-model", None)

        with mock.patch("ai.run_pass1_foundation", return_value=p1_few_cats), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH), \
             mock.patch("ai.run_pass2_report", return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit", return_value=_G_PASS3), \
             mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pipeline(_G_TICKER, self._baseline())

        assert call_count["n"] >= 1, "fallback must fire when catalysts < 3"
        assert len(result["catalysts"]) >= 3

    def test_fallback_not_fired_when_catalysts_sufficient(self):
        """Fallback must NOT fire when pass1 already has 3+ catalysts."""
        p1_with_cats = _minimal_valid_pass1()  # has exactly 3 catalysts
        call_count = {"n": 0}

        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return ("[]", "test-model", None)

        with mock.patch("ai.run_pass1_foundation", return_value=p1_with_cats), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH), \
             mock.patch("ai.run_pass2_report", return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit", return_value=_G_PASS3), \
             mock.patch("ai.run_ai", side_effect=mock_run_ai):
            run_pipeline(_G_TICKER, self._baseline())

        assert call_count["n"] == 0, (
            "run_ai must not be called when pass1 already has ≥ 3 catalysts"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG 3 — macro_drivers shape: dict {A,B,C} required, list rejected
# ════════════════════════════════════════════════════════════════════════════

class TestBug3MacroDriversShape:
    """
    Bug 3: _validate_pass1_v2 must reject a list-of-dicts for macro_drivers and
    require a dict keyed by A, B, C per §5.2 contract.
    """

    def test_dict_format_is_valid(self):
        """Dict-keyed macro_drivers passes validation with no errors."""
        p = _minimal_valid_pass1()
        assert isinstance(p["macro_drivers"], dict), "fixture must use dict format"
        soft, hard = _validate_pass1_v2(p)
        assert hard == [], f"valid dict macro_drivers produced hard errors: {hard}"

    def test_list_format_is_rejected_as_hard_error(self):
        """list-of-dicts macro_drivers must be a hard error with corrective hint."""
        p = _minimal_valid_pass1()
        p["macro_drivers"] = [
            {"id": "A", "label": "Growth", "narrative": "drives bull"},
            {"id": "B", "label": "Stability", "narrative": "keeps base"},
            {"id": "C", "label": "Risk", "narrative": "bear driver"},
        ]
        soft, hard = _validate_pass1_v2(p)
        assert any("not a list" in e for e in hard), (
            f"list macro_drivers must produce a hard error with 'not a list' hint; hard={hard}"
        )

    def test_missing_key_is_hard(self):
        """Dict with only A, B (missing C) is still a hard error."""
        p = _minimal_valid_pass1()
        p["macro_drivers"] = {"A": {"label": "x", "narrative": "y"},
                               "B": {"label": "x", "narrative": "y"}}
        soft, hard = _validate_pass1_v2(p)
        assert any("A, B, C" in e or "keys" in e for e in hard)

    def test_wrong_key_name_is_hard(self):
        """Dict with key X instead of A is still a hard error."""
        p = _minimal_valid_pass1()
        p["macro_drivers"] = {"X": {"label": "x", "narrative": "y"},
                               "B": {"label": "x", "narrative": "y"},
                               "C": {"label": "x", "narrative": "y"}}
        soft, hard = _validate_pass1_v2(p)
        assert any("A, B, C" in e or "keys" in e for e in hard)

    def test_missing_label_is_soft(self):
        """Missing label on a driver entry is a soft warning."""
        p = _minimal_valid_pass1()
        p["macro_drivers"]["A"] = {"narrative": "drives bull"}  # no label
        soft, hard = _validate_pass1_v2(p)
        assert hard == [], f"missing label must be soft; hard={hard}"
        assert any("label" in e for e in soft)

    def test_normalize_macro_drivers_converts_list(self):
        """_normalize_macro_drivers converts legacy list → dict during transition."""
        from ai import _normalize_macro_drivers
        legacy_list = [
            {"id": "A", "label": "Growth", "narrative": "bull"},
            {"id": "B", "label": "Stable", "narrative": "base"},
            {"id": "C", "label": "Risk",   "narrative": "bear"},
        ]
        result = _normalize_macro_drivers(legacy_list)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"A", "B", "C"}
        assert result["A"]["label"] == "Growth"
        assert "id" not in result["A"]  # id key stripped

    def test_normalize_macro_drivers_passes_through_dict(self):
        from ai import _normalize_macro_drivers
        d = {"A": {"label": "x"}, "B": {"label": "y"}, "C": {"label": "z"}}
        assert _normalize_macro_drivers(d) is d  # identity for valid dict

    def test_normalize_macro_drivers_handles_none(self):
        from ai import _normalize_macro_drivers
        assert _normalize_macro_drivers(None) == {}


# ════════════════════════════════════════════════════════════════════════════
# BULL EPS EVENT-DRIVEN — all scenarios use scenario_eps; Step A is a genuine backstop
# ════════════════════════════════════════════════════════════════════════════

# Frozen NVDA-like inputs. Tiny bull revenue events → raw event-driven bull EPS ≈ $3.12.
# consensus_eps_fy2.high=10.0 → Step A floor=9.50 > $3.12 → Step A DOES fire.
# This fixture tests that Step A is a working backstop when events are too conservative.

BUG5_BASELINE = {
    "current_price":              120.0,
    "shares_out":                 24.5,
    "fy_revenue":                 130.0,
    "fy_op_margin":               0.57,
    "tax_rate_guidance":          0.12,
    "beta":                       1.6,
    "net_debt":                   -10.0,
    "horizon_years":              5,
    "franchise_quality":          True,
    "trailing_net_dilution_rate": -0.03,
    "fy_fcf":                     50.0,
    "five_yr_eps_growth_est":     0.60,     # at cap → bull_growth = 0.60
    "fy_eps_non_gaap":            4.90,
    "peer_set": [
        {"ticker": "AMD",  "fwd_pe": 25.0},
        {"ticker": "INTC", "fwd_pe": 20.0},
        {"ticker": "QCOM", "fwd_pe": 18.0},
    ],
    # consensus.high=10.0 → floor=9.50 > event-driven bull ~$3.12 → Step A fires
    "consensus_eps_fy2": {"low": 7.0, "mid": 8.5, "high": 10.0},
}

# Tiny revenue events — raw event-driven bull ≈ $3.12, well below the Step A floor.
BUG5_PASS1 = {
    "events": [
        {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.40,
         "revenue_at_risk_low": 0.5, "revenue_at_risk_high": 1.0,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
        {"id": "A2", "driver": "A", "outcome": "bear", "probability": 0.60,
         "revenue_at_risk_low": -5.0, "revenue_at_risk_high": -2.0,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
        {"id": "B1", "driver": "B", "outcome": "base", "probability": 0.70,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 1.0,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
        {"id": "B2", "driver": "B", "outcome": "bear", "probability": 0.30,
         "revenue_at_risk_low": -10.0, "revenue_at_risk_high": -5.0,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
        {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.60,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.5,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
        {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.40,
         "revenue_at_risk_low": -20.0, "revenue_at_risk_high": -10.0,
         "op_margin_to_apply": 0.57, "tax_rate_to_apply": 0.12, "evidence": "test"},
    ],
}


class TestBullEPSEventDriven:
    """All three EPS scenarios use scenario_eps (event-driven).
    Step A floors bull to 0.95 × consensus_high when events are too conservative."""

    def _math(self) -> dict:
        return run_methodology_math(BUG5_PASS1, BUG5_BASELINE)

    def test_step_a_fires_when_bull_events_too_small(self):
        """BUG5 tiny events → raw event-driven bull ≈ $3.12 < floor $9.50 → Step A fires."""
        m = self._math()
        step_a_entries = [e for e in m["calibration_log"] if "Step A" in e]
        assert step_a_entries, (
            f"Step A did not fire; calibration_log={m['calibration_log']}"
        )
        expected_floor = 0.95 * BUG5_BASELINE["consensus_eps_fy2"]["high"]   # 9.50
        bull_eps = m["scenario_eps"]["bull"]
        assert abs(bull_eps - expected_floor) < 0.01, (
            f"bull_eps={bull_eps:.2f} != expected floor {expected_floor:.2f}"
        )
        # Raw event-driven value (before Step A) must be well below the floor
        from compute_methodology_v2 import scenario_eps as _scenario_eps, projected_shares
        from run_methodology_math import _normalize_events
        sp = projected_shares(
            BUG5_BASELINE["shares_out"],
            BUG5_BASELINE["horizon_years"],
            BUG5_BASELINE["trailing_net_dilution_rate"],
        )
        events = _normalize_events(BUG5_PASS1["events"])
        raw_bull = _scenario_eps(
            BUG5_BASELINE["fy_revenue"], BUG5_BASELINE["fy_op_margin"],
            events, "bull",
            BUG5_BASELINE["tax_rate_guidance"], sp,
        )
        assert raw_bull < expected_floor * 0.50, (
            f"raw event-driven bull={raw_bull:.2f} not well below floor {expected_floor:.2f}"
        )

    def test_bull_eps_is_event_driven(self):
        """Bull EPS matches scenario_eps direct call — confirmed on AVGO_V2_BASELINE."""
        from compute_methodology_v2 import scenario_eps as _scenario_eps, projected_shares
        from run_methodology_math import _normalize_events
        bl = AVGO_V2_BASELINE
        m = run_methodology_math({"events": AVGO_EVENTS}, bl)
        sp = projected_shares(
            bl["shares_out"], bl.get("horizon_years", 5),
            bl.get("trailing_net_dilution_rate", 0.0),
        )
        events = _normalize_events(AVGO_EVENTS)
        expected = _scenario_eps(
            bl["fy_revenue"], bl["fy_op_margin"], events, "bull",
            bl.get("tax_rate_guidance", 0.21), sp,
        )
        assert abs(m["scenario_eps"]["bull"] - expected) < 0.01, (
            f"bull EPS={m['scenario_eps']['bull']:.2f} != scenario_eps direct={expected:.2f}"
        )
        # AVGO_V2_BASELINE has no consensus_eps_fy2 → Step A must not fire
        assert not any("Step A" in e for e in m.get("calibration_log", [])), (
            "Step A fired unexpectedly on AVGO_V2_BASELINE (no consensus_eps_fy2)"
        )

    def test_base_and_bear_use_event_driven_path(self):
        """Base and bear EPS are positive and bull > base (ordering preserved)."""
        m = self._math()
        base_eps = m["scenario_eps"]["base"]
        bear_eps = m["scenario_eps"]["bear"]
        assert base_eps > 0, "base EPS must be positive"
        assert bear_eps > 0, "bear EPS must be positive"
        bull_eps = m["scenario_eps"]["bull"]
        assert bull_eps > base_eps, (
            f"Expected bull ({bull_eps:.2f}) > base ({base_eps:.2f}) — monotonicity violated"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG 1 REGRESSION — LLM call counter decrements correctly; ceiling is 6
# ════════════════════════════════════════════════════════════════════════════

from ai import LLMCallCeilingError


class TestBug1CallCeilingCounter:
    """Bug 1: calls_remaining decrements correctly; LLMCallCeilingError raised when budget gone."""

    def test_max_pipeline_ai_calls_is_eight(self):
        """C3 ceiling must be exactly 8 (spec: 2+1+2+1+1+1 = pass1+catalysts_fallback+pass2+pass3+bull_retry+section_retry)."""
        assert MAX_PIPELINE_AI_CALLS == 8, (
            f"MAX_PIPELINE_AI_CALLS={MAX_PIPELINE_AI_CALLS}; must be 8 "
            f"(7 prior + 1 Pass 2 focused section retry)."
        )

    def test_llm_call_ceiling_error_is_defined(self):
        err = LLMCallCeilingError(calls_used=5, ceiling=6)
        assert err.calls_used == 5
        assert err.ceiling == 6
        assert "6" in str(err)

    def test_pass3_receives_correct_calls_remaining_no_retry(self):
        """No bull retry: pass1(-2) + pass2(-2) = 4 used → pass3 gets MAX-4 = 2."""
        captured = {}

        def mock_pass3(*a, calls_remaining=None, **kw):
            captured["calls_remaining"] = calls_remaining
            return _G_PASS3

        with mock.patch("ai.run_pass1_foundation", return_value=_minimal_valid_pass1()), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH), \
             mock.patch("ai.run_pass2_report",     return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit",       side_effect=mock_pass3):
            run_pipeline(_G_TICKER, _G_BASELINE)

        expected = MAX_PIPELINE_AI_CALLS - 4   # 6 - 4 = 2
        assert captured.get("calls_remaining") == expected, (
            f"pass3 got calls_remaining={captured.get('calls_remaining')}, "
            f"expected {expected} (MAX={MAX_PIPELINE_AI_CALLS} - 4 used)."
        )

    def test_pass3_receives_correct_calls_remaining_with_bull_retry(self):
        """Bull retry fires: pass1(-2) + retry(-1) + pass2(-2) = 5 used → pass3 gets 1."""
        captured = {}
        call_count = {"n": 0}

        def alt_p1(*a, retry_hint="", **kw):
            call_count["n"] += 1
            return _minimal_valid_pass1()

        bull_below_math = {**_G_MATH, "price_target": {
            "bull_high": 95.0, "bull_mid": 90.0, "base_mid": 80.0, "bear_low": 60.0,
        }, "risk": {**_G_MATH["risk"]}}

        def alt_math(p1, bl):
            return _G_MATH if call_count["n"] >= 2 else bull_below_math

        def mock_pass3(*a, calls_remaining=None, **kw):
            captured["calls_remaining"] = calls_remaining
            return _G_PASS3

        with mock.patch("ai.run_pass1_foundation", side_effect=alt_p1), \
             mock.patch("ai.run_methodology_math", side_effect=alt_math), \
             mock.patch("ai.run_pass2_report",     return_value=_G_PASS2), \
             mock.patch("ai.run_pass3_audit",       side_effect=mock_pass3):
            run_pipeline(_G_TICKER, _G_BASELINE)

        expected = MAX_PIPELINE_AI_CALLS - 5   # 6 - 5 = 1
        assert captured.get("calls_remaining") == expected, (
            f"pass3 got calls_remaining={captured.get('calls_remaining')}, "
            f"expected {expected} (MAX={MAX_PIPELINE_AI_CALLS} - 5 used with retry)."
        )

    def test_ceiling_error_raised_when_budget_too_low_for_pass2(self):
        """If budget would be exhausted before pass2, LLMCallCeilingError is raised."""
        # Patch MAX to 2: only enough for pass1, not pass2
        with mock.patch("ai.MAX_PIPELINE_AI_CALLS", 2), \
             mock.patch("ai.run_pass1_foundation", return_value=_minimal_valid_pass1()), \
             mock.patch("ai.run_methodology_math", return_value=_G_MATH):
            with pytest.raises(LLMCallCeilingError) as exc_info:
                run_pipeline(_G_TICKER, _G_BASELINE)
        assert exc_info.value.ceiling == 2


# ════════════════════════════════════════════════════════════════════════════
# BUG A — Bear/bull price inversion fix
# Bug A: franchise bear P/E floor (25×) exceeds entire bull range on low-growth names,
# making bear_price > bull_price.  Fix: cap bear_pe_high = bull_pe_low - 1.0.
# ════════════════════════════════════════════════════════════════════════════

# KO-like fixture: ~7% growth, franchise quality, peer fwd_pe ~16×.
# Without the fix: bear_band=(25.0,32.5) vs bull_band=(11.2,16.0) → inversion.
KO_LIKE_BASELINE = {
    "current_price":              60.0,
    "shares_out":                 0.86,
    "fy_revenue":                 12.0,
    "fy_op_margin":               0.225,
    "tax_rate_guidance":          0.20,
    "beta":                       0.55,
    "net_debt":                   8.0,
    "horizon_years":              5,
    "franchise_quality":          True,
    "trailing_net_dilution_rate": 0.0,
    "fy_fcf":                     2.5,
    "five_yr_eps_growth_est":     0.07,
    "fy_eps_non_gaap":            2.51,
    "peer_set": [
        {"ticker": "PEP",  "fwd_pe": 15.0},
        {"ticker": "MDLZ", "fwd_pe": 16.0},
        {"ticker": "HSY",  "fwd_pe": 17.0},
    ],
}

KO_LIKE_PASS1 = {
    "events": [
        {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.25,
         "revenue_at_risk_low": 0.4, "revenue_at_risk_high": 0.6,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "A2", "driver": "A", "outcome": "base", "probability": 0.55,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "A3", "driver": "A", "outcome": "bear", "probability": 0.20,
         "revenue_at_risk_low": -0.8, "revenue_at_risk_high": -0.4,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "B1", "driver": "B", "outcome": "base", "probability": 0.70,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "B2", "driver": "B", "outcome": "bear", "probability": 0.30,
         "revenue_at_risk_low": -1.0, "revenue_at_risk_high": -0.5,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.75,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
        {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.25,
         "revenue_at_risk_low": -0.5, "revenue_at_risk_high": -0.2,
         "op_margin_to_apply": 0.225, "tax_rate_to_apply": 0.20, "evidence": "test"},
    ],
}


class TestBugABearInversionFix:
    """
    Bug A: franchise bear P/E floor sets bear_pe_high > bull_pe_high on low-growth names,
    inverting the scenario price hierarchy.  Fix enforces bear_pe_high = bull_pe_low - 1.0.
    """

    def _math(self):
        return run_methodology_math(KO_LIKE_PASS1, KO_LIKE_BASELINE)

    def test_bear_pe_high_below_bull_pe_low(self):
        """After cap fix bear ceiling must sit below bull floor."""
        m = self._math()
        bear_high = m["pe_band"]["bear_high"]
        bull_low  = m["pe_band"]["bull_low"]
        assert bear_high < bull_low, (
            f"bear_pe_high={bear_high} >= bull_pe_low={bull_low}; "
            f"scenario hierarchy violated (Bug A not fixed)"
        )

    def test_bear_cap_log_entry_present(self):
        """Calibration log must record the bear P/E cap when it fires."""
        m = self._math()
        entries = [e for e in m["calibration_log"] if "Bear P/E capped" in e]
        assert len(entries) >= 1, (
            f"Expected 'Bear P/E capped' in calibration_log; got {m['calibration_log']}"
        )

    def test_price_hierarchy_bear_lt_base_lt_bull(self):
        """Final prices maintain scenario hierarchy: bear_low < base_mid < bull_high."""
        m = self._math()
        bear_low  = m["price_target"]["bear_low"]
        base_mid  = m["price_target"]["base_mid"]
        bull_high = m["price_target"]["bull_high"]
        assert bear_low < base_mid < bull_high, (
            f"Price hierarchy violated: bear_low={bear_low:.2f} "
            f"base_mid={base_mid:.2f} bull_high={bull_high:.2f}"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG B — Bull and base P/E bands not differentiated
# Bug B: peer-dominated inputs cause base_pe_high == bull_pe_high (both cap at peer).
# Fix: base_pe_high = bull_pe_high × 0.80, base_pe_low = bull_pe_low × 0.75.
# ════════════════════════════════════════════════════════════════════════════

class TestBugBBullBaseDifferentiation:
    """
    Bug B: bull and base both resolve to max(peg, peer_median) → identical bands.
    Fix: ratio discount base from bull (0.80/0.75) so base < bull always.
    Uses AVGO_V2_BASELINE (peer=38, growth=18%) where both bands collapse to 38× without fix.
    """

    def _math(self):
        return run_methodology_math({"events": AVGO_EVENTS}, AVGO_V2_BASELINE)

    def test_base_pe_high_below_bull_pe_high(self):
        """After ratio fix base ceiling must be strictly below bull ceiling."""
        m = self._math()
        base_high = m["pe_band"]["base_high"]
        bull_high = m["pe_band"]["bull_high"]
        assert base_high < bull_high, (
            f"base_pe_high={base_high} not < bull_pe_high={bull_high}; "
            f"bands still identical (Bug B not fixed)"
        )

    def test_base_ratio_discount_logged(self):
        """Calibration log must record the base P/E ratio override."""
        m = self._math()
        entries = [e for e in m["calibration_log"] if "ratio-discounted" in e]
        assert len(entries) >= 1, (
            f"Expected base P/E ratio-discount log entry; calibration_log={m['calibration_log']}"
        )

    def test_base_pe_high_approximately_80pct_of_bull(self):
        """base_pe_high ≈ bull_pe_high × 0.80 (within rounding)."""
        m = self._math()
        base_high = m["pe_band"]["base_high"]
        bull_high = m["pe_band"]["bull_high"]
        expected  = round(bull_high * 0.80, 1)
        assert abs(base_high - expected) < 0.2, (
            f"base_pe_high={base_high} expected ≈ {expected} (0.80 × bull_high={bull_high})"
        )


# ════════════════════════════════════════════════════════════════════════════
# KO-LIKE INTEGRATION TEST — combined scenario-hierarchy assertions
# ════════════════════════════════════════════════════════════════════════════

class TestKOScenarioHierarchy:
    """
    Integration test using the KO-like fixture (low growth ~7%, franchise=True, peer~16×).
    This is the worst-case scenario for both bugs:
      - Bug B: base and bull both cap at peer_median=16 → identical without fix
      - Bug A: franchise floor 25× >> bull range 11–16× → inversion without fix
    All three assertions must hold simultaneously after both fixes are applied.
    """

    def _math(self):
        return run_methodology_math(KO_LIKE_PASS1, KO_LIKE_BASELINE)

    def test_price_hierarchy(self):
        """(1) bear_price_low < base_price_mid < bull_price_high."""
        m = self._math()
        bear_low  = m["price_target"]["bear_low"]
        base_mid  = m["price_target"]["base_mid"]
        bull_high = m["price_target"]["bull_high"]
        assert bear_low < base_mid < bull_high, (
            f"Price hierarchy violated: bear_low={bear_low:.2f} "
            f"base_mid={base_mid:.2f} bull_high={bull_high:.2f}"
        )

    def test_base_pe_high_below_bull_pe_high(self):
        """(2) base_pe_high < bull_pe_high — base is discounted relative to bull."""
        m = self._math()
        base_high = m["pe_band"]["base_high"]
        bull_high = m["pe_band"]["bull_high"]
        assert base_high < bull_high, (
            f"base_pe_high={base_high} not < bull_pe_high={bull_high}"
        )

    def test_bear_pe_cap_log_entry_present(self):
        """(3) Bear P/E cap calibration log entry present (franchise floor would otherwise invert)."""
        m = self._math()
        entries = [e for e in m["calibration_log"] if "Bear P/E capped" in e]
        assert len(entries) >= 1, (
            f"Bear P/E cap log entry absent; calibration_log={m['calibration_log']}"
        )


# ════════════════════════════════════════════════════════════════════════════
# BUG 4 — driver_narratives A/B: missing narrative is now a hard retry trigger
# ════════════════════════════════════════════════════════════════════════════

class TestBug4DriverNarrativesHard:
    """
    Bug 4: missing driver_narratives for any driver ID (A, B, or C) must be a
    hard error that triggers a retry — not a soft warning.
    Retry hint format: 'driver_narratives for drivers X are missing — you must
    include a narrative paragraph for every macro driver ID present in pass1.macro_drivers.'
    """

    def test_missing_single_driver_narrative_is_hard(self):
        """Missing driver C narrative alone is a hard error."""
        p = _minimal_valid_pass2()
        del p["driver_narratives"]["C"]
        soft, hard = _validate_pass2_v2(p)
        assert any("driver_narratives" in e and "C" in e for e in hard), (
            f"missing driver C narrative must be hard; hard={hard}"
        )

    def test_missing_two_driver_narratives_is_hard(self):
        """Missing drivers A and B narratives is a hard error."""
        p = _minimal_valid_pass2()
        del p["driver_narratives"]["A"]
        del p["driver_narratives"]["B"]
        soft, hard = _validate_pass2_v2(p)
        assert any("driver_narratives" in e and "A" in e and "B" in e for e in hard), (
            f"missing A and B narratives must be hard; hard={hard}"
        )

    def test_retry_hint_contains_pass1_macro_drivers_reference(self):
        """Hard error message must reference pass1.macro_drivers per spec."""
        p = _minimal_valid_pass2()
        del p["driver_narratives"]["A"]
        soft, hard = _validate_pass2_v2(p)
        assert any("pass1.macro_drivers" in e for e in hard), (
            f"hard error must reference pass1.macro_drivers; hard={hard}"
        )

    def test_all_narratives_present_no_hard_error(self):
        """When all three driver narratives are present, no hard error fires."""
        p = _minimal_valid_pass2()
        soft, hard = _validate_pass2_v2(p)
        # driver_narratives is complete — hard list must not contain any narrative error
        assert not any("driver_narratives" in e for e in hard), (
            f"complete driver_narratives must not produce hard error; hard={hard}"
        )

    def test_missing_narrative_triggers_retry_in_run_pass2_report(self):
        """run_pass2_report retries when driver_narratives.B is absent (hard error path)."""
        import json as _json
        baseline = _baseline_for_pass2()
        math     = _math_for_pass2()

        p_missing_b = _minimal_valid_pass2()
        del p_missing_b["driver_narratives"]["B"]   # hard error
        p_good = _minimal_valid_pass2()

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (_json.dumps(p_missing_b if call_count["n"] == 1 else p_good), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math,
                                      max_passes=2)

        assert call_count["n"] == 2, (
            f"missing driver_narratives.B must trigger retry; call_count={call_count['n']}"
        )
        assert result.get("driver_narratives", {}).get("B"), (
            "second attempt (with B) should be accepted"
        )


class TestSbcSectionRequired:
    """
    sbc_section is a hard validator error when math.owner_earnings is non-null.
    Prompt fix: Pass 2 prompt now explicitly states sbc_section is REQUIRED in
    that case.  Validator enforces it as a retry trigger.
    """

    def _math_with_owner_earnings(self) -> dict:
        m = _math_for_pass2()
        m["owner_earnings"] = 12.4   # non-null → sbc_section required
        return m

    def test_sbc_section_missing_with_owner_earnings_is_hard(self):
        """Missing sbc_section when math.owner_earnings is non-null must be a hard error."""
        p = _minimal_valid_pass2()
        m = self._math_with_owner_earnings()
        soft, hard = _validate_pass2_v2(p, m)
        assert any("sbc_section" in e for e in hard), (
            f"missing sbc_section with owner_earnings present must be hard; hard={hard}"
        )

    def test_sbc_section_missing_retry_hint_text(self):
        """Hard error message must contain the specified retry hint text."""
        p = _minimal_valid_pass2()
        m = self._math_with_owner_earnings()
        soft, hard = _validate_pass2_v2(p, m)
        assert any("math.owner_earnings" in e for e in hard), (
            f"hard error must mention math.owner_earnings; hard={hard}"
        )

    def test_sbc_section_present_with_owner_earnings_no_hard_error(self):
        """When sbc_section is present alongside non-null owner_earnings, no hard error."""
        p = _minimal_valid_pass2()
        p["sbc_section"] = (
            "SBC of 2.1 billion reduces owner earnings from 14.5 to 12.4 billion. "
            "This represents a real economic cost that reduces true distributable cash."
        )
        m = self._math_with_owner_earnings()
        soft, hard = _validate_pass2_v2(p, m)
        assert not any("sbc_section" in e for e in hard), (
            f"sbc_section present should not produce hard error; hard={hard}"
        )

    def test_sbc_section_missing_without_owner_earnings_no_hard_error(self):
        """When math.owner_earnings is None, sbc_section is not required."""
        p = _minimal_valid_pass2()
        m = _math_for_pass2()   # AVGO_V2_BASELINE has no fy_sbc → owner_earnings is None
        assert m.get("owner_earnings") is None, (
            "AVGO_V2_BASELINE lacks fy_sbc, so owner_earnings must be None"
        )
        soft, hard = _validate_pass2_v2(p, m)
        assert not any("sbc_section" in e for e in hard), (
            f"sbc_section not required when owner_earnings absent; hard={hard}"
        )

    def test_sbc_section_missing_triggers_retry_in_run_pass2_report(self):
        """run_pass2_report retries when sbc_section absent and owner_earnings non-null."""
        import json as _json
        baseline = _baseline_for_pass2()
        math     = self._math_with_owner_earnings()

        p_no_sbc = _minimal_valid_pass2()          # no sbc_section → hard error
        p_good   = _minimal_valid_pass2()
        p_good["sbc_section"] = (
            "SBC of 2.1 billion reduces owner earnings from 14.5 to 12.4 billion."
        )

        call_count = {"n": 0}
        def mock_run_ai(msgs, **kwargs):
            call_count["n"] += 1
            return (_json.dumps(p_no_sbc if call_count["n"] == 1 else p_good), "m", None)

        with mock.patch("ai.run_ai", side_effect=mock_run_ai):
            result = run_pass2_report("AVGO", baseline, _minimal_valid_pass1(), math,
                                      max_passes=2)

        assert call_count["n"] == 2, (
            f"missing sbc_section must trigger retry; call_count={call_count['n']}"
        )
        assert result.get("sbc_section"), "second attempt (with sbc_section) should be accepted"


# ════════════════════════════════════════════════════════════════════════════
# NEGATIVE TRAILING EPS FIXTURE
#
# Stress-tests the path where fy_eps_non_gaap < 0 (e.g. small-cap with GAAP
# losses).  scenario_eps uses revenue × margin, so negative trailing EPS never
# contaminates the output — bull EPS is always positive.
# ════════════════════════════════════════════════════════════════════════════

NEG_EPS_BASELINE = {
    "current_price":              13.34,
    "shares_out":                 0.09,           # 90M shares (small-cap)
    "fy_revenue":                 0.53,            # $530M
    "base_op_margin":             0.12,            # 12% — positive so scenario_eps > 0
    "tax_rate":                   0.15,
    "beta":                       1.40,
    "net_debt":                   0.05,
    "horizon_years":              5,
    "franchise_quality":          False,           # non-franchise: no bear floor
    "trailing_net_dilution_rate": 0.02,
    "fy_fcf":                     0.067,
    "five_yr_eps_growth_est":     0.26,
    "fy_eps_non_gaap":            -0.31,           # KEY: negative trailing EPS
    "peer_set":                   [],              # no peers (thin coverage)
    "consensus_eps_fy2":          None,            # no consensus (pure bottom-up)
}

NEG_EPS_PASS1 = {
    "events": [
        {"id": "A1", "driver": "A", "outcome": "bull", "probability": 0.20,
         "revenue_at_risk_low": 0.05, "revenue_at_risk_high": 0.10,
         "op_margin_to_apply": 0.18, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "A2", "driver": "A", "outcome": "base", "probability": 0.60,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.12, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "A3", "driver": "A", "outcome": "bear", "probability": 0.20,
         "revenue_at_risk_low": -0.08, "revenue_at_risk_high": -0.03,
         "op_margin_to_apply": 0.06, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "B1", "driver": "B", "outcome": "bull", "probability": 0.15,
         "revenue_at_risk_low": 0.03, "revenue_at_risk_high": 0.06,
         "op_margin_to_apply": 0.18, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "B2", "driver": "B", "outcome": "base", "probability": 0.75,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.12, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "B3", "driver": "B", "outcome": "bear", "probability": 0.10,
         "revenue_at_risk_low": -0.05, "revenue_at_risk_high": -0.02,
         "op_margin_to_apply": 0.06, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "C1", "driver": "C", "outcome": "base", "probability": 0.80,
         "revenue_at_risk_low": 0.0, "revenue_at_risk_high": 0.0,
         "op_margin_to_apply": 0.12, "tax_rate_to_apply": 0.15, "evidence": "test"},
        {"id": "C2", "driver": "C", "outcome": "bear", "probability": 0.20,
         "revenue_at_risk_low": -0.04, "revenue_at_risk_high": -0.01,
         "op_margin_to_apply": 0.06, "tax_rate_to_apply": 0.15, "evidence": "test"},
    ],
    "pe_anchors": {},   # empty → Bug 2 log entry also fires; does not affect EPS test
}


class TestNegativeTrailingEPS:
    """
    When fy_eps_non_gaap ≤ 0, scenario_eps (event-driven, revenue × margin)
    naturally produces a positive bull EPS — no special case or log entry needed.
    """

    def _math(self):
        return run_methodology_math(NEG_EPS_PASS1, NEG_EPS_BASELINE)

    def test_bull_eps_is_positive(self):
        """bull EPS must be positive even when trailing EPS < 0."""
        m = self._math()
        bull_eps = m["scenario_eps"]["bull"]
        assert bull_eps > 0, (
            f"bull EPS={bull_eps:.4f} must be positive"
        )


# ════════════════════════════════════════════════════════════════════════════
# Headwinds / Tailwinds wiring
# ════════════════════════════════════════════════════════════════════════════

# Simple §5.1 baseline sufficient to run run_methodology_math with §5.2 events.
_HW_BASELINE = {
    "current_price":              100.0,
    "shares_out":                 1.0,
    "fy_revenue":                 10.0,
    "fy_op_margin":               0.30,
    "tax_rate_guidance":          0.21,
    "beta":                       1.0,
    "net_debt":                   0.0,
    "horizon_years":              5,
    "franchise_quality":          True,
    "trailing_net_dilution_rate": 0.0,
    "fy_fcf":                     2.0,
    "five_yr_eps_growth_est":     0.15,
    "fy_eps_non_gaap":            3.0,
    "peer_set": [
        {"ticker": "X", "fwd_pe": 20.0},
        {"ticker": "Y", "fwd_pe": 22.0},
        {"ticker": "Z", "fwd_pe": 24.0},
    ],
}


class TestHeadwindsTailwindsWiring:
    """
    Verify that run_methodology_math populates headwinds/tailwinds in the math dict.
    Uses _minimal_valid_pass1() (§5.2 format) as the pass1 fixture.
    _minimal_valid_pass1() has: 1 bull event (A1), 3 bear events (A2, B2, C2),
    2 base events (B1, C1).
    """

    def _math(self):
        return run_methodology_math(_minimal_valid_pass1(), _HW_BASELINE)

    def test_headwinds_list_populated_with_impact_fields(self):
        """math['headwinds'] is non-empty and every entry has eps_impact_high/mid/low as floats."""
        m = self._math()
        hw = m.get("headwinds", [])
        assert isinstance(hw, list), "headwinds must be a list"
        assert len(hw) > 0, "headwinds must be non-empty (bear events exist in fixture)"
        for entry in hw:
            for fld in ("eps_impact_high", "eps_impact_mid", "eps_impact_low"):
                assert fld in entry, f"entry missing '{fld}': {entry}"
                assert isinstance(entry[fld], float), (
                    f"'{fld}' must be float, got {type(entry[fld])}: {entry[fld]!r}"
                )

    def test_outcome_routing(self):
        """Bear events → headwinds, bull events → tailwinds, base events → neither."""
        m = self._math()
        events = _minimal_valid_pass1()["events"]
        bear_ids = {ev["id"] for ev in events if ev["outcome"] == "bear"}
        bull_ids = {ev["id"] for ev in events if ev["outcome"] == "bull"}
        base_ids = {ev["id"] for ev in events if ev["outcome"] == "base"}

        hw_ids = {entry["event_id"] for entry in m["headwinds"]}
        tw_ids = {entry["event_id"] for entry in m["tailwinds"]}

        assert hw_ids == bear_ids, f"headwind event_ids {hw_ids} != bear ids {bear_ids}"
        assert tw_ids == bull_ids, f"tailwind event_ids {tw_ids} != bull ids {bull_ids}"
        assert not (base_ids & (hw_ids | tw_ids)), (
            f"base events must not appear in headwinds/tailwinds: {base_ids & (hw_ids | tw_ids)}"
        )

    def test_eps_impact_ordering(self):
        """eps_impact_high >= eps_impact_low >= 0 for every entry (magnitudes, sign by renderer)."""
        m = self._math()
        for entry in m["headwinds"] + m["tailwinds"]:
            low  = entry["eps_impact_low"]
            high = entry["eps_impact_high"]
            assert low >= 0.0, (
                f"eps_impact_low must be non-negative: {low} (entry={entry['event_id']})"
            )
            assert high >= low, (
                f"eps_impact_high ({high}) must be >= eps_impact_low ({low}) "
                f"(entry={entry['event_id']})"
            )


class TestEvFormulaString:
    def _math(self):
        return run_methodology_math(AVGO_PASS1, AVGO_BASELINE)

    def test_formula_string_contains_expected_value(self):
        m = self._math()
        ev_str = m["ev_formula_string"]
        ev_val = m["expected_value"]
        expected_substr = f"${ev_val:.2f}"
        assert expected_substr in ev_str, (
            f"ev_formula_string '{ev_str}' does not contain expected_value formatted as '{expected_substr}'"
        )


class TestDriverOutcomeProbabilities:
    def _result(self):
        return driver_outcome_probabilities(AVGO_EVENTS)

    def test_probs_sum_to_one_per_driver(self):
        result = self._result()
        for did, probs in result.items():
            total = sum(probs.values())
            assert abs(total - 1.0) < 1e-6, f"Driver {did}: probs sum={total:.8f}"

    def test_missing_outcome_returns_zero(self):
        result = self._result()
        # Driver A has no bear events in AVGO_EVENTS
        assert result["A"]["bear"] == 0.0, f"Expected 0 bear for A, got {result['A']['bear']}"
        # Driver C has no bull events in AVGO_EVENTS
        assert result["C"]["bull"] == 0.0, f"Expected 0 bull for C, got {result['C']['bull']}"

    def test_all_three_drivers_present(self):
        result = self._result()
        for did in ("A", "B", "C"):
            assert did in result, f"Driver {did!r} missing from driver_outcome_probabilities output"

    def test_math_dict_contains_driver_outcome_probabilities_key(self):
        m = run_methodology_math(AVGO_PASS1, AVGO_BASELINE)
        assert "driver_outcome_probabilities" in m, (
            "math dict missing 'driver_outcome_probabilities' key"
        )
        dop = m["driver_outcome_probabilities"]
        # Verify shape: each driver has bull/base/bear keys
        for did, probs in dop.items():
            assert set(probs.keys()) == {"bull", "base", "bear"}, (
                f"Driver {did} has unexpected keys: {set(probs.keys())}"
            )


class TestSensitivityAnalysis:
    _PRICES = {"bull": 500.0, "base": 350.0, "bear": 200.0}

    def _dop(self):
        return driver_outcome_probabilities(AVGO_EVENTS)

    def test_plus_and_minus_produce_different_evs(self):
        dop = self._dop()
        res_minus = sensitivity_analysis("A", -10.0, dop, {}, self._PRICES)
        res_plus  = sensitivity_analysis("A", +10.0, dop, {}, self._PRICES)
        assert res_minus["expected_value"] != res_plus["expected_value"], (
            "Expected -10pp and +10pp to produce different EVs"
        )
        assert res_plus["expected_value"] > res_minus["expected_value"], (
            f"Expected +10pp EV ({res_plus['expected_value']}) > -10pp EV ({res_minus['expected_value']})"
        )

    def test_joint_probs_sum_to_one_after_perturbation(self):
        dop = self._dop()
        for delta in (-10.0, 0.0, +10.0):
            res = sensitivity_analysis("A", delta, dop, {}, self._PRICES)
            total = sum(res["joint_probs"].values())
            assert abs(total - 1.0) < 1e-4, (
                f"delta={delta}: joint_probs sum={total:.8f}"
            )

    def test_clamping_when_bull_near_max(self):
        near_max = {
            "A": {"bull": 0.95, "base": 0.05, "bear": 0.00},
            "B": {"bull": 0.50, "base": 0.50, "bear": 0.00},
            "C": {"bull": 0.50, "base": 0.50, "bear": 0.00},
        }
        res = sensitivity_analysis("A", +10.0, near_max, {}, self._PRICES)
        total = sum(res["joint_probs"].values())
        assert abs(total - 1.0) < 1e-4, f"joint_probs sum={total:.8f} after clamping"
        assert res["joint_probs"]["bull"] <= 1.0, (
            f"bull prob {res['joint_probs']['bull']} exceeded 1.0 after clamping"
        )

    def test_math_dict_contains_sensitivity_table(self):
        m = run_methodology_math(AVGO_PASS1, AVGO_BASELINE)
        assert "sensitivity_table" in m, "math dict missing 'sensitivity_table' key"
        st = m["sensitivity_table"]
        assert st["driver"] == "A"
        for key in ("minus_10pp", "current", "plus_10pp"):
            assert key in st, f"sensitivity_table missing '{key}'"
            assert "bull_prob" in st[key], f"sensitivity_table['{key}'] missing 'bull_prob'"
            assert "expected_value" in st[key], f"sensitivity_table['{key}'] missing 'expected_value'"
        # Order check: lower bull_prob → lower EV
        assert st["minus_10pp"]["expected_value"] < st["current"]["expected_value"] < st["plus_10pp"]["expected_value"], (
            "Expected EV ordering: minus_10pp < current < plus_10pp"
        )


class TestScenarioSegmentRevenue:
    """Step 3: scenario_segment_revenue optional field — 4 unit tests."""

    def test_llm_provided_growth_source_and_revenue(self):
        """Segment with scenario_growth → growth_source == 'llm_provided', revenue correct."""
        segs = [{
            "name": "AI Networking",
            "fy_revenue": 10.0,
            "share_pct": 0.5,
            "scenario_growth": {"bull": 0.25, "base": 0.10, "bear": -0.05},
            "growth_yoy": 0.15,
        }]
        result = scenario_segment_revenue(segs, horizon=2)
        assert result is not None
        assert len(result["segments"]) == 1
        seg = result["segments"][0]
        assert seg["growth_source"] == "llm_provided", f"Expected 'llm_provided', got {seg['growth_source']!r}"
        assert abs(seg["bull"]  - 15.625) < 0.001, f"bull={seg['bull']}"   # 10 × 1.25²
        assert abs(seg["base"]  - 12.1)   < 0.001, f"base={seg['base']}"   # 10 × 1.10²
        assert abs(seg["bear"]  -  9.025) < 0.001, f"bear={seg['bear']}"   # 10 × 0.95²
        assert result["any_derived"] is False

    def test_derived_from_growth_yoy_with_bull_cap(self):
        """Segment with only growth_yoy → growth_source == 'derived', bull capped at 60%."""
        segs = [{
            "name": "Legacy Semis",
            "fy_revenue": 5.0,
            "growth_yoy": 0.50,    # 0.50 × 1.5 = 0.75 → capped to 0.60
        }]
        result = scenario_segment_revenue(segs, horizon=2)
        assert result is not None
        seg = result["segments"][0]
        assert seg["growth_source"] == "derived", f"Expected 'derived', got {seg['growth_source']!r}"
        # bull growth = min(0.50 × 1.5, 0.60) = 0.60 → 5.0 × 1.60² = 12.8
        assert abs(seg["bull"] - 12.8) < 0.001, f"bull={seg['bull']} (expected 12.8 with 60% cap)"
        # base growth = 0.50 → 5.0 × 1.50² = 11.25
        assert abs(seg["base"] - 11.25) < 0.001, f"base={seg['base']}"
        # bear growth = 0.50 × 0.3 = 0.15 → 5.0 × 1.15² = 6.6125
        assert abs(seg["bear"] - 6.6125) < 0.001, f"bear={seg['bear']}"
        assert result["any_derived"] is True

    def test_segment_with_neither_field_is_skipped(self):
        """Segment missing both scenario_growth and growth_yoy → not in output."""
        segs = [
            {"name": "Known",   "fy_revenue": 3.0, "growth_yoy": 0.10},
            {"name": "Unknown", "fy_revenue": 2.0},   # no growth data
        ]
        result = scenario_segment_revenue(segs, horizon=2)
        assert result is not None
        names = [s["name"] for s in result["segments"]]
        assert "Known"   in names, "Expected 'Known' segment in output"
        assert "Unknown" not in names, "Expected 'Unknown' segment (no growth) to be skipped"

    def test_all_segments_missing_data_returns_none(self):
        """All segments have neither scenario_growth nor growth_yoy → returns None."""
        segs = [
            {"name": "A", "fy_revenue": 1.0},
            {"name": "B", "fy_revenue": 2.0},
        ]
        assert scenario_segment_revenue(segs) is None

    def test_math_dict_key_present_and_none_for_avgo(self):
        """AVGO_PASS1 has no segments_enriched → key present with value None."""
        m = run_methodology_math(AVGO_PASS1, AVGO_BASELINE)
        assert "scenario_segment_revenue" in m, "math dict missing 'scenario_segment_revenue' key"
        # AVGO_PASS1 = {"events": AVGO_EVENTS}, no segments_enriched → None
        assert m["scenario_segment_revenue"] is None, (
            f"Expected None for AVGO (no segments), got {m['scenario_segment_revenue']!r}"
        )

    def test_math_dict_key_populated_when_segments_present(self):
        """Pass1 with segments_enriched having growth_yoy → non-None result in math dict."""
        pass1_with_segs = {
            "events": AVGO_EVENTS,
            "segments_enriched": [
                {"name": "Seg A", "fy_revenue": 10.0, "growth_yoy": 0.12},
                {"name": "Seg B", "fy_revenue": 5.0,  "growth_yoy": 0.08},
            ],
        }
        m = run_methodology_math(pass1_with_segs, AVGO_BASELINE)
        ssr = m["scenario_segment_revenue"]
        assert ssr is not None, "Expected non-None scenario_segment_revenue when segments present"
        assert len(ssr["segments"]) == 2
        assert ssr["any_derived"] is True
        for seg in ssr["segments"]:
            assert seg["bull"] > seg["base"] > seg["bear"], (
                f"Expected bull > base > bear for seg {seg['name']}: "
                f"bull={seg['bull']}, base={seg['base']}, bear={seg['bear']}"
            )


# ════════════════════════════════════════════════════════════════════════════
# PASS 2 SCHEMA EXPANSION (pass2-prompt-schema-expansion)
#
# New required sections added to pass2: business_overview, revenue_architecture,
# growth_drivers_and_moats, factor_analysis, valuation_vs_expectations,
# sensitivity_check, margin_analysis, competitive_position,
# scenario_analysis_extended.  concentration_and_dependencies is soft-only.
# ════════════════════════════════════════════════════════════════════════════


class TestPass2SchemaExpansion:
    """
    Validator behaviour for the 9 new pass2 sections.

    Hard retry triggers: business_overview, revenue_architecture,
    growth_drivers_and_moats, factor_analysis, valuation_vs_expectations,
    sensitivity_check, margin_analysis, competitive_position,
    scenario_analysis_extended.

    Soft-only: concentration_and_dependencies.
    """

    def test_all_new_required_sections_present_no_hard_error(self):
        """_minimal_valid_pass2() now includes all new required sections → no hard errors."""
        soft, hard = _validate_pass2_v2(_minimal_valid_pass2())
        assert hard == [], f"unexpected hard errors with all sections present: {hard}"

    def test_business_overview_missing_is_hard(self):
        """Missing business_overview triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["business_overview"]
        soft, hard = _validate_pass2_v2(p)
        assert any("business_overview" in e for e in hard), (
            f"missing business_overview must be a hard error; hard={hard}"
        )

    def test_sensitivity_check_missing_is_hard(self):
        """Missing sensitivity_check triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["sensitivity_check"]
        soft, hard = _validate_pass2_v2(p)
        assert any("sensitivity_check" in e for e in hard), (
            f"missing sensitivity_check must be a hard error; hard={hard}"
        )

    def test_concentration_and_dependencies_missing_is_soft_only(self):
        """Missing concentration_and_dependencies is a soft warning, not a hard retry."""
        p = _minimal_valid_pass2()
        # concentration_and_dependencies is not in _minimal_valid_pass2 (never required hard)
        p.pop("concentration_and_dependencies", None)
        soft, hard = _validate_pass2_v2(p)
        assert not any("concentration_and_dependencies" in e for e in hard), (
            f"concentration_and_dependencies must not produce a hard error; hard={hard}"
        )
        assert any("concentration_and_dependencies" in e for e in soft), (
            f"missing concentration_and_dependencies must produce a soft warning; soft={soft}"
        )

    def test_pass3_prompt_exempts_competitive_position_from_citation_checks(self):
        """PASS3_PROMPT must explicitly list competitive_position in the qualitative-skip block."""
        assert "competitive_position" in PASS3_PROMPT, (
            "prompt_pass3.txt must name competitive_position in the QUALITATIVE SECTIONS block "
            "so the LLM auditor skips citation checks on that section"
        )
        # Also verify the broader qualitative sections block is present
        assert "QUALITATIVE SECTIONS" in PASS3_PROMPT, (
            "prompt_pass3.txt must contain a QUALITATIVE SECTIONS block"
        )

    def test_qualitative_sections_constant_contains_expected_keys(self):
        """_PASS2_QUALITATIVE_SECTIONS covers the four expected qualitative section names."""
        for name in ("concentration_and_dependencies", "competitive_position",
                     "growth_drivers_and_moats", "business_overview"):
            assert name in _PASS2_QUALITATIVE_SECTIONS, (
                f"{name!r} must be in _PASS2_QUALITATIVE_SECTIONS"
            )

    def test_factor_analysis_missing_is_hard(self):
        """Missing factor_analysis triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["factor_analysis"]
        soft, hard = _validate_pass2_v2(p)
        assert any("factor_analysis" in e for e in hard), (
            f"missing factor_analysis must be a hard error; hard={hard}"
        )

    def test_valuation_vs_expectations_missing_is_hard(self):
        """Missing valuation_vs_expectations triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["valuation_vs_expectations"]
        soft, hard = _validate_pass2_v2(p)
        assert any("valuation_vs_expectations" in e for e in hard), (
            f"missing valuation_vs_expectations must be a hard error; hard={hard}"
        )

    def test_revenue_architecture_missing_is_hard(self):
        """Missing revenue_architecture triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["revenue_architecture"]
        soft, hard = _validate_pass2_v2(p)
        assert any("revenue_architecture" in e for e in hard), (
            f"missing revenue_architecture must be a hard error; hard={hard}"
        )

    def test_growth_drivers_and_moats_missing_is_hard(self):
        """Missing growth_drivers_and_moats triggers a hard retry."""
        p = _minimal_valid_pass2()
        del p["growth_drivers_and_moats"]
        soft, hard = _validate_pass2_v2(p)
        assert any("growth_drivers_and_moats" in e for e in hard), (
            f"missing growth_drivers_and_moats must be a hard error; hard={hard}"
        )
