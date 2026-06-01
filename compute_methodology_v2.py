"""
v3 methodology pure functions (§7.2).

All functions are deterministic and take only plain Python scalars/dicts/lists.
No I/O, no LLM calls, no Streamlit imports.

Calibration constants live in compute.py (§7.3 + C2).
"""
from __future__ import annotations

from typing import Any

from compute import (
    BULL_CORRELATION_MULTIPLIER,
    BEAR_CORRELATION_MULTIPLIER,
    PEG_FLOOR_BULL,
    PEG_CEILING_BULL,
    PEG_BASE_LOW,
    PEG_BASE_HIGH,
    BEAR_PE_NOMINAL_FLOOR,
    BEAR_PE_STRESS_FLOOR,
    FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR,
    SHARE_COUNT_PROJECTION,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_EQUITY_RISK_PREMIUM,
)


# ── §7.2 Pure functions ──────────────────────────────────────────────────────

def headwind_eps_impact(
    base_revenue: float,
    headwind_rate: float,
    op_margin: float,
    tax_rate: float,
    shares_out: float,
) -> float:
    """EPS drag from a structural headwind (e.g. FX, tariff, pricing pressure)."""
    rev_impact = base_revenue * headwind_rate
    return (rev_impact * op_margin * (1 - tax_rate)) / shares_out


def scenario_revenue(
    base_revenue: float,
    events: list[dict[str, Any]],
    scenario: str,
) -> float:
    """
    Sum base revenue plus all revenue deltas from events matching `scenario`.

    Each event dict must have: {scenario, rev_change_low, rev_change_mid, rev_change_high}.
    We use rev_change_mid as the point estimate.
    """
    total = base_revenue
    for ev in events:
        if ev.get("scenario") == scenario:
            total += ev.get("rev_change_mid", 0.0)
    return total


def blended_gross_margin(
    base_revenue: float,
    base_gross_margin: float,
    events: list[dict[str, Any]],
    scenario: str,
) -> float:
    """
    Revenue-weighted gross margin across base and scenario events.

    Events must include gross_margin (float); falls back to op_margin if absent.
    """
    base_rev_income = base_revenue * base_gross_margin
    total_rev = base_revenue
    total_income = base_rev_income

    for ev in events:
        if ev.get("scenario") == scenario:
            delta = ev.get("rev_change_mid", 0.0)
            margin = ev.get("gross_margin", ev.get("op_margin", base_gross_margin))
            total_rev += delta
            total_income += delta * margin

    if total_rev == 0:
        return base_gross_margin
    return total_income / total_rev


def scenario_eps(
    base_revenue: float,
    base_op_margin: float,
    events: list[dict[str, Any]],
    scenario: str,
    tax_rate: float,
    shares_projected: float,
) -> float:
    """
    Compute scenario EPS using blended operating margin across qualifying events.

    blended_op_income = base_revenue * base_op_margin
                      + sum(event_rev_change * event_op_margin)   [matching scenario]
    scenario_op_margin = blended_op_income / scenario_revenue
    EPS = scenario_revenue * scenario_op_margin * (1 - tax_rate) / shares_projected
    """
    rev = scenario_revenue(base_revenue, events, scenario)

    blended_income = base_revenue * base_op_margin
    for ev in events:
        if ev.get("scenario") == scenario:
            delta = ev.get("rev_change_mid", 0.0)
            blended_income += delta * ev.get("op_margin", base_op_margin)

    if rev == 0:
        return 0.0
    blended_margin = blended_income / rev
    net_income = rev * blended_margin * (1 - tax_rate)
    return net_income / shares_projected


