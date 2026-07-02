"""
Phase 3 live-validation harness (billable — makes real LLM pipeline calls).

Usage: python3 _live_validate.py TICKER
Loads .streamlit/secrets.toml into the env, runs the real pipeline, captures the
exact pass1/math the pipeline used, and writes _live_out_<TICKER>.json for the
deterministic + narrative checks. Does NOT bless any golden.
"""
import os, sys, json, re, traceback
from datetime import datetime, timezone

# ── Load secrets.toml into env BEFORE importing config/ai ────────────────────
for line in open(".streamlit/secrets.toml"):
    m = re.match(r'^\s*([A-Za-z_]+)\s*=\s*"(.*)"\s*$', line)
    if m:
        os.environ.setdefault(m.group(1), m.group(2))

ticker = sys.argv[1] if len(sys.argv) > 1 else "CLS"

import ai, fmp_api
from compute import calc_baseline
from run_methodology_math import run_methodology_math

# ── Capture the exact pass1 / math / baseline the pipeline used ──────────────
cap = {}
_orig = ai._assemble_pipeline_output
def _capture(tk, baseline, pass1, math, pass2, pass3_raw, bull_below):
    cap["pass1"] = pass1
    cap["math"] = math
    cap["baseline"] = baseline
    cap["pass2"] = pass2
    cap["bull_below"] = bull_below
    return _orig(tk, baseline, pass1, math, pass2, pass3_raw, bull_below)
ai._assemble_pipeline_output = _capture

out = {"ticker": ticker}
ai.reset_call_log()   # capture stop_reason/usage/raw text for EVERY LLM call
try:
    sd = fmp_api.fetch_full(ticker)
    cp = fmp_api.fetch_consensus_pack(ticker)
    baseline = calc_baseline(sd, consensus_pack=cp)
    if "error" in baseline:
        raise RuntimeError(f"baseline error: {baseline['error']}")
    baseline_in = {k: v for k, v in baseline.items() if k not in ("recent_news", "history_3y")}
    a = ai.run_pipeline(ticker, baseline_in)
    out["report"] = a
    out["captured_pass1"] = cap.get("pass1")
    out["captured_math"] = cap.get("math")
    out["captured_baseline"] = cap.get("baseline")
    # Independent offline re-run of the deterministic engine on the SAME inputs
    if cap.get("pass1") is not None and cap.get("baseline") is not None:
        out["offline_math"] = run_methodology_math(cap["pass1"], cap["baseline"])
    out["ok"] = not (isinstance(a, dict) and a.get("error"))
except Exception as e:
    out["ok"] = False
    out["exception"] = f"{type(e).__name__}: {e}"
    out["traceback"] = traceback.format_exc()

# Persist per-call telemetry (stop_reason, output_tokens, truncated, raw text for
# EVERY call incl. both Pass 2 attempts) so absent-vs-empty-key and truncation are
# inspectable without another live run.
out["call_log"] = ai.get_call_log()

# Timestamped filename so repeated runs of the same ticker no longer overwrite
# each other — future recommendation swings stay diffable.
_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
_fname = f"_live_out_{ticker}_{_ts}.json"
json.dump(out, open(_fname, "w"), indent=2, default=str)
print("OK" if out.get("ok") else "FAIL", "->", _fname)
if out.get("exception"):
    print(out["exception"])
