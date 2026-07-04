"""
Scenario-core pure functions (rewrite).

All functions are deterministic and take only plain Python scalars/dicts/lists.
No I/O, no LLM calls, no Streamlit imports.

Design (see plans/come-up-with-a-composed-bachman.md):
  • ONE bottom-up revenue→EPS chain for all three scenarios (bull/base/bear share a
    revenue basis).  Drivers modulate a single revenue number; they do not spawn a
    parallel one.
  • P/E bands are peer-anchored; PEG is demoted to a sanity annotation.
  • Joint probabilities are a transparent normalized mean of per-driver outcome
    probabilities — no correlation multipliers.
  • Reverse-DCF is a parameter-free reality check, robustified for tiny-FCF names.

Calibration constants live in compute.py.
"""
from __future__ import annotations

from typing import Any

from compute import (
    MAX_BASE_GROWTH,
    MIN_BASE_GROWTH,
    BULL_GROWTH_MULT,
    BASE_GROWTH_MULT,
    BEAR_GROWTH_MULT,
    MAX_SCENARIO_GROWTH,
    BEAR_GROWTH_FLOOR,
    HORIZON,
    RERATE_PREMIUM,
    DERATE_DISCOUNT,
    BULL_PE_CEILING,
    PE_FLOOR,
    QUALITY_ADJ_LOW,
    QUALITY_ADJ_HIGH,
    NO_PEER_PE_MIN,
    NO_PEER_PE_MAX,
    NO_PEER_PEG,
    BEAR_PE_NOMINAL_FLOOR,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_EQUITY_RISK_PREMIUM,
)

_SCENARIOS = ("bull", "base", "bear")
_GROWTH_MULT = {"bull": BULL_GROWTH_MULT, "base": BASE_GROWTH_MULT, "bear": BEAR_GROWTH_MULT}


# ── Event helpers (accept §5.2 and internal key formats) ─────────────────────

def _ev_outcome(ev: dict) -> str:
    """Scenario an event belongs to: 'bull' | 'base' | 'bear'."""
    return ev.get("scenario") or ev.get("outcome") or "base"


def _ev_rev_at_risk_mid(ev: dict) -> float:
    """Midpoint magnitude of revenue-at-risk ($B), always non-negative."""
    if "rev_change_mid" in ev:
        return abs(float(ev.get("rev_change_mid", 0.0)))
    lo = abs(float(ev.get("revenue_at_risk_low", 0.0)))
    hi = abs(float(ev.get("revenue_at_risk_high", 0.0)))
    return (lo + hi) / 2.0


def _ev_op_margin(ev: dict) -> float | None:
    m = ev.get("op_margin_to_apply", ev.get("op_margin"))
    return float(m) if m is not None else None


# ── Scenario growth / margin / revenue / EPS (ONE chain) ─────────────────────

def _clamp_scenario_growth(g: float) -> float:
    """Upper clamp only; BEAR_GROWTH_FLOOR is None ⇒ bear may contract."""
    g = min(g, MAX_SCENARIO_GROWTH)
    if BEAR_GROWTH_FLOOR is not None:
        g = max(g, BEAR_GROWTH_FLOOR)
    return g


def scenario_growth(
    base_growth: float,
    base_revenue: float,
    events: list[dict[str, Any]],
    scenario: str,
    horizon: int = HORIZON,
) -> float:
    """
    Annual growth rate for one scenario.

    growth_s = base_growth × MULT[s]  ± event_tilt
    where event_tilt = (Σ revenue_at_risk_mid of scenario-s events / base_revenue) / horizon.
    Bull adds the tilt, bear subtracts it (so a heavy-risk bear can go negative),
    base is the anchor (no tilt).  Upper-clamped; NOT floored (cyclicals may contract).
    """
    g = base_growth * _GROWTH_MULT[scenario]
    if scenario != "base" and base_revenue and base_revenue > 0:
        tilt = sum(_ev_rev_at_risk_mid(ev) for ev in events if _ev_outcome(ev) == scenario)
        tilt_annual = (tilt / base_revenue) / max(horizon, 1)
        g += tilt_annual if scenario == "bull" else -tilt_annual
    return _clamp_scenario_growth(g)


