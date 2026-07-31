"""
Tests for signal_snapshot.py.

Deterministic tests (no live marker):
  - capture_signals returns the right shape and values on hand-built inputs.
  - save_signals + compare_signals round-trip correctly.

Live-guarded comparison tests (marked @pytest.mark.live):
  - compare_signals against committed signal goldens, SKIPPING gracefully
    when the golden is missing (it won't exist until a live pipeline run
    populates it).

DO NOT call any LLM or FMP endpoint in this file.  Every test that could
initiate a live call must carry @pytest.mark.live.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from signal_snapshot import (
    capture_signals,
    compare_signals,
    save_signals,
)
from audit_checks import WORD_COUNT_CEILING

# ── Shared fixtures ──────────────────────────────────────────────────────────

def _minimal_math() -> dict:
    return {
        "owner_earnings":     None,
        "consensus_divergent": False,
        "expected_value":     507.48,
        "scenario_eps":       {"bull": 14.14, "base": 10.49, "bear": 6.19},
        "joint_probs":        {"bull": 0.2486, "base": 0.5931, "bear": 0.1583},
        "ev_formula_string":  "0.2486×$507.48 + 0.5931×$303.12 + 0.1583×$98.55 = $507.48",
        "calibration_log":    [],
        "price_target":       {"bull_high": 1222.65, "bull_mid": 507.48,
                               "base_mid": 303.12, "bear_low": 98.55},
    }


def _minimal_pass2(body: str = "") -> dict:
    """Minimal §5.4 pass2 dict with all required sections present."""
    text = body or "The company has strong fundamentals and a durable moat."
    return {
        "investment_thesis":         text,
        "reverse_dcf_commentary":    text,
        "recommendation_rationale":  text,
        "conclusion":                text,
        "revenue_architecture":      text,
        "valuation_vs_expectations": text,
        "sensitivity_check":         text,
        "margin_analysis":           text,
        "competitive_position":      text,
        "scenario_analysis_extended": {"bull": {}, "base": {}, "bear": {}},
        "body":                      text,
    }


# ════════════════════════════════════════════════════════════════════════════
# capture_signals — shape and content
# ════════════════════════════════════════════════════════════════════════════

class TestCaptureSignalsShape:
    def test_returns_required_keys(self):
        sigs = capture_signals("TEST", _minimal_pass2(), _minimal_math())
        for k in (
            "ticker", "sections_present", "sections_missing",
            "word_count", "word_count_pass",
            "forbidden_vocab", "citation_misses",
            "section_gate_violations", "pass3_audit_clean",
        ):
            assert k in sigs, f"missing key: {k}"

    def test_ticker_preserved(self):
        sigs = capture_signals("AVGO", _minimal_pass2(), _minimal_math())
        assert sigs["ticker"] == "AVGO"

    def test_clean_pass2_is_audit_clean(self):
        sigs = capture_signals("AVGO", _minimal_pass2(), _minimal_math())
        assert sigs["pass3_audit_clean"] is True
        assert sigs["forbidden_vocab"] == []
        assert sigs["section_gate_violations"] == []
        assert sigs["field_path_litter"] == []

    def test_field_path_litter_surfaces_and_gates_audit(self):
        p2 = _minimal_pass2()
        # inject a field-path leak into the body the signal layer scans
        p2["body"] = (p2.get("body", "") or "") + " see math_json.tailwinds for the impact"
        sigs = capture_signals("AVGO", p2, _minimal_math())
        assert sigs["field_path_litter"], "litter must surface in signals"
        assert sigs["field_path_litter"][0]["path"] == "math_json.tailwinds"
        assert sigs["pass3_audit_clean"] is False, "litter must gate audit_clean to False"

    def test_all_required_sections_present(self):
        sigs = capture_signals("AVGO", _minimal_pass2(), _minimal_math())
        assert sigs["sections_missing"] == []

    def test_word_count_reflects_body(self):
        body = " ".join(["word"] * 42)
        p2   = _minimal_pass2(body=body)
        sigs = capture_signals("AVGO", p2, _minimal_math())
        assert sigs["word_count"] == 42
        assert sigs["word_count_pass"] is True

    def test_word_count_over_ceiling_fails(self):
        body = " ".join(["word"] * (WORD_COUNT_CEILING + 1))
        p2   = _minimal_pass2(body=body)
        sigs = capture_signals("AVGO", p2, _minimal_math())
        assert sigs["word_count_pass"] is False


class TestCaptureSignalsForbiddenVocab:
    def test_forbidden_token_surfaces_in_signals(self):
        body = "This uses the Sharpe ratio as a risk metric."
        p2   = _minimal_pass2(body=body)
        sigs = capture_signals("AVGO", p2, _minimal_math())
        assert any(h["token"] == "Sharpe" for h in sigs["forbidden_vocab"])
        assert sigs["pass3_audit_clean"] is False


class TestCaptureSignalsSectionGates:
    def test_sbc_missing_violation_surfaces(self):
        math = {**_minimal_math(), "owner_earnings": 12.3}
        sigs = capture_signals("AVGO", _minimal_pass2(), math)
        assert any(v["gate"] == "sbc_section" for v in sigs["section_gate_violations"])
        assert sigs["pass3_audit_clean"] is False

    def test_sbc_present_clears_gate(self):
        math = {**_minimal_math(), "owner_earnings": 12.3}
        p2   = {**_minimal_pass2(), "sbc_section": "Owner earnings = 12.3B after SBC of 2.1B."}
        sigs = capture_signals("AVGO", p2, math)
        gate_gates = {v["gate"] for v in sigs["section_gate_violations"]}
        assert "sbc_section" not in gate_gates

    def test_divergent_banner_missing_surfaces(self):
        math = {**_minimal_math(), "consensus_divergent": True}
        p2   = _minimal_pass2()  # recommendation_rationale = plain text, no divergence mention
        sigs = capture_signals("AVGO", p2, math)
        assert any(
            v["gate"] == "consensus_divergent_banner"
            for v in sigs["section_gate_violations"]
        )

    def test_divergent_banner_present_clears_gate(self):
        math = {**_minimal_math(), "consensus_divergent": True}
        p2   = {
            **_minimal_pass2(),
            "recommendation_rationale": (
                "Step D consensus_divergent flag fired: bull target is below current price."
            ),
        }
        sigs = capture_signals("AVGO", p2, math)
        gates = {v["gate"] for v in sigs["section_gate_violations"]}
        assert "consensus_divergent_banner" not in gates


# ════════════════════════════════════════════════════════════════════════════
# save_signals + compare_signals round-trip
# ════════════════════════════════════════════════════════════════════════════

class TestSaveAndCompare:
    def _tmp_dir(self, tmp_path: pathlib.Path) -> pathlib.Path:
        d = tmp_path / "signal_goldens"
        d.mkdir()
        return d

    def test_round_trip_identical(self, tmp_path: pathlib.Path):
        golden_dir = self._tmp_dir(tmp_path)
        sigs = capture_signals("TEST", _minimal_pass2(), _minimal_math())
        save_signals("TEST", sigs, golden_dir=golden_dir)
        diffs = compare_signals("TEST", sigs, golden_dir=golden_dir)
        assert diffs == []

    def test_diff_detected_on_change(self, tmp_path: pathlib.Path):
        golden_dir = self._tmp_dir(tmp_path)
        sigs = capture_signals("TEST", _minimal_pass2(), _minimal_math())
        save_signals("TEST", sigs, golden_dir=golden_dir)

        mutated = {**sigs, "word_count": sigs["word_count"] + 99}
        diffs   = compare_signals("TEST", mutated, golden_dir=golden_dir)
        assert any("word_count" in d for d in diffs)

    def test_missing_golden_raises_file_not_found(self, tmp_path: pathlib.Path):
        golden_dir = self._tmp_dir(tmp_path)
        sigs = capture_signals("TEST", _minimal_pass2(), _minimal_math())
        with pytest.raises(FileNotFoundError):
            compare_signals("MISSING", sigs, golden_dir=golden_dir)

    def test_save_creates_file(self, tmp_path: pathlib.Path):
        golden_dir = self._tmp_dir(tmp_path)
        sigs = capture_signals("X", _minimal_pass2(), _minimal_math())
        path = save_signals("X", sigs, golden_dir=golden_dir)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["ticker"] == "X"


# ════════════════════════════════════════════════════════════════════════════
# Live-guarded golden comparison tests
#
# These tests are marked @pytest.mark.live and SKIP when the committed
# signal golden is missing (it won't exist until a real pipeline run
# captures a pass2 result and calls save_signals).
#
# To populate a golden for ticker T:
#   1. Run the live pipeline for T.
#   2. Call save_signals(T, capture_signals(T, pass2_result, math_dict)).
#   3. Commit tests/fixtures/signal_goldens/{T}_signals.json.
# ════════════════════════════════════════════════════════════════════════════

_SIGNAL_GOLDEN_DIR = (
    pathlib.Path(__file__).resolve().parent / "fixtures" / "signal_goldens"
)

_LIVE_SENTINELS = ["AVGO", "NVDA", "KO", "ARLO"]


@pytest.mark.live
@pytest.mark.parametrize("ticker", _LIVE_SENTINELS)
def test_live_signals_match_golden(ticker: str) -> None:
    """
    Compare a freshly captured signal snapshot against the committed golden.

    REQUIRES: live pipeline pass2 result — skipped when golden is missing.
    DO NOT run in the credit-free loop (`-m "not live"`).
    """
    golden_path = _SIGNAL_GOLDEN_DIR / f"{ticker}_signals.json"
    if not golden_path.exists():
        pytest.skip(f"No signal golden for {ticker} — run a live pipeline and save_signals() first")

    # If we reach here, a golden exists and we need a live pass2 to compare.
    # This test is intentionally incomplete without live pipeline plumbing —
    # it serves as the harness slot for when live fixtures are available.
    pytest.skip(
        f"Golden for {ticker} exists but live pipeline not wired here; "
        "run capture_signals() after a real pipeline call and compare manually."
    )
