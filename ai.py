"""AI orchestration: Anthropic primary, OpenRouter fallback. Two-pass architecture."""
import json
import os
import time
from datetime import datetime
from openai import OpenAI
import anthropic

from config import (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, FREE_MODELS,
                    FREE_MODELS_EXTENDED)
from formatting import safe_float, fmt_c, fmt_n, fmt_p
from compute import compute_scenario_math


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

def _build_pass1_messages(ticker, m, reverse_dcf_json):
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str)
    description_snippet = (m.get("description") or "N/A")[:800]

    replacements = {
        "{ticker}": ticker,
        "{company_name}": m.get("company_name", ticker),
        "{metrics_json}": ms,
        "{current_price}": str(m.get("current_price")),
        "{trailing_pe}": str(m.get("trailing_pe")),
        "{forward_pe}": str(m.get("forward_pe")),
        "{ev_to_ebitda}": str(m.get("ev_to_ebitda")),
        "{trailing_eps}": str(m.get("trailing_eps")),
        "{forward_eps}": str(m.get("forward_eps")),
        "{operating_margin}": str(m.get("operating_margin")),
        "{profit_margin}": str(m.get("profit_margin")),
        "{description}": description_snippet,
        "{today_date}": datetime.now().strftime("%B %d, %Y"),
        "{total_revenue}": fmt_c(m.get("total_revenue"), m.get("currency", "USD")),
        "{reverse_dcf_json}": reverse_dcf_json,
        "{shares_outstanding}": str(m.get("shares_outstanding")),
    }

    user_prompt = PASS1_PROMPT
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, val)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]


def run_pass1(ticker, m, reverse_dcf_json):
    msgs = _build_pass1_messages(ticker, m, reverse_dcf_json)
    """Pass 1: Get structured assumptions from LLM."""
    msgs = _build_pass1_messages(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=6000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    # Defaults
    defaults = {
        "segments": [], "concentration": {},
        "headwinds": [], "tailwinds": [], "macro_drivers": [],
        "scenarios": {
            "bull": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 20,
                     "pe_rationale": "N/A", "narrative": "N/A"},
            "base": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 18,
                     "pe_rationale": "N/A", "narrative": "N/A"},
            "bear": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 14,
                     "pe_rationale": "N/A", "narrative": "N/A"},
        },
        "market_expectations": {}, "sensitivity": {},
        "catalysts": [], "peer_tickers": [],
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v

    # Validate segment revenue totals
    actual_revenue = safe_float(m.get("total_revenue"))
    if actual_revenue > 0 and a.get("segments"):
        segment_total = sum(safe_float(seg.get("current_revenue"))
                            for seg in a["segments"])
        if segment_total > 0:
            rev_ratio = segment_total / actual_revenue
            if rev_ratio < 0.5 or rev_ratio > 2.0:
                print(f"  VALIDATION FAIL: Segment total ({segment_total:.0f}) vs "
                      f"actual revenue ({actual_revenue:.0f}) = {rev_ratio:.2f}x")
                return {
                    "error": True,
                    "details": [
                        f"LLM segment revenues ({fmt_n(segment_total)}) do not match "
                        f"actual company revenue ({fmt_n(actual_revenue)}). "
                        f"The model may have analyzed the wrong company. Please retry."
                    ]
                }
    return a


# ══════════════════════════════════════════════════════════════
# PASS 2: NARRATIVE
# ══════════════════════════════════════════════════════════════