def scenario_margin(
    base_op_margin: float,
    events: list[dict[str, Any]],
    scenario: str,
) -> float:
    """
    Operating margin for one scenario = revenue-at-risk-weighted average of the
    scenario events' op_margin_to_apply, falling back to base_op_margin when the
    scenario has no margin-bearing events.  Bounded to [0, 0.60].
    """
    num = den = 0.0
    for ev in events:
        if _ev_outcome(ev) != scenario:
            continue
        m = _ev_op_margin(ev)
        if m is None:
            continue
        w = _ev_rev_at_risk_mid(ev) or 1.0
        num += m * w
        den += w
    margin = (num / den) if den > 0 else base_op_margin
    return max(min(margin, 0.60), 0.0)


def _usable_segments(segments: list[dict] | None) -> list[dict]:
    """A genuine breakdown needs ≥2 segments with positive revenue.  A single
    'Consolidated' placeholder (segment == whole company) is NOT usable — it would
    reintroduce trailing-YoY-as-forward-growth, which the methodology forbids."""
    segs = [s for s in (segments or []) if s.get("fy_revenue") and float(s["fy_revenue"]) > 0]
    return segs if len(segs) >= 2 else []


def scenario_revenue_projection(
    base_revenue: float,
    base_growth: float,
    events: list[dict[str, Any]],
    scenario: str,
    horizon: int = HORIZON,
    segments: list[dict] | None = None,
) -> dict:
    """
    Single-source scenario revenue at FY+horizon.

    With a genuine multi-segment breakdown: each segment's growth is FORWARD-rebased
    to the consensus anchor while preserving relative ordering —
        seg_growth_s = base_growth × MULT[s] × (seg_yoy / weighted_avg_seg_yoy)
    so faster segments still grow faster, but the aggregate is anchored to
    base_growth (not raw trailing YoY).  rev = Σ segment projections, and the
    returned `segments` list IS the scenario table — table and EPS agree by
    construction.

    Without a genuine breakdown: top-down rev = base_revenue × (1+growth_s)^horizon,
    where growth_s carries the event tilt.

    Returns {revenue, growth, segments:[{name, fy_revenue, projected}...]}.
    """
    usable = _usable_segments(segments)
    if usable:
        rows = [
            (float(s["fy_revenue"]),
             float(s["growth_yoy"]) if s.get("growth_yoy") is not None else base_growth,
             s.get("name", ""))
            for s in usable
        ]
        tot_w = sum(w for w, _, _ in rows)
        gbar = (sum(w * g for w, g, _ in rows) / tot_w) if tot_w > 0 else base_growth
        mult = _GROWTH_MULT[scenario]
        seg_out: list[dict] = []
        total = 0.0
        for w, g_i, name in rows:
            rel = (g_i / gbar) if gbar > 0 else 1.0
            gseg = _clamp_scenario_growth(base_growth * mult * rel)
            proj = round(w * (1 + gseg) ** horizon, 4)
            seg_out.append({"name": name, "fy_revenue": w, "projected": proj})
            total += proj
        return {"revenue": round(total, 4), "growth": None, "segments": seg_out}

    g = scenario_growth(base_growth, base_revenue, events, scenario, horizon)
    return {"revenue": round(base_revenue * (1 + g) ** horizon, 4), "growth": g, "segments": []}


def scenario_eps(
    base_revenue: float,
    base_op_margin: float,
    base_growth: float,
    events: list[dict[str, Any]],
    scenario: str,
    tax_rate: float,
    shares_projected: float,
    horizon: int = HORIZON,
    segments: list[dict] | None = None,
) -> dict:
    """
    Bottom-up scenario EPS — identical mechanism for bull, base, and bear.

        rev_s   = scenario_revenue_projection(...)          # ONE revenue basis
        margin_s= scenario_margin(...)
        eps_s   = rev_s × margin_s × (1 - tax) / shares_projected

    Returns {eps, revenue, growth, margin, segments}.  A dict (not a bare float)
    so the orchestrator can expose scenario revenue for the reconciliation check.
    """
    proj = scenario_revenue_projection(
        base_revenue, base_growth, events, scenario, horizon, segments
    )
    rev = proj["revenue"]
    margin = scenario_margin(base_op_margin, events, scenario)
    eps = (rev * margin * (1 - tax_rate) / shares_projected) if shares_projected > 0 else 0.0
    return {
        "eps": eps,
        "revenue": rev,
        "growth": proj["growth"],
        "margin": round(margin, 4),
        "segments": proj["segments"],
    }


