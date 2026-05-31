"""
Stage 4 — Live end-to-end pipeline test, NVDA, layer-by-layer.

Usage:
    python stage4_nvda_test.py --layer 1   # fetch + calc_baseline
    python stage4_nvda_test.py --layer 2   # run_pass1_foundation  (LLM)
    python stage4_nvda_test.py --layer 3   # fetch_peer_metrics + run_methodology_math
    python stage4_nvda_test.py --layer 4   # run_pass2_report      (LLM)
    python stage4_nvda_test.py --layer 5   # run_pass3_audit       (LLM) + final summary

METHODOLOGY_VERSION stays v1.  No v1 code is touched.  No flag is flipped.
State is persisted in stage4_state_nvda/ between layers.
"""

import argparse
import json
import sys
from pathlib import Path

TICKER = "NVDA"
STATE_DIR = Path(__file__).parent / "stage4_state_nvda"
STATE_DIR.mkdir(exist_ok=True)


# ── State helpers ─────────────────────────────────────────────────────────────

def _save(name: str, obj: dict) -> None:
    p = STATE_DIR / f"{name}.json"
    with open(p, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  [saved → {p.name}]")


def _load(name: str) -> dict:
    p = STATE_DIR / f"{name}.json"
    if not p.exists():
        sys.exit(f"ERROR: {p} not found — run the preceding layer first.")
    with open(p) as f:
        return json.load(f)


def _hr(label: str = "") -> None:
    print("\n" + "=" * 60 + (f"  {label}" if label else ""))


# ── Layer 1: fetch_full + fetch_consensus_pack + calc_baseline ────────────────

def layer1() -> None:
    from fmp_api import fetch_full, fetch_consensus_pack
    from compute import calc_baseline

    _hr(f"LAYER 1 — calc_baseline({TICKER})")

    print(f"  Fetching full data for {TICKER}…")
    data = fetch_full(TICKER)
    if data.get("error"):
        sys.exit(f"  fetch_full error: {data['error']}")

    print(f"  Fetching consensus pack for {TICKER}…")
    consensus = fetch_consensus_pack(TICKER)

    print(f"  Building baseline…")
    baseline = calc_baseline(data, consensus_pack=consensus)

    _hr("LAYER 1 OUTPUT")
    print(f"  current_price:         {baseline.get('current_price')}")
    print(f"  consensus_eps_fy2:     {baseline.get('consensus_eps_fy2')}")
    print(f"  fy_eps_non_gaap:       {baseline.get('fy_eps_non_gaap')}")
    print(f"  peer_set length:       {len(baseline.get('peer_set', []))}")
    dqw = baseline.get("data_quality_warnings", [])
    print(f"  data_quality_warnings: ({len(dqw)} entries)")
    for w in dqw:
        print(f"    • {w}")

    _save("layer1_baseline", baseline)


# ── Layer 2: run_pass1_foundation ─────────────────────────────────────────────

def layer2() -> None:
    from ai import run_pass1_foundation

    baseline = _load("layer1_baseline")

    _hr(f"LAYER 2 — run_pass1_foundation({TICKER}, baseline)  [LLM]")

    pass1 = run_pass1_foundation(TICKER, baseline)

    _hr("LAYER 2 OUTPUT")

    pgd = pass1.get("primary_growth_driver")
    print(f"  primary_growth_driver: {pgd}")

    pse = pass1.get("peer_set_enriched", [])
    peer_tickers = [p.get("ticker") for p in pse if isinstance(p, dict)]
    print(f"  peer_set_enriched tickers: {peer_tickers}")

    events = pass1.get("events", [])
    print(f"  events count: {len(events)}")

    pe_anchors = pass1.get("pe_anchors") or {}
    bull_anchor = pe_anchors.get("bull") or {}
    bull_reasoning = bull_anchor.get("reasoning", "")
    print(f"  pe_anchors.bull.reasoning[:100]: {bull_reasoning[:100]!r}")

    mds = pass1.get("macro_drivers", {})
    if isinstance(mds, dict):
        ids = set(mds.keys())
        print(f"  macro_drivers: dict format, keys={sorted(ids)}, A/B/C ✓={ids == {'A','B','C'}}")
    else:
        ids = {d.get("id") for d in mds if isinstance(d, dict)}
        print(f"  macro_drivers: list format, ids={sorted(ids)}, A/B/C ✓={ids == {'A','B','C'}}")

    _save("layer2_pass1", pass1)


# ── Layer 3: fetch_peer_metrics + run_methodology_math ───────────────────────

def layer3() -> None:
    from fmp_api import fetch_peer_metrics
    from run_methodology_math import run_methodology_math

    baseline = _load("layer1_baseline")
    pass1 = _load("layer2_pass1")

    pse = pass1.get("peer_set_enriched", [])
    peer_tickers = [p["ticker"] for p in pse if isinstance(p, dict) and p.get("ticker")]

    _hr(f"LAYER 3a — fetch_peer_metrics({peer_tickers})")
    peer_metrics = fetch_peer_metrics(peer_tickers)
    for pm in peer_metrics:
        print(f"  {pm}")

    # Merge into baseline (same logic as run_pipeline in ai.py)
    baseline["peer_set"] = peer_metrics
    _save("layer3_baseline_with_peers", baseline)

    _hr("LAYER 3b — run_methodology_math(pass1, baseline_with_peers)  [deterministic]")
    math = run_methodology_math(pass1, baseline)

    _hr("LAYER 3 OUTPUT")
    se = math.get("scenario_eps", {})
    pt = math.get("price_target", {})
    jp = math.get("joint_probs", {})
    print(f"  scenarios.bull.eps:     {se.get('bull')}")
    print(f"  scenarios.bull.price_high: {pt.get('bull_high')}")
    print(f"  scenarios.base.eps:     {se.get('base')}")
    print(f"  scenarios.bear.eps:     {se.get('bear')}")
    jp_vals = list(jp.values())
    jp_sum = sum(jp_vals) if jp_vals else 0.0
    print(f"  joint_probs:            bull={jp.get('bull', 0):.3f}  base={jp.get('base', 0):.3f}  bear={jp.get('bear', 0):.3f}")
    print(f"  joint_probs sum:        {jp_sum:.6f}")
    print(f"  expected_value:         {math.get('expected_value')}")
    print(f"  consensus_divergent:    {math.get('consensus_divergent')}")
    cal = math.get("calibration_log", [])
    print(f"  calibration_log: ({len(cal)} entries)")
    for entry in cal:
        print(f"    • {entry}")

    _save("layer3_math", math)


# ── Layer 4: run_pass2_report ─────────────────────────────────────────────────

def layer4() -> None:
    from ai import run_pass2_report, _build_pass2_body

    baseline = _load("layer3_baseline_with_peers")
    pass1 = _load("layer2_pass1")
    math = _load("layer3_math")

    _hr(f"LAYER 4 — run_pass2_report({TICKER}, ...)  [LLM]")
    pass2 = run_pass2_report(TICKER, baseline, pass1, math)

    _hr("LAYER 4 OUTPUT")

    body = _build_pass2_body(pass2)
    wc = len(body.split())
    budget_flag = "OK" if wc <= 4500 else "OVER BUDGET"
    print(f"  word_count: {wc}  [{budget_flag}]")

    # 4 hard-required sections
    HARD = ("investment_thesis", "reverse_dcf_commentary",
            "recommendation_rationale", "conclusion")
    sc = pass2.get("scenario_commentary") or {}
    dn = pass2.get("driver_narratives") or {}

    print(f"\n  Sections present:")
    for k in HARD:
        status = "PRESENT" if pass2.get(k) else "MISSING ✗"
        print(f"    [hard] {k}: {status}")
    for k in ("bull", "base", "bear"):
        status = "PRESENT" if sc.get(k) else "MISSING"
        print(f"    [soft] scenario_commentary.{k}: {status}")
    for k in ("A", "B", "C"):
        status = "PRESENT" if dn.get(k) else "MISSING"
        print(f"    [soft] driver_narratives.{k}: {status}")
    fh_status = "PRESENT" if pass2.get("financial_health") else "MISSING"
    print(f"    [soft] financial_health: {fh_status}")

    sc_bull = sc.get("bull", "")
    print(f"\n  scenario_commentary.bull[:200]:\n    {sc_bull[:200]!r}")

    _save("layer4_pass2", pass2)


# ── Layer 5: run_pass3_audit + final summary ──────────────────────────────────

def layer5() -> None:
    from ai import run_pass3_audit, _build_pass2_body

    baseline = _load("layer3_baseline_with_peers")
    pass1 = _load("layer2_pass1")
    math = _load("layer3_math")
    pass2 = _load("layer4_pass2")

    _hr(f"LAYER 5 — run_pass3_audit({TICKER}, ...)  [LLM]")
    pass3 = run_pass3_audit(TICKER, baseline, pass1, math, pass2)

    _hr("LAYER 5 OUTPUT")

    fv = pass3.get("forbidden_vocab", [])
    print(f"  forbidden_vocab flags: ({len(fv)})")
    for flag in fv:
        print(f"    • {flag}")

    ce = pass3.get("citation_errors", [])
    print(f"  citation_errors: ({len(ce)})")
    for err in ce:
        print(f"    • {err}")

    print(f"  audit_clean:   {pass3.get('audit_clean')}")
    print(f"  b1_compliant:  {pass3.get('b1_compliant')}")
    print(f"  tone_label_ok: {pass3.get('tone_label_ok')}")
    print(f"  audit_skipped: {pass3.get('audit_skipped')}")

    body = _build_pass2_body(pass2)
    wc = len(body.split())
    over_budget = wc > 4500
    print(f"  over_word_budget: {over_budget}  ({wc} words)")

    # Full flags list (all boolean/list audit fields)
    _hr("FULL FLAGS")
    for k, v in pass3.items():
        if k not in ("model_used",):
            print(f"  {k}: {v}")

    _save("layer5_pass3", pass3)

    # ── Final summary ─────────────────────────────────────────────────────────
    current_price = baseline.get("current_price", "?")
    bull_high = math.get("price_target", {}).get("bull_high", "?")
    consensus_divergent = math.get("consensus_divergent", "?")
    f1_fix_ok = (consensus_divergent is False)

    import subprocess, sys as _sys
    result = subprocess.run(
        [_sys.executable, "-m", "pytest", "tests_methodology.py", "-q", "--tb=no"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent)
    )
    pytest_line = [l for l in result.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l]
    pytest_summary = pytest_line[-1] if pytest_line else result.stdout.strip()[-80:]

    _hr("FINAL SUMMARY")
    results = {
        "Layer 1 (baseline)":  "PASS" if baseline.get("current_price") else "FAIL",
        "Layer 2 (pass1)":     "PASS" if pass1.get("macro_drivers") else "FAIL",
        "Layer 3 (math)":      "PASS" if math.get("scenario_eps") else "FAIL",
        "Layer 4 (pass2)":     "PASS" if pass2.get("investment_thesis") else "FAIL",
        "Layer 5 (pass3)":     "PASS" if not pass3.get("audit_skipped") else "SKIPPED",
    }
    for layer, result_label in results.items():
        print(f"  {layer}: {result_label}")

    print(f"\n  NVDA current_price:      ${current_price}")
    print(f"  bull price_high:         ${bull_high}")
    bull_above = (
        isinstance(bull_high, (int, float)) and isinstance(current_price, (int, float))
        and bull_high > current_price
    )
    print(f"  bull_high > current:     {bull_above}")
    print(f"  consensus_divergent:     {consensus_divergent}")
    print(f"  consensus_divergent=False (F1 fix OK): {f1_fix_ok}")
    print(f"\n  pytest: {pytest_summary}")


# ── Entry point ───────────────────────────────────────────────────────────────

LAYERS = {1: layer1, 2: layer2, 3: layer3, 4: layer4, 5: layer5}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage 4 layer-by-layer pipeline test (NVDA)")
    ap.add_argument("--layer", type=int, required=True, choices=[1, 2, 3, 4, 5],
                    help="Which layer to run (1–5)")
    args = ap.parse_args()
    LAYERS[args.layer]()
