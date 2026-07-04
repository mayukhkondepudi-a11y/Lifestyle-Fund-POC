# CLAUDE.md — Standing Context for the Methodology Rebuild

> Claude Code reads this file automatically at the start of every session. It is the **non-drift core**: the rules, contracts, and current state that must hold no matter how long a session runs or how much intermediate work accumulates. Treat everything here as immutable unless the human changes it in this file directly.

---

## 0. Document authority (read this first)

Three documents govern this build. When they conflict, **higher wins**:

1. **This file (`CLAUDE.md`)** — the immutable rules and current state. Always authoritative.
2. **`docs/methodology_rebuild_plan_v3.md`** — the execution plan: financial corrections, build order, de-risking protocol. Authoritative on *how and in what order* to build.
3. **`docs/methodology_replacement_plan.md` (v2)** — the detail reference: exact file paths, function signatures, JSON schemas, line numbers, removal manifest. Used for *specifics* only. When v3 and v2 disagree, **v3 wins**.

Do not follow v2's framing, sequencing, or financial calibration where v3 has superseded it. Use v2 only to look up signatures, schemas, and deletion targets that v3 points you to.

---

## 1. CURRENT BUILD STATE — update this block as you go

> This is the most important section. Read it before doing anything. The scenario-core rewrite and the calibration pass are now MERGED to main (tag `calibration-merged`, 2026-07-04). The merged-state summary below is current; the dated build log further down is pre-rewrite history, kept for provenance.

Deferred non-blocking items are tracked in POST_POC_BACKLOG.md — consult it before declaring a phase complete, and append flagged items there rather than leaving them in conversation.

### MERGED POST-CALIBRATION STATE (2026-07-04) — current

Scenario-core rewrite + calibration pass merged to `main` (`--no-ff`, tag `calibration-merged`). Free loop fully green at merge: **306 passed, 4 skipped, 4 live-deselected** (run the suite by explicit file list — the `tests_*.py` names are NOT picked up by bare `pytest`; there is no `python_files` override).

**Deterministic engine (`run_methodology_math` + `compute_methodology_v2`):**
- Unified bottom-up scenario chain — one `scenario_eps` path (revenue × margin) for bull/base/bear; no separate bull-EPS formula.
- Single-source EV — probability-weighted mean of the three scenario MID prices; no correlation multipliers; risk/EV/recommendation all derive from those three mids.
- Peer-anchored P/E: `base_pe = clamp(peer_median × quality_adj, 10, 45)`; `bull_pe = base_pe × (1 + RERATE_PREMIUM)`, `bear_pe = base_pe × (1 − DERATE_DISCOUNT)`, bear franchise-floored only when the floor sits below base.
- **Calibration constants (this pass):** `MAX_BASE_GROWTH = 0.40` (was 0.35); `RERATE_PREMIUM = 0.125`, `DERATE_DISCOUNT = 0.15` (both halved to narrow the scenario P/E spread — base_pe untouched).
- 5 math goldens (AVGO/NVDA/KO/ARLO/CLS) + the CLS B7 hand-calc oracle re-blessed to the new constants (goldens regenerated with content-signature checks; oracle re-derived independently).

**Pipeline / AI robustness:**
- Truncation guard — Pass 1/2/3 fail loud on truncated output (stop-reason checked; token budgets raised).
- Pass 2 fail-loud — missing sections / missing `driver_narratives` / missing `sbc_section` (when `owner_earnings` non-null) are hard errors → corrective retry. No silent DEGRADED path.
- Temperature deprecated/removed — Opus 4.7+ rejects the param; Pass 1 no longer sets it.

**Report / renderer:**
- Op-margin labeled by period: metrics panel "Op. Margin (TTM)"; effective base scenario op margin (event-weighted, FY-basis) surfaced in Margin Analysis.
- Driver names shown alongside bare A/B/C in the headwind/tailwind, factor, and sensitivity tables.

**Deferred items live in `POST_POC_BACKLOG.md` — consult it before declaring anything done.** Three UNGOVERNED-INPUT reliability items sit near the BUY/WATCH threshold and are NOT yet resolved:
- **#14** operating margin is LLM-assigned (per-event `op_margin_to_apply`), not Python-owned — a direct EPS multiplier.
- **quality_adj growth premium** — the peer-multiple premium (and its 1.30 cap) is a calibration seam.
- **#15** peer-set composition is ungoverned — verdict swings with which comparables are fetched each live run.