def headwind_eps_impact(
    base_revenue: float,
    headwind_rate: float,
    op_margin: float,
    tax_rate: float,
    shares_out: float,
) -> float:
    """EPS drag from a revenue-at-risk magnitude (used for headwind/tailwind tables)."""
    if shares_out <= 0:
        return 0.0
    rev_impact = base_revenue * headwind_rate
    return (rev_impact * op_margin * (1 - tax_rate)) / shares_out


# ── P/E bands (peer-anchored; PEG demoted to annotation) ─────────────────────

def _no_peer_base_pe(base_growth: float) -> float:
    """Bounded growth-informed fallback anchor (PEG≈1) when no peer multiples exist."""
    raw = max(base_growth, 0.0) * 100.0 * NO_PEER_PEG
    return max(min(raw, NO_PEER_PE_MAX), NO_PEER_PE_MIN)


def _quality_adjustment(base_growth: float, peer_median_growth: float | None) -> float:
    """
    Quality/growth premium vs peers, bounded [QUALITY_ADJ_LOW, QUALITY_ADJ_HIGH].
    Faster-than-peer growth ⇒ modest premium; slower ⇒ modest discount.
    """
    if not peer_median_growth or peer_median_growth <= 0:
        return 1.0
    ratio = base_growth / peer_median_growth
    return max(min(ratio, QUALITY_ADJ_HIGH), QUALITY_ADJ_LOW)


def pe_bands(
    base_growth: float,
    franchise_quality: bool,
    peer_median_pe: float | None,
    peer_median_growth: float | None = None,
) -> dict:
    """
    Per-scenario P/E points, peer-anchored.

        base_pe = clamp(peer_median × quality_adj, PE_FLOOR, BULL_PE_CEILING)
                  (or bounded growth fallback when no peers)
        bull_pe = min(base_pe × (1 + RERATE_PREMIUM), BULL_PE_CEILING)
        bear_pe = base_pe × (1 - DERATE_DISCOUNT), floored at 25× ONLY when franchise.

    Returns {bull, base, bear, source} where source ∈ {'peer','no_peer_fallback'}.
    """
    if peer_median_pe is not None and peer_median_pe > 0:
        adj = _quality_adjustment(base_growth, peer_median_growth)
        base_pe = peer_median_pe * adj
        source = "peer"
    else:
        base_pe = _no_peer_base_pe(base_growth)
        source = "no_peer_fallback"

    base_pe = max(min(base_pe, BULL_PE_CEILING), PE_FLOOR)
    bull_pe = min(base_pe * (1 + RERATE_PREMIUM), BULL_PE_CEILING)
    bear_pe = base_pe * (1 - DERATE_DISCOUNT)
    # Franchise bear floor applies ONLY when it sits below the base multiple —
    # a floor above base_pe would invert the P/E hierarchy.  For a low-multiple
    # franchise the ordinary derate stands (the 25× floor is irrelevant there).
    if franchise_quality and BEAR_PE_NOMINAL_FLOOR < base_pe:
        bear_pe = max(bear_pe, BEAR_PE_NOMINAL_FLOOR)
    bear_pe = max(bear_pe, PE_FLOOR)

    return {
        "bull": round(bull_pe, 2),
        "base": round(base_pe, 2),
        "bear": round(bear_pe, 2),
        "source": source,
    }


def breakeven_pe(current_price: float, eps: float) -> float | None:
    """Trailing P/E implied by current price and trailing EPS. None if eps ≤ 0."""
    if eps is None or eps <= 0:
        return None
    return round(current_price / eps, 1)


# ── Probabilities (transparent; NO skew multipliers) ─────────────────────────

def driver_outcome_probabilities(events: list[dict]) -> dict:
    """
    {driver_id: {'bull','base','bear'}} — per-driver outcome distribution,
    each driver normalized to sum 1.0.  Accepts §5.2 and internal key formats.
    """
    buckets: dict[str, dict[str, float]] = {}
    for ev in events:
        did = ev.get("driver_id") or ev.get("driver", "")
        sc = _ev_outcome(ev)
        p = float(ev.get("probability", 0.0))
        if did not in buckets:
            buckets[did] = {"bull": 0.0, "base": 0.0, "bear": 0.0}
        key = sc if sc in ("bull", "bear") else "base"
        buckets[did][key] += p
    for d in buckets.values():
        total = sum(d.values())
        if total > 0:
            for k in d:
                d[k] /= total
    return buckets


