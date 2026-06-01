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
    headwind_eps_impact,
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
    # Bull: fy_eps_non_gaap × (1 + capped_growth)^2 (FY+2 per B5).
    # Growth-rate path: uses the same capped rate that drives the P/E band so
    # EPS and multiple are consistent. Falls back to event-driven if fy_eps absent.
    # calibration_log initialized here so the EPS path choice is logged before Step A.
    calibration_log: list[str] = []
    _EPS_HORIZON = 2
    _bull_growth = min(growth_rate, 0.60)
    _fy_eps = float(baseline.get("fy_eps_non_gaap") or 0.0)
    if _fy_eps > 0:
        bull_eps = _fy_eps * (1 + _bull_growth) ** _EPS_HORIZON
    else:
        calibration_log.append(
            f"Negative trailing EPS ({_fy_eps:.2f}) — bull EPS from event-driven "
            f"scenario_eps (growth-rate formula not applicable)"
        )
        bull_eps = scenario_eps(fy_revenue, base_op_margin, events, "bull", tax_rate, shares_proj)
    base_eps  = scenario_eps(fy_revenue, base_op_margin, events, "base",  tax_rate, shares_proj)
    bear_eps  = scenario_eps(fy_revenue, base_op_margin, events, "bear",  tax_rate, shares_proj)

    # ── §6 Step A: consensus bull EPS floor ─────────────────────────────────

    # Bug 2: log pe_anchors absence so the fallback is visible in the annexure
    if not pass1.get("pe_anchors"):
        calibration_log.append("pe_anchors absent — falling back to PEG-only P/E band")

    # Bug 1B: log PEG guard caps that fire in pe_band
    if growth_rate > 0.60:
        calibration_log.append(
            f"PEG guard: growth_rate {growth_rate:.3f} capped to 0.60 in pe_band "
            f"(prevents 3-figure P/E)"
        )

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
    # Log if bull_pe_high hard-cap (60.0) fired due to peer_median > 60
    if peer_median is not None and peer_median > 60.0:
        calibration_log.append(
            f"PEG guard: bull_pe_high capped to 60.0 (peer_median {peer_median:.1f} > 60)"
        )
    base_band = pe_band("base", growth_rate, franchise_q, peer_median)
    bear_band = pe_band("bear", growth_rate, franchise_q, peer_median)

    # Bug B: peer-dominated inputs collapse base and bull to the same ceiling; ratio fix
    # guarantees base trades at a discount to bull (base_high = 0.80×bull_high).
    if base_band[1] >= bull_band[1]:
        new_base_high = round(bull_band[1] * 0.80, 1)
        new_base_low  = round(bull_band[0] * 0.75, 1)
        calibration_log.append(
            f"Base P/E ratio-discounted: base_high {base_band[1]}→{new_base_high}, "
            f"base_low {base_band[0]}→{new_base_low} (0.80/0.75 of bull band)"
        )
        base_band = (new_base_low, new_base_high)

    # Bug A: franchise bear P/E floor (25×) can exceed the entire bull range on low-growth
    # names, inverting scenario prices.  Cap bear below bull_pe_low to preserve hierarchy.
    if bear_band[1] >= bull_band[0]:
        new_bear_high = round(bull_band[0] - 1.0, 1)
        new_bear_low  = round(min(bear_band[0], bull_band[0] - 2.0), 1)
        calibration_log.append(
            f"Bear P/E capped below bull P/E to preserve scenario hierarchy "
            f"(bear_high {bear_band[1]}→{new_bear_high}, bull_pe_low={bull_band[0]})"
        )
        bear_band = (new_bear_low, new_bear_high)

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

    # ── Owner earnings (SBC-adjusted FCF; gates sbc_section in Pass 2) ──────
    # Non-null only when both fy_fcf and fy_sbc are present in baseline.
    # When non-null, Pass 2 validator requires sbc_section in the report.
    _oe_fcf = baseline.get("fy_fcf")
    _oe_sbc = baseline.get("fy_sbc")
    _owner_earnings = (
        round(float(_oe_fcf) - float(_oe_sbc), 4)
        if _oe_fcf is not None and _oe_sbc is not None
        else None
    )

    # ── Headwinds / tailwinds EPS impact lists (bear events → headwinds, bull → tailwinds) ─
    # Reads raw §5.2 events (revenue_at_risk_low/high in $B). Uses abs() so all
    # impacts are non-negative magnitudes; sign is applied by the renderer.
    _hw: list[dict] = []
    _tw: list[dict] = []
    for _event in pass1.get("events", []):
        rev_abs_a = abs(float(_event.get("revenue_at_risk_high", 0)))
        rev_abs_b = abs(float(_event.get("revenue_at_risk_low",  0)))
        rev_high_mag = max(rev_abs_a, rev_abs_b)
        rev_low_mag  = min(rev_abs_a, rev_abs_b)
        rev_mid_mag  = (rev_high_mag + rev_low_mag) / 2.0
        op_m = float(_event.get("op_margin_to_apply", base_op_margin))
        tx   = float(_event.get("tax_rate_to_apply",  tax_rate))
        # headwind_eps_impact(base_revenue, headwind_rate=1.0, op_margin, tax_rate, shares_out)
        # rate=1.0 so rev_impact = magnitude directly
        impact_high = headwind_eps_impact(rev_high_mag, 1.0, op_m, tx, shares_proj)
        impact_mid  = headwind_eps_impact(rev_mid_mag,  1.0, op_m, tx, shares_proj)
        impact_low  = headwind_eps_impact(rev_low_mag,  1.0, op_m, tx, shares_proj)
        entry = {
            "event_id":             _event.get("id", ""),
            "name":                 _event.get("driver", "") + " — " + _event.get("outcome", ""),
            "driver":               _event.get("driver", ""),
            "outcome":              _event.get("outcome", ""),
            "probability":          float(_event.get("probability", 0)),
            "revenue_at_risk_low":  rev_low_mag,
            "revenue_at_risk_high": rev_high_mag,
            "revenue_at_risk":      rev_mid_mag,        # renderer: "Rev. at Risk" column
            "eps_impact_high":      round(impact_high, 4),
            "eps_impact_mid":       round(impact_mid,  4),
            "eps_impact_low":       round(impact_low,  4),
            "bull_eps_impact":      round(impact_high, 4),  # renderer alias
            "base_eps_impact":      round(impact_mid,  4),  # renderer alias
            "bear_eps_impact":      round(impact_low,  4),  # renderer alias
        }
        outcome = _event.get("outcome", "")
        if outcome == "bear":
            _hw.append(entry)
        elif outcome == "bull":
            _tw.append(entry)

    # ── Assemble §5.3 math dict ──────────────────────────────────────────────
    bull_price_mid = price_targets["bull"]
    base_price_mid = price_targets["base"]
    bear_price_mid = price_targets["bear"]
    ev_formula_string = (
        f"{joint_probs['bull']:.4f}×${bull_price_mid:.2f} + "
        f"{joint_probs['base']:.4f}×${base_price_mid:.2f} + "
        f"{joint_probs['bear']:.4f}×${bear_price_mid:.2f} = "
        f"${ev:.2f}"
    )
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
        "owner_earnings": _owner_earnings,
        "headwinds": _hw,
        "tailwinds": _tw,
        "ev_formula_string": ev_formula_string,
    }