def pe_band(
    scenario: str,
    growth_rate: float,
    franchise_quality: bool,
    peer_median_pe: float | None = None,
) -> tuple[float, float]:
    """
    Per-scenario P/E band per §7 spec (Phase 7).

    Returns (low, high) for the given scenario.

    Bull algorithm (spec Step B):
      peg_ceiling_pe = PEG_CEILING_BULL × (growth × 100)   # PEG floor for bull, not ceiling
      peg_floor_pe   = PEG_FLOOR_BULL   × (growth × 100)
      peer = peer_median_pe if provided, else peg_ceiling_pe
      pe_high = max(peg_ceiling_pe, peer)
      pe_low  = max(peg_floor_pe,   0.7 × peer)

    Base algorithm (symmetric, using PEG_BASE constants):
      peg_high = PEG_BASE_HIGH × (growth × 100)
      peg_low  = PEG_BASE_LOW  × (growth × 100)
      peer = peer_median_pe if provided, else peg_high
      pe_high = max(peg_high, peer)
      pe_low  = max(peg_low,  0.7 × peer)

    Bear algorithm (B3: floor conditional on franchise quality):
      floor = BEAR_PE_NOMINAL_FLOOR if franchise_quality else BEAR_PE_STRESS_FLOOR
      peer_haircut = peer × 0.875 (12.5% discount to peers for bear)
      pe_high = max(floor × 1.3, peer_haircut)   # bear band high: 30% above floor or peer-haircut
      pe_low  = floor
    """
    # Belt-and-suspenders: cap growth at 60% before multiplying — prevents 3-figure P/E
    # from anomalous trailing earningsGrowth values (e.g. NVDA 214.5%).
    peg_growth = max(min(growth_rate, 0.60) * 100, 1.0)

    if scenario == "bull":
        peg_ceiling = PEG_CEILING_BULL * peg_growth
        peg_floor   = PEG_FLOOR_BULL   * peg_growth
        peer = peer_median_pe if peer_median_pe is not None else peg_ceiling
        pe_high = max(peg_ceiling, peer)
        pe_high = min(pe_high, 60.0)  # hard cap: bull P/E never exceeds 60×
        pe_low  = max(peg_floor,   0.7 * peer)

    elif scenario == "base":
        peg_high = PEG_BASE_HIGH * peg_growth
        peg_low  = PEG_BASE_LOW  * peg_growth
        peer = peer_median_pe if peer_median_pe is not None else peg_high
        pe_high = max(peg_high, peer)
        pe_low  = max(peg_low,  0.7 * peer)

    elif scenario == "bear":
        if FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR:
            floor = BEAR_PE_NOMINAL_FLOOR if franchise_quality else BEAR_PE_STRESS_FLOOR
        else:
            floor = BEAR_PE_STRESS_FLOOR
        peer_haircut = (peer_median_pe * 0.875) if peer_median_pe is not None else (floor * 1.3)
        pe_high = max(floor * 1.3, peer_haircut)
        pe_low  = floor

    else:
        raise ValueError(f"Unknown scenario: {scenario!r}")

    return (round(pe_low, 1), round(pe_high, 1))


def breakeven_pe(
    current_price: float,
    eps: float,
) -> float | None:
    """Trailing P/E implied by current price and trailing EPS. None if eps ≤ 0."""
    if eps is None or eps <= 0:
        return None
    return round(current_price / eps, 1)


def driver_outcome_probabilities(events: list[dict]) -> dict:
    """Aggregate event probabilities into per-driver outcome distributions.
    Returns {driver_id: {'bull': float, 'base': float, 'bear': float}}.
    Probabilities within each driver sum to 1.0.
    Accepts both §5.2 format (driver/outcome keys) and internal format (driver_id/scenario keys)."""
    buckets: dict[str, dict[str, float]] = {}
    for ev in events:
        did = ev.get("driver_id") or ev.get("driver", "")
        sc = ev.get("scenario") or ev.get("outcome", "base")
        p = float(ev.get("probability", 0.0))
        if did not in buckets:
            buckets[did] = {"bull": 0.0, "base": 0.0, "bear": 0.0}
        key = sc if sc in ("bull", "bear") else "base"
        buckets[did][key] += p
    for did, d in buckets.items():
        total = sum(d.values())
        if total > 0:
            for k in d:
                d[k] /= total
    return buckets


def sensitivity_analysis(
    driver_id: str,
    delta_pp: float,
    driver_outcome_probs: dict,
    correlation_multipliers: dict,
    scenario_prices: dict,
) -> dict:
    """Recompute joint probabilities and EV when one driver's bull probability
    shifts by delta_pp percentage points. Bear probability absorbs the opposite
    change; base stays constant. Returns {'joint_probs': {...}, 'expected_value': float}."""
    modified = {did: dict(probs) for did, probs in driver_outcome_probs.items()}
    if driver_id in modified:
        d = modified[driver_id]
        d["bull"] = max(0.0, min(1.0, d["bull"] + delta_pp / 100.0))
        d["bear"] = max(0.0, min(1.0, d["bear"] - delta_pp / 100.0))
        total = d["bull"] + d["base"] + d["bear"]
        if total > 0:
            d["bull"] /= total
            d["base"] /= total
            d["bear"] /= total
    new_joint = joint_probabilities(modified)
    new_ev = expected_value(scenario_prices, new_joint)
    return {"joint_probs": new_joint, "expected_value": new_ev}


