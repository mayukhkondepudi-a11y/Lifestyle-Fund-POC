"""AI orchestration: Anthropic primary, OpenRouter fallback. Three-pass + compute architecture."""
from __future__ import annotations

import json
import time
from datetime import datetime
from openai import OpenAI
import anthropic
from compute import clean_latex

from config import (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, FREE_MODELS,
                    FREE_MODELS_EXTENDED)
from formatting import safe_float
from compute import (
    MAX_PIPELINE_AI_CALLS,
)
from run_methodology_math import run_methodology_math


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


# ── LLM output-token budgets (reviewable in one place) ───────────────────────
# Set generously ABOVE observed real output so a complete response fits; the
# truncation guard in run_ai still FAILS LOUD if a call hits the ceiling even at
# these budgets (a truncation at a generous budget is a real signal, not noise —
# we do NOT auto-retry with a higher budget).
#
# Pass 1: observed 4500 output_tokens (truncated exactly at the old 4500 ceiling).
#   9000 gives ~2× headroom so a complete pass1 JSON fits.
# Pass 2: observed ~27k chars (~8-9k tokens) against the old 10000 ceiling.
#   16000 gives clear headroom (~2× real output) above the largest observed body.
PASS1_MAX_TOKENS = 9000
PASS2_MAX_TOKENS = 16000

# NOTE: no sampling-temperature knob. Anthropic Opus 4.7/4.8 REJECT a custom
# temperature with HTTP 400 ("`temperature` is deprecated for this model"), so
# run_ai does not pass one at all. Reducing Pass-1 recommendation variance needs
# a different approach (see backlog).


# ══════════════════════════════════════════════════════════════
# AI RUNNER (single canonical implementation)
# ══════════════════════════════════════════════════════════════

# ── Per-call LLM telemetry ───────────────────────────────────────────────────
# Every run_ai call appends one record here (stop_reason, token usage, truncation
# flag, and the raw text). Live/validate harnesses read get_call_log() and persist
# it so stop_reason + output_tokens land in the run artifact — the fields needed to
# tell a truncation apart from a clean-but-incomplete completion.
_CALL_LOG: list[dict] = []


def reset_call_log() -> None:
    _CALL_LOG.clear()


def get_call_log() -> list[dict]:
    return [dict(e) for e in _CALL_LOG]


def run_ai(messages, max_tokens=4000, model="claude-opus-4-7",
           free_models=None):
    """
    Try Anthropic first, then fall back to OpenRouter free models.

    No temperature is sent: Anthropic Opus 4.7/4.8 reject a custom temperature
    with HTTP 400 ("`temperature` is deprecated for this model").

    A response with stop_reason == "max_tokens" (Anthropic) / finish_reason ==
    "length" (OpenRouter) is a TRUNCATED completion: it is treated as a FAILED
    call (returns None + a TRUNCATED error), never returned as if complete.
    """
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
            stop = getattr(r, "stop_reason", None)
            usage = getattr(r, "usage", None)
            in_tok = getattr(usage, "input_tokens", None) if usage else None
            out_tok = getattr(usage, "output_tokens", None) if usage else None
            truncated = (stop == "max_tokens")
            _CALL_LOG.append({
                "model": model, "stop_reason": stop, "input_tokens": in_tok,
                "output_tokens": out_tok, "max_tokens": max_tokens,
                "chars": len(text), "truncated": truncated, "text": text,
            })
            if truncated:
                print(f"  ⚠️ TRUNCATED: {model} hit max_tokens={max_tokens} "
                      f"(output_tokens={out_tok}, {len(text)} chars) — treating as FAILED")
                return None, model, [
                    f"TRUNCATED: {model} stop_reason=max_tokens output_tokens={out_tok} "
                    f"max_tokens={max_tokens}"
                ]
            print(f"  AI response via {model} ({len(text)} chars, stop={stop}, out_tok={out_tok})")
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
            fr = getattr(r.choices[0], "finish_reason", None)
            usage = getattr(r, "usage", None)
            out_tok = getattr(usage, "completion_tokens", None) if usage else None
            truncated = (fr == "length")
            _CALL_LOG.append({
                "model": fm, "stop_reason": fr, "input_tokens": None,
                "output_tokens": out_tok, "max_tokens": max_tokens,
                "chars": len(text), "truncated": truncated, "text": text,
            })
            if truncated:
                print(f"  ⚠️ TRUNCATED: {fm} finish_reason=length "
                      f"(output_tokens={out_tok}, {len(text)} chars) — treating as FAILED")
                return None, fm, [f"TRUNCATED: {fm} finish_reason=length output_tokens={out_tok}"]
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
        except json.JSONDecodeError as _first_err:
            pass

        # Repair strategy 1: the most common LLM failure is an unescaped double-quote
        # inside a string value in a later section, which makes json.loads fail even though
        # all earlier sections are valid.  Walk *backwards* from the first parse error
        # position (or the full length) looking for the last complete top-level key whose
        # value closed cleanly, then close the outer object there.
        try:
            # Re-run the first parse to get the error position, then progressively shrink
            # from that position looking for a clean close of the outer '{'.
            import re as _re
            err_pos = _first_err.pos if hasattr(_first_err, 'pos') and _first_err.pos else len(raw)
            # Try closing at each top-level key boundary before the error
            # A top-level key boundary looks like:  ..."lastvalue", "nextkey":
            # We find the last comma that separates two top-level keys before err_pos.
            search_zone = raw[:err_pos]
            # Find all positions of pattern  },"  or  ","  at approximately depth-1
            for m in reversed(list(_re.finditer(r'[}\]"]\s*,\s*"', search_zone))):
                trunc = raw[:m.start() + 1]  # include the } or " char before the comma
                trunc += "}" * (trunc.count("{") - trunc.count("}"))
                try:
                    a = json.loads(trunc)
                    a["model_used"] = model
                    return a, None
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

        # Repair strategy 2: find last } and truncate (original approach)
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