def _build_pass2_messages(ticker, m, scenario_math, pass1_output, reverse_dcf_json):
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str)
    description_snippet = (m.get("description") or "N/A")[:800]

    sm = scenario_math
    scenarios = sm.get("scenarios", {})
    math_summary = {
        "expected_value":        sm.get("expected_value"),
        "expected_return":       f"{sm.get('expected_return', 0) * 100:.1f}%",
        "prob_positive_return":  f"{sm.get('prob_positive_return', 0) * 100:.0f}%",
        "risk_adjusted_score":   sm.get("risk_adjusted_score"),
        "upside_downside_ratio": sm.get("upside_downside_ratio"),
    }
    for sname in ["bull", "base", "bear"]:
        s = scenarios.get(sname, {})
        math_summary[f"{sname}_price_target"]    = s.get("price_target")
        math_summary[f"{sname}_implied_return"]  = f"{s.get('implied_return', 0) * 100:.1f}%"
        math_summary[f"{sname}_probability"]     = f"{s.get('probability', 0) * 100:.0f}%"
        math_summary[f"{sname}_eps"]             = s.get("projected_eps")
        math_summary[f"{sname}_pe"]              = s.get("pe_multiple")
        math_summary[f"{sname}_revenue"]         = s.get("total_revenue")
        math_summary[f"{sname}_op_margin"]       = s.get("operating_margin")
        math_summary[f"{sname}_fcf_yield"]       = s.get("fcf_yield_at_target")
        math_summary[f"{sname}_breakeven_pe"]    = s.get("breakeven_pe")
        math_summary[f"{sname}_margin_rationale"] = s.get("margin_rationale")

    mkt = sm.get("market_expectations", {})
    hw_tw = {
        "headwinds": pass1_output.get("headwinds", []),
        "tailwinds": pass1_output.get("tailwinds", []),
    }

    replacements = {
        "{ticker}": ticker,
        "{company_name}": m.get("company_name", ticker),
        "{metrics_json}": ms,
        "{description}": description_snippet,
        "{segments_json}": json.dumps(pass1_output.get("segments", []),
                                       indent=2, default=str),
        "{scenario_math_json}": json.dumps(math_summary, indent=2, default=str),
        "{market_expectations_json}": json.dumps(mkt, indent=2, default=str),
        "{headwinds_tailwinds_json}": json.dumps(hw_tw, indent=2, default=str),
        "{expected_return}": math_summary["expected_return"],
        "{prob_positive}": math_summary["prob_positive_return"],
        "{risk_adjusted_score}": str(sm.get("risk_adjusted_score")),
        "{upside_downside_ratio}": str(sm.get("upside_downside_ratio")),
        "{implied_vs_base}": mkt.get("vs_base_case", "N/A"),
        "{reverse_dcf_json}": reverse_dcf_json,
    }

    user_prompt = PASS2_PROMPT
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, str(val))

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]


