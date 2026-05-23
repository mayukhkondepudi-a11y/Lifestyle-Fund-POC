"""
Phase A orchestrator: run_methodology_math(pass1, baseline) → math dict (§5.3).

Takes the frozen pass1 and baseline dicts, calls all pure functions in order,
and returns the complete math contract dict. No LLM calls, no I/O.
"""
from __future__ import annotations

import statistics
from typing import Any

from compute import HEADLINE_METRIC, ANALYST_CONSENSUS_BULL_FLOOR_FRAC
from compute_methodology_v2 import (
    scenario_revenue,
    scenario_eps,
    pe_band,
    breakeven_pe,
    driver_probabilities,
    joint_probabilities,
    expected_value,
    risk_metrics,
    implied_fcf_cagr,
    projected_shares,
    dcf_intrinsic_value,
    project_fcf,
    wacc as compute_wacc,
    recommendation,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_EQUITY_RISK_PREMIUM,
)


def _normalize_events(events: list[dict]) -> list[dict]:
    """
    Bridge §5.2 event format (from pass1 v2) to internal math format.

    §5.2 uses: driver, outcome, revenue_at_risk_low/high, op_margin_to_apply, tax_rate_to_apply
    Internal uses: driver_id, scenario, rev_change_mid, op_margin

    Both formats are accepted; §5.2 fields are mapped to their internal equivalents.
    """
    out = []
    for ev in events:
        n = dict(ev)
        if "driver" in ev and "driver_id" not in ev:
            n["driver_id"] = ev["driver"]
        if "outcome" in ev and "scenario" not in ev:
            n["scenario"] = ev["outcome"]
        if "rev_change_mid" not in ev:
            low  = float(ev.get("revenue_at_risk_low",  0.0))
            high = float(ev.get("revenue_at_risk_high", 0.0))
            n["rev_change_mid"] = (low + high) / 2.0
        if "op_margin" not in ev and "op_margin_to_apply" in ev:
            n["op_margin"] = float(ev["op_margin_to_apply"])
        out.append(n)
    return out