def _cl(text):
    """Apply clean_latex to a string; return '' for non-strings."""
    if isinstance(text, str):
        return clean_latex(text)
    return ""


# ══════════════════════════════════════════════════════════════
# SHARED HELPERS (survive both v1 and v2; used by check_prices.py / app.py)
# ══════════════════════════════════════════════════════════════

def thesis_check(ticker, company, original_metrics, original_thesis,
                 current_metrics, model="claude-opus-4-7",
                 free_models=None):
    """Thesis-integrity check for tracked stocks. Called by check_prices.py."""
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


class LLMCallCeilingError(Exception):
    """
    Raised by run_pipeline when a required LLM pass (Pass 1 or Pass 2) would
    exceed MAX_PIPELINE_AI_CALLS. Hard stop — no silent skip.
    """
    def __init__(self, calls_used: int, ceiling: int):
        self.calls_used = calls_used
        self.ceiling = ceiling
        super().__init__(
            f"LLM call ceiling hit: {calls_used} calls already used against "
            f"a ceiling of {ceiling}; cannot start another required pass."
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

    # macro_drivers: must be a dict with exactly keys A, B, C (not a list)
    mds = pass1.get("macro_drivers")
    if isinstance(mds, list):
        hard.append(
            "macro_drivers must be a dict keyed by A, B, C — not a list. "
            'Use: {"A": {"label": ..., "narrative": ...}, "B": {...}, "C": {...}}'
        )
    elif not isinstance(mds, dict):
        hard.append("macro_drivers wrong type: expected dict with keys A, B, C")
    elif set(mds.keys()) != {"A", "B", "C"}:
        hard.append(
            f"macro_drivers must have exactly keys A, B, C, got {set(mds.keys())}"
        )
    else:
        for did, md in mds.items():
            if not isinstance(md, dict):
                soft.append(f"macro_driver {did}: expected dict value, got {type(md).__name__}")
            else:
                if not md.get("label"):
                    soft.append(f"macro_driver {did}: missing label")
                if not md.get("narrative"):
                    soft.append(f"macro_driver {did}: missing narrative")

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

    # catalysts: 3-6 entries with required fields; empty list treated same as missing
    cats = pass1.get("catalysts", [])
    if "catalysts" in pass1 and len(cats) == 0:
        soft.append(
            "catalysts was empty — you must provide at least 3 specific dated catalyst entries"
        )
    elif len(cats) < 3:
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
            "{current_date}":      datetime.now().strftime("%Y-%m-%d"),
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
    raw, model, errors = run_ai(_build_messages(), max_tokens=PASS1_MAX_TOKENS)
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
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=PASS1_MAX_TOKENS)
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
        _event_count_errors = [
            e for e in hard if "too few" in e or "≥ 2 events" in e
        ]
        _event_guidance = ""
        if _event_count_errors:
            _event_guidance = (
                "\n\nEVENT COUNT GUIDANCE: You produced too few events. "
                "Each of the three drivers (A, B, C) MUST have at least 2 events — "
                "one bull-outcome and one bear-outcome at minimum — for 6 events total. "
                "If recent news does not provide direct evidence for a driver, construct events "
                "from the driver structural logic: every driver has a plausible positive outcome "
                "(the driver plays out favorably) and a plausible negative outcome (the driver "
                "disappoints), regardless of whether a specific news article exists. Base the "
                "revenue and margin assumptions on the segment data and the company business model. "
                "EXPAND your previous output — keep all valid events you already produced and ADD "
                "events to reach the minimum. Do not remove or shrink existing events."
            )
        corrective = (
            "CRITICAL ERRORS — the following must be fixed or the output cannot be used:\n"
            + "\n".join(f"  - {e}" for e in hard)
            + _event_guidance
            + "\n\nRe-emit the complete corrected JSON. Do not omit any fields."
        )
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=PASS1_MAX_TOKENS)
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
        raw2, model2, errs2 = run_ai(_build_messages(corrective), max_tokens=PASS1_MAX_TOKENS)
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
    # New sections added in pass2-prompt-schema-expansion
    "business_overview", "revenue_architecture",
    "growth_drivers_and_moats", "factor_analysis",
    "valuation_vs_expectations", "sensitivity_check",
    "margin_analysis", "competitive_position",
    "scenario_analysis_extended",
)
_PASS2_SCENARIO_KEYS  = ("bull", "base", "bear")
_PASS2_DRIVER_KEYS    = ("A", "B", "C")
_PASS2_FORBIDDEN      = ("Sharpe", "DEGRADED", "capture ratio")