def run_pass2(ticker, m, scenario_math, pass1_output, reverse_dcf_json):
    msgs = _build_pass2_messages(ticker, m, scenario_math, pass1_output, reverse_dcf_json)
    """Pass 2: Get narrative from LLM seeing computed math."""
    msgs = _build_pass2_messages(ticker, m, scenario_math, pass1_output)
    raw, model, errors = run_ai(msgs, max_tokens=6000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    defaults = {
        "recommendation": "WATCH", "conviction": "Medium",
        "investment_thesis": "Analysis not available.",
        "business_overview": "Analysis not available.",
        "revenue_architecture": "Analysis not available.",
        "growth_drivers": "Analysis not available.",
        "margin_analysis": "Analysis not available.",
        "financial_health": "Analysis not available.",
        "competitive_position": "Analysis not available.",
        "headwind_narrative": "Analysis not available.",
        "tailwind_narrative": "Analysis not available.",
        "market_pricing_commentary": "Analysis not available.",
        "scenario_commentary": "Analysis not available.",
        "conclusion": "Analysis not available.",
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v
    a["model_used"] = model
    return a


# ══════════════════════════════════════════════════════════════
# TWO-PASS ORCHESTRATOR
# (No @st.cache_data here - app.py wraps with caching)
# ══════════════════════════════════════════════════════════════

def run_two_pass(ticker, m, pass1_fn=None, pass2_fn=None):
    """
    Full orchestration:
    1. Pass 1 (assumptions) -> 2. Python math -> 3. Pass 2 (narrative) -> 4. Merge

    pass1_fn / pass2_fn allow app.py to inject @st.cache_data-wrapped versions.
    Falls back to uncached run_pass1 / run_pass2 if not provided.

    NOTE: compute_scenario_math now receives both `m` (metrics) and
    `pass1` (llm_output).  The probability engine derives scenario
    probabilities from the metrics signals, not from LLM driver estimates.
    """
    _pass1 = pass1_fn or (lambda t, m_dict: run_pass1(t, m_dict))
    _pass2 = pass2_fn or (lambda t, m_dict, sm, p1: run_pass2(t, m_dict, sm, p1))

    # Pass 1
    pass1 = _pass1(ticker, m)
    if isinstance(pass1, dict) and pass1.get("error"):
        return pass1

    # Python math  — m (metrics) is passed through so the probability
    # engine can read financial signals directly.
    scenario_math = compute_scenario_math(m, pass1)

    # Pass 2
    pass2 = _pass2(ticker, m, scenario_math, pass1)
    if isinstance(pass2, dict) and pass2.get("error"):
        return pass2

    # Merge
    final = {}
    for key in ["recommendation", "conviction", "investment_thesis",
                "business_overview", "revenue_architecture", "growth_drivers",
                "margin_analysis", "financial_health", "competitive_position",
                "headwind_narrative", "tailwind_narrative",
                "market_pricing_commentary", "scenario_commentary",
                "conclusion", "model_used"]:
        final[key] = pass2.get(key, "")

    for key in ["segments", "concentration", "headwinds", "tailwinds",
                "macro_drivers", "scenarios", "catalysts", "peer_tickers",
                "market_expectations", "sensitivity"]:
        final[key] = pass1.get(key, {} if key in ["concentration",
                     "market_expectations", "sensitivity"] else [])

    final["scenario_math"] = scenario_math

    # Consistency override
    exp_ret  = scenario_math.get("expected_return", 0)
    prob_pos = scenario_math.get("prob_positive_return", 0)
    rec      = final["recommendation"].upper()

    if rec == "BUY" and exp_ret < -0.20 and prob_pos < 0.25:
        final["recommendation"] = "PASS"
        final["conviction"] = "High"
        final["rec_override_reason"] = (
            f"Override: LLM recommended BUY despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return.")
    elif rec == "PASS" and exp_ret > 0.20 and prob_pos > 0.70:
        final["recommendation"] = "BUY"
        final["conviction"] = "Medium"
        final["rec_override_reason"] = (
            f"Override: LLM recommended PASS despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return.")

    return final


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


# ══════════════════════════════════════════════════════════════
# HTML REPORT GENERATOR (legacy)
# ══════════════════════════════════════════════════════════════

def run_ai_html(ticker, m):
    ms = json.dumps({k: v for k, v in m.items() if k not in ["news"]},
                    indent=2, default=str)
    msgs = [
        {"role": "system", "content": (
            "You are a senior equity research analyst producing a comprehensive "
            "investment research report.\n\n"
            "CRITICAL: Use ONLY the financial data provided. Do not invent any figures.\n"
            "Output clean HTML with inline CSS. White background (#ffffff), "
            "dark text (#1a1a2e), professional sans-serif font.\n"
            "Use proper HTML tables with borders. Include a research masthead at the top.")},
        {"role": "user", "content": (
            f"Produce the full institutional research report for "
            f"{ticker} ({m.get('company_name', ticker)}).\n\n"
            f"VERIFIED FINANCIAL DATA:\n{ms}\n\n"
            f"Generate the complete HTML report now.")}
    ]
    raw, model, errors = run_ai(msgs, max_tokens=5500)
    if raw is None:
        return None, errors
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    if raw.startswith("html"):
        raw = raw[4:]
    return raw.strip(), None