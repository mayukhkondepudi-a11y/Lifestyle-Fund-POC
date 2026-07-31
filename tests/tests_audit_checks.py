"""
Unit tests for audit_checks.py — all deterministic, no live calls, no I/O.

Each function is exercised with hand-built positive/negative dicts so the
expected outcomes are obvious without running any pipeline code.
"""
from __future__ import annotations

import pytest

from audit_checks import (
    FORBIDDEN_VOCAB,
    WORD_COUNT_CEILING,
    citation_check,
    forbidden_vocab_check,
    field_path_litter_check,
    section_gating_check,
    word_count_check,
)


# ════════════════════════════════════════════════════════════════════════════
# field_path_litter_check
# ════════════════════════════════════════════════════════════════════════════

class TestFieldPathLitterCheck:
    def test_clean_prose_passes(self):
        text = ("The recommendation is BUY, with a base-case return of 14.6% and a "
                "base target of 414.45 built on FY+2 EPS of 14.08 at a 28.9x multiple.")
        assert field_path_litter_check(text) == []

    def test_bare_json_name_flagged(self):
        text = "The implied CAGR is 49 percent, but math_json flags it as unreliable."
        hits = field_path_litter_check(text)
        assert len(hits) == 1
        assert hits[0]["path"] == "math_json"
        assert "unreliable" in hits[0]["context"]

    def test_dotted_paths_flagged_with_strings(self):
        text = ("eps_impact reaches 1.3051 per math_json.tailwinds and the bear side "
                "per math_json.headwinds; segments per baseline_json.segments are absent.")
        paths = {h["path"] for h in field_path_litter_check(text)}
        assert paths == {"math_json.tailwinds", "math_json.headwinds", "baseline_json.segments"}

    def test_all_three_source_names_caught(self):
        text = "See math_json, pass1_json, and baseline_json for the values."
        paths = {h["path"] for h in field_path_litter_check(text)}
        assert paths == {"math_json", "pass1_json", "baseline_json"}

    def test_hit_is_hard_failure_signal(self):
        # Any hit is non-empty ⇒ the caller treats it as a hard audit failure.
        assert field_path_litter_check("value per math_json.scenario_margin here") != []


# ════════════════════════════════════════════════════════════════════════════
# forbidden_vocab_check
# ════════════════════════════════════════════════════════════════════════════

class TestForbiddenVocabCheck:
    def test_clean_text_returns_empty(self):
        text = "Expected value is $507.48. BUY with high conviction."
        assert forbidden_vocab_check(text) == []

    def test_sharpe_detected(self):
        text = "The Sharpe ratio is 1.2, indicating strong risk-adjusted returns."
        hits = forbidden_vocab_check(text)
        assert len(hits) == 1
        assert hits[0]["token"] == "Sharpe"

    def test_degraded_detected(self):
        text = "The pipeline returned a DEGRADED report due to missing data."
        hits = forbidden_vocab_check(text)
        assert len(hits) == 1
        assert hits[0]["token"] == "DEGRADED"

    def test_capture_ratio_detected(self):
        text = "The upside capture ratio of 1.4 justifies the risk."
        hits = forbidden_vocab_check(text)
        assert len(hits) == 1
        assert hits[0]["token"] == "capture ratio"

    def test_bare_capture_not_flagged(self):
        # "capture" alone is NOT in FORBIDDEN_VOCAB (only "capture ratio").
        # smoke_harness.py uses the looser "capture" — this module uses the
        # stricter Pass-3 list.  Both behaviors are intentional; do not reconcile.
        text = "The model was able to capture the AI tailwind effectively."
        assert forbidden_vocab_check(text) == []

    def test_multiple_hits_in_one_text(self):
        text = "Sharpe looks fine. But this is DEGRADED output using the capture ratio."
        hits = forbidden_vocab_check(text)
        tokens_found = {h["token"] for h in hits}
        assert tokens_found == {"Sharpe", "DEGRADED", "capture ratio"}

    def test_hit_dict_has_context(self):
        text = "This is a DEGRADED result from the pipeline."
        hits = forbidden_vocab_check(text)
        assert "DEGRADED" in hits[0]["context"]

    def test_forbidden_vocab_constant_matches_pass3(self):
        # Verify the constant is in sync with what we know ai._PASS3_FORBIDDEN contains.
        assert "Sharpe" in FORBIDDEN_VOCAB
        assert "DEGRADED" in FORBIDDEN_VOCAB
        assert "capture ratio" in FORBIDDEN_VOCAB
        assert "capture" not in FORBIDDEN_VOCAB  # bare "capture" is NOT in this set


