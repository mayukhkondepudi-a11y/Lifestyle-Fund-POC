"""
Scenario-core orchestrator: run_methodology_math(pass1, baseline) → math dict.

Takes the frozen pass1 and baseline dicts, runs the deterministic scenario chain,
and returns the complete math contract dict.  No LLM calls, no I/O.

The chain (ONE revenue basis per scenario, no clamp-on-clamp):
  base_growth → scenario growth/margin/revenue → scenario EPS → peer-anchored P/E
  → per-scenario mid price → single-source EV.  Consensus is a warn-only sanity
  band; it never replaces a computed number.
"""
from __future__ import annotations

import statistics
from typing import Any

from compute import (
    HEADLINE_METRIC,
    MAX_BASE_GROWTH,
    MIN_BASE_GROWTH,
    HORIZON,
    SANITY_BAND_FRAC,
    REVDCF_TINY_FCF_YIELD,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH,
)
from compute_methodology_v2 import (
    headwind_eps_impact,
    scenario_eps,
    pe_bands,
    breakeven_pe,
    driver_probabilities,
    driver_outcome_probabilities,
    sensitivity_analysis,
    joint_probabilities,
    expected_value,
    risk_metrics,
    implied_fcf_cagr,
    projected_shares,
    dcf_intrinsic_value,
    project_fcf,
    wacc as compute_wacc,
    recommendation,
)

_SCENARIOS = ("bull", "base", "bear")


def _normalize_segments(pass1: dict) -> list[dict]:
    """Extract [{name, fy_revenue, growth_yoy}] from pass1.segments_enriched."""
    out = []
    for s in pass1.get("segments_enriched", []) or []:
        if not isinstance(s, dict):
            continue
        if s.get("fy_revenue") is None:
            continue
        out.append({
            "name":       s.get("name", ""),
            "fy_revenue": s.get("fy_revenue"),
            "growth_yoy": s.get("growth_yoy"),
        })
    return out


def _base_growth(baseline: dict, segments: list[dict]) -> tuple[float, str]:
    """
    Organic annual base-growth anchor + the signal it came from (logged for
    traceability).  Priority: consensus revenue CAGR → consensus EPS CAGR →
    five_yr_eps_growth_est → segment/company trailing YoY → 0.
    Clamped to [MIN_BASE_GROWTH, MAX_BASE_GROWTH].
    """
    fy_revenue = float(baseline.get("fy_revenue") or 0.0)
    fy_eps     = baseline.get("fy_eps_non_gaap")
    source = "none"
    g = None

    # 1) consensus revenue CAGR (revenue in raw $ → convert to $B)
    crev2 = (baseline.get("consensus_revenue_fy2") or {}).get("mid")
    if g is None and crev2 and fy_revenue > 0:
        rev2 = float(crev2) / 1e9
        if rev2 > 0:
            g = (rev2 / fy_revenue) ** (1.0 / HORIZON) - 1.0
            source = "consensus_revenue_cagr"

    # 2) consensus EPS implied CAGR
    ceps2 = (baseline.get("consensus_eps_fy2") or {}).get("mid")
    if g is None and ceps2 and fy_eps and float(fy_eps) > 0:
        ratio = float(ceps2) / float(fy_eps)
        if ratio > 0:
            g = ratio ** (1.0 / HORIZON) - 1.0
            source = "consensus_eps_cagr"

    # 3) prior estimate
    if g is None and baseline.get("five_yr_eps_growth_est") is not None:
        g = float(baseline["five_yr_eps_growth_est"])
        source = "five_yr_eps_growth_est"

    # 4) trailing YoY (segment-weighted, else company)
    if g is None:
        segs = [s for s in segments if s.get("growth_yoy") is not None and s.get("fy_revenue")]
        if segs:
            tot = sum(float(s["fy_revenue"]) for s in segs)
            g = sum(float(s["growth_yoy"]) * float(s["fy_revenue"]) for s in segs) / tot if tot else None
            source = "segment_weighted_yoy"
    if g is None and baseline.get("fy_revenue_yoy") is not None:
        g = float(baseline["fy_revenue_yoy"])
        source = "company_yoy"

    if g is None:
        g, source = 0.0, "none"

    g = max(min(g, MAX_BASE_GROWTH), MIN_BASE_GROWTH)
    return g, source


