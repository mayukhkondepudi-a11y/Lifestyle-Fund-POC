"""
Phase B validation: run calc_baseline on 5 tickers and check §5.1 contract shape.

Usage: python validate_phase_b.py [--save]  (--save writes fixtures to tests/fixtures/)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TICKERS = ["AVGO", "KO", "ASML", "NVDA", "ADBE"]   # ADBE as the "small/mid" tech stand-in

REQUIRED_KEYS = [
    "ticker", "company_name", "current_price", "shares_out", "market_cap",
    "net_debt", "currency", "fy_revenue", "fy_revenue_yoy", "fy_gross_margin",
    "fy_op_margin", "fy_net_income", "fy_eps_non_gaap", "fy_fcf",
    "fy_fcf_margin", "fy_sbc", "fy_contract_assets", "prior_contract_assets",
    "fy_software_revenue", "fy_dso", "prior_dso", "fy_ocf", "fy_net_income_gaap",
    "tax_rate_guidance", "beta", "fwd_pe", "trailing_pe", "peg",
    "consensus_eps_fy1", "consensus_eps_fy2", "consensus_eps_fy3",
    "consensus_revenue_fy1", "consensus_revenue_fy2",
    "consensus_price_target", "n_analysts",
    "five_yr_eps_growth_est", "segments", "history_3y", "peer_set",
    "recent_news", "data_quality_warnings",
]

OPTIONAL_KEYS = {
    "fy_sbc", "fy_contract_assets", "prior_contract_assets",
    "fy_software_revenue", "fy_dso", "prior_dso",
    "consensus_eps_fy1", "consensus_eps_fy2", "consensus_eps_fy3",
    "consensus_revenue_fy1", "consensus_revenue_fy2",
    "consensus_price_target", "n_analysts", "five_yr_eps_growth_est", "segments",
    "fwd_pe", "trailing_pe", "peg", "net_debt", "shares_out", "market_cap",
    "fy_revenue", "fy_revenue_yoy", "fy_gross_margin", "fy_op_margin",
    "fy_net_income", "fy_eps_non_gaap", "fy_fcf", "fy_fcf_margin",
    "fy_ocf", "fy_net_income_gaap",
}


def check_contract(ticker, baseline):
    errors = []
    if "error" in baseline:
        errors.append(f"  ERROR field present: {baseline['error']}")
        return errors

    for k in REQUIRED_KEYS:
        if k not in baseline:
            errors.append(f"  MISSING key: {k}")

    # current_price must be positive
    cp = baseline.get("current_price")
    if cp is None or not isinstance(cp, (int, float)) or cp <= 0:
        errors.append(f"  BAD current_price: {cp!r}")

    # data_quality_warnings must be a list
    dqw = baseline.get("data_quality_warnings")
    if not isinstance(dqw, list):
        errors.append(f"  data_quality_warnings must be list, got {type(dqw)}")

    # consensus dicts must have low/mid/high if present
    for ck in ("consensus_eps_fy1", "consensus_eps_fy2", "consensus_eps_fy3",
               "consensus_revenue_fy1", "consensus_revenue_fy2"):
        val = baseline.get(ck)
        if val is not None:
            if not isinstance(val, dict) or "mid" not in val:
                errors.append(f"  {ck} must be dict with 'mid', got: {val!r}")

    return errors


def run(save_fixtures=False):
    from fmp_api import fetch_full, fetch_consensus_pack
    from compute import calc_baseline

    fixture_dir = Path("tests/fixtures")
    if save_fixtures:
        fixture_dir.mkdir(parents=True, exist_ok=True)

    all_ok = True
    for ticker in TICKERS:
        print(f"\n{'='*60}")
        print(f"  {ticker}")
        print(f"{'='*60}")
        try:
            data = fetch_full(ticker)
            if data is None:
                print(f"  FAIL: fetch_full returned None")
                all_ok = False
                continue

            consensus = fetch_consensus_pack(ticker)
            baseline  = calc_baseline(data, consensus_pack=consensus)

            errors = check_contract(ticker, baseline)
            if errors:
                print(f"  CONTRACT VIOLATIONS:")
                for e in errors:
                    print(e)
                all_ok = False
            else:
                print(f"  Contract: OK")

            # Print key populated fields
            print(f"  company:        {baseline.get('company_name')}")
            print(f"  price:          {baseline.get('current_price')}")
            print(f"  fy_revenue:     {baseline.get('fy_revenue')}")
            print(f"  fy_eps:         {baseline.get('fy_eps_non_gaap')}")
            print(f"  fy_fcf:         {baseline.get('fy_fcf')}")
            print(f"  consensus_fy2:  {baseline.get('consensus_eps_fy2')}")
            print(f"  peer_set:       {len(baseline.get('peer_set', []))} peers")
            print(f"  history_3y:     {len(baseline.get('history_3y', []))} years")
            print(f"  warnings:       {baseline.get('data_quality_warnings')}")

            if save_fixtures:
                fixture = {"baseline": baseline}
                path = fixture_dir / f"{ticker}_pipeline.json"
                path.write_text(json.dumps(fixture, indent=2, default=str))
                print(f"  Fixture saved: {path}")

        except Exception as exc:
            import traceback
            print(f"  EXCEPTION: {exc}")
            traceback.print_exc()
            all_ok = False

    print(f"\n{'='*60}")
    print(f"Phase B validation: {'PASSED' if all_ok else 'FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    save = "--save" in sys.argv
    sys.exit(run(save_fixtures=save))
