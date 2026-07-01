"""
Deterministic audit checks extracted from the Pass-3 pipeline as standalone
pure functions.  No LLM calls, no I/O, no side effects.

These functions can be called against any (pass2, math) pair to get
structured audit signals without spending API credits.

Pass 3 itself (`run_pass3_audit` in ai.py) is NOT modified — this module
supplements it with a credit-free deterministic layer.
"""
from __future__ import annotations

import json
import re
from typing import Any


# ── Forbidden vocabulary ─────────────────────────────────────────────────────
# Copied from ai._PASS3_FORBIDDEN (the Pass-3 banned-token set).
# DISCREPANCY NOTE: smoke_harness.py bans the shorter string "capture" (not
# "capture ratio"), so it fires on any sentence containing the word "capture".
# This module uses the stricter Pass-3 set to stay consistent with the
# audit layer. DO NOT reconcile the two lists here — flag to human if either
# list needs to change.
FORBIDDEN_VOCAB: frozenset[str] = frozenset({"Sharpe", "DEGRADED", "capture ratio"})

# ── Word count ───────────────────────────────────────────────────────────────
# Pass 3 does not enforce a word-count ceiling; the deterministic gate here
# mirrors the smoke-harness pairing: pass2.body ≤ 4500 words.
# (smoke_harness.check_word_count reads the pre-assembled "body" field and
# rejects anything > 4500.)
WORD_COUNT_CEILING: int = 4500

# ── Citation: patterns for pipeline-precision numeric figures ────────────────
# Matches dollar amounts ($1,222.65) and bare decimals with ≥2 places (0.2486).
# Two or more decimal places is the threshold because pipeline outputs are
# always computed to at least 2dp; bare integers and 1dp numbers are too
# common in qualitative prose to check reliably.
_FIGURE_RE = re.compile(r"\$?([\d,]+\.\d{2,})")

# ── Citation: consensus-divergent banner patterns ────────────────────────────
# When math.consensus_divergent is True the LLM is instructed to acknowledge
# it in recommendation_rationale.  These patterns catch the expected phrases.
_DIVERGENCE_PATTERNS = re.compile(
    r"(consensus_divergent|divergence|divergent|bull.{0,40}below.{0,20}current)",
    re.IGNORECASE,
)


# ── Public API ───────────────────────────────────────────────────────────────

def forbidden_vocab_check(narrative_text: str) -> list[dict[str, str]]:
    """
    Scan *narrative_text* for FORBIDDEN_VOCAB tokens.

    Returns a list of hit dicts:
        {"token": str, "context": str}  — one entry per occurrence.
    Empty list means no forbidden tokens found (check passes).
    """
    hits: list[dict[str, str]] = []
    for token in FORBIDDEN_VOCAB:
        start = 0
        while True:
            idx = narrative_text.find(token, start)
            if idx < 0:
                break
            ctx_start = max(0, idx - 30)
            ctx_end   = min(len(narrative_text), idx + len(token) + 30)
            hits.append({
                "token":   token,
                "context": narrative_text[ctx_start:ctx_end].strip(),
            })
            start = idx + 1
    return hits


def word_count_check(narrative_text: str) -> dict[str, Any]:
    """
    Count words in *narrative_text* and compare against WORD_COUNT_CEILING.

    Caller is responsible for passing the right text — use pass2.get("body", "")
    to mirror the smoke-harness check.

    Returns:
        {"word_count": int, "pass": bool, "ceiling": int}
    """
    n = len(narrative_text.split())
    return {"word_count": n, "pass": n <= WORD_COUNT_CEILING, "ceiling": WORD_COUNT_CEILING}


