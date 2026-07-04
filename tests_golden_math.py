"""
Golden-master regression gate for run_methodology_math.

For each of the 4 sentinel tickers (AVGO, NVDA, KO, ARLO) this test:
  1. Loads the frozen archive inputs (layer1_baseline.json + layer2_pass1.json)
     from tests_archive/ and verifies the ticker content-signature.
  2. Runs the real run_methodology_math — no mocks, no stubs.
  3. Asserts the output matches the committed golden JSON in
     tests/fixtures/math_goldens/ float-exact within 1e-9.

Goldens were generated (and must be regenerated) by running:
  python3 -c "
  import json, pathlib, sys; sys.path.insert(0,'.')
  from run_methodology_math import run_methodology_math
  ...
  "
Any change to run_methodology_math, compute_methodology_v2, or compute that
alters math output will cause this test to fail. That is the intent: the
failure is the signal, not the bug. Update the goldens only after deliberately
accepting the numerical change (regenerate + commit together).
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from run_methodology_math import run_methodology_math

# ── Paths ────────────────────────────────────────────────────────────────────

_REPO = pathlib.Path(__file__).parent
_ARCHIVE = _REPO / "tests_archive"
_GOLDENS = _REPO / "tests" / "fixtures" / "math_goldens"

# Archive directory per ticker (content-signature confirmed in generate step).
_ARCHIVE_DIRS: dict[str, pathlib.Path] = {
    "AVGO": _ARCHIVE / "stage4_state",
    "NVDA": _ARCHIVE / "stage4_state_nvda",
    "KO":   _ARCHIVE / "stage4_state_ko",
    "ARLO": _ARCHIVE / "stage4_state_arlo",
    "CLS":  _ARCHIVE / "stage4_state_cls",
}

_SENTINELS = list(_ARCHIVE_DIRS.keys())


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_archive(ticker: str) -> tuple[dict, dict]:
    """Return (pass1, baseline) for *ticker*, with provenance checks."""
    arc = _ARCHIVE_DIRS[ticker]
    b_path  = arc / "layer1_baseline.json"
    p1_path = arc / "layer2_pass1.json"

    assert b_path.exists(),  f"MISSING archive baseline: {b_path}"
    assert p1_path.exists(), f"MISSING archive pass1: {p1_path}"

    baseline = json.loads(b_path.read_text())
    pass1    = json.loads(p1_path.read_text())

    # Content-signature: the ticker field inside the file must match
    content_ticker = baseline.get("ticker")
    assert content_ticker == ticker, (
        f"PROVENANCE FAIL: {b_path} contains ticker={content_ticker!r}, "
        f"expected {ticker!r} — never trust filename alone"
    )

    return pass1, baseline


def _load_golden(ticker: str) -> dict:
    path = _GOLDENS / f"{ticker}_math_golden.json"
    assert path.exists(), (
        f"Golden missing: {path}  — run the golden-generation script to create it"
    )
    return json.loads(path.read_text())


_FLOAT_TOLERANCE = 1e-9


def _assert_equal_recursive(actual, expected, path: str = "root") -> None:
    """
    Recursively assert actual == expected with float tolerance _FLOAT_TOLERANCE.
    Raises AssertionError with full key-path on first divergence.
    """
    if isinstance(expected, float) or isinstance(actual, float):
        # Both must be the same nan/inf/finite type, then within tolerance
        a_val = float(actual) if actual is not None else None
        e_val = float(expected) if expected is not None else None
        if a_val is None or e_val is None:
            assert a_val == e_val, f"{path}: got {a_val!r}, expected {e_val!r}"
        elif math.isnan(e_val):
            assert math.isnan(a_val), f"{path}: expected nan, got {a_val!r}"
        elif math.isinf(e_val):
            assert math.isinf(a_val) and (a_val > 0) == (e_val > 0), (
                f"{path}: expected {e_val!r}, got {a_val!r}"
            )
        else:
            assert not math.isnan(a_val) and not math.isinf(a_val), (
                f"{path}: got {a_val!r} (nan/inf), expected {e_val!r}"
            )
            assert abs(a_val - e_val) <= _FLOAT_TOLERANCE, (
                f"{path}: got {a_val!r}, expected {e_val!r}, "
                f"diff={abs(a_val - e_val):.2e} > tol={_FLOAT_TOLERANCE:.0e}"
            )
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), (
            f"{path}: expected dict, got {type(actual).__name__}"
        )
        assert set(actual.keys()) == set(expected.keys()), (
            f"{path}: key mismatch — "
            f"extra={set(actual)-set(expected)}, "
            f"missing={set(expected)-set(actual)}"
        )
        for k in expected:
            _assert_equal_recursive(actual[k], expected[k], path=f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), (
            f"{path}: expected list, got {type(actual).__name__}"
        )
        assert len(actual) == len(expected), (
            f"{path}: list length {len(actual)} != {len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_equal_recursive(a, e, path=f"{path}[{i}]")
    else:
        assert actual == expected, (
            f"{path}: got {actual!r}, expected {expected!r}"
        )


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker", _SENTINELS)
def test_math_matches_golden(ticker: str) -> None:
    """
    Re-run run_methodology_math on the frozen archive inputs and assert the
    output matches the committed golden JSON, float-exact within 1e-9.

    This is the core regression gate: any change to math output is a failure.
    """
    pass1, baseline = _load_archive(ticker)
    golden = _load_golden(ticker)

    actual = run_methodology_math(pass1, baseline)

    _assert_equal_recursive(actual, golden, path=f"{ticker}/math")


@pytest.mark.parametrize("ticker", _SENTINELS)
def test_math_joint_probs_sum(ticker: str) -> None:
    """Sanity: joint_probs always sum to 1.0 ±0.001 on live archive inputs."""
    pass1, baseline = _load_archive(ticker)
    m = run_methodology_math(pass1, baseline)
    total = sum(m["joint_probs"].values())
    assert abs(total - 1.0) < 0.001, (
        f"{ticker}: joint_probs sum={total:.6f}, expected 1.0 ±0.001"
    )


@pytest.mark.parametrize("ticker", _SENTINELS)
def test_math_implied_fcf_cagr_finite(ticker: str) -> None:
    """Sanity: implied_fcf_cagr must be a finite float on all archive inputs."""
    pass1, baseline = _load_archive(ticker)
    m = run_methodology_math(pass1, baseline)
    cagr = m["implied_fcf_cagr"]
    assert isinstance(cagr, float) and math.isfinite(cagr), (
        f"{ticker}: implied_fcf_cagr={cagr!r} is not a finite float"
    )