# Qualitative sections exempt from Pass 3 citation checks
_PASS2_QUALITATIVE_SECTIONS = frozenset({
    "concentration_and_dependencies",
    "competitive_position",
    "growth_drivers_and_moats",
    "business_overview",
})


def _build_pass2_body(pass2: dict) -> str:
    """Concatenate all narrative string sections for word count / forbidden token audit."""
    parts: list[str] = []
    for k in (
        "business_overview", "revenue_architecture",
        "growth_drivers_and_moats", "margin_analysis",
        "competitive_position", "valuation_vs_expectations",
        "sensitivity_check",
        "investment_thesis", "reverse_dcf_commentary",
        "financial_health", "recommendation_rationale", "conclusion",
    ):
        v = pass2.get(k, "")
        if isinstance(v, str) and v:
            parts.append(v)

    # concentration_and_dependencies: extract string sub-fields
    c_and_d = pass2.get("concentration_and_dependencies")
    if isinstance(c_and_d, dict):
        for sub in ("geographic_exposure", "top_customer_concentration",
                    "supply_chain_dependencies", "relationships_at_risk"):
            v = c_and_d.get(sub, "")
            if isinstance(v, str) and v:
                parts.append(v)

    # factor_analysis: extract outcome descriptions from the list
    fa = pass2.get("factor_analysis")
    if isinstance(fa, list):
        for item in fa:
            if isinstance(item, dict):
                for oc in (item.get("outcomes") or []):
                    if isinstance(oc, dict):
                        d = oc.get("description", "")
                        if isinstance(d, str) and d:
                            parts.append(d)

    # scenario_analysis_extended: extract string values from nested dicts
    sae = pass2.get("scenario_analysis_extended")
    if isinstance(sae, dict):
        for sc in _PASS2_SCENARIO_KEYS:
            sc_dict = sae.get(sc)
            if isinstance(sc_dict, dict):
                for sub in ("segment_revenue_note", "headwind_tailwind_summary",
                            "valuation_rationale"):
                    v = sc_dict.get(sub, "")
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