def section_gating_check(
    math_dict: dict[str, Any],
    pass2_dict: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Check that pass2 sections are present (or absent) in accordance with math flags.

    Two gates (no others — distribution_skew_flag does not exist in the math contract):

    Gate 1 — sbc_section ↔ owner_earnings
        • math.owner_earnings non-null  → pass2.sbc_section must be present and truthy.
        • math.owner_earnings is null   → pass2.sbc_section must be absent or falsy.

    Gate 2 — consensus-divergent banner ↔ consensus_divergent
        • math.consensus_divergent=True → pass2.recommendation_rationale must mention
          the divergence (pattern: "consensus_divergent", "divergent/divergence", or
          "bull … below … current").
        • math.consensus_divergent=False → no constraint on recommendation_rationale.

    Returns a list of violation dicts:
        {"gate": str, "direction": str, "issue": str}
    Empty list means all gates pass.
    """
    violations: list[dict[str, str]] = []

    # ── Gate 1: sbc_section ──────────────────────────────────────────────────
    owner_earnings_present = math_dict.get("owner_earnings") is not None
    sbc_section_present    = bool(pass2_dict.get("sbc_section"))

    if owner_earnings_present and not sbc_section_present:
        violations.append({
            "gate":      "sbc_section",
            "direction": "missing",
            "issue":     "math.owner_earnings is non-null but pass2.sbc_section is absent",
        })
    elif not owner_earnings_present and sbc_section_present:
        violations.append({
            "gate":      "sbc_section",
            "direction": "unexpected",
            "issue":     "pass2.sbc_section is present but math.owner_earnings is null",
        })

    # ── Gate 2: consensus-divergent banner ───────────────────────────────────
    if math_dict.get("consensus_divergent", False):
        rationale = pass2_dict.get("recommendation_rationale") or ""
        if not _DIVERGENCE_PATTERNS.search(rationale):
            violations.append({
                "gate":      "consensus_divergent_banner",
                "direction": "missing",
                "issue":     (
                    "math.consensus_divergent is True but pass2.recommendation_rationale "
                    "does not acknowledge the divergence (expected: 'consensus_divergent', "
                    "'divergent/divergence', or 'bull … below … current')"
                ),
            })

    return violations


def citation_check(
    narrative_text: str,
    math_dict: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Deterministic citation gate.

    Extracts every numeric figure with ≥2 decimal places from *narrative_text*
    (the patterns most likely to be pipeline-sourced) and verifies that each
    appears verbatim somewhere in the math_dict's serialized form, including
    the pre-formatted ev_formula_string.

    Returns a list of miss dicts:
        {"figure": str, "context": str}
    Empty list means every extracted figure can be traced back to the math.

    LIMITATIONS (known):
    • Numbers from baseline or pass1 cited in narrative will be flagged as
      misses — the check has no visibility into those sources.
    • Rounded figures (e.g. "$507" from expected_value=507.48) will be flagged.
    • Qualitative-section figures are not excluded here (the LLM Pass 3 skips them).
    Use this as a structural signal, not a replacement for the LLM audit.
    """
    cite_blob = _build_cite_blob(math_dict)
    misses: list[dict[str, str]] = []
    for figure, context in _extract_figures(narrative_text):
        if figure not in cite_blob:
            misses.append({"figure": figure, "context": context})
    return misses


# ── Internal helpers ─────────────────────────────────────────────────────────

def _build_cite_blob(math_dict: dict[str, Any]) -> str:
    """
    Build a single searchable string from all math_dict values.

    Includes:
    • json.dumps(math_dict) — covers all values in their serialized form.
    • Extra formatted representations of every float (X.XX, X.XXXX, $X.XX)
      to handle minor formatting differences.
    • ev_formula_string verbatim (already inside json.dumps, but duplicated
      for clarity as the primary cite-source string).
    """
    parts: list[str] = [json.dumps(math_dict)]

    def _walk(obj: Any) -> None:
        if isinstance(obj, float) and not isinstance(obj, bool):
            parts.append(f"{obj:.2f}")
            parts.append(f"{obj:.4f}")
            parts.append(f"${obj:.2f}")
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(math_dict)
    return " ".join(parts)


def _extract_figures(text: str) -> list[tuple[str, str]]:
    """
    Extract pipeline-precision numeric figures from *text*.

    Only matches numbers with ≥2 decimal places ($1,222.65 or 0.2486).
    Strips leading "$" and commas to produce a canonical form for lookup.
    Returns list of (canonical_figure, context_snippet) tuples.
    """
    results: list[tuple[str, str]] = []
    for m in _FIGURE_RE.finditer(text):
        canonical = m.group(1).replace(",", "")
        try:
            float(canonical)
        except ValueError:
            continue
        ctx_start = max(0, m.start() - 40)
        ctx_end   = min(len(text), m.end() + 40)
        results.append((canonical, text[ctx_start:ctx_end].strip()))
    return results
