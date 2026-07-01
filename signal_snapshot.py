"""
LLM-signal snapshot machinery (Piece 4).

capture_signals(ticker, pass2_result, math_dict)
    Extracts purely structural signals from a completed pass2 + math pair —
    no LLM calls, no FMP calls, no I/O beyond returning a dict.

save_signals(ticker, signals, golden_dir)
    Writes the signals dict to a golden JSON file.

compare_signals(ticker, signals, golden_dir) → list[str]
    Loads the committed golden and returns a list of diff strings.
    Returns [] when they match.

The snapshot goldens live under tests/fixtures/signal_goldens/.
Any test that compares against a golden skips gracefully when the golden is
missing (the first live run populates it).

Mark every test that calls the live pipeline or any live FMP/API endpoint
with @pytest.mark.live so that `python -m pytest -q -m "not live"` is clean.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from audit_checks import (
    citation_check,
    forbidden_vocab_check,
    section_gating_check,
    word_count_check,
)

_DEFAULT_GOLDEN_DIR = pathlib.Path(__file__).parent / "tests" / "fixtures" / "signal_goldens"

# Required pass2 section keys (mirrors _PASS2_REQUIRED_SECTIONS in ai.py)
_REQUIRED_SECTIONS = (
    "investment_thesis", "reverse_dcf_commentary", "recommendation_rationale",
    "conclusion", "revenue_architecture",
    "valuation_vs_expectations", "sensitivity_check",
    "margin_analysis", "competitive_position",
    "scenario_analysis_extended",
)


def capture_signals(
    ticker: str,
    pass2_result: dict[str, Any],
    math_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract structured audit signals from a pass2 result and math dict.

    No live calls.  All inputs must already be computed.

    Returns a signals dict with:
      ticker             — the ticker symbol (provenance anchor)
      sections_present   — sorted list of section keys present in pass2
      sections_missing   — required sections that are absent
      word_count         — int: word count of pass2.body
      word_count_pass    — bool: word_count ≤ WORD_COUNT_CEILING
      forbidden_vocab    — list of {token, context} dicts (empty = clean)
      citation_misses    — list of {figure, context} dicts (figures not in math)
      section_gate_violations — list of {gate, direction, issue} dicts
      pass3_audit_clean  — bool: True iff forbidden_vocab and section gates both pass
    """
    body = pass2_result.get("body", "") or ""

    wc_result  = word_count_check(body)
    fv_hits    = forbidden_vocab_check(body)
    cite_misses = citation_check(body, math_dict)
    gate_viols  = section_gating_check(math_dict, pass2_result)

    sections_present = sorted(
        k for k in _REQUIRED_SECTIONS if pass2_result.get(k)
    )
    sections_missing = sorted(
        k for k in _REQUIRED_SECTIONS if not pass2_result.get(k)
    )

    audit_clean = (not fv_hits) and (not gate_viols)

    return {
        "ticker":                   ticker,
        "sections_present":         sections_present,
        "sections_missing":         sections_missing,
        "word_count":               wc_result["word_count"],
        "word_count_pass":          wc_result["pass"],
        "forbidden_vocab":          fv_hits,
        "citation_misses":          cite_misses,
        "section_gate_violations":  gate_viols,
        "pass3_audit_clean":        audit_clean,
    }


def save_signals(
    ticker: str,
    signals: dict[str, Any],
    golden_dir: pathlib.Path = _DEFAULT_GOLDEN_DIR,
) -> pathlib.Path:
    """
    Write *signals* to tests/fixtures/signal_goldens/{ticker}_signals.json.

    Creates the directory if needed.  Returns the path written.
    """
    golden_dir.mkdir(parents=True, exist_ok=True)
    path = golden_dir / f"{ticker}_signals.json"
    path.write_text(json.dumps(signals, indent=2, sort_keys=True))
    return path


def compare_signals(
    ticker: str,
    signals: dict[str, Any],
    golden_dir: pathlib.Path = _DEFAULT_GOLDEN_DIR,
) -> list[str]:
    """
    Compare *signals* against the committed golden for *ticker*.

    Returns a list of human-readable diff strings.  Empty list means identical.
    Raises FileNotFoundError if the golden is missing (callers should catch and
    skip — see tests_signal_snapshot.py).
    """
    path = golden_dir / f"{ticker}_signals.json"
    golden = json.loads(path.read_text())

    diffs: list[str] = []
    _diff_recursive(signals, golden, path="root", diffs=diffs)
    return diffs


def _diff_recursive(
    actual: Any,
    expected: Any,
    path: str,
    diffs: list[str],
) -> None:
    """Recursively collect diff strings between actual and expected."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        all_keys = set(expected) | set(actual)
        for k in sorted(all_keys):
            _diff_recursive(
                actual.get(k),
                expected.get(k),
                path=f"{path}.{k}",
                diffs=diffs,
            )
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            diffs.append(
                f"{path}: list length {len(actual)} != {len(expected)}"
            )
            return
        for i, (a, e) in enumerate(zip(actual, expected)):
            _diff_recursive(a, e, path=f"{path}[{i}]", diffs=diffs)
    else:
        if actual != expected:
            diffs.append(f"{path}: got {actual!r}, expected {expected!r}")