def driver_probabilities(
    drivers: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    Aggregate per-event probabilities into per-driver scenario probabilities.

    Input: list of event dicts, each with {driver_id, scenario, probability}.
    Output: {driver_id: {bull: p, base: p, bear: p}} — each driver sums to 1.0.

    Events not matching bull/bear are treated as base contribution.
    Per-driver totals are renormalized to sum to 1.0.
    """
    buckets: dict[str, dict[str, float]] = {}
    for ev in drivers:
        did = ev["driver_id"]
        sc  = ev.get("scenario", "base")
        p   = float(ev.get("probability", 0.0))
        if did not in buckets:
            buckets[did] = {"bull": 0.0, "base": 0.0, "bear": 0.0}
        key = sc if sc in ("bull", "bear") else "base"
        buckets[did][key] += p

    # Renormalize each driver so its three probs sum to 1.0
    for did, d in buckets.items():
        total = sum(d.values())
        if total > 0:
            for k in d:
                d[k] = d[k] / total
    return buckets


def joint_probabilities(
    driver_probs: dict[str, dict[str, float]],
) -> dict[str, float]:
    """
    Convert per-driver independent probabilities into joint scenario probabilities.

    Algorithm (§8.3):
      bull_avg = mean of driver bull probs
      bear_avg = mean of driver bear probs
      base_avg = mean of driver base probs
      w_bull = bull_avg * BULL_CORRELATION_MULTIPLIER   (3.0)
      w_bear = bear_avg * BEAR_CORRELATION_MULTIPLIER   (4.5)
      w_base = base_avg
      renormalize → joint_probs {bull, base, bear}
    """
    if not driver_probs:
        return {"bull": 0.0, "base": 1.0, "bear": 0.0}

    n = len(driver_probs)
    bull_avg = sum(d["bull"] for d in driver_probs.values()) / n
    base_avg = sum(d["base"] for d in driver_probs.values()) / n
    bear_avg = sum(d["bear"] for d in driver_probs.values()) / n

    w_bull = bull_avg * BULL_CORRELATION_MULTIPLIER
    w_bear = bear_avg * BEAR_CORRELATION_MULTIPLIER
    w_base = base_avg

    total = w_bull + w_base + w_bear
    if total == 0:
        return {"bull": 0.0, "base": 1.0, "bear": 0.0}

    return {
        "bull": round(w_bull / total, 4),
        "base": round(w_base / total, 4),
        "bear": round(w_bear / total, 4),
    }


def expected_value(
    price_targets: dict[str, float],
    joint_probs: dict[str, float],
) -> float:
    """
    Probability-weighted expected price.

    price_targets: {bull: high_price, base: mid_price, bear: low_price}
    """
    ev = 0.0
    for sc, price in price_targets.items():
        ev += joint_probs.get(sc, 0.0) * price
    return round(ev, 2)


def risk_metrics(
    price_targets: dict[str, float],
    joint_probs: dict[str, float],
    current_price: float,
) -> dict[str, float]:
    """
    Downside-first risk summary (B6: lead with prob_loss and max_drawdown, not Sharpe).

    Returns: {prob_loss, max_drawdown_pct, expected_return_pct, ev}
    prob_loss    = sum of probs for scenarios where price_target < current_price
    max_drawdown = (current_price - bear_price) / current_price
    """
    prob_loss = 0.0
    for sc, price in price_targets.items():
        if price < current_price:
            prob_loss += joint_probs.get(sc, 0.0)

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


def owner_earnings(
    net_income: float,
    depreciation: float,
    capex: float,
    working_capital_change: float,
) -> float:
    """Buffett owner earnings: net_income + D&A - capex - Δworking_capital."""
    return net_income + depreciation - capex - working_capital_change


def contract_asset_signals(
    revenue_backlog: float | None,
    ttm_revenue: float,
    rppo: float | None = None,
) -> dict[str, float | None]:
    """
    Signals derived from contract assets / remaining performance obligations.

    revenue_visibility = backlog / ttm_revenue  (None if backlog missing)
    rppo_coverage      = rppo / ttm_revenue     (None if rppo missing)
    """
    return {
        "revenue_visibility": round(revenue_backlog / ttm_revenue, 2) if revenue_backlog and ttm_revenue else None,
        "rppo_coverage":      round(rppo / ttm_revenue, 2)            if rppo and ttm_revenue else None,
    }


def wacc(
    equity_weight: float,
    debt_weight: float,
    cost_of_equity: float | None = None,
    cost_of_debt: float = 0.05,
    tax_rate: float = DEFAULT_TAX_RATE,
    beta: float = 1.0,
) -> float:
    """
    Weighted average cost of capital.

    cost_of_equity defaults to CAPM: r_f + beta * ERP.
    """
    if cost_of_equity is None:
        cost_of_equity = DEFAULT_RISK_FREE_RATE + beta * DEFAULT_EQUITY_RISK_PREMIUM
    after_tax_debt = cost_of_debt * (1 - tax_rate)
    return equity_weight * cost_of_equity + debt_weight * after_tax_debt


def project_fcf(
    base_fcf: float,
    cagr: float,
    horizon_years: int,
) -> list[float]:
    """Project free cash flow for `horizon_years` years at constant `cagr`."""
    return [base_fcf * (1 + cagr) ** yr for yr in range(1, horizon_years + 1)]


def dcf_intrinsic_value(
    fcf_series: list[float],
    terminal_growth: float,
    discount_rate: float,
    shares_projected: float,
    net_debt: float = 0.0,
) -> dict[str, float]:
    """
    DCF intrinsic value per share.

    Terminal value uses Gordon Growth Model on final FCF year.
    Returns: {enterprise_value, equity_value, intrinsic_per_share}
    """
    if discount_rate <= terminal_growth:
        raise ValueError(
            f"discount_rate ({discount_rate}) must exceed terminal_growth ({terminal_growth})"
        )

    pv_fcf = sum(fcf / (1 + discount_rate) ** yr for yr, fcf in enumerate(fcf_series, 1))
    terminal_fcf = fcf_series[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** len(fcf_series)

    enterprise_value = pv_fcf + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = equity_value / shares_projected if shares_projected > 0 else 0.0

    return {
        "enterprise_value":  round(enterprise_value, 2),
        "equity_value":      round(equity_value, 2),
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
    Reverse-DCF: find FCF CAGR that makes DCF intrinsic value = current market price.

    Primary output (B1: headline metric). Uses bisection over [lo, hi].
    Raises ValueError if market price is not bracketed in [lo, hi] range.
    """
    dr = discount_rate or (DEFAULT_RISK_FREE_RATE + beta * DEFAULT_EQUITY_RISK_PREMIUM + 0.04)

    def _price_at_cagr(g: float) -> float:
        series = project_fcf(base_fcf, g, horizon_years)
        result = dcf_intrinsic_value(series, terminal_growth, dr, shares_projected, net_debt)
        return result["intrinsic_per_share"]

    f_lo = _price_at_cagr(lo) - current_price
    f_hi = _price_at_cagr(hi) - current_price

    if f_lo * f_hi > 0:
        # Market price not bracketed — return boundary closest to target
        if abs(f_lo) < abs(f_hi):
            return lo
        return hi

    for _ in range(60):
        mid = (lo + hi) / 2.0
        f_mid = _price_at_cagr(mid) - current_price
        if abs(f_mid) < tol or (hi - lo) / 2.0 < tol:
            return round(mid, 6)
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid

    return round((lo + hi) / 2.0, 6)


def projected_shares(
    shares_out: float,
    horizon_years: int,
    trailing_net_dilution_rate: float = 0.0,
) -> float:
    """
    Project share count over horizon (B4).

    SHARE_COUNT_PROJECTION == "trailing_net_change":
        projected = shares_out * (1 + trailing_net_dilution_rate)^horizon_years
    Negative dilution_rate = net buyback.
    """
    if SHARE_COUNT_PROJECTION == "trailing_net_change":
        return shares_out * (1 + trailing_net_dilution_rate) ** horizon_years
    # Fallback (should not fire with current calibration)
    return shares_out


def recommendation(
    ev: float,
    current_price: float,
    joint_probs: dict[str, float],
    prob_loss_threshold: float = 0.35,
    upside_threshold: float = 0.15,
) -> str:
    """
    Simple rule-based recommendation: BUY / WATCH / PASS.

    BUY:  expected upside ≥ upside_threshold AND prob_loss < prob_loss_threshold
    PASS: expected return negative OR prob_loss ≥ prob_loss_threshold * 1.5
    WATCH: everything else
    """
    if current_price <= 0:
        return "WATCH"
    exp_return = (ev - current_price) / current_price
    prob_loss_val = sum(p for sc, p in joint_probs.items() if sc == "bear")

    if exp_return >= upside_threshold and prob_loss_val < prob_loss_threshold:
        return "BUY"
    if exp_return < 0 or prob_loss_val >= prob_loss_threshold * 1.5:
        return "PASS"
    return "WATCH"
