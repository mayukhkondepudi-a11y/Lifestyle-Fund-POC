# Methodology Rebuild — Execution Plan v3

> **What this document is.** A corrected control layer over your existing v2 spec. It supersedes the v2 spec's *framing, sequencing, and financial calibration*. It does **not** repeat the exhaustive file-path / function-signature / JSON-schema detail — keep the v2 spec open as the detail reference for those (§5 contracts, §7 function list, §8 data fields, §11 removal manifest). When v3 and v2 disagree, v3 wins.
>
> **How to run this with Claude Code.** Split this into two things:
> 1. **The Standing Context (Parts A–C below).** Give this to Claude Code *once*, at the top of every session, and instruct it to treat the contracts/constants/guardrails as immutable. This is the part that must never drift.
> 2. **The Phases (Part E).** Feed these *one at a time*, each in its own session, with the phase's exit criterion as the literal acceptance test. Get green, commit, start a fresh session for the next phase.
>
> Do not paste the whole plan and say "build it." That is how these break.

---

# PART A — MENTAL MODEL (read first, internalize)

**This is not surgical. It is a ground-up rewrite of the analytical core behind a frozen I/O interface.** Section 11 of the v2 spec deletes ~22 functions in `compute.py`, ~13 in `ai.py`, all three prompts, the entire render block, and changes all four data contracts. The only things that survive are the outer shell (FMP fetch, `report_store`, auth, Streamlit chrome) and a handful of helpers.

Calling it "surgical" is the trap: it makes you under-resource testing and tempts you to edit in place. Treat it as a **rewrite with a frozen interface**. The interface is sacred (the four dicts in v2 §5); everything behind it is being replaced. That single reframe is what keeps the build from breaking the rest of the app.

**The core financial logic is sound — keep it.** Two decisions in your v2 spec are correct and load-bearing; do not let any "simplification" undo them:

1. **Per-scenario EPS *and* per-scenario P/E, then probability-weight the prices.** Not one blended EPS times one multiple. EPS and the multiple are correlated (bull = higher earnings *and* re-rating; bear = the reverse), so collapsing to a single net EPS systematically understates both tails. The three-scenario architecture is the right call.
2. **Single source of truth: Python owns every number, the LLM cites verbatim and does zero arithmetic.** This is the strongest decision in the spec and directly delivers your "AI does no calculations" requirement.

---

# PART B — FINANCIAL CORRECTIONS (what changed from v2 and why)

These are the substantive methodology fixes. They change behavior, so they belong in the Standing Context.

## B1. The invented parameters must be visible, and the reverse-DCF leads
The correlation multipliers (3.0× / 4.5×), bear P/E floors (15× / 25×), and consensus fractions (0.95 / 0.75) are the parameters that actually determine your tail probabilities, prob-of-loss, expected value, and final recommendation — and none has an empirical basis. Worse, the *probabilities themselves come from the LLM*, which is uncalibrated; "65% chance the driver plays out" is a vibe wearing a decimal point.

You cannot make this rigorous by adding precision. You make it honest:
- All calibration constants stay **named, visible, and printed in the annexure calibration log** (v2 already does this — good).
- **Headline outputs are ranges, not points.** Report bull/base/bear price targets and an EV range; never a single "fair value" number dressed as fact.
- **The reverse-DCF — "what FCF growth is the market already pricing in" — is the lead number**, not the probability-weighted EV. It is the one output that does *not* depend on your invented parameters, so it is the most defensible thing the system produces. Promote it in both the report header and the Pass 2 prompt.

## B2. Consensus is a backstop, not the answer
Removing the three CAGR caps is the real F1 fix — those were genuinely crushing high-growth names (your Celestica case). Keep that removal.

But the `0.95 × consensus_FY2_high` floor anchors your "independent" analysis to sell-side, and the whole point of doing your own work is to find where you *disagree* — consensus is most wrong at the turning points where a differentiated view pays. So:
- Keep the consensus floor **only as a sanity backstop**, and when it binds, emit a **loud annexure note** ("bull case floored to consensus high — model's bottom-up bull was lower; investigate") rather than letting it silently become the answer.
- The fix for F1 is the **CAGR-cap removal**. The consensus floor is a guardrail. Do not conflate them, or every bull case quietly collapses to "consensus high" and you've built a consensus-parroting machine.

