"""AI orchestration: Anthropic primary, OpenRouter fallback. Three-pass + compute architecture."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from openai import OpenAI
import anthropic
from compute import clean_latex

from config import (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, FREE_MODELS,
                    FREE_MODELS_EXTENDED)
from formatting import safe_float, fmt_c, fmt_n, fmt_p
from compute import (
    compute_scenario_math,
    compute_scenarios_from_drivers,
    derive_recommendation,
    compute_fundamentals_diagnostic,
    validate_pass1_inputs,
    _compute_pe_ranges_per_scenario,
    MAX_PIPELINE_AI_CALLS,
)


# ── Clients ──────────────────────────────────────────────────

_or_client = OpenAI(base_url="https://openrouter.ai/api/v1",
                     api_key=OPENROUTER_API_KEY) if OPENROUTER_API_KEY else None
_an_client = (anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
              if ANTHROPIC_API_KEY else None)


# ── Prompts ──────────────────────────────────────────────────

def _load_prompt(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

SYSTEM_PROMPT = _load_prompt("prompt_system.txt")
PASS1_PROMPT  = _load_prompt("prompt_pass1.txt")
PASS2_PROMPT  = _load_prompt("prompt_pass2.txt")
PASS3_PROMPT  = _load_prompt("prompt_pass3.txt")


# ══════════════════════════════════════════════════════════════
# AI RUNNER (single canonical implementation)
# ══════════════════════════════════════════════════════════════

def run_ai(messages, max_tokens=4000, model="claude-opus-4-7",
           free_models=None):
    """Try Anthropic first, then fall back to OpenRouter free models."""
    if free_models is None:
        free_models = FREE_MODELS

    if _an_client:
        try:
            system_msg = ""
            user_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)
            r = _an_client.messages.create(
                model=model, system=system_msg, messages=user_msgs,
                max_tokens=max_tokens,
            )
            text = r.content[0].text.strip()
            print(f"  AI response via {model} ({len(text)} chars)")
            return text, model, None
        except Exception as e:
            err = f"Claude: {str(e)[:120]}"
    else:
        err = "Claude: No API key configured"

    errors = [err]
    for fm in free_models:
        try:
            r = _or_client.chat.completions.create(
                model=fm, messages=messages, max_tokens=max_tokens,
                extra_headers={"HTTP-Referer": "https://pickr.streamlit.app",
                                "X-Title": "PickR"},
            )
            text = r.choices[0].message.content.strip()
            print(f"  AI response via {fm} ({len(text)} chars)")
            return text, fm, None
        except Exception as e:
            errors.append(f"{fm}: {str(e)[:120]}")
            time.sleep(3)
    return None, None, errors


# ══════════════════════════════════════════════════════════════
# JSON PARSER (single canonical implementation)
# ══════════════════════════════════════════════════════════════

def parse_json_response(raw, model="unknown"):
    """Parse JSON from LLM response with repair attempts."""
    if not raw:
        return None, "Empty response"
    try:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

        try:
            a = json.loads(raw)
            a["model_used"] = model
            return a, None
        except json.JSONDecodeError:
            pass

        # Repair truncated JSON
        last_brace = raw.rfind("}")
        if last_brace > len(raw) * 0.5:
            attempt = raw[:last_brace + 1]
            if attempt.count('"') % 2 != 0:
                attempt += '"'
            attempt += "]" * (attempt.count("[") - attempt.count("]"))
            attempt += "}" * (attempt.count("{") - attempt.count("}"))
            try:
                a = json.loads(attempt)
                a["model_used"] = model
                return a, None
            except json.JSONDecodeError:
                pass

        # Progressive truncation
        for i in range(len(raw) - 1, len(raw) // 2, -1):
            if raw[i] == '"' and (i == 0 or raw[i-1] != '\\'):
                attempt = raw[:i+1]
                attempt += "]" * (attempt.count("[") - attempt.count("]"))
                attempt += "}" * (attempt.count("{") - attempt.count("}"))
                try:
                    a = json.loads(attempt)
                    a["model_used"] = model
                    return a, None
                except json.JSONDecodeError:
                    continue

        return None, f"{model}: Bad JSON - could not repair | Raw: {raw[:300]}"
    except Exception as e:
        return None, f"{model}: Parse error - {str(e)[:100]}"


# ══════════════════════════════════════════════════════════════
# PASS 1: STRUCTURED ASSUMPTIONS
# ══════════════════════════════════════════════════════════════

def run_pass1(ticker, m, pe_ranges, extra_context=None):
    """Pass 1: Get structured driver inputs from LLM."""
    msgs = _build_pass1_messages(ticker, m, pe_ranges, extra_context=extra_context)
    raw, model, errors = run_ai(msgs, max_tokens=3500)
    if raw is None:
        return None, errors or ["run_ai returned None"]
    a, err = parse_json_response(raw, model)
    if err:
        return None, [err]

    # Defaults for optional fields
    a.setdefault("segments", [])
    a.setdefault("competitive_context", {})
    a.setdefault("concentration", {})
    a.setdefault("peer_tickers", [])

    return a, []


def run_pass1_with_retry(ticker, m, pe_ranges, max_retries=1, extra_context=None):
    """
    Run pass 1 with schema validation and up to `max_retries` retry attempts.
    Returns (validated_pass1_or_None, list_of_errors).
    Soft-clamps importance > 0.5 in-place (not a retry trigger).
    """
    pass1, errors = run_pass1(ticker, m, pe_ranges, extra_context=extra_context)
    if pass1 is None:
        return None, errors

    ok, val_errors = validate_pass1_inputs(pass1, m, pe_ranges)
    if ok:
        return pass1, []

    print(f"  Pass1 validation failed ({len(val_errors)} errors): {val_errors[:3]}")
    if max_retries <= 0:
        return None, val_errors

    # Retry once with the error list embedded
    retry_context = (
        "Your previous response failed validation with these errors:\n"
        + "\n".join(f"- {e}" for e in val_errors)
        + "\n\nRe-emit corrected JSON addressing all errors above."
    )
    pass1_retry, errors2 = run_pass1(
        ticker, m, pe_ranges,
        extra_context=(extra_context or "") + "\n" + retry_context
    )
    if pass1_retry is None:
        return None, errors2

    ok2, val_errors2 = validate_pass1_inputs(pass1_retry, m, pe_ranges)
    if ok2:
        return pass1_retry, []

    print(f"  Pass1 retry also failed ({len(val_errors2)} errors); proceeding DEGRADED")
    return pass1_retry, val_errors2


def _build_pass1_messages(ticker, m, pe_ranges, extra_context=None):
    # NOTE: news and latest_quarter are intentionally INCLUDED — see {recent_news_json}
    # and {latest_quarter_json} below. They ground pass1 baselines in current filings.
    exclude_keys = {"description", "news", "revenue_history", "net_income_history",
                    "multi_year_financials", "stmt_eps_series", "capex_3y",
                    "sbc_3y", "shares_outstanding_3y"}
    ms = json.dumps(
        {k: v for k, v in m.items() if k not in exclude_keys},
        indent=2, default=str)
    description_snippet = (m.get("description") or "N/A")[:800]

    peer_metrics = m.get("peer_metrics", [])
    reverse_dcf  = m.get("reverse_dcf", {"available": False})

    # Latest reported quarter (from quarterly income statement) — anchors forward baselines
    latest_quarter = m.get("latest_quarter") or {}

    # Analyst forward consensus — HARD constraint floor for scenario revenues
    analyst_consensus = m.get("analyst_consensus") or {}

    # Recent news headlines (last 90 days where timestamp is available)
    import time
    cutoff_ts = time.time() - (90 * 86400)
    raw_news  = m.get("news") or []
    news_summary = []
    for n in raw_news[:8]:
        ts = n.get("providerPublishTime") or n.get("provider_publish_time")
        if ts and isinstance(ts, (int, float)) and ts < cutoff_ts:
            continue  # older than 90 days
        news_summary.append({
            "title":     n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "ts":        ts,
        })

    def _fmt_band(band):
        if not band:
            return "unavailable"
        return (f"min={band['min']:.4f}, max={band['max']:.4f}, "
                f"median={band['median']:.4f} (n={band.get('n',0)})")

    def _fmt_pe_range(r):
        if not r or len(r) < 2:
            return "unavailable"
        return f"[{r[0]:.1f}, {r[1]:.1f}]"

    user_prompt = PASS1_PROMPT
    replacements = {
        "{ticker}":          ticker,
        "{company_name}":    m.get("company_name", ticker),
        "{metrics_json}":    ms,
        "{peer_metrics}":    json.dumps(peer_metrics, indent=2, default=str),
        "{reverse_dcf}":     json.dumps(reverse_dcf, indent=2, default=str),
        "{description}":     description_snippet,
        "{today_date}":      datetime.now().strftime("%B %d, %Y"),
        "{total_revenue}":   fmt_c(m.get("total_revenue"), m.get("currency", "USD")),
        "{current_price}":   str(m.get("current_price")),
        "{shares_outstanding}": str(m.get("shares_outstanding")),
        "{op_margin_band}":  _fmt_band(m.get("op_margin_5y_band")),
        "{tax_rate_band}":   _fmt_band(m.get("tax_rate_3y_band")),
        "{pe_range_bull}":   _fmt_pe_range(pe_ranges.get("bull") if pe_ranges else None),
        "{pe_range_base}":   _fmt_pe_range(pe_ranges.get("base") if pe_ranges else None),
        "{pe_range_bear}":   _fmt_pe_range(pe_ranges.get("bear") if pe_ranges else None),
        "{latest_quarter_json}":    json.dumps(latest_quarter, indent=2, default=str),
        "{recent_news_json}":       json.dumps(news_summary, indent=2, default=str),
        "{analyst_consensus_json}": json.dumps(analyst_consensus, indent=2, default=str),
    }
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, str(val))

    if extra_context:
        user_prompt = extra_context.strip() + "\n\n" + user_prompt

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]


def run_pass2(ticker, m, pass1_output, python_outputs, retry=False):
    """Pass 2: Get narrative from LLM. python_outputs contains all computed numbers."""
    msgs = _build_pass2_messages(ticker, m, pass1_output, python_outputs, retry=retry)
    raw, model, errors = run_ai(msgs, max_tokens=7000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    # Clean LaTeX from all string fields
    for key, val in a.items():
        if isinstance(val, str):
            a[key] = clean_latex(val)
        elif isinstance(val, dict):
            a[key] = {k2: clean_latex(v2) if isinstance(v2, str) else v2
                      for k2, v2 in val.items()}

    # Defaults
    defaults = {
        "investment_thesis": "Analysis not available.",
        "business_overview": "Analysis not available.",
        "revenue_architecture": "Analysis not available.",
        "growth_drivers": "Analysis not available.",
        "margin_analysis": "Analysis not available.",
        "financial_health": "Analysis not available.",
        "competitive_position": "Analysis not available.",
        "driver_narratives": {},
        "scenario_commentary": {"bull": "", "base": "", "bear": ""},
        "reverse_dcf_commentary": "",
        "monitoring_dashboard_intro": "",
        "catalysts_intro": "",
        "recommendation_rationale": "",
        "conclusion": "Analysis not available.",
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v
    a["model_used"] = model
    return a


# ══════════════════════════════════════════════════════════════
# PASS 2: NARRATIVE
# ══════════════════════════════════════════════════════════════

def _build_pass2_messages(ticker, m, pass1_output, python_outputs, retry=False):
    description_snippet = (m.get("description") or "N/A")[:800]

    probs  = python_outputs.get("final_probabilities", {})
    pt     = python_outputs.get("price_target", {})
    eps    = python_outputs.get("eps", {})
    si     = pass1_output.get("scenario_inputs", {})
    rev    = python_outputs.get("scenario_revenue", {})
    rdcf   = m.get("reverse_dcf", {})

    rec        = python_outputs.get("recommendation", "WATCH")
    conviction = python_outputs.get("conviction", "Medium")
    flags      = {
        "monotonicity_violation": python_outputs.get("monotonicity_violation", False),
        "divergence_flag":        python_outputs.get("diagnostic", {}).get("divergence_flag", False),
        "degraded_sections":      python_outputs.get("degraded_sections", []),
    }

    math_block = {
        "expected_value":        python_outputs.get("expected_value"),
        "expected_return_pct":   f"{python_outputs.get('expected_return', 0)*100:.1f}%",
        "base_implied_return_pct": f"{python_outputs.get('base_implied_return', 0)*100:.1f}%",
        "prob_positive_pct":     f"{python_outputs.get('prob_positive', 0)*100:.0f}%",
        "upside_downside_ratio": python_outputs.get("upside_downside_ratio"),
        "future_shares":         python_outputs.get("future_shares"),
        "implied_fcf_cagr":      rdcf.get("implied_fcf_cagr"),
    }

    # Focused financial-health block — exact field names the financial_health prompt cites
    financial_metrics = {
        "sbc_ttm":             m.get("sbc_ttm"),
        "sbc_to_revenue":      m.get("sbc_to_revenue"),
        "capex_ttm":           m.get("capex_ttm"),
        "capex_to_revenue":    m.get("capex_to_revenue"),
        "dilution_rate_3y":    m.get("dilution_rate_3y"),
        "goodwill":            m.get("goodwill"),
        "goodwill_to_equity":  m.get("goodwill_to_equity"),
        "debt_to_equity":      m.get("debt_to_equity"),
        "free_cashflow":       m.get("free_cashflow"),
        "operating_margin_ttm": m.get("operating_margin"),
        "fcf_yield":           m.get("fcf_yield"),
        "current_ratio":       m.get("current_ratio"),
    }
    for s in ("bull", "base", "bear"):
        math_block[f"{s}_probability_pct"] = f"{probs.get(s, 0)*100:.0f}%"
        math_block[f"{s}_price_target"]    = pt.get(s)
        math_block[f"{s}_eps"]             = round(eps.get(s, 0), 4)
        math_block[f"{s}_revenue"]         = rev.get(s)
        math_block[f"{s}_op_margin_pct"]   = f"{si.get(s, {}).get('op_margin', 0)*100:.1f}%"
        math_block[f"{s}_tax_rate_pct"]    = f"{si.get(s, {}).get('tax_rate', 0)*100:.1f}%"
        math_block[f"{s}_pe"]              = si.get(s, {}).get("pe_multiple_pick")

    user_prompt = PASS2_PROMPT
    replacements = {
        "{ticker}":             ticker,
        "{company_name}":       m.get("company_name", ticker),
        "{description}":        description_snippet,
        "{recommendation}":     rec,
        "{conviction}":         conviction,
        "{pass1_json}":         json.dumps(pass1_output, indent=2, default=str),
        "{python_outputs_json}": json.dumps(math_block, indent=2, default=str),
        "{flags_json}":         json.dumps(flags, indent=2, default=str),
        "{financial_metrics_json}": json.dumps(financial_metrics, indent=2, default=str),
        "{today_date}":         datetime.now().strftime("%B %d, %Y"),
        "{retry_hint}":         (
            "RETRY: Your previous response lacked the required paragraph depth "
            "(≥2 paragraphs in investment_thesis and conclusion). Please expand."
            if retry else ""
        ),
    }
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, str(val))

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]


# ══════════════════════════════════════════════════════════════
# PASS 3: SELF-CHECK
# ══════════════════════════════════════════════════════════════

def run_pass3_selfcheck(ticker, m, pass1_output, python_outputs, pass2_output):
    """Pass 3: Auditor LLM checks pass-2 narrative for consistency. Returns audit dict."""
    msgs = _build_pass3_messages(ticker, m, pass1_output, python_outputs, pass2_output)
    raw, model, errors = run_ai(msgs, max_tokens=1500)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = parse_json_response(raw, model)
    if err:
        return {
            "consistency_flags": [],
            "numbers_outside_source": [],
            "tone_label_mismatch": False,
            "tone_label_evidence": None,
            "parse_error": err,
        }
    a.setdefault("consistency_flags", [])
    a.setdefault("numbers_outside_source", [])
    a.setdefault("tone_label_mismatch", False)
    a.setdefault("tone_label_evidence", None)
    return a


def _build_pass3_messages(ticker, m, pass1_output, python_outputs, pass2_output):
    probs = python_outputs.get("final_probabilities", {})
    pt    = python_outputs.get("price_target", {})
    eps   = python_outputs.get("eps", {})
    rev   = python_outputs.get("scenario_revenue", {})
    si    = pass1_output.get("scenario_inputs", {})
    lq    = m.get("latest_quarter") or {}

    allowed_sources = {
        # Deterministic Python outputs
        "recommendation":        python_outputs.get("recommendation"),
        "conviction":            python_outputs.get("conviction"),
        "expected_value":        python_outputs.get("expected_value"),
        "expected_return":       python_outputs.get("expected_return"),
        "base_implied_return":   python_outputs.get("base_implied_return"),
        "prob_positive":         python_outputs.get("prob_positive"),
        "upside_downside_ratio": python_outputs.get("upside_downside_ratio"),
        "future_shares":         python_outputs.get("future_shares"),
        # Per-scenario probabilities, targets, EPS, revenue
        "bull_probability":      probs.get("bull"),
        "base_probability":      probs.get("base"),
        "bear_probability":      probs.get("bear"),
        "bull_price_target":     pt.get("bull"),
        "base_price_target":     pt.get("base"),
        "bear_price_target":     pt.get("bear"),
        "bull_eps":              eps.get("bull"),
        "base_eps":              eps.get("base"),
        "bear_eps":              eps.get("bear"),
        "bull_revenue":          rev.get("bull"),
        "base_revenue":          rev.get("base"),
        "bear_revenue":          rev.get("bear"),
        # Per-scenario inputs (op margin, P/E, tax rate)
        "bull_op_margin":        si.get("bull", {}).get("op_margin"),
        "base_op_margin":        si.get("base", {}).get("op_margin"),
        "bear_op_margin":        si.get("bear", {}).get("op_margin"),
        "bull_pe_multiple":      si.get("bull", {}).get("pe_multiple_pick"),
        "base_pe_multiple":      si.get("base", {}).get("pe_multiple_pick"),
        "bear_pe_multiple":      si.get("bear", {}).get("pe_multiple_pick"),
        "bull_tax_rate":         si.get("bull", {}).get("tax_rate"),
        "base_tax_rate":         si.get("base", {}).get("tax_rate"),
        "bear_tax_rate":         si.get("bear", {}).get("tax_rate"),
        # Verified company TTM metrics
        "current_price":         m.get("current_price"),
        "total_revenue":         m.get("total_revenue"),
        "operating_margin_ttm":  m.get("operating_margin"),
        "fcf_yield":             m.get("fcf_yield"),
        "free_cashflow":         m.get("free_cashflow"),
        "implied_fcf_cagr":      m.get("reverse_dcf", {}).get("implied_fcf_cagr"),
        # Latest-quarter facts (visible to audit so it doesn't flag legitimate citations)
        "latest_quarter_revenue":   lq.get("revenue"),
        "latest_quarter_op_margin": lq.get("operating_margin"),
        "latest_quarter_period":    lq.get("period_label"),
        "latest_quarter_eps":       lq.get("diluted_eps"),
        "driver_count":             len(pass1_output.get("drivers", [])),
    }

    prompt = PASS3_PROMPT
    replacements = {
        "{ticker}":              ticker,
        "{recommendation}":      python_outputs.get("recommendation", "WATCH"),
        "{pass2_json}":          json.dumps(pass2_output, indent=2, default=str),
        "{allowed_sources_json}": json.dumps(allowed_sources, indent=2, default=str),
        "{pass1_json}":          json.dumps(pass1_output, indent=2, default=str),
    }
    for key, val in replacements.items():
        prompt = prompt.replace(key, str(val))

    return [
        {"role": "system", "content": "You are an internal audit system for equity research reports. Respond only with valid JSON."},
        {"role": "user",   "content": prompt},
    ]


# ══════════════════════════════════════════════════════════════
# TWO-PASS ORCHESTRATOR
# (No @st.cache_data here - app.py wraps with caching)
# ══════════════════════════════════════════════════════════════

def _paragraph_count_check_failed(pass2):
    """Return True if investment_thesis or conclusion lack ≥2 paragraphs."""
    for field in ("investment_thesis", "conclusion"):
        text = pass2.get(field, "")
        if isinstance(text, str) and text.count("\n\n") < 1:
            return True
    return False


def _check_divergence(diagnostic, scenario_math):
    """Flag if any signal-implied prob differs from driver-derived by >15pp."""
    sig = diagnostic.get("signal_implied_probabilities", {})
    drv = scenario_math.get("final_probabilities", {})
    for s in ("bull", "base", "bear"):
        if abs(sig.get(s, 0) - drv.get(s, 0)) > 0.15:
            return True
    return False


def _emit_degraded_report(ticker, m, reason, errors):
    """Return a minimal report dict with a DEGRADED banner when pipeline fails."""
    return {
        "recommendation":   "WATCH",
        "conviction":       "Low",
        "investment_thesis": (
            f"DEGRADED — report unavailable: {reason}.\n\n"
            f"Errors: {'; '.join(str(e) for e in (errors or [])[:3])}"
        ),
        "business_overview": "", "revenue_architecture": "",
        "growth_drivers": "", "margin_analysis": "", "financial_health": "",
        "competitive_position": "", "scenario_commentary": {"bull": "", "base": "", "bear": ""},
        "driver_narratives": {}, "reverse_dcf_commentary": "",
        "monitoring_dashboard_intro": "", "catalysts_intro": "",
        "recommendation_rationale": "Report generation failed.", "conclusion": "",
        "model_used": "N/A",
        "segments": [], "drivers": [], "scenario_inputs": {},
        "monitoring_kpis": [], "catalysts": [], "peer_tickers": [],
        "concentration": {}, "competitive_context": {},
        "scenario_math": {},
        "python_outputs": {"recommendation": "WATCH", "conviction": "Low"},
        "pass3": {},
        "degraded_sections": [reason],
        "data_quality_warnings": [f"DEGRADED:{reason}"] + list(errors or []),
    }


def run_two_pass(ticker, m):
    """
    Three-pass + Python compute orchestration.
    Phase A: pass 1 (inputs JSON) + validation retry
    Phase B: Python compute layer (deterministic math)
    Phase C: pass 2 (narrative)
    Phase D: pass 3 (self-check)
    """
    peer_metrics = m.get("peer_metrics", [])
    pe_ranges    = _compute_pe_ranges_per_scenario(m, peer_metrics)

    # ── Phase A: Pass 1 with retry ────────────────────────────
    pass1, p1_errors = run_pass1_with_retry(ticker, m, pe_ranges, max_retries=1)
    if not pass1:
        return _emit_degraded_report(ticker, m, "pass1_failed", p1_errors)

    degraded_sections = []
    if p1_errors:  # non-empty means second attempt also had issues
        degraded_sections.append("pass1_validation_partial")

    # ── Phase B: Python compute layer ─────────────────────────
    current_price = safe_float(m.get("current_price", 0))
    scenario_math = compute_scenarios_from_drivers(m, pass1, current_price)

    # Consolidated scenario-sanity check: monotonicity + bull-below-current.
    # Single retry that addresses ALL detected issues at once.
    def _sanity_warnings(sm):
        warnings = []
        if sm.get("monotonicity_violation"):
            warnings.append(("monotonicity_violation", sm.get("violation_msg", "")))
        if sm.get("bull_below_current"):
            warnings.append(("bull_below_current", sm.get("bull_below_msg", "")))
        return warnings

    initial_warnings = _sanity_warnings(scenario_math)
    if initial_warnings:
        retry_ctx = (
            "Scenario sanity issues detected — please reconsider:\n"
            + "\n".join(f"- {msg}" for _, msg in initial_warnings)
        )
        pass1_retry, _ = run_pass1_with_retry(
            ticker, m, pe_ranges, max_retries=1, extra_context=retry_ctx
        )
        if pass1_retry:
            scenario_math_retry = compute_scenarios_from_drivers(
                m, pass1_retry, current_price)
            retry_warnings = _sanity_warnings(scenario_math_retry)
            # Accept retry only if it RESOLVED at least one warning without adding new ones
            initial_keys = {k for k, _ in initial_warnings}
            retry_keys   = {k for k, _ in retry_warnings}
            if retry_keys < initial_keys or (retry_keys == initial_keys and len(retry_warnings) < len(initial_warnings)):
                pass1 = pass1_retry
                scenario_math = scenario_math_retry
                final_warnings = retry_warnings
            else:
                final_warnings = initial_warnings
        else:
            final_warnings = initial_warnings
        for k, _ in final_warnings:
            if k not in degraded_sections:
                degraded_sections.append(k)

    rec_label, conviction = derive_recommendation(scenario_math)
    diagnostic = compute_fundamentals_diagnostic(m, scenario_math.get("final_probabilities"))
    diagnostic["divergence_flag"] = _check_divergence(diagnostic, scenario_math)

    python_outputs = {
        **scenario_math,
        "recommendation":         rec_label,
        "conviction":             conviction,
        "diagnostic":             diagnostic,
        "degraded_sections":      degraded_sections,
        "pe_ranges":              pe_ranges,
        "pass1_validation_errors": p1_errors or [],
    }

    # ── Phase C: Pass 2 narrative ─────────────────────────────
    pass2 = run_pass2(ticker, m, pass1, python_outputs)
    if isinstance(pass2, dict) and pass2.get("error"):
        pass2 = {"model_used": "N/A", "investment_thesis": "Narrative unavailable."}

    if _paragraph_count_check_failed(pass2):
        pass2_retry = run_pass2(ticker, m, pass1, python_outputs, retry=True)
        if not (isinstance(pass2_retry, dict) and pass2_retry.get("error")):
            pass2 = pass2_retry

    # ── Phase D: Pass 3 self-check ────────────────────────────
    pass3 = run_pass3_selfcheck(ticker, m, pass1, python_outputs, pass2)

    return _merge_outputs(pass1, python_outputs, pass2, pass3)


def _merge_outputs(pass1, python_outputs, pass2, pass3):
    """Merge all passes into the final report dict."""
    rec   = python_outputs.get("recommendation", "WATCH")
    conv  = python_outputs.get("conviction", "Medium")
    sm    = python_outputs  # scenario_math fields are at top level

    final = {
        # Deterministic
        "recommendation":  rec,
        "conviction":      conv,
        "model_used":      pass2.get("model_used", ""),
        # Narrative from pass 2
        "investment_thesis":        _cl(pass2.get("investment_thesis", "")),
        "business_overview":        _cl(pass2.get("business_overview", "")),
        "revenue_architecture":     _cl(pass2.get("revenue_architecture", "")),
        "growth_drivers":           _cl(pass2.get("growth_drivers", "")),
        "margin_analysis":          _cl(pass2.get("margin_analysis", "")),
        "financial_health":         _cl(pass2.get("financial_health", "")),
        "competitive_position":     _cl(pass2.get("competitive_position", "")),
        "driver_narratives":        {
            k: _cl(v) for k, v in pass2.get("driver_narratives", {}).items()
        },
        "scenario_commentary":      pass2.get("scenario_commentary", {}),
        "reverse_dcf_commentary":   _cl(pass2.get("reverse_dcf_commentary", "")),
        "monitoring_dashboard_intro": _cl(pass2.get("monitoring_dashboard_intro", "")),
        "catalysts_intro":          _cl(pass2.get("catalysts_intro", "")),
        "recommendation_rationale": _cl(pass2.get("recommendation_rationale", "")),
        "conclusion":               _cl(pass2.get("conclusion", "")),
        # Structured from pass 1
        "segments":          pass1.get("segments", []),
        "drivers":           pass1.get("drivers", []),
        "scenario_inputs":   pass1.get("scenario_inputs", {}),
        "monitoring_kpis":   pass1.get("monitoring_kpis", []),
        "catalysts":         pass1.get("catalysts", []),
        "concentration":     pass1.get("concentration", {}),
        "competitive_context": pass1.get("competitive_context", {}),
        "peer_tickers":      pass1.get("peer_tickers", []),
        # Math
        "scenario_math":     sm,
        "python_outputs":    python_outputs,
        "pass3":             pass3,
        # Legacy fields (kept for backward compat with app.py render paths)
        "headwind_narrative":        "",
        "tailwind_narrative":        "",
        "market_pricing_commentary": "",
        "scenarios":                 {},  # old format; render uses python_outputs
        "headwinds":                 [],
        "tailwinds":                 [],
        "macro_drivers":             [],
        "market_expectations":       {},
        "sensitivity":               {},
        "data_quality_warnings": (
            list(python_outputs.get("degraded_sections") or []) +
            list(python_outputs.get("guard_warnings") or []) +
            [f"pass1_validation: {e}" for e in (python_outputs.get("pass1_validation_errors") or [])]
        ),
    }
    return final


def _cl(text):
    """Apply clean_latex to a string; return '' for non-strings."""
    if isinstance(text, str):
        return clean_latex(text)
    return ""


# ══════════════════════════════════════════════════════════════
# v2 TYPED EXCEPTIONS
# ══════════════════════════════════════════════════════════════

class Pass1ValidationError(Exception):
    """Raised when §5.2 validation fails after retry. No DEGRADED path — surface to UI."""
    def __init__(self, errors: list):
        self.errors = list(errors)
        super().__init__(f"Pass1 v2 validation failed ({len(errors)} errors): {errors[:2]}")


class BullCaseTooLowError(Exception):
    """
    Raised by run_methodology_math when bull EPS < ANALYST_CONSENSUS_HARD_GAP_FRAC ×
    consensus_eps_fy2.high. Triggers ONE Pass 1 retry with a calibration hint (§6 Step D).
    """
    def __init__(self, bull_eps: float, consensus_high: float):
        self.bull_eps = bull_eps
        self.consensus_high = consensus_high
        super().__init__(
            f"Bull EPS ${bull_eps:.2f} is too far below consensus_high ${consensus_high:.2f}; "
            f"trigger Pass 1 retry with calibration hint."
        )


# ══════════════════════════════════════════════════════════════
# v2 PASS 1 — FOUNDATION
# ══════════════════════════════════════════════════════════════

def _validate_pass1_v2(pass1: dict) -> tuple:
    """
    Validate §5.2 contract. Returns (soft_errors, hard_errors).

    hard_errors  — math-critical: macro_drivers or events missing/malformed.
                   Always raise Pass1ValidationError after two failed attempts.
    soft_errors  — report-quality: missing catalysts, pe_anchors sub-fields, etc.
                   Trigger one retry with a corrective hint; non-blocking if still
                   present after retry (proceed with a logged warning).

    This split is intentional: the downstream math layer can run without catalysts
    or pe_anchors text; it cannot run without events and macro_drivers.
    """
    soft: list[str] = []
    hard: list[str] = []

    # ── Math-critical keys — hard on any pass ───────────────────────────────
    for k in ("macro_drivers", "events"):
        if k not in pass1:
            hard.append(f"missing math-critical key: {k}")

    if hard:
        return soft, hard  # can't validate sub-fields

    # ── Report-quality keys — soft (retry-eligible) ──────────────────────────
    for k in ("corporate_dna", "segments_enriched", "primary_growth_driver",
              "peer_set_enriched", "pe_anchors", "catalysts"):
        if k not in pass1:
            soft.append(f"missing key: {k}")

    # macro_drivers: exactly 3 with ids A/B/C
    mds = pass1.get("macro_drivers", [])
    if len(mds) != 3:
        hard.append(f"macro_drivers must have exactly 3 entries, got {len(mds)}")
    else:
        actual_ids = {d.get("id") for d in mds}
        if actual_ids != {"A", "B", "C"}:
            hard.append(f"macro_drivers ids must be exactly {{A, B, C}}, got {actual_ids}")
        for md in mds:
            if not md.get("label"):
                soft.append(f"macro_driver {md.get('id', '?')}: missing label")
            if not md.get("narrative"):
                soft.append(f"macro_driver {md.get('id', '?')}: missing narrative")

    # events: 6-12 total; each driver ≥ 2; probabilities sum to 1.0 per driver
    events = pass1.get("events", [])
    if len(events) < 6:
        hard.append(f"events must have 6-12 entries, got {len(events)} (too few)")
    elif len(events) > 12:
        soft.append(f"events has {len(events)} entries (spec max is 12)")

    driver_event_counts: dict[str, int] = {}
    driver_prob_sums: dict[str, float] = {}
    for ev in events:
        d = ev.get("driver", "")
        driver_event_counts[d] = driver_event_counts.get(d, 0) + 1
        prob = ev.get("probability", 0.0)
        try:
            driver_prob_sums[d] = driver_prob_sums.get(d, 0.0) + float(prob)
        except (TypeError, ValueError):
            pass

    for d in ("A", "B", "C"):
        if driver_event_counts.get(d, 0) < 2:
            hard.append(
                f"driver {d} must have ≥ 2 events, got {driver_event_counts.get(d, 0)}"
            )
        psum = driver_prob_sums.get(d, 0.0)
        if abs(psum - 1.0) > 0.05:
            soft.append(
                f"driver {d} event probabilities sum to {psum:.3f} (must be 1.0 ±0.05)"
            )

    for ev in events:
        ev_id = ev.get("id", f"[driver={ev.get('driver','?')}]")

        prob = ev.get("probability")
        if prob is None:
            soft.append(f"event {ev_id}: missing probability")
        else:
            try:
                if not (0.0 <= float(prob) <= 1.0):
                    soft.append(f"event {ev_id}: probability={prob} out of [0,1]")
            except (TypeError, ValueError):
                soft.append(f"event {ev_id}: probability not numeric: {prob!r}")

        outcome = ev.get("outcome")
        if outcome not in ("bull", "base", "bear"):
            soft.append(f"event {ev_id}: outcome={outcome!r} must be bull/base/bear")

        low  = ev.get("revenue_at_risk_low")
        high = ev.get("revenue_at_risk_high")
        if low is None or high is None:
            soft.append(f"event {ev_id}: missing revenue_at_risk_low or _high")
        else:
            try:
                if float(high) < float(low):
                    soft.append(
                        f"event {ev_id}: revenue_at_risk_high ({high}) < low ({low})"
                    )
            except (TypeError, ValueError):
                soft.append(f"event {ev_id}: revenue_at_risk values not numeric")

        op = ev.get("op_margin_to_apply")
        if op is None:
            soft.append(f"event {ev_id}: missing op_margin_to_apply")
        else:
            try:
                if not (0.0 <= float(op) <= 1.0):
                    soft.append(f"event {ev_id}: op_margin_to_apply={op} out of [0,1]")
            except (TypeError, ValueError):
                soft.append(f"event {ev_id}: op_margin_to_apply not numeric: {op!r}")

        tax = ev.get("tax_rate_to_apply")
        if tax is None:
            soft.append(f"event {ev_id}: missing tax_rate_to_apply")
        else:
            try:
                if not (0.0 <= float(tax) <= 0.5):
                    soft.append(f"event {ev_id}: tax_rate_to_apply={tax} out of [0, 0.5]")
            except (TypeError, ValueError):
                soft.append(f"event {ev_id}: tax_rate_to_apply not numeric: {tax!r}")

        if not ev.get("evidence"):
            soft.append(f"event {ev_id}: missing evidence field")

    # pe_anchors: all three scenarios; reasoning must be present
    pe_anchors = pass1.get("pe_anchors", {})
    for scenario in ("bull", "base", "bear"):
        anchor = pe_anchors.get(scenario)
        if not isinstance(anchor, dict):
            soft.append(f"pe_anchors.{scenario}: missing or wrong type (need dict with 'reasoning')")
        elif not anchor.get("reasoning"):
            soft.append(f"pe_anchors.{scenario}: missing reasoning field")

    # catalysts: 3-6 entries with required fields
    cats = pass1.get("catalysts", [])
    if len(cats) < 3:
        soft.append(f"catalysts must have 3-6 entries, got {len(cats)} (too few)")
    elif len(cats) > 6:
        soft.append(f"catalysts has {len(cats)} entries (spec max is 6)")
    for cat in cats:
        if not cat.get("date"):
            soft.append(f"catalyst missing date: {cat.get('event', '?')!r}")
        if not cat.get("event"):
            soft.append("catalyst missing event field")
        if not cat.get("what_to_watch"):
            soft.append(f"catalyst missing what_to_watch: {cat.get('event', '?')!r}")

    return soft, hard


def run_pass1_foundation(
    ticker: str,
    baseline: dict,
    max_passes: int = 2,
    retry_hint: str = "",
) -> dict:
    """
    Pass 1 v2: build §5.2 qualitative input pack from baseline (§5.1).

    Fault-tolerant:
      - Soft errors on first attempt → retry once with corrective hint.
      - Hard errors after retry → raise Pass1ValidationError (no DEGRADED path).
      - retry_hint: pre-populated by orchestrator when BullCaseTooLowError was raised.

    Args:
        ticker:      stock ticker
        baseline:    §5.1 baseline dict from calc_baseline
        max_passes:  1 = no retry; 2 = retry once on errors (default)
        retry_hint:  populated by orchestrator when BullCaseTooLowError fires
    """
    company_name = baseline.get("company_name", ticker)
    recent_news  = baseline.get("recent_news", [])
    # Exclude large nested fields to keep prompt size manageable
    _exclude = {"recent_news", "history_3y"}
    baseline_for_prompt = {k: v for k, v in baseline.items() if k not in _exclude}

    def _build_messages(corrective: str = "") -> list:
        prompt = PASS1_PROMPT
        # On a calibration retry from BullCaseTooLowError the hint goes at the top
        hint = corrective or retry_hint
        replacements = {
            "{ticker}":            ticker,
            "{company_name}":      company_name,
            "{baseline_json}":     json.dumps(baseline_for_prompt, indent=2, default=str),
            "{recent_news_json}":  json.dumps(recent_news, indent=2, default=str),
            "{retry_hint}":        hint,
        }
        p = prompt
        for k, v in replacements.items():
            p = p.replace(k, str(v))
        return [
            {"role": "system",
             "content": "You are an equity research analyst. Respond with valid JSON only, no prose before or after."},
            {"role": "user", "content": p},
        ]

    # ── First attempt ────────────────────────────────────────────────────────
    raw, model, errors = run_ai(_build_messages(), max_tokens=4500)
    if raw is None:
        raise Pass1ValidationError(errors or ["run_ai returned None on first attempt"])

    pass1, parse_err = parse_json_response(raw, model)
    if parse_err or pass1 is None:
        if max_passes <= 1:
            raise Pass1ValidationError([parse_err or "JSON parse failed on first attempt"])
        corrective = (
            "PARSE ERROR: Your previous response could not be parsed as JSON. "
            "Return ONLY a valid JSON object — no prose, no markdown, no fences."
        )
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=4500)
        if raw2 is None:
            raise Pass1ValidationError(errs2 or ["run_ai returned None on JSON-repair retry"])
        pass1, parse_err2 = parse_json_response(raw2, model2)
        if parse_err2 or pass1 is None:
            raise Pass1ValidationError([parse_err2 or "JSON parse failed after repair retry"])
        model = model2

    soft, hard = _validate_pass1_v2(pass1)

    if hard:
        if max_passes <= 1:
            raise Pass1ValidationError(hard)
        # Math-critical errors on first attempt — retry once with explicit fix instructions
        corrective = (
            "CRITICAL ERRORS — the following must be fixed or the output cannot be used:\n"
            + "\n".join(f"  - {e}" for e in hard)
            + "\n\nRe-emit the complete corrected JSON. Do not omit any fields."
        )
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=4500)
        if raw2 is None:
            raise Pass1ValidationError(hard + (errs2 or []))
        pass1_r, parse_err_r = parse_json_response(raw2, model2)
        if parse_err_r or pass1_r is None:
            raise Pass1ValidationError(hard + [parse_err_r or "JSON parse failed on retry"])
        soft_r, hard_r = _validate_pass1_v2(pass1_r)
        if hard_r:
            raise Pass1ValidationError(hard_r)
        pass1 = pass1_r
        soft  = soft_r
        model = model2

    # ── Soft errors → one corrective retry ──────────────────────────────────
    elif soft and max_passes >= 2:
        corrective = (
            "VALIDATION WARNINGS — fix all of the following before re-emitting:\n"
            + "\n".join(f"  - {e}" for e in soft)
            + "\n\nInclude ALL fields from the output schema, especially 'catalysts'. "
            "Re-emit the complete corrected JSON."
        )
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=4500)
        if raw2 is not None:
            pass1_r, parse_err_r = parse_json_response(raw2, model2)
            if not parse_err_r and pass1_r is not None:
                soft_r, hard_r = _validate_pass1_v2(pass1_r)
                if hard_r:
                    # Retry introduced math-critical regressions — keep first attempt
                    print(f"  Pass1 v2 retry regressed ({hard_r[:2]}); keeping first attempt.")
                else:
                    pass1  = pass1_r
                    soft   = soft_r
                    model  = model2
        if soft:
            print(f"  Pass1 v2: {len(soft)} residual soft warnings (non-blocking): {soft[:3]}")

    # ── Defaults for optional fields ─────────────────────────────────────────
    pass1.setdefault("sbc_context", None)
    pass1.setdefault("contract_asset_context", None)
    pass1["model_used"] = model
    return pass1


# ══════════════════════════════════════════════════════════════
# v2 PASS 2 — NARRATIVE REPORT
# ══════════════════════════════════════════════════════════════

_PASS2_REQUIRED_SECTIONS = (
    "investment_thesis", "reverse_dcf_commentary",
    "recommendation_rationale", "conclusion",
)
_PASS2_SCENARIO_KEYS  = ("bull", "base", "bear")
_PASS2_DRIVER_KEYS    = ("A", "B", "C")
_PASS2_FORBIDDEN      = ("Sharpe", "DEGRADED", "capture")


def _build_pass2_body(pass2: dict) -> str:
    """Concatenate all narrative string sections for word count / forbidden token audit."""
    parts: list[str] = []
    for k in ("investment_thesis", "reverse_dcf_commentary",
              "financial_health", "recommendation_rationale", "conclusion"):
        v = pass2.get(k, "")
        if isinstance(v, str) and v:
            parts.append(v)
    for sc in _PASS2_SCENARIO_KEYS:
        v = (pass2.get("scenario_commentary") or {}).get(sc, "")
        if isinstance(v, str) and v:
            parts.append(v)
    for did in _PASS2_DRIVER_KEYS:
        v = (pass2.get("driver_narratives") or {}).get(did, "")
        if isinstance(v, str) and v:
            parts.append(v)
    return "\n\n".join(parts)


def _validate_pass2_v2(pass2: dict) -> tuple:
    """
    Validate §5.4 pass2 report dict. Returns (soft_errors, hard_errors).

    hard_errors — missing required sections, forbidden vocabulary present.
    soft_errors — word count > 4500, missing optional sections.
    """
    soft: list[str] = []
    hard: list[str] = []

    for k in _PASS2_REQUIRED_SECTIONS:
        if not pass2.get(k):
            hard.append(f"missing required section: {k}")

    body = _build_pass2_body(pass2)

    for token in _PASS2_FORBIDDEN:
        if token in body:
            hard.append(f"forbidden token present: {token!r}")

    wc = len(body.split())
    if wc > 4500:
        soft.append(f"word count {wc} exceeds 4500")

    sc_dict = pass2.get("scenario_commentary") or {}
    for sc in _PASS2_SCENARIO_KEYS:
        if not sc_dict.get(sc):
            soft.append(f"missing scenario_commentary.{sc}")

    dn_dict = pass2.get("driver_narratives") or {}
    for did in _PASS2_DRIVER_KEYS:
        if not dn_dict.get(did):
            soft.append(f"missing driver_narratives.{did}")

    if not pass2.get("financial_health"):
        soft.append("missing financial_health section")

    return soft, hard


def run_pass2_report(
    ticker: str,
    baseline: dict,
    pass1: dict,
    math: dict,
    max_passes: int = 2,
    retry_hint: str = "",
) -> dict:
    """
    Pass 2 v2: write narrative report from §5.1 baseline, §5.2 pass1, §5.3 math dict.

    Returns a dict with all narrative sections plus a 'body' key (concatenated text)
    for smoke harness word-count and forbidden-token checks.

    Fault-tolerant:
      - Hard errors (missing required sections, forbidden tokens) → retry once.
      - Soft errors (word count, missing optional sections) → retry once.
      - If retry regresses on hard errors → keep first attempt.
      - No DEGRADED path.
    """
    company_name = baseline.get("company_name", ticker)
    today_date   = datetime.now().strftime("%B %d, %Y")

    _exclude_bl = {"recent_news", "history_3y"}
    baseline_slim = {k: v for k, v in baseline.items() if k not in _exclude_bl}

    def _build_messages(corrective: str = "") -> list:
        hint = corrective or retry_hint
        prompt = PASS2_PROMPT
        for k, v in {
            "{ticker}":       ticker,
            "{company_name}": company_name,
            "{today_date}":   today_date,
            "{math_json}":    json.dumps(math,         indent=2, default=str),
            "{pass1_json}":   json.dumps(pass1,        indent=2, default=str),
            "{baseline_json}": json.dumps(baseline_slim, indent=2, default=str),
            "{retry_hint}":   hint,
        }.items():
            prompt = prompt.replace(k, str(v))
        return [
            {"role": "system",
             "content": "You are a senior equity research analyst. Respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]

    # ── First attempt ────────────────────────────────────────────────────────
    raw, model, errors = run_ai(_build_messages(), max_tokens=6000)
    if raw is None:
        raise Pass1ValidationError(errors or ["run_ai returned None (pass2 attempt 1)"])

    pass2, parse_err = parse_json_response(raw, model)
    if parse_err or pass2 is None:
        if max_passes <= 1:
            raise Pass1ValidationError([parse_err or "JSON parse failed (pass2 attempt 1)"])
        raw2, model2, _ = run_ai(
            _build_messages("PARSE ERROR: return ONLY a valid JSON object."),
            max_tokens=6000,
        )
        if raw2 is None:
            raise Pass1ValidationError(["run_ai returned None on parse-repair retry (pass2)"])
        pass2, pe2 = parse_json_response(raw2, model2)
        if pe2 or pass2 is None:
            raise Pass1ValidationError([pe2 or "JSON parse failed on repair retry (pass2)"])
        model = model2

    soft, hard = _validate_pass2_v2(pass2)

    if hard:
        if max_passes <= 1:
            raise Pass1ValidationError(hard)
        corrective = (
            "CRITICAL ERRORS — fix all before re-emitting:\n"
            + "\n".join(f"  - {e}" for e in hard)
            + "\n\nRe-emit the complete corrected JSON. No forbidden words. No omitted sections."
        )
        raw2, model2, _ = run_ai(_build_messages(corrective), max_tokens=6000)
        if raw2 is not None:
            p2r, pe_r = parse_json_response(raw2, model2)
            if not pe_r and p2r is not None:
                soft_r, hard_r = _validate_pass2_v2(p2r)
                if hard_r:
                    print(f"  Pass2 v2 retry introduced hard regressions ({hard_r[:2]}); "
                          "keeping first attempt.")
                else:
                    pass2, soft, model = p2r, soft_r, model2

    elif soft and max_passes >= 2:
        corrective = (
            "VALIDATION WARNINGS — please address:\n"
            + "\n".join(f"  - {e}" for e in soft)
            + "\n\nRe-emit the complete corrected JSON within 4500 total words."
        )
        raw2, model2, _ = run_ai(_build_messages(corrective), max_tokens=6000)
        if raw2 is not None:
            p2r, pe_r = parse_json_response(raw2, model2)
            if not pe_r and p2r is not None:
                soft_r, hard_r = _validate_pass2_v2(p2r)
                if not hard_r:
                    pass2, soft, model = p2r, soft_r, model2
        if soft:
            print(f"  Pass2 v2: {len(soft)} residual soft warnings (non-blocking): {soft[:3]}")

    # ── Apply clean_latex and attach body ────────────────────────────────────
    for k, v in pass2.items():
        if isinstance(v, str):
            pass2[k] = clean_latex(v)
        elif isinstance(v, dict):
            pass2[k] = {k2: clean_latex(v2) if isinstance(v2, str) else v2
                        for k2, v2 in v.items()}

    pass2["body"]       = _build_pass2_body(pass2)
    pass2["model_used"] = model
    return pass2


# ══════════════════════════════════════════════════════════════
# v2 PASS 3 — AUDIT
# ══════════════════════════════════════════════════════════════

_PASS3_FORBIDDEN = frozenset({"Sharpe", "DEGRADED", "capture"})


def _scan_forbidden_vocab(pass2: dict) -> list:
    """
    Deterministic B6 scan — no LLM call.
    Returns a list of hit dicts: {token, quoted_context} for each forbidden word found.
    """
    body = pass2.get("body", "") or _build_pass2_body(pass2)
    hits = []
    for token in _PASS3_FORBIDDEN:
        idx = body.find(token)
        if idx >= 0:
            ctx_start = max(0, idx - 30)
            ctx_end   = min(len(body), idx + len(token) + 30)
            hits.append({
                "token":          token,
                "quoted_context": body[ctx_start:ctx_end].strip(),
            })
    return hits


def _build_pass3_audit_messages(
    ticker: str,
    baseline: dict,
    pass1: dict,
    math: dict,
    pass2: dict,
) -> list:
    body = pass2.get("body", "") or _build_pass2_body(pass2)
    recommendation = math.get("recommendation", "WATCH")
    _exclude_bl = {"recent_news", "history_3y"}
    baseline_slim = {k: v for k, v in baseline.items() if k not in _exclude_bl}

    prompt = PASS3_PROMPT
    for k, v in {
        "{ticker}":         ticker,
        "{recommendation}": recommendation,
        "{pass2_body}":     body,
        "{math_json}":      json.dumps(math,          indent=2, default=str),
        "{pass1_json}":     json.dumps(pass1,         indent=2, default=str),
        "{baseline_json}":  json.dumps(baseline_slim, indent=2, default=str),
    }.items():
        prompt = prompt.replace(k, str(v))

    return [
        {"role": "system",
         "content": "You are an internal audit system. Respond with valid JSON only, no prose."},
        {"role": "user", "content": prompt},
    ]


def run_pass3_audit(
    ticker: str,
    baseline: dict,
    pass1: dict,
    math: dict,
    pass2: dict,
    calls_remaining: int = MAX_PIPELINE_AI_CALLS,
) -> dict:
    """
    Pass 3 v2: deterministic forbidden-vocab scan + 1 LLM citation/tone audit.

    calls_remaining (C3): global call budget. If ≤ 0, the LLM call is skipped
    and the function returns immediately with audit_skipped=True.
    The LLM call decrements calls_remaining by 1 in the return dict.

    This function makes AT MOST 1 LLM call — no internal retry loop.
    """
    # Step 1: deterministic B6 forbidden-vocab scan (no LLM call)
    forbidden_hits = _scan_forbidden_vocab(pass2)

    # Step 2: enforce C3 call ceiling
    if calls_remaining <= 0:
        return {
            "audit_skipped":    True,
            "reason":           "call budget exhausted (C3 ceiling)",
            "calls_remaining":  0,
            "forbidden_vocab":  forbidden_hits,
            "citation_errors":  [],
            "b1_compliant":     None,
            "tone_label_ok":    None,
            "tone_label_evidence": None,
            "audit_clean":      False if forbidden_hits else None,
        }

    # Step 3: single LLM audit call
    msgs = _build_pass3_audit_messages(ticker, baseline, pass1, math, pass2)
    raw, model, errors = run_ai(msgs, max_tokens=1500)

    if raw is None:
        return {
            "audit_skipped":    False,
            "llm_error":        errors,
            "calls_remaining":  calls_remaining - 1,
            "forbidden_vocab":  forbidden_hits,
            "citation_errors":  [],
            "b1_compliant":     None,
            "tone_label_ok":    None,
            "tone_label_evidence": None,
            "audit_clean":      False if forbidden_hits else None,
        }

    audit, parse_err = parse_json_response(raw, model)
    if parse_err or audit is None:
        audit = {}

    citation_errors = audit.get("citation_errors", [])
    b1_compliant    = audit.get("b1_compliant", True)
    tone_ok         = audit.get("tone_label_ok", True)

    error_severities = {"error", "warn"}
    severe_citations = [e for e in citation_errors
                        if e.get("severity") in error_severities]

    return {
        "audit_skipped":     False,
        "calls_remaining":   calls_remaining - 1,
        "forbidden_vocab":   forbidden_hits,
        "citation_errors":   citation_errors,
        "b1_compliant":      b1_compliant,
        "tone_label_ok":     tone_ok,
        "tone_label_evidence": audit.get("tone_label_evidence"),
        "audit_clean":       (not forbidden_hits and not severe_citations
                              and b1_compliant and tone_ok),
        "model_used":        model,
    }


# ══════════════════════════════════════════════════════════════
# THESIS CHECK (used by check_prices.py and app.py)
# ══════════════════════════════════════════════════════════════

def thesis_check(ticker, company, original_metrics, original_thesis,
                 current_metrics, model="claude-opus-4-7",
                 free_models=None):
    messages = [
        {"role": "system", "content": (
            "You are a senior equity research analyst performing a thesis integrity check. "
            "Respond ONLY with valid JSON, no fences.")},
        {"role": "user", "content": f"""THESIS CHECK: {ticker} ({company})

ORIGINAL THESIS:
{original_thesis}

ORIGINAL METRICS:
{json.dumps(original_metrics, default=str)}

CURRENT METRICS:
{json.dumps(current_metrics, default=str)}

Respond with exactly this JSON:
{{
  "thesis_intact": true,
  "confidence": "High",
  "updated_action": "BUY",
  "key_changes": ["Change 1", "Change 2"],
  "rationale": "2-3 sentence summary of whether the thesis holds."
}}

thesis_intact: true if the core investment case is still valid.
updated_action: exactly BUY, WATCH, or PASS.
confidence: High, Medium, or Low."""}
    ]
    raw, _, _ = run_ai(messages, max_tokens=800, model=model,
                       free_models=free_models or FREE_MODELS_EXTENDED)
    result, _ = parse_json_response(raw)
    if not result:
        result = {
            "thesis_intact": True, "confidence": "Low",
            "updated_action": "WATCH",
            "key_changes": ["AI evaluation unavailable at this time."],
            "rationale": "Automated thesis check could not be completed. "
                         "Please review manually.",
        }
    return result


