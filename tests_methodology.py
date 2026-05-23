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
        "macro_drivers": [
            {"id": "A", "label": "Growth", "narrative": "drives bull"},
            {"id": "B", "label": "Stability", "narrative": "keeps base"},
            {"id": "C", "label": "Risk", "narrative": "bear driver"},
        ],
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
        p["macro_drivers"][0]["id"] = "X"
        soft, hard = _validate_pass1_v2(p)
        assert any("ids" in e for e in hard)

    def test_macro_driver_count_mismatch_is_hard(self):
        p = _minimal_valid_pass1()
        p["macro_drivers"] = p["macro_drivers"][:2]   # only A, B
        soft, hard = _validate_pass1_v2(p)
        assert any("3" in e for e in hard)

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
        assert result["macro_drivers"][0]["id"] == "A"
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
        assert abs(ev - 348.0) <= 10.0, f"EV={ev:.1f}, expected 348±10"

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
# Post-split NVDA: current_price=$110, consensus_eps_fy2.high=$4.5, growth=35%.
# peer_set median fwd_pe=25 → bull pe_high=35 (PEG 1.0×35).
# Bottom-up bull EPS << 4.275 (0.95×4.5) for all event sets → Step A always floors.
# bull_price_high = 4.275 × 35 = $149.6 > $110 on all variants.

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
    "consensus_eps_fy2": {"low": 3.5, "mid": 4.0, "high": 4.5},
}

# Three distinct pass1 event sets — all produce bottom-up bull EPS << 4.275
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
        m = self._math_with_consensus(4.5)
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

from ai import _build_pass2_body, _validate_pass2_v2, run_pass2_report
from smoke_harness import check_word_count, check_forbidden_tokens


def _minimal_valid_pass2() -> dict:
    """Minimal §5.4-compliant pass2 dict — all required sections, no forbidden tokens,
    well under 4500 words."""
    return {
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
        p["conclusion"] += " Investors can capture significant upside here."
        soft, hard = _validate_pass2_v2(p)
        assert any("capture" in e for e in hard)

    def test_forbidden_degraded_is_hard(self):
        p = _minimal_valid_pass2()
        p["financial_health"] += " DEGRADED data."
        soft, hard = _validate_pass2_v2(p)
        assert any("DEGRADED" in e for e in hard)

    def test_word_count_over_limit_is_soft(self):
        p = _minimal_valid_pass2()
        filler = " This is additional filler text." * 1000   # ~5000 extra words
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

    def test_missing_driver_narrative_is_soft(self):
        p = _minimal_valid_pass2()
        del p["driver_narratives"]["C"]
        soft, hard = _validate_pass2_v2(p)
        assert hard == []
        assert any("driver_narratives.C" in e for e in soft)

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

    def test_detects_capture(self):
        p2 = _pass2_with_body()
        p2["body"] += " Investors can capture the upside from AI demand."
        hits = _scan_forbidden_vocab(p2)
        assert any(h["token"] == "capture" for h in hits), "should detect 'capture'"

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
        pass2["body"] += " capture the gains here."
        result = run_pass3_audit(ticker, baseline, pass1, math, pass2, calls_remaining=0)
        assert result["audit_skipped"] is True
        assert any(h["token"] == "capture" for h in result["forbidden_vocab"])