def run_methodology_math(pass1: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """
    Orchestrate all math-layer computations and return the §5.3 math dict.

    Inputs:
      pass1    — §5.2 contract: events, drivers, revenue/margin/growth estimates
      baseline — §5.1 contract: current_price, shares_out, trailing metrics

    Output: §5.3 math contract dict.
    """
    # ── Pull required baseline fields ───────────────────────────────────────
    current_price  = float(baseline["current_price"])
    shares_out     = float(baseline["shares_out"])           # billions
    fy_revenue     = float(baseline["fy_revenue"])           # trailing/forward base

    # §5.1 canonical field names; fall back to Phase A synthetic names for legacy fixtures
    base_op_margin = float(baseline.get("fy_op_margin") or baseline.get("base_op_margin", 0.30))
    tax_rate       = float(baseline.get("tax_rate_guidance") or baseline.get("tax_rate", DEFAULT_TAX_RATE))
    growth_rate    = float(baseline.get("five_yr_eps_growth_est") or baseline.get("earnings_cagr", 0.15))

    beta           = float(baseline.get("beta", 1.0))
    net_debt       = float(baseline.get("net_debt", 0.0))
    horizon_years  = int(baseline.get("horizon_years", 5))
    franchise_q    = bool(baseline.get("franchise_quality", True))
    trailing_dilution = float(baseline.get("trailing_net_dilution_rate", 0.0))

    _raw_fcf  = baseline.get("fy_fcf") or baseline.get("base_fcf")
    base_fcf  = float(_raw_fcf) if _raw_fcf is not None else fy_revenue * base_op_margin * 0.9

    # peer_pes: §5.1 peer_set[].fwd_pe preferred; fallback to flat peer_pes list
    _peer_set = baseline.get("peer_set", [])
    _from_set = [float(p["fwd_pe"]) for p in _peer_set if p.get("fwd_pe") is not None]
    peer_pes: list[float] = _from_set if _from_set else baseline.get("peer_pes", [])

    # consensus pack for §6 calibration (Step A + Step D)
    _consensus = baseline.get("consensus_eps_fy2") or {}
    consensus_high = float(_consensus.get("high", 0)) if _consensus else 0.0

    # ── Pull pass1 events (normalise §5.2 → internal format) ────────────────
    events: list[dict] = _normalize_events(pass1.get("events", []))

    # ── B4: project shares ───────────────────────────────────────────────────
    shares_proj = projected_shares(shares_out, horizon_years, trailing_dilution)

    # ── Per-scenario EPS ─────────────────────────────────────────────────────
    bull_eps  = scenario_eps(fy_revenue, base_op_margin, events, "bull",  tax_rate, shares_proj)
    base_eps  = scenario_eps(fy_revenue, base_op_margin, events, "base",  tax_rate, shares_proj)
    bear_eps  = scenario_eps(fy_revenue, base_op_margin, events, "bear",  tax_rate, shares_proj)

    # ── §6 Step A: consensus bull EPS floor ─────────────────────────────────
    calibration_log: list[str] = []
    if consensus_high > 0 and bull_eps < ANALYST_CONSENSUS_BULL_FLOOR_FRAC * consensus_high:
        floored = ANALYST_CONSENSUS_BULL_FLOOR_FRAC * consensus_high
        calibration_log.append(
            f"Step A: bull EPS floored ${bull_eps:.2f}→${floored:.2f} "
            f"(0.95×consensus_high=${consensus_high:.2f})"
        )
        bull_eps = floored

    # ── PEG-anchored P/E band per scenario (B3 bear floor conditional) ─────────
    peer_median = statistics.median(peer_pes) if len(peer_pes) >= 3 else None
    bull_band = pe_band("bull", growth_rate, franchise_q, peer_median)
    base_band = pe_band("base", growth_rate, franchise_q, peer_median)
    bear_band = pe_band("bear", growth_rate, franchise_q, peer_median)

    # EV uses band midpoints; bull_high / bear_low use band extremes for price range
    bull_pe_mid = (bull_band[0] + bull_band[1]) / 2
    base_pe     = (base_band[0] + base_band[1]) / 2
    bear_pe     = (bear_band[0] + bear_band[1]) / 2

    price_targets = {
        "bull": round(bull_eps * bull_pe_mid, 2),
        "base": round(base_eps * base_pe,     2),
        "bear": round(bear_eps * bear_pe,     2),
    }

    bull_price_high = round(bull_eps * bull_band[1], 2)   # pe_high for smoke harness
    bear_price_low  = round(bear_eps * bear_band[0], 2)   # pe_low for stress check

    # ── §6 Step D: consensus_divergent flag ──────────────────────────────────
    consensus_divergent = False
    if consensus_high > 0 and bull_price_high <= current_price:
        consensus_divergent = True
        calibration_log.append(
            f"Step D: consensus_divergent=True — bull_high=${bull_price_high:.2f} "
            f"≤ current_price=${current_price:.2f}"
        )

    # Assemble band dict for the math output (for renderers / Pass 2 reference)
    band = {
        "bull_low": bull_band[0], "bull_high": bull_band[1],
        "base_low": base_band[0], "base_high": base_band[1],
        "bear_low": bear_band[0], "bear_high": bear_band[1],
    }

    # ── Driver & joint probabilities ─────────────────────────────────────────
    driver_probs = driver_probabilities(events)
    joint_probs  = joint_probabilities(driver_probs)

    # ── EV, risk metrics ─────────────────────────────────────────────────────
    ev    = expected_value(price_targets, joint_probs)
    risks = risk_metrics(price_targets, joint_probs, current_price)

    # ── Breakeven P/E ────────────────────────────────────────────────────────
    trailing_eps = baseline.get("fy_eps_non_gaap") or baseline.get("trailing_eps")
    bkev_pe = breakeven_pe(current_price, trailing_eps) if trailing_eps else None

    # ── Reverse-DCF: implied FCF CAGR (B1 headline metric) ───────────────────
    dr = compute_wacc(
        equity_weight=0.85, debt_weight=0.15,
        beta=beta, tax_rate=tax_rate,
    )
    implied_cagr = implied_fcf_cagr(
        current_price=current_price,
        base_fcf=base_fcf,
        shares_projected=shares_proj,
        horizon_years=horizon_years,
        terminal_growth=DEFAULT_TERMINAL_GROWTH,
        discount_rate=dr,
        net_debt=net_debt,
        beta=beta,
    )

    # ── Scenario DCF intrinsic values ────────────────────────────────────────
    def _dcf_for_scenario(eps_val: float, pe_val: float) -> dict:
        # Use implied CAGR from EPS ratio vs trailing as proxy growth for FCF projection
        trailing = max(base_eps, 0.01)
        # Clamp ratio to ≥ 0 to avoid complex-number from fractional power of negative
        ratio = max(eps_val / trailing, 0.0)
        cagr_proxy = ratio ** (1.0 / max(horizon_years, 1)) - 1.0
        cagr_proxy = max(min(cagr_proxy, 0.80), -0.30)
        series = project_fcf(base_fcf, cagr_proxy, horizon_years)
        return dcf_intrinsic_value(series, DEFAULT_TERMINAL_GROWTH, dr, shares_proj, net_debt)

    bull_dcf = _dcf_for_scenario(bull_eps, bull_pe_mid)
    base_dcf = _dcf_for_scenario(base_eps, base_pe)
    bear_dcf = _dcf_for_scenario(bear_eps, bear_pe)

    # ── Recommendation ────────────────────────────────────────────────────────
    rec = recommendation(ev, current_price, joint_probs)

    # ── Assemble §5.3 math dict ──────────────────────────────────────────────
    return {
        "headline_metric": HEADLINE_METRIC,
        "implied_fcf_cagr": implied_cagr,
        "discount_rate": round(dr, 4),
        "shares_projected": round(shares_proj, 4),
        "scenario_eps": {
            "bull": round(bull_eps, 2),
            "base": round(base_eps, 2),
            "bear": round(bear_eps, 2),
        },
        "pe_band": band,
        "price_target": {
            "bull_high": bull_price_high,
            "bull_mid":  price_targets["bull"],
            "base_mid":  price_targets["base"],
            "bear_low":  bear_price_low,
        },
        "joint_probs": joint_probs,
        "driver_probs": driver_probs,
        "expected_value": ev,
        "risk": risks,
        "breakeven_pe": bkev_pe,
        "dcf": {
            "bull": bull_dcf,
            "base": base_dcf,
            "bear": bear_dcf,
        },
        "recommendation": rec,
        "calibration_log": calibration_log,
        "consensus_divergent": consensus_divergent,
    }