**Consequence: borderline-name verdicts (e.g. CLS) are NOT yet reproducible run-to-run.** Recommendation stability (#1) and full live validation of the merged engine remain OPEN — no live LLM validation has been run on this merge.

### Historical build log (pre-rewrite v2 through Phase I) — SUPERSEDED by the merged-state block above; kept for provenance. Descriptions of PEG-based P/E bands, bull-EPS paths, and per-bug fixes below reflect the pre-rewrite engine, not the current one.

#### PHASE I COMPLETE (2026-05-31)
All three hard stops cleared:
- **Step 1** (`phase-i-compute-v1-deletions`, 8b0ee63): 21 v1 compute functions deleted, CAGR caps removed.
- **Step 2** (`phase-i-ai-v1-deletions`, 26365e0): 12 v1 AI functions deleted including `_emit_degraded_report`, `run_two_pass`.
- **Step 3a** (`phase-i-render-deletions`, 33ff1ee): 6 dead render blocks + empty-string stubs deleted from app.py / ai.py.
- **Step 3b** (grep checklist): All 13 §11.6 checks pass. `driver_narratives`, `scenario_commentary`, `recommendation_rationale` are expected v2 field names.
- **Step 3c** (`cleanup-stale-comments` 748345f, `methodology-v2-live` a421f94): Flag flipped to v2. AVGO live run all 5 layers PASS — `bull_price_high $1,222.65 > current $446.77`, `audit_clean=True`, 0 forbidden vocab, `joint_probs=1.0000`. 234/234 pytest.

### VERIFIED (credit-free, 2026-05-30)
- **227/227 pytest pass** (`tests_methodology.py`) — deterministic math layer fully green. (207 prior + 20 new: `TestBug2CalibrationLogWiring` × 4, `TestCatalystsFallback` × 3, `TestBug3MacroDriversShape` × 7, `TestBug4DriverNarrativesHard` × 5, plus 1 renamed ceiling test.)
- **Bug A fixed (2026-05-25)** — `run_methodology_math` now enforces `bear_pe_high = min(bear_pe_high, bull_pe_low − 1.0)` and `bear_pe_low = min(bear_pe_low, bull_pe_low − 2.0)` after computing all three P/E bands. On low-growth franchise names (e.g. KO: 7% growth, peer 16×) the B3 bear floor (25× nominal) previously exceeded the entire bull range (11–16×), making bear prices higher than bull prices. Fix logged as `"Bear P/E capped below bull P/E to preserve scenario hierarchy"` in `calibration_log` when it fires. KO-like fixture added (`KO_LIKE_BASELINE / KO_LIKE_PASS1`); `TestBugABearInversionFix` × 3 added.
- **Bug B fixed (2026-05-25)** — `run_methodology_math` now applies a ratio discount to the base P/E band when `base_pe_high >= bull_pe_high` (peer-dominated inputs collapse both to the same ceiling). Fix: `base_pe_high = bull_pe_high × 0.80`, `base_pe_low = bull_pe_low × 0.75`. This is the dominant case for all current fixtures (PEG_BASE_HIGH = 1.7 > PEG_CEILING_BULL = 1.0 ensures base always equals or exceeds bull without the fix). Fix logged as `"Base P/E ratio-discounted: ..."` in `calibration_log`. `TestBugBBullBaseDifferentiation` × 3 added.
- **AVGO EV target recalibrated (2026-05-25)** — Bug B lowers the base P/E midpoint from 32.3× to 25.2×, reducing AVGO EV from ~$348 to ~$295 (AVGO_BASELINE) and ~$299 (AVGO_V2_BASELINE). Both test targets updated with ±15 tolerance. The prior $348 figure was calibrated against the bug (base P/E = bull P/E). New math composition (AVGO_V2_BASELINE): joint_probs {0.249, 0.593, 0.158}, bull EPS $14.62, EV ≈ $299.
- **Bug 1 fixed (2026-05-24)** — `five_yr_eps_growth_est` in `calc_baseline` (`compute.py`) now uses 2yr implied CAGR from `(consensus_eps_fy2.mid / fy_eps_non_gaap)^0.5 - 1` (capped 60%), with `revenueGrowth` (capped 40%) as fallback. Raw `earningsGrowth` (trailing YoY) is never used. Belt-and-suspenders guard also added in `pe_band` (`compute_methodology_v2.py`): growth capped at 0.60 before PEG multiply, bull `pe_high` hard-capped at 60.0. Both caps logged in `calibration_log` by `run_methodology_math` when they fire.
- **Bug 2 fixed (2026-05-24)** — `run_methodology_math` now emits `"pe_anchors absent — falling back to PEG-only P/E band"` in `calibration_log` whenever `pass1["pe_anchors"]` is missing or empty.
- **Bug 5 fixed (2026-05-25)** — `bull_eps` in `run_methodology_math` now uses `fy_eps_non_gaap × (1 + min(growth_rate, 0.60))^2` (FY+2 growth-rate path) when `fy_eps_non_gaap > 0`. Previously `scenario_eps` was called for bull too, ignoring `five_yr_eps_growth_est` entirely. Base and bear remain event-driven. NVDA_BASELINE consensus updated to `high=6.0` so Step A still fires in D3 tests. `TestBug5BullEPSGrowthRate` × 4 added.
- **Bug 1 fixed (2026-05-25)** — `MAX_PIPELINE_AI_CALLS` corrected from 8 → 6 (spec: 2+2+1+1). `run_pipeline` now tracks `calls_remaining` (decrement from MAX) instead of `calls_used` (increment). `LLMCallCeilingError` added to `ai.py`; raised before Pass 1 or Pass 2 when budget < 2. `TestBug1CallCeilingCounter` × 5 added.
- **Bug 3 fixed (2026-05-24)** — `prompt_pass1.txt` rule 5 now reads "catalysts is REQUIRED" with explicit rejection warning. `_validate_pass1_v2` in `ai.py` treats `catalysts: []` as a distinct soft error with the specific hint "catalysts was empty — you must provide at least 3 specific dated catalyst entries."
- **`fetch_peer_metrics` added to `fmp_api.py` (2026-05-24)** — fetches `fwd_pe` from `info` and `growth` from `earnings_estimate['+1y']` (the confirmed correct index key) for each peer. Falls back to `earningsGrowth`/`revenueGrowth` from info if estimate row absent. Returns §5.1 `peer_set` shape. Wired into `run_pipeline` (`ai.py`) between Pass 1 and Math: extracts tickers from `pass1.peer_set_enriched`, calls `fetch_peer_metrics`, merges into `baseline['peer_set']` before `run_methodology_math`. Live output confirmed: NVDA `{fwd_pe: 17.03, growth: 0.415}`, AAPL `{fwd_pe: 32.16, growth: 0.103}`.
- **yfinance period-index bug fixed (2026-05-24)** — `fetch_consensus_pack` was mapping `"1y"`/`"2y"` but yfinance returns `"+1y"`/`"+2y"`. Fixed in `fmp_api.py`. `consensus_eps_fy2` now populates correctly from live yfinance: `{'low': 13.35, 'mid': 18.26, 'high': 21.45}` for AVGO.
- **Grep scan (v2 code only)** — no forbidden vocab usage; no DEGRADED reintroduction; call ceiling wired correctly. Two ambiguous items for future resolution:
  1. `trailing_net_dilution_rate` is read by `run_methodology_math` but never set by `calc_baseline` → B4 projected-shares always uses 0.0 dilution (silent).
  2. `franchise_quality` defaults to `True` in math → B3 bear P/E floor applies to all companies silently; non-franchise names need `franchise_quality=False` added to `calc_baseline`.
- **Baseline shape (AVGO live FMP)** — all 41 §5.1 keys present with correct types. One remaining data-source gap: `peer_set=[]` from `calc_baseline` (FMP paid endpoint) — now overridden in `run_pipeline` via `fetch_peer_metrics` when Pass 1 returns peers. `consensus_eps_fy2` is now populated (not a gap).
- **Renderer routing** — `_assemble_pipeline_output` does NOT set `methodology_version`, so pipeline output routes to v1 renderer (correct). `_render_v2` raises `NotImplementedError` (fails loudly if accidentally triggered). One gap: `consensus_divergent=True` in `scenario_math` does NOT surface the divergence banner because `render()` reads `diagnostic.divergence_flag` and `diagnostic` is stubbed `{}`.
- **Smoke harness** — exits 0; all tickers SKIP (no fixtures yet). Word-count, forbidden-token, pipeline_runs, and NVDA checks are deferred until live fixtures exist.
- **Bug 1 (catalysts fallback) fixed (2026-05-30)** — `run_pipeline` now makes one additional focused API call after `run_pass1_foundation` if `pass1["catalysts"]` has fewer than 3 entries. System prompt returns a bare JSON array; non-blocking (failure leaves catalysts as-is). `MAX_PIPELINE_AI_CALLS` raised from 6 → 7 (`compute.py`). `TestCatalystsFallback` × 3 added.
- **Bug 2 (calibration log wiring) verified (2026-05-30)** — all three cap/absence conditions (`growth_rate > 0.60`, `bull_pe_high` capped at 60×, `pe_anchors` absent) confirmed in correct scope in `run_methodology_math`. `TestBug2CalibrationLogWiring` × 4 added (including the previously missing 60× peer-median cap test).
- **Bug 3 (macro_drivers shape) fixed (2026-05-30)** — `_validate_pass1_v2` now requires `macro_drivers` to be a dict keyed by `{A, B, C}` and rejects a list with hard error + corrective hint `"macro_drivers must be a dict keyed by A, B, C — not a list."` `_normalize_macro_drivers()` helper added for downstream backward-compat conversion. `_assemble_pipeline_output` uses `_normalize_macro_drivers()`. `_minimal_valid_pass1()` fixture updated to dict format. `TestBug3MacroDriversShape` × 7 added.
- **Bug 4 (driver_narratives A/B retry) fixed (2026-05-30)** — `_validate_pass2_v2` now treats missing `driver_narratives` for any driver ID as a **hard** error (was soft). Retry hint: `"driver_narratives for drivers {X} are missing — you must include a narrative paragraph for every macro driver ID present in pass1.macro_drivers."` `TestBug4DriverNarrativesHard` × 5 added.
- **ASML live pipeline test complete (2026-05-30)** — all 5 layers PASS on Opus 4.7. L1: baseline clean, `fy_sbc=$0.20B` (SBC gates on), `fy_contract_assets=None` (contract assets gates off), FCF divergence warning expected. L2: pass1 clean on corrective retry, Bug 3 fix confirmed live (macro_drivers keyed dict), catalysts ≥3. L3: peers AMAT/LRCX/KLAC/TOELY fetched, all three calibration guards fired live (Step A, Bug A, Bug B), hierarchy PASS, joint_probs sum=1.0000. L4: all 11 sections present, word count 1394, **one gap: `sbc_section` absent despite `fy_sbc` non-null** — Pass 2 prompt needs explicit gate instruction (see `docs/session_handoff.md` §4). L5: `audit_clean=True`, `b1_compliant=True`, 0 forbidden vocab, 4 of 7 LLM calls used. **227/227 pytest confirmed post-run.**
- **Live pipeline tickers tested (five total): AVGO, NVDA, KO, ASML (large-cap), ARLO (small-cap).** ARLO complete (2026-05-30): all 5 layers PASS. `fy_eps_non_gaap=-0.31` triggered new negative-EPS calibration log entry; Step A floored $0.13→$1.04 with full audit trail; RING-private 404 skipped gracefully; catalysts=0 (thin coverage); all 4 guards fired and logged; `audit_clean=True`, 0 forbidden vocab, 0 severity:error. `sbc_section` absent despite `fy_sbc` non-null — confirmed pre-existing gap (same as ASML, not a regression).
- **Negative trailing EPS guard logged (2026-05-30)** — `run_methodology_math` now initializes `calibration_log` before the EPS block (moved from line ~120 to before `_fy_eps` assignment). When `fy_eps_non_gaap ≤ 0`, appends `"Negative trailing EPS (X.XX) — bull EPS from event-driven scenario_eps (growth-rate formula not applicable)"` before Step A runs. Prevents the growth-rate formula from silently producing a more-negative bull EPS that Step A would then paper over with no path-choice record. `TestNegativeTrailingEPS` × 2 added: asserts log entry present and bull EPS > 0. **229/229 pytest pass.**
- **sbc_section prompt gap fixed (2026-05-30)** — `prompt_pass2.txt` now carries an explicit conditional directive: `sbc_section` is REQUIRED when `math_json.owner_earnings` is non-null. `_validate_pass2_v2` now accepts an optional `math` parameter; when `math.owner_earnings` is non-null and `sbc_section` is absent it raises a hard error triggering a retry. `run_methodology_math` now computes `owner_earnings = fy_fcf - fy_sbc` (None when either is absent). Both `_validate_pass2_v2` call sites in `run_pass2_report` updated to pass `math`. `TestSbcSectionRequired` × 5 added. **234/234 pytest pass.**
- **Phase I complete (2026-05-31).** `METHODOLOGY_VERSION = "v2"` live. v1 analytical path (`run_two_pass`, 21 compute functions, 12 AI functions) fully deleted. v1 renderer still in place — `_assemble_pipeline_output` does not set `methodology_version`, so render() routes to v1 renderer correctly for v2 reports.
- **Headwinds/tailwinds EPS impact wired (2026-05-31)** — `run_methodology_math` now computes `headwinds` and `tailwinds` lists from raw §5.2 events (bear→headwinds, bull→tailwinds, base→neither). Each entry includes `eps_impact_high/mid/low` (magnitudes, abs() applied; sign handled by renderer) plus renderer-alias fields `bull/base/bear_eps_impact` and `revenue_at_risk` (midpoint). `_assemble_pipeline_output` now passes these through from math instead of hard-coded `[]`. `TestHeadwindsTailwindsWiring` × 3 added. **237/237 pytest pass.**
- **Bull EPS reverted to event-driven (2026-06-21)** — commit 3030fd7 had silently changed bull EPS to use `fy_eps_non_gaap × (1 + capped_growth)^2` (growth-rate formula). Reverted to Phase D behavior (commit 3151a28): all three scenarios — bull, base, bear — now use `scenario_eps(fy_revenue, base_op_margin, events, scenario, tax_rate, shares_proj)`, the identical event-driven mechanism. Step A (`0.95 × consensus_high` floor) remains as the backstop when events produce a too-low bull EPS. The negative-EPS special-case log entry is also removed — `scenario_eps` produces positive EPS from revenue × margin regardless of trailing EPS sign. AVGO event-driven values: bull $14.14, base $10.49, bear $6.19. `TestBug5BullEPSGrowthRate` renamed to `TestBullEPSEventDriven`; 4 tests updated (2 rewritten, 1 deleted, 1 kept). `TestNegativeTrailingEPS` trimmed to 1 test (log-entry assertion deleted). **260/260 pytest pass.**

Everything else — writing v2 code, prompts, renderer, tests, running pytest/grep/structural smoke checks — is safe to do now.

---

## 2. Mental model

This is **not surgical**. It is a ground-up rewrite of the analytical core behind a **frozen I/O interface**. The interface (the dict contracts in §5) is sacred; everything behind it is being replaced. The outer shell survives: FMP fetch, `report_store`, auth, Streamlit chrome.

Two financial decisions are correct and load-bearing — never simplify them away:
1. **Per-scenario EPS *and* per-scenario P/E, then probability-weight the prices.** Not one blended EPS × one multiple.
2. **Single source of truth: Python owns every number; the LLM cites verbatim and does zero arithmetic.**

---

## 3. Hard rules (any violation = stop and fix; do not work around)

- The LLM does **zero arithmetic.** Every number in the report body comes verbatim from the `math` or `baseline` dict.
- **No silent fallbacks for required signals.** Pass 1 fails twice → typed `Pass1ValidationError` → real error UI. The DEGRADED path does not exist and must never be reintroduced.
- **No clamp/floor/ceiling/anchor fires without (a) a methodology justification and (b) a line in `math.calibration_log` saying why.**
- The company's **own current/trailing P/E is never an anchor or a cap** — sanity log line only.
- **Global LLM-call ceiling per report: 7** (1+1 Pass 1, +1 catalysts fallback, 1+1 Pass 2, 1 Pass 3, +1 BullCaseTooLow retry). Every retry path must terminate in a definite end state, including "retry failed → ship with the divergence note."

---

## 4. Build discipline (prevents breakage)

- **Never delete-in-place.** Build v2 paths *alongside* v1 behind the feature flag. Deleting v1 is always a **separate commit** from the one that builds v2, and only in the final deletion phase.
- **Commit at every phase exit criterion.** Each exit criterion is a commit boundary and a rollback point.
- **One phase per session.** Re-ground from this file at the start of each. Do not build a phase on top of an unverified earlier phase as if it passed.
- **Tests are written alongside or before the code in each phase**, never bolted on after.
- A baseline commit is tagged `pre-rebuild-baseline` for emergency rollback.

---

## 5. Frozen data contracts (immutable)

The four dict shapes — `baseline`, `pass1`, `math`, `pass2` (and `pass3`) — are defined in **v2 §5**. They are the contract between layers. Render and all downstream code rely on these shapes and nothing else.

- No new key is added without updating the contract first.
- No layer reads a key not in the contract.
- If a phase needs a new field, that is a contract change — flag it explicitly to the human, do not invent the key silently.

**Drift check:** the most common long-session failure is a later phase reading a key that isn't in the contract (a half-remembered name from earlier work). Before finishing any phase, grep the dict key names across `compute.py`, `ai.py`, and the prompt files to confirm every layer reads the same vocabulary defined in v2 §5.

---

## 6. Financial behavior rules (these change output — honor them)

Condensed from v3 Part B. Full reasoning lives there.

- **B1 — Reverse-DCF leads.** The implied-FCF-CAGR ("what growth the market is already pricing in") is the headline metric, because it's the one output that doesn't depend on the invented calibration parameters. Promote it in the report header and the Pass 2 prompt. Output targets as **ranges, not point estimates.**
- **B2 — Consensus floor is a backstop, not the answer.** The CAGR-cap removal is the real bull-case fix. The `0.95 × consensus_FY2_high` floor is a guardrail; when it binds, emit a **loud annexure note**. Never let the bull case silently collapse to consensus high with no flag.
- **B3 — Bear P/E floors are conditional.** The 15×/25× floors apply only to durable franchises (gate on `FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR`). Non-franchise names get no floor — real downside must be allowed to show.
- **B4 — Share count evolves over the horizon.** `scenario_eps` must use a projected share-count path (buybacks/dilution), not static shares.
- **B5 — Frame the output as FY+2 fair value, not a 12-month price forecast.** The framework does not model the timing of re-rating. Label it honestly everywhere.
- **B6 — Risk leads with prob-of-loss + worst-case drawdown.** Do not use "Sharpe." Do not use "capture ratio" without an explicit annexure definition (prefer renaming to a defined reward-to-risk ratio).
- **B7 — The regression fixture needs an independent check.** `tests_methodology.py` must include at least one hand-calculation independent of the v2 worked example, so the suite proves correctness, not just reproduction of the doc.

**Calibration constants** live in one named block (v2 §7.3, plus the v3 C2 additions). Changing any constant is a deliberate, reviewed act that requires regenerating the regression fixture.

---

## 7. Verification you can run anytime (no API credits needed)

These are free and must stay green:
- `pytest tests_methodology.py` (deterministic math layer — exact assertions).
- The grep checklist (v2 §11.6) — zero hits required after the deletion phase.
- The structural smoke harness: pipeline runs without exception, every required contract key present and typed, `joint_probs` sums to 1.0 (±0.001), word count ≤ 4500, no forbidden tokens, reverse-DCF present and finite.

**LLM-dependent checks require real pipeline calls and are deferred until credits return:** the 3× robustness runs, "succeeds on N tickers," the citation-error injection, and the NVDA bull-above-current end-to-end check.

**Nondeterminism rule:** never treat an LLM pass like a deterministic function. A single green LLM run is a false green. Either run LLM criteria 3× and require all to pass, or make the validator tolerant enough that normal variation always passes. The deterministic math layer gets exact assertions; anything touching the LLM gets tolerance. (Note: three *fixed fixtures* only cover what you deliberately varied — they do not substitute for real stochastic variation.)

---

## 8. How to run a phase

1. Re-read this file (you're doing that now).
2. The human gives you one phase from v3 Part E. Its exit criterion is the literal acceptance test.
3. Build it. When the phase references "v2 §X," read that section from `docs/methodology_replacement_plan.md` for the specifics.
4. Write the tests alongside the code.
5. Run all free verifications (§7). Mark anything that needs a live pipeline as UNVERIFIED in a code comment.
6. Stop at the exit criterion. Do not start the next phase. Do not touch the §1 hard stops.