# alias kept for run_methodology_math import compatibility
def driver_probabilities(drivers: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Same as driver_outcome_probabilities (both key formats accepted)."""
    return driver_outcome_probabilities(drivers)


def joint_probabilities(driver_probs: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    Joint scenario probabilities = normalized mean of per-driver outcome probs.

    NO correlation multipliers.  Bull-leaning drivers ⇒ bull-leaning joint probs.
    """
    if not driver_probs:
        return {"bull": 0.0, "base": 1.0, "bear": 0.0}

    n = len(driver_probs)
    avg = {
        s: sum(d.get(s, 0.0) for d in driver_probs.values()) / n
        for s in _SCENARIOS
    }
    total = sum(avg.values())
    if total <= 0:
        return {"bull": 0.0, "base": 1.0, "bear": 0.0}
    return {s: round(avg[s] / total, 4) for s in _SCENARIOS}


def sensitivity_analysis(
    driver_id: str,
    delta_pp: float,
    driver_outcome_probs: dict,
    correlation_multipliers: dict,   # unused; kept for signature stability
    scenario_prices: dict,
) -> dict:
    """Recompute joint probs and EV when one driver's bull prob shifts by delta_pp
    (bear absorbs the opposite change; base constant)."""
    modified = {did: dict(probs) for did, probs in driver_outcome_probs.items()}
    if driver_id in modified:
        d = modified[driver_id]
        d["bull"] = max(0.0, min(1.0, d["bull"] + delta_pp / 100.0))
        d["bear"] = max(0.0, min(1.0, d["bear"] - delta_pp / 100.0))
        total = d["bull"] + d["base"] + d["bear"]
        if total > 0:
            for k in ("bull", "base", "bear"):
                d[k] /= total
    new_joint = joint_probabilities(modified)
    return {"joint_probs": new_joint, "expected_value": expected_value(scenario_prices, new_joint)}


def expected_value(price_targets: dict[str, float], joint_probs: dict[str, float]) -> float:
    """Probability-weighted expected price. price_targets keyed {bull,base,bear}."""
    ev = sum(joint_probs.get(s, 0.0) * price_targets.get(s, 0.0) for s in _SCENARIOS)
    return round(ev, 2)


def risk_metrics(
    price_targets: dict[str, float],
    joint_probs: dict[str, float],
    current_price: float,
) -> dict[str, float]:
    """Downside-first risk summary (B6). price_targets keyed {bull,base,bear} (mids)."""
    prob_loss = sum(
        joint_probs.get(s, 0.0)
        for s in _SCENARIOS
        if price_targets.get(s, current_price) < current_price
    )
    bear_price = price_targets.get("bear", current_price)
    max_drawdown_pct = (current_price - bear_price) / current_price if current_price > 0 else 0.0
    ev = expected_value(price_targets, joint_probs)
    expected_return_pct = (ev - current_price) / current_price if current_price > 0 else 0.0
    return {
        "prob_loss":           round(prob_loss, 4),
        "max_drawdown_pct":    round(max_drawdown_pct, 4),
        "expected_return_pct": round(expected_return_pct, 4),
        "ev":                  ev,
    }


# ── Segment scenario table (same multipliers as the EPS chain) ───────────────

def scenario_segment_revenue(segments_enriched: list[dict], horizon: int = HORIZON) -> dict | None:
    """
    Per-segment FY+horizon revenue for bull/base/bear using the SAME scenario
    growth multipliers as the EPS chain (segment growth_yoy × MULT[s]).  This is
    the display table; its per-scenario totals equal the EPS revenue basis.
    Returns None when no segment has usable revenue.
    """
    result = []
    for seg in segments_enriched:
        fy_rev = seg.get("fy_revenue")
        gy = seg.get("growth_yoy")
        if fy_rev is None or gy is None:
            continue
        fy_rev = float(fy_rev)
        gy = float(gy)
        entry = {"name": seg.get("name", ""), "fy_revenue": fy_rev, "growth_source": "scenario_multiplier"}
        for sc in _SCENARIOS:
            gseg = _clamp_scenario_growth(gy * _GROWTH_MULT[sc])
            entry[sc] = round(fy_rev * (1 + gseg) ** horizon, 4)
        result.append(entry)
    if not result:
        return None
    return {"segments": result, "any_derived": True}


# ── Owner earnings / contract signals (unchanged utility) ────────────────────

def owner_earnings(net_income, depreciation, capex, working_capital_change) -> float:
    return net_income + depreciation - capex - working_capital_change


def contract_asset_signals(revenue_backlog, ttm_revenue, rppo=None) -> dict:
    return {
        "revenue_visibility": round(revenue_backlog / ttm_revenue, 2) if revenue_backlog and ttm_revenue else None,
        "rppo_coverage":      round(rppo / ttm_revenue, 2)            if rppo and ttm_revenue else None,
    }


# ── DCF / reverse-DCF ────────────────────────────────────────────────────────

def wacc(equity_weight, debt_weight, cost_of_equity=None, cost_of_debt=0.05,
         tax_rate=DEFAULT_TAX_RATE, beta=1.0) -> float:
    if cost_of_equity is None:
        cost_of_equity = DEFAULT_RISK_FREE_RATE + beta * DEFAULT_EQUITY_RISK_PREMIUM
    after_tax_debt = cost_of_debt * (1 - tax_rate)
    return equity_weight * cost_of_equity + debt_weight * after_tax_debt


def project_fcf(base_fcf: float, cagr: float, horizon_years: int) -> list[float]:
    return [base_fcf * (1 + cagr) ** yr for yr in range(1, horizon_years + 1)]


def dcf_intrinsic_value(fcf_series, terminal_growth, discount_rate, shares_projected, net_debt=0.0) -> dict:
    if discount_rate <= terminal_growth:
        raise ValueError(f"discount_rate ({discount_rate}) must exceed terminal_growth ({terminal_growth})")
    pv_fcf = sum(fcf / (1 + discount_rate) ** yr for yr, fcf in enumerate(fcf_series, 1))
    terminal_fcf = fcf_series[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** len(fcf_series)
    enterprise_value = pv_fcf + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = equity_value / shares_projected if shares_projected > 0 else 0.0
    return {
        "enterprise_value":    round(enterprise_value, 2),
        "equity_value":        round(equity_value, 2),
        "intrinsic_per_share": round(per_share, 2),
    }


def implied_fcf_cagr(
    current_price: float,
    base_fcf: float,
    shares_projected: float,
    horizon_years: int = 5,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
    discount_rate: float | None = None,
    net_debt: float = 0.0,
    beta: float = 1.0,
    lo: float = -0.30,
    hi: float = 1.00,
    tol: float = 1e-5,
) -> float:
    """
    Reverse-DCF: FCF CAGR that makes DCF intrinsic value = current price.

    Rounded to whole-percent (2 dp) — this is a directional reality check, not a
    precision instrument.  Stability (tiny-FCF) is flagged by the orchestrator.
    """
    dr = discount_rate or (DEFAULT_RISK_FREE_RATE + beta * DEFAULT_EQUITY_RISK_PREMIUM + 0.04)

    def _price_at_cagr(g: float) -> float:
        series = project_fcf(base_fcf, g, horizon_years)
        return dcf_intrinsic_value(series, terminal_growth, dr, shares_projected, net_debt)["intrinsic_per_share"]

    f_lo = _price_at_cagr(lo) - current_price
    f_hi = _price_at_cagr(hi) - current_price
    if f_lo * f_hi > 0:
        return round(lo, 2) if abs(f_lo) < abs(f_hi) else round(hi, 2)

    for _ in range(60):
        mid = (lo + hi) / 2.0
        f_mid = _price_at_cagr(mid) - current_price
        if abs(f_mid) < tol or (hi - lo) / 2.0 < tol:
            return round(mid, 2)
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return round((lo + hi) / 2.0, 2)


def projected_shares(shares_out: float, horizon_years: int, trailing_net_dilution_rate: float = 0.0) -> float:
    """Project share count over horizon (B4). Negative dilution = net buyback."""
    return shares_out * (1 + trailing_net_dilution_rate) ** horizon_years


def recommendation(ev, current_price, joint_probs,
                   prob_loss_threshold=0.35, upside_threshold=0.15) -> str:
    """Rule-based BUY / WATCH / PASS from EV upside and bear probability."""
    if current_price <= 0:
        return "WATCH"
    exp_return = (ev - current_price) / current_price
    prob_loss_val = joint_probs.get("bear", 0.0)
    if exp_return >= upside_threshold and prob_loss_val < prob_loss_threshold:
        return "BUY"
    if exp_return < 0 or prob_loss_val >= prob_loss_threshold * 1.5:
        return "PASS"
    return "WATCH"
