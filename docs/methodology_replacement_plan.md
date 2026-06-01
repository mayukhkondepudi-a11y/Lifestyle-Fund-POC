# Methodology Replacement — Full Execution Spec (v2, from first principles)

> Self-contained execution document. Read end-to-end before starting work. Every file path, function signature, prompt skeleton, JSON schema, validation rule, and removal target needed to execute the change is contained here.
>
> Source methodology: [newmethodology.md](newmethodology.md).

---

# PART I — FOUNDATION

## 1. Problem Statement

The current pipeline produces analytically weak reports. Three failure modes are confirmed from the user and from runtime logs:

**F1. Bull case price target sits below current price even on names with positive analyst consensus.** Structural, not tuning. Root causes (layered):
- Three stacked CAGR caps in `compute.py` clamp historical growth at 40% / 30% / 25% before it reaches any scenario logic ([compute.py:401-411](compute.py#L401-L411), [518-523](compute.py#L518-L523), [527-532](compute.py#L527-L532)). A genuine 60%+ grower (e.g. Celestica in logs) gets floored before Pass 1 even runs.
- `_apply_pe_guardrails` ([compute.py:1835](compute.py#L1835)) clamps bull P/E toward the company's own current/trailing multiple. A name already trading rich has its bull multiple ceiling near current, so bull price ≈ current.
- `_detect_gaap_suppression` ([compute.py:1817](compute.py#L1817)) silently re-adjusts EPS downward when LLM and stamped numbers diverge.
- Importance-weighted probabilities in `compute_scenarios_from_drivers` ([compute.py:1144+](compute.py#L1144)) dilute bull weight whenever Pass 1 produces drivers with importance mass spread across base/bear.
- The "analyst consensus = HARD floor" claim in [app.py:1082](app.py#L1082) and [compute.py:1118](compute.py#L1118) is implemented as a Pass-1 instruction to the LLM, not as a post-math assertion. The LLM doesn't always honour it.

**F2. Pass 1 validation fails on nearly every run and falls into a silent DEGRADED path.** Logs show `Pass1 retry also failed; proceeding DEGRADED` repeatedly. Root cause: `validate_pass1_inputs` ([compute.py:988](compute.py#L988)) requires 9+ structural constraints including `catalysts`, monotonicity, differentiation, importance ≤0.5, band compliance. The LLM produces JSON that misses one of them, retry fails, `_emit_degraded_report` ([ai.py:540](ai.py#L540)) ships a partial pipeline run as if it were valid. The downstream math runs against incomplete input.

**F3. Render crashes and data-quality warnings are swallowed.** `AttributeError: 'str' object has no attribute 'html'` in the render path, plus logged divergences (`revenue_growth 52.8% vs earnings_growth 1.5% diverge by 51.3pp`) that never surface in the report. The render path is also brittle to the DEGRADED dict shape.

## 2. What "Good" Looks Like

After this work:
- **Bull case is anchored to peer P/E and analyst-consensus high-end EPS**, both peer-relative and consensus-relative, never to the company's own current multiple. Hard-coded growth caps are gone. A post-math assertion (`scenarios.bull.eps ≥ 0.9 × consensus_eps_fy2.high` and `scenarios.bull.price_high > current_price` when consensus is positive) re-runs Pass 1 with a corrective hint if violated, and surfaces a "consensus-divergent" warning in the annexure if it still fails. No silent degradation.
- **Every number in the report body is produced by Python**, then cited verbatim by the LLM. The LLM does no arithmetic.
- **Math is pure functions** with a regression fixture (the AVGO worked example in [newmethodology.md](newmethodology.md)) that locks behaviour.
- **Validation is fault-tolerant**: Pass 1 produces a *minimum viable input pack*; missing optional fields don't trigger DEGRADED, they degrade only the corresponding optional section of the report.
- **Report is ≤ 4500 words** (Pass 3 enforces; re-prompt once if over). Structure follows the methodology's 9 sections + annexure, with SBC and contract-assets as optional sections gated on data availability.
- **No leftover vocabulary from the old methodology** anywhere in the codebase (grep checklist in §11).

## 3. Design Principles (brick-by-brick non-negotiables)

1. **Single source of truth for numbers**: all scenario / probability / EPS / DCF math lives in pure Python functions in [compute.py](compute.py), returning plain dicts. LLM and render both read from one math output object.
2. **No silent fallbacks for required signals**: if Pass 1 fails twice, raise a typed error and show a real error UI, not a fake report. Optional signals (SBC, contract assets, segments) degrade gracefully — but the *core scenario framework is never optional*.
3. **No clamps that suppress reality**: every cap, floor, or guardrail must have a methodology-justified reason and a logged audit trail. The new bear P/E floor (15× stress, 25× nominal) is methodology-derived; the old 40% CAGR cap is not — it's gone.
4. **Calibration is post-math, not pre-LLM**: floors and ceilings are asserted *after* Python computes the scenario, with corrective-retry hints, instead of trying to constrain the LLM upfront. This is what fixes F1.
5. **Surgical means surgical**: every deleted symbol, every deleted prompt phrase, every deleted vocabulary token is enumerated in §11. After the work, grep returns zero hits for any of them.
6. **Render reads only the new schema.** No backward-compat branches. Old reports stored in GitHub are marked unviewable with a one-time migration banner (see §10.5).

---

# PART II — ARCHITECTURE

## 4. Pipeline

```
ticker  ───►  fmp_api.fetch_full(ticker)                          [extended — §8.1]
              │
              ▼
              metrics (dict with raw FMP/yfinance + news + consensus)
              │
              ▼
              compute.calc_baseline(metrics)                       [NEW — §7.1]
              │
              ▼
              baseline (frozen dict — actuals snapshot only)
              │
              ▼
              ai.run_pass1_foundation(baseline, metrics)           [NEW prompt §9.1]
              │   ├─ retry once with corrective hint if validation soft-fails
              │   └─ raise Pass1ValidationError if retry also fails (no DEGRADED)
              ▼
              pass1 (dict — qualitative + event scaffolding)
              │
              ▼
              compute.run_methodology_math(pass1, baseline)        [NEW — §7.2]
              │   ├─ may raise BullCaseTooLowError, triggers ONE Pass 1 re-run
              │   │   with retry_hint="consensus_divergent"
              │   └─ otherwise produces math dict
              ▼
              math (dict — scenarios, probs, EV, DCF, risk metrics, etc.)
              │
              ▼
              ai.run_pass2_report(pass1, math, baseline)           [NEW prompt §9.2]
              │   ├─ self-counts words; if > 4500 trims internally
              │   └─ produces report sections JSON
              ▼
              pass2 (dict — 9 sections + annexure + optional SBC/contract)
              │
              ▼
              ai.run_pass3_audit(pass2, math, baseline)            [NEW prompt §9.3]
              │   └─ flags numeric citations not in math/baseline + over-budget
              ▼
              pass3 (dict — flags only)
              │
              ▼
              if pass3.over_word_budget: re-run pass2 once with "compress"
              if any pass3.flags[severity=error]: raise CitationError
              │
              ▼
              report_store.save(...)                               [unchanged interface]
              │
              ▼
              app.py render_report(report_dict)                    [REWRITTEN — §10]
```

3 LLM passes preserved (minimises orchestration churn). Every prompt and every math function is replaced. The DEGRADED escape hatch is **removed entirely**.

## 5. Data Contracts (the four dicts that flow through the pipeline)

These are the only shapes the render layer and downstream code may rely on. They are the contract.

### 5.1 `baseline` (output of `calc_baseline`)
```python
{
  "ticker": str,
  "company_name": str,
  "current_price": float,
  "shares_out": float,
  "market_cap": float,
  "net_debt": float,
  "currency": str,                         # "USD", "EUR", etc.

  "fy_revenue": float,
  "fy_revenue_yoy": float,
  "fy_gross_margin": float,
  "fy_op_margin": float,
  "fy_net_income": float,
  "fy_eps_non_gaap": float,
  "fy_fcf": float,
  "fy_fcf_margin": float,
  "fy_sbc": float | None,                  # optional — gates SBC section
  "fy_contract_assets": float | None,      # optional — gates contract section
  "prior_contract_assets": float | None,
  "fy_software_revenue": float | None,
  "fy_dso": float | None,
  "prior_dso": float | None,
  "fy_ocf": float,
  "fy_net_income_gaap": float,

  "tax_rate_guidance": float,              # default 0.21 if no guidance
  "beta": float,
  "fwd_pe": float,
  "trailing_pe": float,
  "peg": float | None,

  "consensus_eps_fy1": {"low": float, "mid": float, "high": float} | None,
  "consensus_eps_fy2": {"low": float, "mid": float, "high": float} | None,
  "consensus_eps_fy3": {"low": float, "mid": float, "high": float} | None,
  "consensus_revenue_fy1": {"low": float, "mid": float, "high": float} | None,
  "consensus_revenue_fy2": {"low": float, "mid": float, "high": float} | None,
  "consensus_price_target": {"low": float, "median": float, "high": float} | None,
  "n_analysts": int | None,

  "five_yr_eps_growth_est": float | None,
  "segments": [{"name": str, "revenue": float, "share_pct": float}] | None,
  "history_3y": [{"fy": str, "revenue": float, "op_margin": float, "fcf": float, "eps": float}],

  "peer_set": [{
    "ticker": str, "fwd_pe": float | None, "growth": float | None,
    "op_margin": float | None, "fcf_margin": float | None
  }],

  "recent_news": [{"date": str, "title": str, "summary": str}],

  "data_quality_warnings": [str],          # raised here, surfaced in report
}
```

### 5.2 `pass1` (output of `run_pass1_foundation`)
```python
{
  "corporate_dna": str,                    # ≤180 words
  "segments_enriched": [
    {"name": str, "fy_revenue": float, "share_pct": float,
     "growth_yoy": float, "gross_margin": float | None,
     "sub_segments": [{"name": str, "products": str, "trend": str}]}
  ],
  "primary_growth_driver": {
    "name": str, "narrative": str,        # ≤200 words
    "key_data_points": [str], "tam_view": str
  },
  "peer_set_enriched": [{"ticker": str, "rationale": str}],
  "macro_drivers": [                       # exactly 3, ids A/B/C
    {"id": "A", "label": str, "narrative": str},
    {"id": "B", "label": str, "narrative": str},
    {"id": "C", "label": str, "narrative": str}
  ],
  "events": [                              # 6-12 events
    {"id": str, "driver": "A"|"B"|"C", "outcome": "bull"|"base"|"bear",
     "probability": float,                 # 0..1
     "revenue_at_risk_low": float, "revenue_at_risk_high": float,
     "op_margin_to_apply": float, "tax_rate_to_apply": float,
     "evidence": str}                      # ≤60 words, must cite a date or source
  ],
  "pe_anchors": {
    "bull": {"reasoning": str},            # must cite a peer ticker
    "base": {"reasoning": str},
    "bear": {"reasoning": str}
  },
  "sbc_context": str | None,
  "contract_asset_context": str | None,
  "catalysts": [                           # 3-6 dated catalysts
    {"date": str, "event": str, "what_to_watch": str}
  ]
}
```

### 5.3 `math` (output of `run_methodology_math`)
```python
{
  "headwinds": [                           # one per event
    {"event_id": str, "driver": str, "outcome": str,
     "eps_impact_low": float, "eps_impact_high": float, "eps_impact_mid": float}
  ],
  "scenarios": {
    "bull": {"revenue": float, "op_margin": float, "tax_rate": float,
             "eps": float, "owner_eps": float | None,
             "pe_low": float, "pe_high": float,
             "price_low": float, "price_mid": float, "price_high": float,
             "breakeven_pe": float},
    "base": {...same shape...},
    "bear": {...same shape...}
  },
  "driver_probs": {                        # per driver
    "A": {"bull": float, "base": float, "bear": float},
    "B": {...}, "C": {...}
  },
  "joint_probs": {"bull": float, "base": float, "bear": float},  # sums to 1.0
  "correlation_multipliers": {"bull": 3.0, "bear": 4.5},          # defaults, exposed
  "expected_value": float,
  "risk_metrics": {
    "expected_return": float, "std_dev": float,
    "prob_loss": float, "max_drawdown": float,
    "upside_downside_capture": float        # primary metric (not Sharpe)
  },
  "owner_earnings": {                       # optional
    "owner_eps_by_scenario": {"bull": float, "base": float, "bear": float},
    "sbc_per_share_after_tax": float,
    "owner_fcf_fy": float
  } | None,
  "contract_signals": {                     # optional
    "contract_assets_to_software_rev": float,
    "cash_conversion_ratio": float,
    "dso_delta": float,
    "flag": "benign"|"monitor"|"concerning"
  } | None,
  "dcf": {
    "wacc": float, "terminal_growth": float,
    "fcf_path": [float],                    # 10 years
    "gordon_per_share": float, "exit_multiple_per_share": float,
    "blended_per_share": float
  },
  "implied_fcf_cagr": float,
  "recommendation": {"label": "BUY"|"WATCH"|"PASS", "rationale_handle": str},
  "calibration_log": [str],                 # every clamp/anchor/floor that fired
  "consensus_divergent": bool               # true if bull case still below consensus high after retry
}
```

### 5.4 `pass2` (report content)
```python
{
  "investment_thesis": str,                # 350-450 words
  "corporate_overview": str,               # 200-300 words
  "business_model": str,                   # 400-500 words
  "primary_growth_driver": str,            # 500-600 words
  "financial_summary": str,                # 350-400 words
  "peer_comparison": str,                  # 250-300 words
  "scenario_framework": str,               # 1000-1200 words (LARGEST)
  "catalysts": str,                        # 200-250 words
  "conclusion": str,                       # 250-300 words
  "annexure": str,                         # raw tables — verbatim from math
  "sbc_section": str | None,               # 300 words if math.owner_earnings present
  "contract_assets_section": str | None,   # 250 words if math.contract_signals present
  "word_count_self_report": int
}
```

### 5.5 `pass3` (audit)
```python
{
  "flags": [{"section": str, "issue": str, "severity": "error"|"warn"|"info"}],
  "over_word_budget": bool,
  "consensus_divergent_surfaced": bool      # true if pass2 actually included the divergence note
}
```

## 6. The Bull-Case Fix — Specified End-to-End

Because this is the load-bearing change, it gets its own section. The bug is the user-visible failure; the fix must be airtight.

**Inputs (from baseline)**: `current_price`, `consensus_eps_fy2.high`, `peer_set` with peer fwd P/E + peer growth.

**Step A — Bull EPS construction (in `run_methodology_math`)**:
```
bull_eps = max(
    bottom_up_bull_eps,                                # from scenario revenue × bull op margin × (1−tax) / shares
    0.95 × consensus_eps_fy2.high                      # consensus-high floor
)
```
If `bottom_up_bull_eps < 0.9 × consensus_eps_fy2.high` AND `consensus_eps_fy2.high > fy_eps_non_gaap`, log a `calibration_log` line and clamp up. If the gap is > 25%, raise `BullCaseTooLowError` which triggers ONE Pass 1 retry with a corrective hint (see §9.1).

**Step B — Bull P/E construction**:
```
peer_pe_growth_adjusted = median([
    p.fwd_pe for p in peer_set
    if p.growth and abs(p.growth − bull_implied_growth) ≤ 0.25 × bull_implied_growth
])

peg_ceiling_pe = PEG_CEILING_BULL × (bull_implied_growth × 100)
peg_floor_pe   = PEG_FLOOR_BULL   × (bull_implied_growth × 100)

bull_pe_high = max(peg_ceiling_pe, peer_pe_growth_adjusted)
bull_pe_low  = max(peg_floor_pe,   0.7 × peer_pe_growth_adjusted)
```
The company's own current/trailing P/E **enters only as a sanity log line**, never as a cap. This is the hard rule.

**Step C — Bull price target**:
```
bull_price_high = bull_eps × bull_pe_high
bull_price_low  = bull_eps × bull_pe_low
bull_price_mid  = (bull_price_high + bull_price_low) / 2
```

**Step D — Calibration assertion**:
```
if consensus_eps_fy2 and consensus_eps_fy2.high > fy_eps_non_gaap:
    assert bull_price_high > current_price, \
        "bull case below current despite positive consensus"
```
On failure: ONE Pass 1 retry with `retry_hint="consensus_divergent"`. If retry also fails, set `math.consensus_divergent = True` and surface a "consensus-divergent: bull case below consensus despite positive sell-side view; investigate" line in the annexure. Do not silently produce a broken report.

**Step E — Existing suppressors that MUST be removed for this fix to hold**:
- All three CAGR caps at [compute.py:401-411, 518-523, 527-532](compute.py#L401-L411).
- `_apply_pe_guardrails` at [compute.py:1835](compute.py#L1835).
- `_detect_gaap_suppression` at [compute.py:1817](compute.py#L1817).
- The pre-LLM "consensus floor" instruction in [prompt_pass1.txt](prompt_pass1.txt) and the floor-application loop at [compute.py:1118](compute.py#L1118) (the new post-math assertion replaces them).

---

# PART III — MATH LAYER SPEC

## 7. Pure Functions in [compute.py](compute.py)

All functions below are pure: no I/O, no globals, no LLM. Each returns floats or plain dicts. Each maps to a phase in [newmethodology.md](newmethodology.md).

### 7.1 `calc_baseline(metrics) → baseline_dict`
Replaces the existing `calc()` at [compute.py:137](compute.py#L137). Slimmer; produces only the §5.1 shape. Reuses these existing helpers (keep them):
- `_get_statement_eps`, `_compute_base_fcf`, `_compute_margins_from_statements`, `_compute_dilution_rate`, `_extract_latest_quarter`, `_extract_n_year_values`, `_build_multi_year_financials`, `_extract_capex_history`, `_extract_sbc_history`, `_extract_shares_history`, `_compute_debt_equity`, `_cross_validate_forward_pe`, `_compute_price_history`, `clean_latex`.

Removes from `calc()`:
- All band computations (`_compute_pe_band`, `_compute_op_margin_band`, `_compute_tax_rate_band`).
- All CAGR cap branches (`_compute_cagrs` simplified to raw CAGR without caps; raw values preserved for the math layer to consume directly).
- PEG band override logic.
- `_check_growth_consistency` flag emission (raw warnings still surface via `data_quality_warnings`).
- Anything writing `pe_ranges` (old data shape).
- `_add_depth_metrics`, `compute_qglp_score` callers.

### 7.2 New math functions (replace removed scenario/probability/DCF code)

| Function | Signature | Purpose | Methodology ref |
|---|---|---|---|
| `headwind_eps_impact` | `(revenue_loss, op_margin, tax_rate, shares) → float` | EPS dollars per share lost per event | Phase 5 (line 207-209) |
| `scenario_revenue` | `(segment_actuals, growth_assumptions, headwind_dollars) → dict` | Per-scenario revenue by segment + total | Phase 6.1 |
| `blended_gross_margin` | `(seg_rev, seg_gm) → float` | Mix-weighted GM | Phase 6.2 (line 259-261) |
| `scenario_eps` | `(revenue, op_margin, tax_rate, shares) → float` | EPS from revenue path | Phase 6.3 |
| `pe_band` | `(scenario, growth, peer_anchors, peg_floor, peg_ceiling, bear_floor) → (low, high)` | P/E band per scenario, peer-anchored. **No own-current-P/E input.** | Phase 7 |
| `breakeven_pe` | `(current_price, scenario_eps) → float` | Sanity log line only | Phase 7 (line 320-323) |
| `driver_probabilities` | `(events_in_driver) → {bull, base, bear}` | Renormalised | Phase 8.2 |
| `joint_probabilities` | `(driver_probs, bull_corr, bear_corr) → {bull, base, bear}` | With correlation multiplier | Phase 8.3 |
| `expected_value` | `(midpoints, probs) → float` | Sum of weighted midpoints | Phase 9 (381-384) |
| `risk_metrics` | `(returns, probs) → dict` | Upside/downside capture as primary; std_dev as input only; **no Sharpe** | Phase 9 (line 407 deprecation) |
| `owner_earnings` | `(non_gaap_eps, sbc_total, shares, tax_rate) → dict` | Optional | Phase 12 |
| `contract_asset_signals` | `(contract_assets, software_rev, ocf, net_income, dso_now, dso_prior) → dict` | Optional | Phase 13 |
| `wacc` | `(rf, erp, beta, cost_of_debt, tax_rate, debt_to_capital) → float` | WACC helper | Phase 14 |
| `project_fcf` | `(base_fcf, year1_growth, terminal_growth, years=10) → [float]` | Mechanical taper | Phase 14 |
| `dcf_intrinsic_value` | `(fcf_path, wacc, terminal_growth, exit_multiple, net_debt, shares) → dict` | Gordon AND exit-multiple in parallel | Phase 14 (535-537) |
| `implied_fcf_cagr` | `(market_cap, current_fcf, wacc, terminal_growth, years=10, net_debt=0) → float` | **Primary DCF output** — bisection solver | Phase 14 (540-541) |
| `recommendation` | `(ev, current_price, prob_loss, max_dd) → dict` | BUY/WATCH/PASS + handle | derived |
| `run_methodology_math` | `(pass1, baseline) → math_dict` | **Top-level orchestrator** — wires all of the above | §5.3 shape |

### 7.3 Calibration constants (top of compute.py, named, reviewable)
```python
# Phase 8.3 correlation multipliers
BULL_CORRELATION_MULTIPLIER = 3.0
BEAR_CORRELATION_MULTIPLIER = 4.5

# Phase 7 PEG framework
PEG_FLOOR_BULL    = 0.7
PEG_CEILING_BULL  = 1.0
PEG_BASE_LOW      = 1.3
PEG_BASE_HIGH     = 1.7

# Phase 7 mature-tech P/E floors
BEAR_PE_NOMINAL_FLOOR = 25.0
BEAR_PE_STRESS_FLOOR  = 15.0

# Calibration assertions (the F1 fix)
ANALYST_CONSENSUS_BULL_FLOOR_FRAC = 0.95   # bull EPS must be ≥ this × consensus_high
ANALYST_CONSENSUS_HARD_GAP_FRAC   = 0.75   # if bull EPS < this × consensus_high, raise BullCaseTooLowError

# DCF defaults
DEFAULT_TAX_RATE        = 0.21
DEFAULT_TERMINAL_GROWTH = 0.04
DEFAULT_RISK_FREE_RATE  = 0.045
DEFAULT_EQUITY_RISK_PREMIUM = 0.055
```
Changing any of these should be a deliberate, code-reviewed act. The AVGO regression fixture must be regenerated if they change.

### 7.4 Unit test fixture (`tests_methodology.py`)
Single file with the AVGO worked example from [newmethodology.md](newmethodology.md) as a frozen fixture. Asserts:
- `bull_eps ≈ $14.50` (within $0.50), `base_eps ≈ $10.80`, `bear_eps ≈ $6.35`
- `breakeven_pe.bull ≈ 22.1`, `base ≈ 29.6`, `bear ≈ 50.4`
- `joint_probs ≈ {bull: 0.249, base: 0.593, bear: 0.158}` (within 1pp)
- `expected_value ≈ $348` (within $5)
- `risk_metrics.prob_loss ≈ 0.158`, `upside_downside_capture ≈ 2.31` (within 5%)
- `recommendation.label == "WATCH"` or `"BUY"` (within tolerance band)
This is the regression sentinel.

---

# PART IV — DATA LAYER

## 8. Extensions to [fmp_api.py](fmp_api.py)

### 8.1 New fields to fetch (all best-effort, return `None` on miss)
| Field | yfinance source | FMP fallback |
|---|---|---|
| `stock_based_compensation` | `cashflow.loc["Stock Based Compensation"]` | `cash-flow-statement.stockBasedCompensation` |
| `contract_assets` (current + prior) | `balance_sheet.loc["Contract Assets"]` if present | search BS for `contractAssets` |
| `dso` (current + prior) | `accounts_receivable / revenue × 365` | same |
| `analyst_consensus_eps_fy1/fy2/fy3` (low/mid/high) | `Ticker.earnings_estimate` table | FMP `analyst-estimates` |
| `analyst_consensus_revenue_fy1/fy2` (low/mid/high) | `Ticker.revenue_estimate` table | FMP `analyst-estimates` |
| `consensus_price_target` (low/median/high) + `n_analysts` | `Ticker.analyst_price_targets()` | FMP `price-target-consensus` |
| `segment_revenue` | not reliable on yfinance | FMP `revenue-product-segmentation` |
| `peer_set_enriched` (peer growth + fcf_margin) | per-peer `Ticker.info` | FMP `key-metrics` |

### 8.2 New helper
```python
def fetch_consensus_pack(ticker) -> dict | None:
    """Returns consensus_eps_fy1/2/3, consensus_revenue_fy1/2, price_target, n_analysts.
       Never raises; returns None for missing fields."""
```

### 8.3 Surface data quality
Move existing log-only warnings (`FCF DIVERGENCE`, `PEG CONFLICT`, `DATA QUALITY WARNING`) into a `data_quality_warnings: [str]` list on the metrics dict. `calc_baseline` propagates the list through. Render shows it as a collapsed disclaimer block.

---

# PART V — LLM PASSES

## 9. New Prompts and Pass Wiring

### 9.1 Pass 1 — [prompt_pass1.txt](prompt_pass1.txt) (full rewrite)

**Template variables**: `{ticker}`, `{company_name}`, `{baseline_json}`, `{recent_news_json}`, `{retry_hint}` (empty on first call; populated on retry).

**Skeleton**:
```
You are an equity research analyst building a structured input pack for downstream Python math.
You produce STRICT JSON only — no prose outside the JSON object.

NUMBERS: do not invent any. Every number in your output must come from {baseline_json}
or {recent_news_json}. Your job is to organise, label, and add qualitative context.

OUTPUT SCHEMA (all fields required unless marked optional):
{schema from §5.2}

VALIDATION RULES (your output will be machine-checked):
- macro_drivers: exactly 3, with ids "A", "B", "C".
  A = primary growth realisation; B = recurring/franchise stability; C = legacy/competitive/insourcing risk.
  Labels may be tailored to the company (e.g. for a REIT, B = "rental income stability";
  for a miner, A = "commodity cycle + production growth"). Ids stay A/B/C.
- events: 6-12 total, each driver has ≥ 2 events.
- For each event: probability ∈ [0,1]; revenue_at_risk_high ≥ low ≥ 0;
  op_margin_to_apply ∈ [0,1]; tax_rate_to_apply ∈ [0, 0.5]; evidence cites a date or source from {recent_news_json} or {baseline_json}.
- pe_anchors.{bull,base,bear}.reasoning must mention at least one peer ticker from {baseline_json}.peer_set.
  It MUST NOT reference the company's own current or trailing P/E as an anchor.
- catalysts: 3-6 entries, each with a real future date and a specific event.
- sbc_context: ONE paragraph if baseline.fy_sbc is non-null; otherwise the literal value null.
- contract_asset_context: ONE paragraph if baseline.fy_contract_assets is non-null; otherwise null.

{retry_hint}
```

**`retry_hint` populated when `BullCaseTooLowError` triggered**:
```
PRIOR ATTEMPT WAS REJECTED FOR CALIBRATION. Your bull-scenario revenue and op-margin combination
produced a bull EPS of $X. Analyst consensus FY+2 high-end EPS is $Y. Your bull case must be
consistent with where the most optimistic analyst sees this name. INCREASE bull-outcome event
revenue_at_risk and/or op_margin_to_apply under driver A until the implied bull EPS reaches
at least 0.95 × $Y. DO NOT reduce bear-side probabilities to compensate. The bull-case
plausibility is a structural requirement — re-examine your driver A events.
```

**Fault-tolerant validation in `ai.run_pass1_foundation`** (replaces `validate_pass1_inputs`):
- Soft errors (LLM forgot a sub-field): on first attempt, append a corrective hint and retry once.
- Hard errors after retry: raise `Pass1ValidationError` — no DEGRADED path. Caller (`run_pipeline`) catches and surfaces a real error UI to the user.
- Validation never blocks on stylistic things (paragraph count, tone). Only on contract violations (missing required field, out-of-range number, wrong schema type).

### 9.2 Pass 2 — [prompt_pass2.txt](prompt_pass2.txt) (full rewrite)

**Template variables**: `{ticker}`, `{company_name}`, `{pass1_json}`, `{math_json}`, `{baseline_json}`.

**Top of prompt (ALL CAPS, non-negotiable)**:
```
EVERY NUMBER IN THE REPORT BODY MUST COME VERBATIM FROM math_json OR baseline_json.
YOU DO NO ARITHMETIC. If a number you want to cite is not in those JSONs, omit it.
This rule will be machine-audited in Pass 3.
```

**Output schema**: §5.4.

**Mandatory inclusions in `scenario_framework`**:
- Headwind decomposition (summarise math.headwinds in prose; the table itself goes in annexure).
- Bull / base / bear price targets with the P/E anchor reasoning from pass1.pe_anchors.
- Joint probability + correlation multipliers explicitly stated (3.0× / 4.5× by default).
- Expected value vs current price.
- Risk metrics block: prob_loss, max_drawdown, upside_downside_capture. **Never** mention Sharpe.
- DCF block: gordon_per_share, exit_multiple_per_share, blended_per_share, implied_fcf_cagr — with one sentence comparing implied growth to pass1.macro_drivers[A].narrative.
- Bear-case stress paragraph per [newmethodology.md](newmethodology.md) Phase 7 line 318 (15-20× scenario, true tail risk).
- If `math.consensus_divergent` is true: a one-paragraph "divergence note" explaining the model bull is below consensus high.

**Mandatory if data present**:
- `sbc_section` if `math.owner_earnings` is non-null (Phase 12).
- `contract_assets_section` if `math.contract_signals` is non-null (Phase 13).

**Forbidden vocabulary** (Pass 3 will flag):
- "Sharpe" anywhere in user-facing output.
- "importance weight", "monotonicity gate", "differentiation gate", "outcome sum" (old jargon).
- "DEGRADED" anywhere.

**Word budget**: prompt instructs LLM to self-count and trim to ≤ 4500 (excluding annexure). Self-report in `word_count_self_report`.

### 9.3 Pass 3 — [prompt_pass3.txt](prompt_pass3.txt) (full rewrite, narrower scope)

**Template variables**: `{pass2_json}`, `{math_json}`, `{baseline_json}`.

**Output schema**: §5.5.

**Audit rules**:
- For every numeric token in pass2 body text, fuzzy-match against any value in `math_json` or `baseline_json`. Tolerance 2%. No match → `{severity: error}`.
- Forbidden vocabulary scan (§9.2 list) → `{severity: error}`.
- Word count > 4500 → `over_word_budget: true`.
- If `math.consensus_divergent == true` but pass2 didn't include a divergence note → `{severity: error}`.
- No tone, no style, no length-of-paragraph checks. The report is allowed to have opinions.

**On `over_word_budget`**: orchestrator re-runs Pass 2 once with `"compress to ≤ 4500 words"` prepended.

### 9.4 New `ai.run_pipeline(ticker)` orchestrator
Replaces `run_two_pass`. Returns the final report dict assembled from `baseline + pass1 + math + pass2 + pass3` flags. Hard contract:
- Raises `Pass1ValidationError`, `BullCaseTooLowError`, `CitationError` as typed exceptions.
- Never returns a partial/degraded result.
- Has no calls to any of the removed functions (§11 grep checklist).

---

# PART VI — RENDER LAYER

## 10. [app.py](app.py) Render Rewrite

### 10.1 Section order (replaces lines ≈ 418–1100)
1. Header strip (ticker, recommendation, EV vs current, joint_probs, conviction-from-`upside_downside_capture`).
2. Data-quality disclaimer (collapsed) — populated from `baseline.data_quality_warnings`.
3. Investment Thesis
4. Corporate Overview
5. Business Model (segment + sub-segment tables from `pass1.segments_enriched`)
6. Primary Growth Driver
7. Financial Summary (Python-rendered KPI table from `baseline`)
8. Peer Comparison (Python-rendered table from `baseline.peer_set` + `pass1.peer_set_enriched`)
9. **Scenario Framework** — the long section:
   - Headwind decomposition table (`math.headwinds`)
   - Scenario revenue/EPS/price-target table (`math.scenarios`)
   - Probability framework table (`math.driver_probs`, `math.joint_probs`, with multipliers shown)
   - EV + risk metrics block (upside/downside capture, prob of loss, max drawdown — NOT Sharpe)
   - DCF block (intrinsic value range + implied FCF CAGR)
   - Bear-case stress paragraph
   - If `math.consensus_divergent`: a visible divergence banner
10. Catalysts (timeline from `pass1.catalysts`)
11. Conclusion
12. Annexure (collapsed): event list, driver probs, correlation multipliers used, DCF inputs, calibration log
13. **Optional**: SBC owner-earnings table + section (rendered iff `math.owner_earnings` non-null)
14. **Optional**: Contract Assets monitor + section (rendered iff `math.contract_signals` non-null)

### 10.2 Sticky widgets
Three `_sc.html` injection sites at [app.py:13, 1177, 1940](app.py#L13). Each needs repoint to new schema. The recurring `AttributeError: 'str' object has no attribute 'html'` suggests `_sc` is being shadowed somewhere — fix as part of the rewrite (it should always be a Streamlit container, never a string).

### 10.3 Recommendation widget
Pulls `math.recommendation.label` and `.rationale_handle`. No more `derive_recommendation` call.

### 10.4 [styles.py](styles.py)
Add CSS for new section IDs (`scenario-framework`, `primary-growth-driver`, `sbc-section`, `contract-section`, `consensus-divergent-banner`, `data-quality-warning`). Remove CSS for deleted IDs (see §11).

### 10.5 Old-report compatibility
Reports saved by the old methodology have a different section schema. Two options:
- **Recommended**: tag old reports with a `methodology_version: "v1"` field on load. Render shows a one-time banner: "Report generated with prior methodology — re-run for updated analysis." Old reports stay viewable in their original form (no migration), but new reports use the v2 renderer. This is one extra branch in `render_report` keyed off `methodology_version`.
- Alternative: hide old reports entirely from the index. Cleaner but loses user history.

`report_store.save_report` writes `methodology_version: "v2"` on every new save.

---

# PART VII — SURGICAL REMOVAL

## 11. Complete deletion manifest

### 11.1 [compute.py](compute.py) — symbols to delete
After the work, grep `^def <name>` returns zero hits for each:
- `_compute_pe_band` (line 809)
- `_compute_pe_ranges_per_scenario` (line 853)
- `_compute_op_margin_band` (line 745)
- `_compute_tax_rate_band` (line 776)
- `_check_growth_consistency` (line 567)
- `validate_pass1_inputs` (line 988)
- `compute_scenarios_from_drivers` (line 1144)
- `derive_recommendation` (line 1332)
- `compute_fundamentals_diagnostic` (line 1365)
- `compute_scenario_probabilities` (line 1396)
- `compute_reverse_dcf` (line 1656)
- `stamp_headwind_tailwind_eps` (line 1757)
- `_sum_item_eps` (line 1798)
- `_stamp_item_eps` (line 1806)
- `_detect_gaap_suppression` (line 1817)
- `_apply_pe_guardrails` (line 1835)
- `_compute_single_scenario` (line 1854)
- `compute_sensitivity_table` (line 2068)
- `compute_scenario_math` (line 2117)
- `validate_post_scenario` (line 2282)
- `compute_qglp_score` (line 2355)
- `_add_depth_metrics` (line 930)

Plus delete the three CAGR cap branches inside `_compute_cagrs` (lines 401-411) and the cap branches inside `_compute_peg` (lines 518-523, 527-532).

### 11.2 [ai.py](ai.py) — symbols to delete
- `run_pass1` (line 155)
- `run_pass1_with_retry` (line 174)
- `_build_pass1_messages` (line 213)
- `run_pass2` (line 292)
- `_build_pass2_messages` (line 338)
- `run_pass3_selfcheck` (line 421)
- `_build_pass3_messages` (line 443)
- `_paragraph_count_check_failed` (line 521)
- `_check_divergence` (line 530)
- `_emit_degraded_report` (line 540)
- `run_two_pass` (line 567)
- `_merge_outputs` (line 659)
- `thesis_check` (line 729) — verify this isn't called by a feature still in scope; if so, port; otherwise delete

Keep: `_load_prompt`, `run_ai`, `parse_json_response`, `_cl`, model fallback chain.

### 11.3 Prompt files — full replacement
- [prompt_pass1.txt](prompt_pass1.txt) — replace per §9.1
- [prompt_pass2.txt](prompt_pass2.txt) — replace per §9.2
- [prompt_pass3.txt](prompt_pass3.txt) — replace per §9.3

### 11.4 [app.py](app.py) — render block rewrite
Delete the render code for old section IDs:
- `revenue_architecture`
- `growth_drivers`
- `margin_analysis`
- `financial_health`
- `competitive_position`
- `driver_narratives`
- `scenario_commentary`
- `recommendation_rationale`
- `monitoring_dashboard_intro`
- `catalysts_intro` (replaced with structured catalysts)

Repoint orchestrator call at [app.py:1878](app.py#L1878) to `ai.run_pipeline`.

### 11.5 [styles.py](styles.py)
Remove CSS bound to deleted section IDs (grep `revenue-architecture`, `growth-drivers`, etc.).

### 11.6 Grep checklist — must return zero hits when done
```bash
grep -rn "compute_scenarios_from_drivers\|_compute_pe_ranges_per_scenario" .
grep -rn "derive_recommendation\|compute_fundamentals_diagnostic" .
grep -rn "validate_pass1_inputs\|compute_reverse_dcf" .
grep -rn "stamp_headwind_tailwind_eps\|_apply_pe_guardrails\|_detect_gaap_suppression" .
grep -rn "compute_scenario_probabilities\|compute_scenario_math\|validate_post_scenario" .
grep -rn "compute_qglp_score\|compute_sensitivity_table\|_compute_single_scenario" .
grep -rn "_emit_degraded_report\|DEGRADED" .
grep -rn "importance_weight\|monotonicity_gate\|differentiation_gate" .
grep -rn "Sharpe" .
grep -rn "revenue_architecture\|growth_drivers\|margin_analysis\|competitive_position" .
grep -rn "driver_narratives\|scenario_commentary\|recommendation_rationale" .
grep -rn "monitoring_dashboard_intro\|catalysts_intro" .
grep -rn "CAP = 0.40\|CAP at 30%\|capped at 25%" .
```
Any hit is a leftover that must be removed.

### 11.7 Vocabulary alignment check
Diff [prompt_pass1.txt](prompt_pass1.txt), [prompt_pass2.txt](prompt_pass2.txt), [prompt_pass3.txt](prompt_pass3.txt) against [newmethodology.md](newmethodology.md). The only methodology vocabulary that should appear: macro driver A/B/C, events, joint probability, correlation multiplier, owner earnings, implied FCF CAGR, breakeven P/E, headwind sizing, peer-anchored P/E, upside/downside capture.

---

# PART VIII — IMPLEMENTATION SEQUENCE

## 12. Build order (each phase produces a verifiable artefact)

### Phase A — Math foundation (no LLM, no UI)
A1. Add §7.3 calibration constants to top of [compute.py](compute.py).
A2. Implement §7.2 pure functions one-by-one.
A3. Write `tests_methodology.py` with the AVGO fixture (§7.4). Iterate until all assertions pass.
A4. Implement `run_methodology_math(pass1, baseline)` (§5.3 shape) by composing the pure functions.
A5. Write a synthetic-Pass1 fixture for AVGO and confirm `run_methodology_math` reproduces the worked example within tolerance.

**Exit criterion for Phase A**: `pytest tests_methodology.py` is green. AVGO synthetic run produces bull EPS ~$14.50 ± 0.50, EV ~$348 ± 5, joint_probs within 1pp of methodology.

### Phase B — Data layer
B1. Add §8.1 fetches to [fmp_api.py](fmp_api.py). Each new helper returns None on miss.
B2. Add `fetch_consensus_pack` (§8.2).
B3. Add `data_quality_warnings` list propagation (§8.3).
B4. Implement `calc_baseline(metrics)` per §7.1. Delete `calc()` once the new function passes a smoke test on AVGO, KO, ASML, a small-cap.

**Exit criterion**: `calc_baseline` returns the §5.1 schema on 5 test tickers; optional fields are None where data is missing; no crashes.

### Phase C — Pass 1
C1. Write [prompt_pass1.txt](prompt_pass1.txt) per §9.1.
C2. Implement `ai.run_pass1_foundation` with the fault-tolerant validator (§9.1). Delete old Pass1 functions (§11.2).
C3. Run on AVGO, NVDA, KO, ASML, a small-cap. Inspect each JSON output against §5.2 schema.
C4. Verify retry-with-hint mechanism by intentionally feeding a baseline where consensus is positive but a manually corrupted Pass 1 would produce low bull — confirm `BullCaseTooLowError` triggers a retry.

**Exit criterion**: Pass 1 succeeds on 5 tickers without ever entering DEGRADED. Retry mechanism fires when expected.

### Phase D — Math orchestrator end-to-end
D1. Wire `run_methodology_math` to consume Pass 1's actual output (not synthetic).
D2. Run AVGO end-to-end Pass1 → math; compare against worked example.
D3. Verify calibration assertions §6 fire on NVDA (positive consensus, expect bull > current).

**Exit criterion**: bull_price_high > current_price on NVDA. AVGO numbers reproduce within tolerance.

### Phase E — Pass 2
E1. Write [prompt_pass2.txt](prompt_pass2.txt) per §9.2.
E2. Implement `ai.run_pass2_report`. Delete old Pass2 functions (§11.2).
E3. Run on the 5 test tickers. Manually inspect: every section present, word count ≤ 4500, no forbidden vocabulary, numbers visibly cited from math/baseline.

### Phase F — Pass 3
F1. Write [prompt_pass3.txt](prompt_pass3.txt) per §9.3.
F2. Implement `ai.run_pass3_audit`. Delete old Pass3 functions (§11.2).
F3. Run on the 5 test tickers. Inject a deliberate citation error in a Pass 2 output and confirm the flag fires.
F4. Implement the over-budget re-prompt loop.

### Phase G — Orchestrator + render
G1. Implement `ai.run_pipeline(ticker)`. Delete `run_two_pass` and all DEGRADED machinery.
G2. Rewrite [app.py](app.py) render block per §10. Delete all old section render code in the same commit.
G3. Update [styles.py](styles.py) per §10.4.
G4. Add `methodology_version: "v2"` tag in `report_store.save_report`; add v1 banner branch in render (§10.5).

### Phase H — Surgical sweep
H1. Run the grep checklist (§11.6). Clean up every hit.
H2. Run the vocabulary diff (§11.7).
H3. Read the diff of every changed file. Look for stray comments, dead imports, commented-out code.
H4. End-to-end run on all 5 verification tickers (§13).

---

# PART IX — VERIFICATION

## 13. Acceptance tests

End-to-end pipeline on these tickers. Each must pass all listed criteria.

### Ticker matrix
| Ticker | Why included | Specific pass criterion |
|---|---|---|
| AVGO | Methodology's worked example | bull mid within $30 of $470; base within $20 of $340; bear within $20 of $185; EV within $10 of $348; prob_loss within 2pp of 15.8% |
| NVDA | Strong positive analyst consensus — direct test of F1 fix | `bull_price_high > current_price`; `calibration_log` does NOT include "consensus_divergent"; recommendation ∈ {BUY, WATCH} |
| CLS (Celestica) | 60%+ grower the old system was crushing with the 40% CAGR cap | `bull_eps > consensus_eps_fy2.high × 0.95`; `bull_price_high > current_price`; no DEGRADED anywhere in logs |
| KO | Low-growth blue chip | bear P/E doesn't collapse below 15× stress floor; base case ≈ current; correlation multipliers don't blow up tails on a stable stock |
| ASML | Non-US, high-quality, but possibly thinner FMP coverage | Report renders; optional sections (SBC, contract assets) gracefully omitted if data missing; DCF still runs from yfinance |
| A genuine small-cap (e.g. random Russell 2000) | Stress test data gaps | Report renders or fails with a clear typed error; never DEGRADED; never crashes the render |

### Universal pass criteria for every ticker
- Word count ≤ 4500 (Pass 3 reports `over_word_budget: false`).
- Pass 3 returns zero `severity: error` flags.
- Annexure contains: full event list, driver probs, joint probs with correlation multipliers (3.0× / 4.5×), DCF inputs, calibration log.
- Mandatory sections present: scenario framework, DCF block, bear stress paragraph.
- Optional sections present iff data: SBC, contract assets.
- Recommendation label aligns with EV vs current price.
- No `Sharpe` token in user-facing output.
- No DEGRADED token anywhere.
- Render does not crash; no `AttributeError`.

### Regression sentinel
`tests_methodology.py` AVGO fixture must stay green. Any future change that breaks it requires explicit documentation + fixture regeneration.

### Manual eyeball pass (AVGO)
Read AVGO front-to-back. Confirm visible: peer-anchored P/E (not own-current-anchored), correlation multipliers 3.0× / 4.5×, owner-earnings reconciliation, reverse-engineered implied FCF CAGR as the lead DCF output, upside/downside capture (not Sharpe), bear stress paragraph.

---

# PART X — RISK & ROLLBACK

## 14. What could go wrong

| Risk | Mitigation |
|---|---|
| LLM produces invalid JSON on Pass 1 frequently | Schema is leaner than old (no 9 hard gates). Soft validator + one retry. If still failing, typed error to user — no silent fallback. |
| Consensus data missing on small/foreign caps | Calibration assertion §6 is gated: it only fires when `consensus_eps_fy2.high` is non-null AND `> fy_eps_non_gaap`. On stocks with no consensus, the assertion skips and the report ships with a "no consensus data — bull case is bottom-up only" annexure line. |
| AVGO regression fixture drifts when calibration constants change | Constants are named and reviewable. Fixture must be regenerated as a deliberate act with reviewer sign-off. |
| Old reports in GitHub no longer render | §10.5 v1 banner branch. Old reports still readable; new ones use v2 renderer. |
| Pipeline takes longer due to retry loops | Worst case: Pass 1 retry + Pass 2 retry = 2 extra LLM calls per report. Acceptable; current system retries too. |
| `_sc.html` AttributeError persists | Audit every assignment to `_sc` during the render rewrite; ensure it's always a Streamlit container. Add a startup assertion. |

## 15. Out of scope (do not touch)
- Email / alerts pipeline
- Auth and user management
- Search / ticker resolution
- GitHub storage layer interface (only the `methodology_version` tag is added)
- Streamlit chrome other than the render block

## 16. Done definition
- All Phase A–H exit criteria met.
- All §13 ticker matrix criteria met on a single end-to-end run.
- §11.6 grep checklist returns zero hits.
- `tests_methodology.py` is green.
- User confirms a manual read-through of the AVGO and NVDA reports.