## B3. Bear P/E floors are conditional, not universal
A 15× stress / 25× nominal floor is defensible for a *durable mature-tech franchise*. Applied to everything, it forbids the 8–10× multiple a structurally challenged business can absolutely trade at — understating downside on exactly the names where downside matters most. **Gate the floors on a franchise-quality flag** (e.g. positive FCF margin + stable/growing recurring revenue + investment-grade balance sheet). Off-franchise names get no floor, or a much lower one.

## B4. Share count must evolve over the horizon
`scenario_eps` currently takes `shares` as a fixed input. Over two years, buybacks and SBC dilution move EPS materially — a big repurchaser compounds EPS through a shrinking share count; a serial diluter does the opposite. Holding shares constant overstates diluters and understates buyers. **Wire a share-count path into the EPS calculation** using the dilution/buyback helpers already on your keep-list (`_compute_dilution_rate`, `_extract_shares_history`). At minimum: project shares forward at the trailing net change rate, per scenario.

## B5. Reframe the horizon honestly
Over 12 months, price is driven far more by multiple re-rating and estimate revisions than by realized EPS, which moves slowly. What you are actually building is a **fair value based on FY+2 earnings power**, which the market *may or may not* price within twelve months. That is a genuinely useful thing — just label it as such everywhere (report header, conclusion, Pass 2 prompt). Do not call it a 12-month price forecast; the framework does not model the *timing* of re-rating.

## B6. Demote "upside/downside capture"; lead risk with prob-of-loss and drawdown
Capture ratios are normally computed against a benchmark over many periods, not from three scenario points — using the term here will confuse a finance-literate reader. Make **probability of loss** and **worst-case drawdown** the primary risk metrics. If you keep a capture-style number, rename it (e.g. "reward-to-risk ratio = prob-weighted upside ÷ prob-weighted downside") and define it explicitly in the annexure.

## B7. The regression fixture needs an independent check
The AVGO fixture locks the code to *the methodology document's* worked example — which proves the code reproduces the doc, not that the doc is correct. **Add at least one independent hand-calculation** (a second ticker worked by hand, or AVGO's bull EPS recomputed from scratch outside the doc) so you are not enshrining a possible error in the example itself.

---

# PART C — FROZEN INTERFACE & GUARDRAILS (the non-drift core)

Give this verbatim to Claude Code every session.

## C1. The four data contracts are immutable
The `baseline`, `pass1`, `math`, `pass2` (and `pass3`) dict shapes in **v2 §5** are the contract between layers. Render and downstream code rely on them and nothing else. No new key gets added without updating this contract first. No layer reads a key not in the contract.

## C2. Calibration constants live in one named block (v2 §7.3) — plus the new ones
Add to that block:
```python
FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR = True   # B3
SHARE_COUNT_PROJECTION = "trailing_net_change"     # B4
HEADLINE_METRIC = "implied_fcf_cagr"               # B1 — reverse-DCF leads
```
Changing any constant is a deliberate, reviewed act that requires regenerating the regression fixture.

## C3. Hard rules (any violation = stop and fix, do not work around)
- LLM does **zero arithmetic**. Every number in the report body comes verbatim from `math` or `baseline`.
- **No silent fallbacks** for required signals. Pass 1 fails twice → typed `Pass1ValidationError` → real error UI. The DEGRADED path does not exist.
- **No clamp without a methodology justification + a calibration-log line.** Every floor/ceiling/anchor that fires logs why.
- Company's **own current/trailing P/E is never an anchor or cap** — sanity log line only.
- **Global LLM-call ceiling per report.** Cap total calls (suggest 6: 1+1 Pass1, 1+1 Pass2, 1 Pass3, +1 BullCaseTooLow retry). Every retry path must terminate in a definite end state, including "retry failed → ship with the divergence note."

## C4. Build-discipline guardrails (the part that prevents breakage)
- **Never delete-in-place.** Build v2 paths *alongside* v1 behind a feature flag. Deletion of v1 is always a **separate commit** from the one that builds v2.
- **Commit at every exit criterion.** Each phase's exit criterion is a commit boundary. A bad phase is then one `git reset` away.
- **One phase per Claude Code session.** Fresh context each time. Re-supply this Standing Context at the top.
- **Tests are written alongside (or before) the code in each phase**, not after.

---

# PART D — DO THIS BEFORE PHASE A (pre-flight)