def run_methodology_math(pass1: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Orchestrate the scenario chain and return the math contract dict."""
    # ── Baseline fields ─────────────────────────────────────────────────────
    current_price  = float(baseline["current_price"])
    shares_out     = float(baseline["shares_out"])              # billions
    fy_revenue     = float(baseline["fy_revenue"])              # $B
    base_op_margin = float(baseline.get("fy_op_margin") or baseline.get("base_op_margin", 0.20))
    tax_rate       = float(baseline.get("tax_rate_guidance") or baseline.get("tax_rate", DEFAULT_TAX_RATE))
    beta           = float(baseline.get("beta", 1.0))
    net_debt       = float(baseline.get("net_debt") or 0.0)
    franchise_q    = bool(baseline.get("franchise_quality", False))
    trailing_dilution = float(baseline.get("trailing_net_dilution_rate") or 0.0)
    market_cap     = float(baseline.get("market_cap") or (current_price * shares_out))

    _raw_fcf = baseline.get("fy_fcf") or baseline.get("base_fcf")
    base_fcf = float(_raw_fcf) if _raw_fcf is not None else fy_revenue * base_op_margin * 0.9

    # Peer multiples (§5.1 peer_set[].fwd_pe; fallback flat peer_pes list)
    _peer_set  = baseline.get("peer_set", []) or []
    peer_pes   = [float(p["fwd_pe"]) for p in _peer_set if p.get("fwd_pe") is not None]
    peer_grow  = [float(p["growth"]) for p in _peer_set if p.get("growth") is not None]
    peer_median_pe     = statistics.median(peer_pes)  if len(peer_pes)  >= 2 else None
    peer_median_growth = statistics.median(peer_grow) if len(peer_grow) >= 2 else None

    consensus = baseline.get("consensus_eps_fy2") or {}
    consensus_low  = float(consensus.get("low",  0) or 0)
    consensus_high = float(consensus.get("high", 0) or 0)

    events   = pass1.get("events", []) or []
    segments = _normalize_segments(pass1)

    calibration_log: list[str] = []

    # ── Base growth anchor (traceable) ───────────────────────────────────────
    base_growth, growth_source = _base_growth(baseline, segments)
    if growth_source != "consensus_revenue_cagr":
        calibration_log.append(
            f"Base growth {base_growth:.3f} sourced from '{growth_source}' "
            f"(consensus revenue unavailable/unused)"
        )
    if base_growth in (MAX_BASE_GROWTH, MIN_BASE_GROWTH):
        calibration_log.append(f"Base growth clamped to {base_growth:.2f} bound")

    # ── B4: project shares over the FY+2 horizon ─────────────────────────────
    shares_proj = projected_shares(shares_out, HORIZON, trailing_dilution)

    # ── Per-scenario EPS (ONE bottom-up chain for bull/base/bear) ────────────
    eps_out = {
        s: scenario_eps(
            fy_revenue, base_op_margin, base_growth, events, s,
            tax_rate, shares_proj, HORIZON, segments,
        )
        for s in _SCENARIOS
    }
    scenario_eps_vals = {s: eps_out[s]["eps"] for s in _SCENARIOS}
    scenario_revenue  = {s: eps_out[s]["revenue"] for s in _SCENARIOS}
    scenario_margins  = {s: eps_out[s]["margin"] for s in _SCENARIOS}

    # ── Consensus sanity band (warn-only; NEVER replaces the number) ─────────
    if consensus_high > 0:
        lo_b = consensus_low * (1 - SANITY_BAND_FRAC)
        hi_b = consensus_high * (1 + SANITY_BAND_FRAC)
        for s in _SCENARIOS:
            e = scenario_eps_vals[s]
            if e < lo_b or e > hi_b:
                calibration_log.append(
                    f"Sanity: {s} EPS ${e:.2f} outside consensus band "
                    f"[${lo_b:.2f}, ${hi_b:.2f}] (informational; not adjusted)"
                )

    # ── Peer-anchored P/E points ─────────────────────────────────────────────
    pe = pe_bands(base_growth, franchise_q, peer_median_pe, peer_median_growth)
    if pe["source"] == "no_peer_fallback":
        calibration_log.append(
            f"P/E from no-peer growth fallback (base_pe={pe['base']}); "
            f"peer multiples unavailable"
        )
    if not franchise_q:
        calibration_log.append(
            "franchise_quality=False — no 25× bear P/E floor (pure peer-derate bear)"
        )

    # ── Per-scenario mid price (single source of truth) ──────────────────────
    price_mids = {
        "bull": round(scenario_eps_vals["bull"] * pe["bull"], 2),
        "base": round(scenario_eps_vals["base"] * pe["base"], 2),
        "bear": round(scenario_eps_vals["bear"] * pe["bear"], 2),
    }
    # Range extremes for display only (do NOT feed EV)
    bull_high = round(price_mids["bull"] * 1.15, 2)
    bear_low  = round(price_mids["bear"] * 0.85, 2)

    # ── Probabilities (transparent; no multipliers) ──────────────────────────
    driver_probs = driver_probabilities(events)
    joint_probs  = joint_probabilities(driver_probs)

    # ── Single-source EV + risk (all from the three mids) ────────────────────
    ev    = expected_value(price_mids, joint_probs)
    risks = risk_metrics(price_mids, joint_probs, current_price)

    ev_formula_string = (
        f"{joint_probs['bull']:.4f}×${price_mids['bull']:.2f} + "
        f"{joint_probs['base']:.4f}×${price_mids['base']:.2f} + "
        f"{joint_probs['bear']:.4f}×${price_mids['bear']:.2f} = ${ev:.2f}"
    )

    # ── Breakeven P/E (sanity line only) ─────────────────────────────────────
    trailing_eps = baseline.get("fy_eps_non_gaap") or baseline.get("trailing_eps")
    bkev_pe = breakeven_pe(current_price, float(trailing_eps)) if trailing_eps else None

    # ── Reverse-DCF (parameter-free reality check; tiny-FCF guarded) ─────────
    dr = compute_wacc(equity_weight=0.85, debt_weight=0.15, beta=beta, tax_rate=tax_rate)
    implied_cagr = implied_fcf_cagr(
        current_price=current_price, base_fcf=base_fcf, shares_projected=shares_proj,
        horizon_years=5, terminal_growth=DEFAULT_TERMINAL_GROWTH,
        discount_rate=dr, net_debt=net_debt, beta=beta,
    )
    fcf_yield = (base_fcf / market_cap) if market_cap > 0 else 0.0
    revdcf_unstable = fcf_yield < REVDCF_TINY_FCF_YIELD
    if revdcf_unstable:
        calibration_log.append(
            f"Reverse-DCF unstable: FCF yield {fcf_yield:.1%} < {REVDCF_TINY_FCF_YIELD:.0%} "
            f"— implied CAGR {implied_cagr:.0%} is a small-denominator artifact, read directionally"
        )

    # ── Scenario DCF intrinsic values (context; not headline) ────────────────
    def _dcf_for_scenario(eps_val: float) -> dict:
        trailing = max(scenario_eps_vals["base"], 0.01)
        ratio = max(eps_val / trailing, 0.0)
        cagr_proxy = max(min(ratio ** (1.0 / HORIZON) - 1.0, 0.80), -0.30)
        series = project_fcf(base_fcf, cagr_proxy, 5)
        return dcf_intrinsic_value(series, DEFAULT_TERMINAL_GROWTH, dr, shares_proj, net_debt)

    dcf = {s: _dcf_for_scenario(scenario_eps_vals[s]) for s in _SCENARIOS}

    # ── Recommendation + base-case return (headline) ─────────────────────────
    rec = recommendation(ev, current_price, joint_probs)
    base_case_return = round(price_mids["base"] / current_price - 1, 4) if current_price > 0 else 0.0

    # ── Owner earnings (gates sbc_section in Pass 2) ─────────────────────────
    _oe_fcf, _oe_sbc = baseline.get("fy_fcf"), baseline.get("fy_sbc")
    owner_earn = (
        round(float(_oe_fcf) - float(_oe_sbc), 4)
        if _oe_fcf is not None and _oe_sbc is not None else None
    )

    # ── Headwind / tailwind EPS impact tables ────────────────────────────────
    _hw, _tw = [], []
    for _e in events:
        hi_mag = abs(float(_e.get("revenue_at_risk_high", 0)))
        lo_mag = abs(float(_e.get("revenue_at_risk_low", 0)))
        hi_mag, lo_mag = max(hi_mag, lo_mag), min(hi_mag, lo_mag)
        mid_mag = (hi_mag + lo_mag) / 2.0
        op_m = float(_e.get("op_margin_to_apply", base_op_margin))
        tx   = float(_e.get("tax_rate_to_apply", tax_rate))
        entry = {
            "event_id":             _e.get("id", ""),
            "name":                 f"{_e.get('driver', '')} — {_e.get('outcome', '')}",
            "driver":               _e.get("driver", ""),
            "outcome":              _e.get("outcome", ""),
            "probability":          float(_e.get("probability", 0)),
            "revenue_at_risk_low":  lo_mag,
            "revenue_at_risk_high": hi_mag,
            "revenue_at_risk":      mid_mag,
            "eps_impact_high":      round(headwind_eps_impact(hi_mag, 1.0, op_m, tx, shares_proj), 4),
            "eps_impact_mid":       round(headwind_eps_impact(mid_mag, 1.0, op_m, tx, shares_proj), 4),
            "eps_impact_low":       round(headwind_eps_impact(lo_mag, 1.0, op_m, tx, shares_proj), 4),
            "bull_eps_impact":      round(headwind_eps_impact(hi_mag, 1.0, op_m, tx, shares_proj), 4),
            "base_eps_impact":      round(headwind_eps_impact(mid_mag, 1.0, op_m, tx, shares_proj), 4),
            "bear_eps_impact":      round(headwind_eps_impact(lo_mag, 1.0, op_m, tx, shares_proj), 4),
        }
        if _e.get("outcome") == "bear":
            _hw.append(entry)
        elif _e.get("outcome") == "bull":
            _tw.append(entry)

    # ── Segment scenario table — built from the SAME per-scenario projections
    # the EPS chain used, so the table totals equal scenario_revenue exactly. ──
    ssr = None
    _base_segs = eps_out["base"]["segments"]
    if _base_segs:
        _by_name = {sc: {r["name"]: r for r in eps_out[sc]["segments"]} for sc in _SCENARIOS}
        seg_rows = []
        for r in _base_segs:
            nm = r["name"]
            seg_rows.append({
                "name":       nm,
                "fy_revenue": r["fy_revenue"],
                "bull":       _by_name["bull"].get(nm, {}).get("projected"),
                "base":       _by_name["base"].get(nm, {}).get("projected"),
                "bear":       _by_name["bear"].get(nm, {}).get("projected"),
                "growth_source": "scenario_multiplier_rebased",
            })
        ssr = {"segments": seg_rows, "any_derived": True}

    # ── Driver outcome breakdown + sensitivity ───────────────────────────────
    driver_outcome_probs = driver_outcome_probabilities(events)
    _sens_minus = sensitivity_analysis("A", -10.0, driver_outcome_probs, {}, price_mids)
    _sens_plus  = sensitivity_analysis("A", +10.0, driver_outcome_probs, {}, price_mids)
    sensitivity_table = {
        "driver": "A",
        "minus_10pp": {"bull_prob": _sens_minus["joint_probs"]["bull"], "expected_value": _sens_minus["expected_value"]},
        "current":    {"bull_prob": joint_probs["bull"],                "expected_value": ev},
        "plus_10pp":  {"bull_prob": _sens_plus["joint_probs"]["bull"],  "expected_value": _sens_plus["expected_value"]},
    }

    # ── Assemble math dict ───────────────────────────────────────────────────
    return {
        "headline_metric":   HEADLINE_METRIC,
        "recommendation":    rec,
        "base_case_return":  base_case_return,
        "base_growth":       round(base_growth, 4),
        "base_growth_source": growth_source,
        "implied_fcf_cagr":  implied_cagr,
        "reverse_dcf_unstable": revdcf_unstable,
        "discount_rate":     round(dr, 4),
        "shares_projected":  round(shares_proj, 4),
        "scenario_eps": {s: round(scenario_eps_vals[s], 2) for s in _SCENARIOS},
        "scenario_revenue": {s: round(scenario_revenue[s], 4) for s in _SCENARIOS},
        "scenario_margin":  {s: scenario_margins[s] for s in _SCENARIOS},
        "pe_band": {
            "bull_low": pe["bull"], "bull_high": pe["bull"],
            "base_low": pe["base"], "base_high": pe["base"],
            "bear_low": pe["bear"], "bear_high": pe["bear"],
            "source":   pe["source"],
        },
        "pe_points": {s: pe[s] for s in _SCENARIOS},
        "price_target": {
            "bull":      price_mids["bull"],
            "base":      price_mids["base"],
            "bear":      price_mids["bear"],
            "bull_mid":  price_mids["bull"],
            "base_mid":  price_mids["base"],
            "bear_mid":  price_mids["bear"],
            "bull_high": bull_high,
            "bear_low":  bear_low,
        },
        "joint_probs":     joint_probs,
        "driver_probs":    driver_probs,
        "expected_value":  ev,
        "risk":            risks,
        "breakeven_pe":    bkev_pe,
        "dcf":             dcf,
        "calibration_log": calibration_log,
        "owner_earnings":  owner_earn,
        "headwinds":       _hw,
        "tailwinds":       _tw,
        "ev_formula_string": ev_formula_string,
        "driver_outcome_probabilities": driver_outcome_probs,
        "sensitivity_table": sensitivity_table,
        "scenario_segment_revenue": ssr,
    }