def _validate_pass2_v2(pass2: dict, math: dict | None = None) -> tuple:
    """
    Validate §5.4 pass2 report dict. Returns (soft_errors, hard_errors).

    hard_errors — missing required sections, forbidden vocabulary present,
                  sbc_section absent when math.owner_earnings is non-null.
    soft_errors — word count > 4500, missing optional sections.

    math: optional §5.3 math dict. When provided, used to gate sbc_section check.
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
    if wc > 7000:
        soft.append(f"word count {wc} exceeds 7000")

    sc_dict = pass2.get("scenario_commentary") or {}
    for sc in _PASS2_SCENARIO_KEYS:
        if not sc_dict.get(sc):
            soft.append(f"missing scenario_commentary.{sc}")

    dn_dict = pass2.get("driver_narratives") or {}
    missing_dns = [did for did in _PASS2_DRIVER_KEYS if not dn_dict.get(did)]
    if missing_dns:
        if len(missing_dns) == 1:
            missing_str = missing_dns[0]
        elif len(missing_dns) == 2:
            missing_str = f"{missing_dns[0]} and {missing_dns[1]}"
        else:
            missing_str = ", ".join(missing_dns[:-1]) + " and " + missing_dns[-1]
        hard.append(
            f"driver_narratives for drivers {missing_str} are missing — you must include "
            "a narrative paragraph for every macro driver ID present in pass1.macro_drivers."
        )

    if not pass2.get("financial_health"):
        soft.append("missing financial_health section")

    # concentration_and_dependencies: soft only — qualitative data may be unavailable
    c_and_d = pass2.get("concentration_and_dependencies")
    if not c_and_d or not isinstance(c_and_d, dict):
        soft.append(
            "missing concentration_and_dependencies section — include geographic_exposure, "
            "top_customer_concentration, supply_chain_dependencies, relationships_at_risk "
            "(qualitative; label estimates as (estimate))"
        )

    # sbc_section: hard error when math.owner_earnings is non-null and section absent
    if math is not None and math.get("owner_earnings") is not None:
        if not pass2.get("sbc_section"):
            hard.append(
                "sbc_section is missing but math.owner_earnings is present — "
                "you must include the SBC owner-earnings section."
            )

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
    raw, model, errors = run_ai(_build_messages(), max_tokens=PASS2_MAX_TOKENS)
    if raw is None:
        raise Pass1ValidationError(errors or ["run_ai returned None (pass2 attempt 1)"])

    pass2, parse_err = parse_json_response(raw, model)
    if parse_err or pass2 is None:
        if max_passes <= 1:
            raise Pass1ValidationError([parse_err or "JSON parse failed (pass2 attempt 1)"])
        raw2, model2, _ = run_ai(
            _build_messages("PARSE ERROR: return ONLY a valid JSON object."),
            max_tokens=PASS2_MAX_TOKENS,
        )
        if raw2 is None:
            raise Pass1ValidationError(["run_ai returned None on parse-repair retry (pass2)"])
        pass2, pe2 = parse_json_response(raw2, model2)
        if pe2 or pass2 is None:
            raise Pass1ValidationError([pe2 or "JSON parse failed on repair retry (pass2)"])
        model = model2

    soft, hard = _validate_pass2_v2(pass2, math)

    if hard:
        if max_passes <= 1:
            raise Pass1ValidationError(hard)
        corrective = (
            "CRITICAL ERRORS — fix all before re-emitting:\n"
            + "\n".join(f"  - {e}" for e in hard)
            + "\n\nRe-emit the complete corrected JSON. No forbidden words. No omitted sections."
        )
        raw2, model2, _ = run_ai(_build_messages(corrective), max_tokens=PASS2_MAX_TOKENS)

        # Best-of the two attempts, ranked by completeness. "Best" = fewest missing
        # REQUIRED sections, then fewest total hard errors, then fewest soft. This
        # guarantees a more-complete retry is never discarded in favour of a
        # more-incomplete first attempt (the previous "keep first" bug).
        def _incompleteness(hs, ss):
            req_missing = sum(1 for e in hs if e.startswith("missing required section"))
            return (req_missing, len(hs), len(ss))

        candidates = [(pass2, soft, hard, model)]
        if raw2 is not None:
            p2r, pe_r = parse_json_response(raw2, model2)
            if not pe_r and p2r is not None:
                soft_r, hard_r = _validate_pass2_v2(p2r, math)
                candidates.append((p2r, soft_r, hard_r, model2))

        pass2, soft, hard, model = min(
            candidates, key=lambda c: _incompleteness(c[2], c[1])
        )

        # Fail loud: never ship an incomplete report. If even the best candidate
        # still has hard errors (e.g. a required section missing), refuse to ship.
        if hard:
            print(f"  Pass2 v2 FAILED after {max_passes} attempts "
                  f"(best candidate hard errors: {hard[:3]}) — refusing to ship")
            raise Pass1ValidationError(
                ["Pass 2 incomplete after retry — refusing to ship an incomplete report"] + hard
            )

    elif soft and max_passes >= 2:
        corrective = (
            "VALIDATION WARNINGS — please address:\n"
            + "\n".join(f"  - {e}" for e in soft)
            + "\n\nRe-emit the complete corrected JSON within 4500 total words."
        )
        raw2, model2, _ = run_ai(_build_messages(corrective), max_tokens=PASS2_MAX_TOKENS)
        if raw2 is not None:
            p2r, pe_r = parse_json_response(raw2, model2)
            if not pe_r and p2r is not None:
                soft_r, hard_r = _validate_pass2_v2(p2r, math)
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

_PASS3_FORBIDDEN = frozenset({"Sharpe", "DEGRADED", "capture ratio"})


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
# v2 PIPELINE ORCHESTRATOR (Phase G)
# ══════════════════════════════════════════════════════════════

def run_pipeline(ticker: str, baseline: dict) -> dict:
    """
    v2 three-pass pipeline orchestrator.

    Args:
        ticker:   stock ticker
        baseline: §5.1 baseline dict from calc_baseline() — all units per §5.1 contract
                  (fy_revenue in billions, shares_out in billions, etc.)

    Returns:
        Final report dict compatible with app.py render() under METHODOLOGY_VERSION='v2'.
    """
    current_price   = safe_float(baseline.get("current_price", 0))
    calls_remaining = MAX_PIPELINE_AI_CALLS  # decrement as calls are spent

    # ── Pass 1: §5.2 qualitative input pack ─────────────────────────────────
    if calls_remaining < 2:
        raise LLMCallCeilingError(MAX_PIPELINE_AI_CALLS - calls_remaining, MAX_PIPELINE_AI_CALLS)
    try:
        pass1           = run_pass1_foundation(ticker, baseline)
        calls_remaining -= 2   # up to 2 LLM calls internally
    except Pass1ValidationError as exc:
        return {
            "error":   "Pass 1 failed — check baseline data quality",
            "details": [str(exc)],
            "recommendation": "WATCH", "conviction": "Low", "model_used": "N/A",
            "scenario_math": _empty_scenario_math(),
            "pass3": {}, "data_quality_warnings": list(baseline.get("data_quality_warnings", []) or []),
        }

    # ── Catalysts fallback: focused call when pass1 returned < 3 catalysts ────
    # Budget: 1 additional LLM call (accounted for in MAX_PIPELINE_AI_CALLS = 7).
    # Non-blocking — failure leaves catalysts as-is without halting the pipeline.
    if len(pass1.get("catalysts", [])) < 3 and calls_remaining >= 1:
        company_name = baseline.get("company_name", ticker)
        _current_date = datetime.now().strftime("%Y-%m-%d")
        _cats_msgs = [
            {"role": "system",
             "content": (
                 f"You are a financial analyst. Return ONLY a JSON array of 3-6 catalysts "
                 f"for {ticker} ({company_name}) over the next 12 months. "
                 f"All catalyst dates must be strictly after {_current_date}; do not include "
                 f"events that have already occurred. "
                 'Each entry: {"date": "YYYY-QX or YYYY-MM", "event": "string", '
                 '"what_to_watch": "string"}. No prose, no wrapper object, just the array.'
             )},
            {"role": "user",
             "content": f"List 3-6 catalysts for {ticker} ({company_name}) as a JSON array."},
        ]
        _cats_raw, _, _ = run_ai(_cats_msgs, max_tokens=800)
        calls_remaining -= 1
        if _cats_raw:
            try:
                _stripped = _cats_raw.strip()
                if _stripped.startswith("```"):
                    _stripped = _stripped.split("\n", 1)[1] if "\n" in _stripped else _stripped[3:]
                if _stripped.endswith("```"):
                    _stripped = _stripped[:-3]
                if _stripped.startswith("json"):
                    _stripped = _stripped[4:]
                _cats = json.loads(_stripped.strip())
                if isinstance(_cats, list) and len(_cats) >= 3:
                    pass1 = {**pass1, "catalysts": _cats}
            except Exception:
                pass  # non-blocking; keep whatever catalysts we have

    # ── Peer enrichment: fetch live market metrics for Pass 1 peers ──────────
    # Order: baseline → Pass 1 → peer fetch → math (per Option B wiring)
    _peer_tickers = [
        p.get("ticker", "") for p in pass1.get("peer_set_enriched", [])
        if isinstance(p, dict) and p.get("ticker")
    ]
    if _peer_tickers:
        from fmp_api import fetch_peer_metrics
        baseline = {**baseline, "peer_set": fetch_peer_metrics(_peer_tickers)}

    # ── Math: deterministic, no LLM ─────────────────────────────────────────
    try:
        math = run_methodology_math(pass1, baseline)
    except Exception as exc:
        return {
            "error":   f"Math layer failed: {type(exc).__name__}: {exc}",
            "details": [str(exc)],
            "recommendation": "WATCH", "conviction": "Low", "model_used": "N/A",
            "scenario_math": _empty_scenario_math(),
            "pass3": {}, "data_quality_warnings": list(baseline.get("data_quality_warnings", []) or []),
        }

    # ── B1/B5 sanity: bull-below-current retry (1 extra LLM call) ────────────
    pt           = math.get("price_target", {})
    bull_mid_val = safe_float(pt.get("bull_mid", 0))
    bull_below   = current_price > 0 and bull_mid_val < current_price

    if bull_below and calls_remaining >= 1:
        hint = (
            f"IMPORTANT: your bull-case scenario produced a price target "
            f"({bull_mid_val:.2f}) below the current price ({current_price:.2f}). "
            "In a genuine bull case the primary growth driver (A) must resolve with "
            "meaningfully higher EPS or P/E re-rating. Revise driver A's bull-outcome "
            "so the resulting price target exceeds the current price."
        )
        try:
            pass1_retry      = run_pass1_foundation(ticker, baseline, max_passes=1, retry_hint=hint)
            calls_remaining -= 1
            math_retry       = run_methodology_math(pass1_retry, baseline)
            if safe_float(math_retry.get("price_target", {}).get("bull_mid", 0)) > current_price:
                pass1, math = pass1_retry, math_retry
                bull_below  = False
        except (Pass1ValidationError, Exception):
            pass   # keep original

    pt   = math.get("price_target", {})
    risk = math.get("risk", {})

    # ── Pass 2: §5.4 narrative ───────────────────────────────────────────────
    if calls_remaining < 2:
        raise LLMCallCeilingError(MAX_PIPELINE_AI_CALLS - calls_remaining, MAX_PIPELINE_AI_CALLS)
    try:
        pass2           = run_pass2_report(ticker, baseline, pass1, math)
        calls_remaining -= 2
    except Pass1ValidationError as exc:
        # Fail loud — never silently ship an incomplete narrative. Return an error
        # report (same shape as the Pass 1 failure path) so the app halts and shows
        # the failure rather than rendering a stub.
        print(f"  run_pipeline: Pass 2 FAILED ({exc}) — refusing to ship incomplete report")
        details = exc.args[0] if (exc.args and isinstance(exc.args[0], list)) else [str(exc)]
        return {
            "error":   "Pass 2 narrative incomplete — report withheld",
            "details": details,
            "recommendation": "WATCH", "conviction": "Low", "model_used": "N/A",
            "scenario_math": _empty_scenario_math(),
            "pass3": {}, "data_quality_warnings": list(baseline.get("data_quality_warnings", []) or []),
        }

    # ── Pass 3: §5.5 audit ───────────────────────────────────────────────────
    pass3_raw = run_pass3_audit(ticker, baseline, pass1, math, pass2,
                                calls_remaining=max(0, calls_remaining))

    return _assemble_pipeline_output(ticker, baseline, pass1, math, pass2, pass3_raw, bull_below)


def _normalize_macro_drivers(mds) -> dict:
    """
    Normalize macro_drivers to dict format {A: {...}, B: {...}, C: {...}}.

    Handles both the new dict format (pass-through) and legacy list-of-dicts format
    (converted) so downstream code is not broken during the transition period.
    """
    if isinstance(mds, dict):
        return mds
    if isinstance(mds, list):
        result = {}
        for d in mds:
            if isinstance(d, dict) and d.get("id") in ("A", "B", "C"):
                did = d["id"]
                result[did] = {k: v for k, v in d.items() if k != "id"}
        return result
    return {}


def _empty_scenario_math() -> dict:
    """Minimal scenario_math dict for error-path returns."""
    return {
        "final_probabilities": {"bull": 0.0, "base": 0.0, "bear": 0.0},
        "eps": {}, "price_target": {}, "scenario_revenue": {},
        "expected_value": 0, "expected_return": 0,
        "base_implied_return": 0, "prob_positive": 0,
        "upside_downside_ratio": None,
        "monotonicity_violation": False, "violation_msg": "",
        "bull_below_current": False, "bull_below_msg": "",
        "diagnostic": {}, "degraded_sections": [],
    }


def _assemble_pipeline_output(
    ticker: str,
    baseline: dict,
    pass1: dict,
    math: dict,
    pass2: dict,
    pass3_raw: dict,
    bull_below: bool,
) -> dict:
    """Assemble all pipeline layers into the final report dict render() expects."""
    current_price = safe_float(baseline.get("current_price", 0))
    pt            = math.get("price_target", {})
    risk          = math.get("risk", {})
    joint_probs   = math.get("joint_probs", {})
    pe_band_d     = math.get("pe_band", {})

    # ── Derived scalars ──────────────────────────────────────────────────────
    # bear_mid is the probability-weighted bear PRICE (single source of truth for
    # EV/risk).  bear_low is a display-only range extreme (bear_mid × 0.85) and is
    # NEVER used in EV or risk — that divergence was the two-EV bug.
    bull_mid  = safe_float(pt.get("bull_mid", 0))
    base_mid  = safe_float(pt.get("base_mid", 0))
    bear_mid  = safe_float(pt.get("bear_mid", pt.get("bear", 0)))
    bear_low  = safe_float(pt.get("bear_low", 0))

    ev_val          = safe_float(risk.get("ev", math.get("expected_value", 0)))
    expected_return = safe_float(risk.get("expected_return_pct", 0))
    prob_loss       = safe_float(risk.get("prob_loss", 0))
    prob_positive   = round(max(0.0, 1.0 - prob_loss), 4)
    base_implied    = safe_float(math.get("base_case_return",
                        round(base_mid / current_price - 1, 4) if current_price > 0 and base_mid > 0 else 0.0))

    # Upside/downside ratio — uses the same bear_mid the EV uses (no divergence).
    price_map    = {"bull": bull_mid, "base": base_mid, "bear": bear_mid}
    upside_sum   = sum(
        joint_probs.get(s, 0) * (price_map[s] / current_price - 1)
        for s in ("bull", "base", "bear")
        if current_price > 0 and price_map.get(s, 0) > current_price
    )
    downside_sum = sum(
        joint_probs.get(s, 0) * (price_map[s] / current_price - 1)
        for s in ("bull", "base", "bear")
        if current_price > 0 and price_map.get(s, 0) < current_price
    )
    if downside_sum < 0:
        ud_ratio = round(abs(upside_sum / downside_sum), 4)
    elif upside_sum > 0:
        ud_ratio = None   # effectively infinite
    else:
        ud_ratio = 0

    # ── Sanity flags ─────────────────────────────────────────────────────────
    mono_viol = (
        bull_mid > 0 and base_mid > 0 and bear_mid > 0
        and not (bull_mid > base_mid > bear_mid)
    )
    mono_msg      = (f"Non-monotonic targets: bull={bull_mid:.2f} / base={base_mid:.2f} / bear={bear_mid:.2f}." if mono_viol else "")
    bull_below_msg = (f"Bull target ({bull_mid:.2f}) below current price ({current_price:.2f})." if bull_below else "")

    # ── Recommendation + conviction (deterministic) ──────────────────────────
    # rec_label comes from run_methodology_math (v2 recommendation() pure function).
    # conviction is derived inline from already-computed scalars; same thresholds
    # as the v1 derive_recommendation that this replaces.
    rec_label = math.get("recommendation", "WATCH")
    _ud = safe_float(ud_ratio) if ud_ratio is not None else float("inf")
    if _ud > 3.0 and prob_positive > 0.70:
        conviction = "High"
    elif _ud < 1.5 or (0.40 <= prob_positive <= 0.60):
        conviction = "Low"
    else:
        conviction = "Medium"

    # ── P/E midpoints per scenario (for scenario_inputs) ─────────────────────
    bull_pe_mid = round((pe_band_d.get("bull_low", 0) + pe_band_d.get("bull_high", 0)) / 2, 2)
    base_pe_mid = round((pe_band_d.get("base_low", 0) + pe_band_d.get("base_high", 0)) / 2, 2)
    bear_pe_mid = round((pe_band_d.get("bear_low", 0) + pe_band_d.get("bear_high", 0)) / 2, 2)

    baseline_om  = safe_float(baseline.get("fy_op_margin") or baseline.get("operating_margin") or 0.20)
    events_v2    = pass1.get("events", [])

    def _avg_margin(outcome: str) -> float:
        evs = [e for e in events_v2 if e.get("outcome") == outcome]
        if not evs:
            return baseline_om
        rev = sum(abs(safe_float(e.get("revenue_at_risk_high", 0))) for e in evs)
        if not rev:
            return baseline_om
        return round(
            sum(safe_float(e.get("op_margin_to_apply") or baseline_om) * abs(safe_float(e.get("revenue_at_risk_high", 0))) for e in evs) / rev,
            4,
        )

    scenario_inputs = {
        "bull": {"op_margin": _avg_margin("bull"), "pe_multiple_pick": bull_pe_mid},
        "base": {"op_margin": _avg_margin("base"), "pe_multiple_pick": base_pe_mid},
        "bear": {"op_margin": _avg_margin("bear"), "pe_multiple_pick": bear_pe_mid},
    }

    # ── scenario_math subdict (render accesses as `sm`) ──────────────────────
    scenario_math = {
        **math,                          # v2 native fields
        "final_probabilities": joint_probs,
        "eps":                 math.get("scenario_eps", {}),
        "price_target": {
            **pt,
            "bull": bull_mid,            # alias: scenario tabs (probability-weighted mid)
            "base": base_mid,            # alias: render_track_box + scenario tabs
            "bear": bear_mid,            # alias: scenario tabs — MID (EV price), not range low
            "bear_low": bear_low,        # display-only range extreme
        },
        "scenario_revenue":    math.get("scenario_revenue", {}),
        "expected_value":      ev_val,
        "expected_return":     expected_return,
        "base_implied_return": base_implied,
        "prob_positive":       prob_positive,
        "upside_downside_ratio": ud_ratio,
        "monotonicity_violation": mono_viol,
        "violation_msg":       mono_msg,
        "bull_below_current":  bull_below,
        "bull_below_msg":      bull_below_msg,
        "diagnostic":          {},       # stub; fundamentals signal check not wired
        "degraded_sections":   [],
    }

    # ── Bridge pass3 v2 keys → render field names ─────────────────────────────
    citation_errors = (pass3_raw or {}).get("citation_errors", [])
    pass3 = {
        **(pass3_raw or {}),
        "consistency_flags": [
            {"field": e.get("field", ""), "issue": e.get("issue", e.get("context", "")), "severity": e.get("severity", "warn")}
            for e in citation_errors
        ],
        "numbers_outside_source": [],
        "tone_label_mismatch":    not (pass3_raw or {}).get("tone_label_ok", True),
        "tone_label_evidence":    (pass3_raw or {}).get("tone_label_evidence", ""),
    }

    # ── Bridge pass1 catalysts → render format (adds bull_signal / bear_signal) ─
    catalysts = [
        {**cat, "bull_signal": cat.get("what_to_watch", ""), "bear_signal": ""}
        for cat in pass1.get("catalysts", []) if isinstance(cat, dict)
    ]

    # ── Bridge segments_enriched → render segments format ────────────────────
    segments = [
        {
            "name":            s.get("name", ""),
            "current_revenue": s.get("fy_revenue"),
            "pct_of_total":    s.get("share_pct"),
            "gross_margin":    s.get("gross_margin"),
            "yoy_growth":      s.get("growth_yoy"),
            "trajectory":      "",
            "primary_driver":  "",
        }
        for s in pass1.get("segments_enriched", []) if isinstance(s, dict)
    ]

    peer_tickers = [p.get("ticker", "") for p in pass1.get("peer_set_enriched", []) if isinstance(p, dict)]

    return {
        # Deterministic
        "recommendation": rec_label,
        "conviction":     conviction,
        "model_used":     pass2.get("model_used", ""),
        # Narrative (v2 pass2 output schema)
        "investment_thesis":          _cl(pass2.get("investment_thesis", "")),
        "reverse_dcf_commentary":     _cl(pass2.get("reverse_dcf_commentary", "")),
        "recommendation_rationale":   _cl(pass2.get("recommendation_rationale", "")),
        "conclusion":                 _cl(pass2.get("conclusion", "")),
        "financial_health":           _cl(pass2.get("financial_health", "")),
        "scenario_commentary":        {k: _cl(v) for k, v in (pass2.get("scenario_commentary") or {}).items()},
        "driver_narratives":          {k: _cl(v) for k, v in (pass2.get("driver_narratives") or {}).items()},
        "business_overview":          _cl(pass2.get("business_overview", "")),
        "revenue_architecture":       _cl(pass2.get("revenue_architecture", "")),
        "growth_drivers_and_moats":   _cl(pass2.get("growth_drivers_and_moats", "")),
        "margin_analysis":            _cl(pass2.get("margin_analysis", "")),
        "competitive_position":       _cl(pass2.get("competitive_position", "")),
        "valuation_vs_expectations":  _cl(pass2.get("valuation_vs_expectations", "")),
        "sensitivity_check":          _cl(pass2.get("sensitivity_check", "")),
        "concentration_and_dependencies": pass2.get("concentration_and_dependencies") or {},
        "factor_analysis":            pass2.get("factor_analysis") or [],
        "scenario_analysis_extended": pass2.get("scenario_analysis_extended") or {},
        "headwind_narrative": "", "tailwind_narrative": "",
        "market_pricing_commentary": "",
        # Structured from pass1
        "segments":        segments,
        "peer_tickers":    peer_tickers,
        "catalysts":       catalysts,
        "scenario_inputs": scenario_inputs,
        "macro_drivers":   _normalize_macro_drivers(pass1.get("macro_drivers")),
        "drivers":         [],    # stub; v2 events not yet rendered as driver cards
        "headwinds":       math.get("headwinds", []),
        "tailwinds":       math.get("tailwinds", []),
        "scenario_segment_revenue": math.get("scenario_segment_revenue", None),
        "ev_formula_string": math.get("ev_formula_string", ""),
        "concentration":   {},
        "monitoring_kpis": [],
        # Math + audit
        "scenario_math":   scenario_math,
        "python_outputs":  {},
        "pass3":           pass3,
        # QA
        "data_quality_warnings": list(baseline.get("data_quality_warnings", []) or []),
        "rec_override_reason":   "",
    }