# ════════════════════════════════════════════════════════════════════════════
# word_count_check
# ════════════════════════════════════════════════════════════════════════════

class TestWordCountCheck:
    def test_empty_text_passes(self):
        result = word_count_check("")
        assert result["word_count"] == 0
        assert result["pass"] is True

    def test_under_ceiling_passes(self):
        text = " ".join(["word"] * 100)
        result = word_count_check(text)
        assert result["word_count"] == 100
        assert result["pass"] is True

    def test_exactly_at_ceiling_passes(self):
        text = " ".join(["word"] * WORD_COUNT_CEILING)
        result = word_count_check(text)
        assert result["pass"] is True

    def test_one_over_ceiling_fails(self):
        text = " ".join(["word"] * (WORD_COUNT_CEILING + 1))
        result = word_count_check(text)
        assert result["pass"] is False
        assert result["word_count"] == WORD_COUNT_CEILING + 1

    def test_ceiling_reported_in_result(self):
        result = word_count_check("hello world")
        assert result["ceiling"] == WORD_COUNT_CEILING

    def test_ceiling_value_matches_smoke_harness(self):
        # Regression guard: ceiling must stay in sync with smoke_harness.check_word_count.
        assert WORD_COUNT_CEILING == 4500


# ════════════════════════════════════════════════════════════════════════════
# section_gating_check
# ════════════════════════════════════════════════════════════════════════════

class TestSectionGatingCheck:

    # ── Gate 1: sbc_section ──────────────────────────────────────────────────

    def test_sbc_present_when_owner_earnings_set(self):
        math   = {"owner_earnings": 12.3, "consensus_divergent": False}
        pass2  = {"sbc_section": "SBC was 2.1B, owner earnings = 12.3B.", "recommendation_rationale": "BUY."}
        assert section_gating_check(math, pass2) == []

    def test_sbc_absent_when_owner_earnings_null(self):
        math   = {"owner_earnings": None, "consensus_divergent": False}
        pass2  = {"recommendation_rationale": "WATCH."}
        assert section_gating_check(math, pass2) == []

    def test_sbc_missing_violation(self):
        math   = {"owner_earnings": 12.3, "consensus_divergent": False}
        pass2  = {"recommendation_rationale": "BUY."}
        viols  = section_gating_check(math, pass2)
        assert len(viols) == 1
        assert viols[0]["gate"] == "sbc_section"
        assert viols[0]["direction"] == "missing"

    def test_sbc_unexpected_violation(self):
        math   = {"owner_earnings": None, "consensus_divergent": False}
        pass2  = {"sbc_section": "SBC text present unexpectedly.", "recommendation_rationale": "PASS."}
        viols  = section_gating_check(math, pass2)
        assert len(viols) == 1
        assert viols[0]["gate"] == "sbc_section"
        assert viols[0]["direction"] == "unexpected"

    # ── Gate 2: consensus-divergent banner ───────────────────────────────────

    def test_divergent_banner_present_when_flag_set(self):
        math   = {"owner_earnings": None, "consensus_divergent": True}
        pass2  = {
            "recommendation_rationale": (
                "The calibration log confirms a Step D consensus_divergent flag: "
                "bull_high of 55.04 is at or below current price."
            )
        }
        assert section_gating_check(math, pass2) == []

    def test_divergent_banner_present_via_divergence_word(self):
        math   = {"owner_earnings": None, "consensus_divergent": True}
        pass2  = {"recommendation_rationale": "The bull-case divergence from consensus is notable here."}
        assert section_gating_check(math, pass2) == []

    def test_divergent_banner_present_via_bull_below_current(self):
        math   = {"owner_earnings": None, "consensus_divergent": True}
        pass2  = {"recommendation_rationale": "Even the bull case target falls below current price, reflecting elevated risk."}
        assert section_gating_check(math, pass2) == []

    def test_divergent_banner_missing_violation(self):
        math   = {"owner_earnings": None, "consensus_divergent": True}
        pass2  = {"recommendation_rationale": "Expected return is negative; risk metrics are unfavourable."}
        viols  = section_gating_check(math, pass2)
        assert len(viols) == 1
        assert viols[0]["gate"] == "consensus_divergent_banner"

    def test_no_divergent_check_when_flag_false(self):
        math   = {"owner_earnings": None, "consensus_divergent": False}
        pass2  = {"recommendation_rationale": "Straightforward BUY with no calibration flags."}
        assert section_gating_check(math, pass2) == []

    def test_both_violations_fire_together(self):
        math   = {"owner_earnings": 5.0, "consensus_divergent": True}
        pass2  = {"recommendation_rationale": "Risk metrics are unfavourable."}
        viols  = section_gating_check(math, pass2)
        gates  = {v["gate"] for v in viols}
        assert "sbc_section" in gates
        assert "consensus_divergent_banner" in gates


