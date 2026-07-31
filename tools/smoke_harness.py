"""Phase F smoke harness for the v3 methodology rewrite.

Runs after every phase. Cheap automated gate against contract drift and LLM
regression. Per-ticker checks against frozen pipeline-output fixtures stored
under tests/fixtures/{TICKER}_pipeline.json.

Current state: Phase 0 — infrastructure only. No fixtures exist yet, so every
ticker reports SKIP and the harness exits 0. Checks light up as their
contracts come online:

  - joint_probs_sum, reverse_dcf, nvda_bull_above_current → Phase A (math)
  - word_count, forbidden_tokens                          → Phase E (Pass 2)
  - pipeline_runs                                          → Phase G (end-to-end)

A check returns one of:
  (True,  None) → pass
  (False, msg)  → fail (reported, harness exits non-zero)
  (None,  msg)  → skip (contract not yet wired; not a failure)

LLM nondeterminism note (Part F): math-layer checks are exact (deterministic);
LLM-touching checks are tolerant by design (loose bounds, contract-only).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures"
VERIFICATION_TICKERS = ["AVGO", "NVDA", "CLS", "KO", "ASML", "SMALLCAP"]

CheckResult = Tuple[Optional[bool], Optional[str]]
Check = Callable[[dict], CheckResult]


def load_fixture(ticker: str) -> Optional[dict]:
    path = FIXTURE_DIR / f"{ticker}_pipeline.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ── Checks ──────────────────────────────────────────────────────────────────

def check_pipeline_runs(fixture: dict) -> CheckResult:
    # Phase G: presence of a top-level "ok" flag indicates the orchestrator
    # composed without raising. Until then, skip.
    if "ok" not in fixture:
        return None, "no top-level 'ok' flag (Phase G not landed)"
    return (True, None) if fixture["ok"] else (False, fixture.get("error", "pipeline reported not-ok"))


def check_joint_probs_sum(fixture: dict) -> CheckResult:
    probs = (fixture.get("math") or {}).get("joint_probs")
    if probs is None:
        return None, "no math.joint_probs (Phase A not landed)"
    total = sum(probs.values())
    if abs(total - 1.0) > 0.001:
        return False, f"joint_probs sum={total:.4f} (need 1.0 ±0.001)"
    return True, None


def check_word_count(fixture: dict) -> CheckResult:
    body = (fixture.get("pass2") or {}).get("body")
    if not body:
        return None, "no pass2.body (Phase E not landed)"
    n = len(body.split())
    if n > 4500:
        return False, f"word count {n} exceeds 4500"
    return True, None


def check_forbidden_tokens(fixture: dict) -> CheckResult:
    body = (fixture.get("pass2") or {}).get("body")
    if not body:
        return None, "no pass2.body (Phase E not landed)"
    # "capture" appears in B6 — drop only if/when we rename. Conservative for now.
    forbidden = ["Sharpe", "DEGRADED", "capture"]
    hits = [t for t in forbidden if t in body]
    if hits:
        return False, f"forbidden tokens present: {hits}"
    return True, None


def check_reverse_dcf(fixture: dict) -> CheckResult:
    val = (fixture.get("math") or {}).get("implied_fcf_cagr")
    if val is None:
        return None, "no math.implied_fcf_cagr (Phase A not landed)"
    if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
        return False, f"implied_fcf_cagr not finite: {val!r}"
    return True, None


def check_nvda_bull_above_current(fixture: dict, ticker: str) -> CheckResult:
    if ticker.upper() != "NVDA":
        return None, None
    baseline = fixture.get("baseline") or {}
    math_d = fixture.get("math") or {}
    cp = baseline.get("current_price")
    bull_high = (math_d.get("price_target") or {}).get("bull_high")
    if cp is None or bull_high is None:
        return None, "NVDA fixture missing current_price or price_target.bull_high"
    if not bull_high > cp:
        return False, f"NVDA bull_high {bull_high} not > current_price {cp}"
    return True, None


# ── Phase B: baseline contract checks ───────────────────────────────────────

# Required keys and expected types for the §5.1 baseline shape.
# Value is (type_or_tuple_of_types, required=True|False).
_BASELINE_CONTRACT: dict[str, tuple] = {
    "ticker":        (str,   True),
    "company_name":  (str,   True),
    "current_price": (float, True),
    "shares_out":    ((float, type(None)), True),
    "market_cap":    ((float, type(None)), True),
    "net_debt":      ((float, type(None)), True),
    "currency":      (str,   True),
    "fy_revenue":    ((float, type(None)), True),
    "fy_revenue_yoy":((float, type(None)), True),
    "fy_gross_margin":((float, type(None)), True),
    "fy_op_margin":  ((float, type(None)), True),
    "fy_net_income": ((float, type(None)), True),
    "fy_eps_non_gaap":((float, type(None)), True),
    "fy_fcf":        ((float, type(None)), True),
    "fy_fcf_margin": ((float, type(None)), True),
    "fy_sbc":        ((float, type(None)), True),
    "fy_contract_assets":    ((float, type(None)), True),
    "prior_contract_assets": ((float, type(None)), True),
    "fy_software_revenue":   ((float, type(None)), True),
    "fy_dso":        ((float, type(None)), True),
    "prior_dso":     ((float, type(None)), True),
    "fy_ocf":        ((float, type(None)), True),
    "fy_net_income_gaap":    ((float, type(None)), True),
    "tax_rate_guidance":     (float, True),
    "beta":          (float, True),
    "fwd_pe":        ((float, type(None)), True),
    "trailing_pe":   ((float, type(None)), True),
    "peg":           ((float, type(None)), True),
    "consensus_eps_fy1":     ((dict, type(None)), True),
    "consensus_eps_fy2":     ((dict, type(None)), True),
    "consensus_eps_fy3":     ((dict, type(None)), True),
    "consensus_revenue_fy1": ((dict, type(None)), True),
    "consensus_revenue_fy2": ((dict, type(None)), True),
    "consensus_price_target":((dict, type(None)), True),
    "n_analysts":            ((int, type(None)), True),
    "five_yr_eps_growth_est":((float, type(None)), True),
    "segments":      ((list, type(None)), True),
    "history_3y":    (list, True),
    "peer_set":      (list,  True),
    "recent_news":   (list,  True),
    "data_quality_warnings": (list, True),
}


def check_baseline_contract(fixture: dict) -> CheckResult:
    """Phase B: baseline dict contains all required keys with correct types."""
    baseline = fixture.get("baseline")
    if baseline is None:
        return None, "no baseline key (Phase B not landed)"
    if "error" in baseline:
        return False, f"baseline has error field: {baseline['error']}"
    missing = []
    wrong_type = []
    for key, (expected_type, required) in _BASELINE_CONTRACT.items():
        if key not in baseline:
            if required:
                missing.append(key)
        else:
            val = baseline[key]
            if not isinstance(val, expected_type):
                wrong_type.append(f"{key}={type(val).__name__} (expected {expected_type})")
    if missing:
        return False, f"baseline missing required keys: {missing}"
    if wrong_type:
        return False, f"baseline type mismatches: {wrong_type}"
    return True, None


def check_baseline_no_crash(fixture: dict) -> CheckResult:
    """Phase B: baseline.current_price is a positive float (pipeline didn't crash)."""
    baseline = fixture.get("baseline")
    if baseline is None:
        return None, "no baseline key (Phase B not landed)"
    price = baseline.get("current_price")
    if price is None or not isinstance(price, (int, float)) or price <= 0:
        return False, f"baseline.current_price={price!r} (must be positive float)"
    return True, None


GENERIC_CHECKS: list[tuple[str, Check]] = [
    ("pipeline_runs",       check_pipeline_runs),
    ("baseline_contract",   check_baseline_contract),
    ("baseline_no_crash",   check_baseline_no_crash),
    ("joint_probs_sum",     check_joint_probs_sum),
    ("word_count",          check_word_count),
    ("forbidden_tokens",    check_forbidden_tokens),
    ("reverse_dcf",         check_reverse_dcf),
]


# ── Runner ──────────────────────────────────────────────────────────────────

def run() -> int:
    passed = 0
    failed: list[str] = []
    skipped = 0
    missing_fixtures: list[str] = []

    for ticker in VERIFICATION_TICKERS:
        fixture = load_fixture(ticker)
        if fixture is None:
            missing_fixtures.append(ticker)
            continue

        for name, check in GENERIC_CHECKS:
            try:
                ok, msg = check(fixture)
            except Exception as e:
                failed.append(f"{ticker}.{name}: raised {type(e).__name__}: {e}")
                continue
            if ok is None:
                skipped += 1
            elif ok:
                passed += 1
            else:
                failed.append(f"{ticker}.{name}: {msg}")

        ok, msg = check_nvda_bull_above_current(fixture, ticker)
        if ok is None:
            skipped += 1 if msg else 0
        elif ok:
            passed += 1
        else:
            failed.append(f"{ticker}.nvda_bull_above_current: {msg}")

    if missing_fixtures:
        print(f"Smoke harness: no fixtures for {missing_fixtures} "
              f"(expected — fixtures land per phase under tests/fixtures/).")
    print(f"Smoke harness: {passed} passed, {len(failed)} failed, {skipped} skipped.")

    if failed:
        print("\nFAILURES:")
        for f in failed:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