1. **Fix the `'str' object has no attribute 'html'` bug in isolation, first.** It is currently hand-waved as "_sc is probably shadowed somewhere." Going into a rewrite with an unsolved crash means it resurfaces mid-transplant, entangled with everything. Find it, fix it, commit it on its own. Add the startup assertion that `_sc` is always a Streamlit container.
2. **Tag a known-good baseline commit** (`git tag pre-rebuild-baseline`) so you always have a clean rollback point.
3. **Add the feature flag** (`METHODOLOGY_VERSION = "v1" | "v2"`, default `v1`) and the routing branch in the orchestrator and renderer. v2 builds behind it; v1 keeps working until cutover.
4. **Build the smoke harness now** (see Part F) with frozen/mock data, before any analytical code. It will be near-empty at first and grow as contracts come online.

---

# PART E — REVISED PHASE SEQUENCE

Each phase: own session, own commit, exit criterion is the acceptance test. **Render is split out** from the old Phase G because it has the highest blast radius and the hardest verification.

### Phase 0 — Pre-flight (Part D)
**Exit:** `_sc` bug fixed and committed; baseline tagged; feature flag in place routing to v1; empty smoke harness runs.

### Phase A — Math foundation (no LLM, no UI)
A1. Calibration constants (v2 §7.3 + C2 additions).
A2. Pure functions (v2 §7.2), one at a time — **including B4 share-count path and B3 conditional bear floor.**
A3. `tests_methodology.py`: AVGO fixture **plus the B7 independent hand-calc.**
A4. `run_methodology_math` composing the pure functions.
A5. Synthetic-Pass1 AVGO fixture reproduces the worked example.
**Exit:** `pytest tests_methodology.py` green, including the independent check. AVGO synthetic: bull EPS ~$14.50 ±0.50, EV ~$348 ±5, joint_probs within 1pp.

### Phase B — Data layer
B1–B3 per v2 §8 (new fetches, `fetch_consensus_pack`, `data_quality_warnings`).
B4. `calc_baseline` per v2 §7.1 — **built alongside `calc()`, not replacing it.** Both callable behind the flag.
**Exit:** `calc_baseline` returns the §5.1 schema on 5 tickers (AVGO, KO, ASML, a small-cap, NVDA); optional fields `None` where data missing; no crashes; smoke harness green on the data layer. (`calc()` still present — deletion deferred to Phase H.)

### Phase C — Pass 1
C1. `prompt_pass1.txt` per v2 §9.1.
C2. `run_pass1_foundation` with fault-tolerant validator — **built alongside old Pass-1 functions.**
C3. Run on 5 tickers; inspect each against §5.2.
C4. Verify retry-with-hint by feeding a corrupted-low-bull baseline; confirm `BullCaseTooLowError` fires.
**Exit:** Pass 1 succeeds on 5 tickers, **run 3× each** (LLM is stochastic — see Part F) without entering any error path on normal input; retry fires when expected.

### Phase D — Math orchestrator end-to-end
D1. Wire `run_methodology_math` to real Pass-1 output.
D2. AVGO Pass1 → math reproduces the worked example.
D3. Calibration assertions (v2 §6) fire correctly on NVDA.
**Exit:** `bull_price_high > current_price` on NVDA across 3 runs; AVGO within tolerance; reverse-DCF (B1 headline) present and sane.

### Phase E — Pass 2
E1. `prompt_pass2.txt` per v2 §9.2 — **include B1 (reverse-DCF leads), B5 (FY+2 framing), B6 (no "capture"/Sharpe).**
E2. `run_pass2_report` alongside old Pass-2.
E3. Run on 5 tickers; inspect: all sections, ≤4500 words, no forbidden vocab, numbers traceable to math/baseline.
**Exit:** smoke harness passes Pass-2 structural checks on all 5, across 3 runs.

### Phase F — Pass 3
F1. `prompt_pass3.txt` per v2 §9.3.
F2. `run_pass3_audit` alongside old Pass-3.
F3. Inject a deliberate citation error; confirm flag fires. Confirm forbidden-vocab scan catches "Sharpe" and "capture" if B6 renamed it.
F4. Over-budget re-prompt loop, with the global call ceiling (C3) enforced.
**Exit:** audit catches injected errors; clean reports pass; no retry path can loop.

### Phase G — Orchestrator + cutover
G1. `run_pipeline(ticker)` composing baseline+pass1+math+pass2+pass3.
G2. **Flip the feature flag to v2 for the analytical pipeline.** v1 analytical path still present but unrouted.
**Exit:** all 5 tickers run end-to-end through v2 analytical pipeline; smoke harness green; v1 still reachable by flipping the flag back.