# ════════════════════════════════════════════════════════════════════════════
# citation_check
# ════════════════════════════════════════════════════════════════════════════

class TestCitationCheck:
    """
    Checks that numeric figures in narrative appear verbatim in math_dict.
    Uses hand-built math dicts and short narrative snippets.
    """

    def _math(self, **kwargs) -> dict:
        defaults = {
            "expected_value": 507.48,
            "scenario_eps": {"bull": 14.14, "base": 10.49, "bear": 6.19},
            "joint_probs": {"bull": 0.2486, "base": 0.5931, "bear": 0.1583},
            "price_target": {"bull_high": 1222.65, "bull_mid": 507.48,
                             "base_mid": 303.12, "bear_low": 98.55},
            "ev_formula_string": "0.2486×$507.48 + 0.5931×$303.12 + 0.1583×$98.55 = $507.48",
            "calibration_log": [],
        }
        defaults.update(kwargs)
        return defaults

    def test_known_figure_passes(self):
        # 507.48 is in the math dict
        narrative = "The expected value of $507.48 is well above the current price."
        misses = citation_check(narrative, self._math())
        figures_missed = {m["figure"] for m in misses}
        assert "507.48" not in figures_missed

    def test_unknown_figure_flagged(self):
        # 999.99 is not in the math dict
        narrative = "Our target is $999.99 based on the scenario analysis."
        misses = citation_check(narrative, self._math())
        assert any(m["figure"] == "999.99" for m in misses)

    def test_ev_formula_string_figures_pass(self):
        # Figures that appear in ev_formula_string should be found
        narrative = "The probability-weighted EV uses 0.2486 for the bull weight."
        misses = citation_check(narrative, self._math())
        figures_missed = {m["figure"] for m in misses}
        assert "0.2486" not in figures_missed

    def test_empty_narrative_returns_empty(self):
        assert citation_check("", self._math()) == []

    def test_text_without_pipeline_figures_returns_empty(self):
        # No multi-decimal-place numbers → nothing to check
        narrative = "The company is a franchise with strong pricing power and durable moats."
        assert citation_check(narrative, self._math()) == []

    def test_miss_dict_has_figure_and_context(self):
        narrative = "The target is $888.88 in the base case."
        misses = citation_check(narrative, self._math())
        assert misses
        m = misses[0]
        assert "figure" in m and "context" in m
        assert m["figure"] == "888.88"

    def test_correctly_cited_scenario_eps(self):
        narrative = "Bull EPS of 14.14 and base EPS of 10.49 drive the scenario targets."
        misses = citation_check(narrative, self._math())
        figures_missed = {m["figure"] for m in misses}
        assert "14.14" not in figures_missed
        assert "10.49" not in figures_missed
