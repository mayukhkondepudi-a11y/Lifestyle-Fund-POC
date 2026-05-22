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
#   EV         ~$348   ± $5
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
        assert abs(ev - 348.0) <= 10.0, f"EV={ev:.1f}, target=348 ±10"

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