### Phase H — Render rewrite (own phase — highest blast radius)
H1. Build v2 renderer per v2 §10 **alongside** the v1 renderer, keyed off `methodology_version`.
H2. `styles.py` updates (v2 §10.4) — add new IDs; old IDs stay until deletion phase.
H3. `methodology_version: "v2"` tag in `save_report`; v1 banner branch for old reports (v2 §10.5).
H4. Eyeball AVGO + NVDA front-to-back (v2 §13 manual pass).
**Exit:** v2 reports render with no `AttributeError`; old v1 reports still render with the banner; both paths coexist.

### Phase I — Surgical deletion sweep (separate commits)
**Only now does v1 get deleted.** This is its own session and its own series of commits, *after* v2 is proven end-to-end.
I1. Delete v1 symbols per v2 §11.1 / §11.2 — in small commits, running the smoke harness after each.
I2. Delete old render blocks (v2 §11.4) and dead CSS (v2 §11.5).
I3. Run the **grep checklist (v2 §11.6)** — zero hits required. This is now *post-deletion verification*, not build-time pressure.
I4. Vocabulary diff (v2 §11.7).
I5. Read the full diff of every changed file; remove stray comments, dead imports, commented-out code.
**Exit:** grep checklist zero hits; smoke harness + `tests_methodology.py` green; full end-to-end run on all 6 verification tickers passes Part-G universal criteria.

---

# PART F — THE SMOKE HARNESS & NONDETERMINISM (the thing that lets you move fast)

Build this in Phase 0 and run it after **every** phase. It is a cheap automated gate that catches regressions manual eyeballing misses.

**Per-ticker automated checks (no human needed):**
- Pipeline runs without exception.
- Every required key in each dict contract is present and correctly typed.
- `joint_probs` sums to 1.0 (±0.001).
- Word count ≤ 4500.
- No forbidden tokens in Pass-2 output ("Sharpe", "DEGRADED", old jargon, and "capture" if you renamed per B6).
- Reverse-DCF / implied FCF CAGR present and finite.
- For NVDA specifically: `bull_price_high > current_price`.

**Handling LLM nondeterminism — this is critical and the v2 spec misses it.** "Pass 1 succeeds on 5 tickers" can pass once and fail the next run because LLMs are stochastic. A single green is a false green. Two acceptable approaches, pick one and apply it to every LLM-dependent exit criterion:
- **Robustness runs:** run each LLM criterion N times (suggest 3) and require all to pass. Slower but honest.
- **Tolerant validators:** make the validator forgiving enough that normal output variation always sails through, and only contract violations fail. Faster; preferred for the soft-validation path.

Never treat an LLM pass like a deterministic function. The math layer (Phase A) *is* deterministic and gets exact assertions; everything touching the LLM gets tolerance.

---

# PART G — VERIFICATION (unchanged from v2 §13, with additions)

Keep the v2 §13 ticker matrix (AVGO / NVDA / CLS / KO / ASML / small-cap) and universal pass criteria. **Add these to the universal criteria:**
- Reverse-DCF / implied FCF CAGR is the headline metric in the report (B1).
- Bear P/E floor did **not** fire on a non-franchise name (B3 — verify on the small-cap or a deliberately weak ticker).
- Share count evolves across the horizon (B4 — verify EPS path differs from static-share calc on AVGO, a heavy repurchaser).
- Report frames its output as FY+2 fair value, not a 12-month price forecast (B5).
- Risk section leads with prob-of-loss + drawdown; no "capture ratio" without an explicit definition (B6).
- `tests_methodology.py` independent hand-calc still green (B7).

**Regression sentinel:** `tests_methodology.py` must stay green forever. Any change that breaks it requires explicit documentation + reviewed fixture regeneration.

---

# PART H — WHY CHUNKED, NOT ONE BIG PLAN (the answer to your question)

| Approach | What happens |
|---|---|
| Whole spec, "go" | Agent makes broad edits fast, loses the contract mid-build, drifts from the schema, deletes old code while building new, and you can't A/B compare or cleanly roll back. This is how big surgical changes break. |
| **Standing Context once + phases one at a time** | Contracts and guardrails stay fixed (re-supplied each session so they can't drift out of context). Each phase is small enough to verify, commit, and roll back independently. v1 stays alive until v2 is proven. Fresh context per phase stops confusion from compounding. |

So: **Parts A–C and F as the standing reference, re-pasted at the top of every session. Part E phases fed one per session, exit criterion as the acceptance test. v1 deleted only in Phase I, after v2 is proven, in its own commits.**