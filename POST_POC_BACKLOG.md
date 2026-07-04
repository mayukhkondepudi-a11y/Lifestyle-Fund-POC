# Post-POC Backlog

Deferred items from the scenario-core rewrite. Append the moment something is flagged — do NOT leave deferrals in chat, where they evaporate. Consult before declaring any phase done.

## Central open question
| # | Item | Type | Notes |
|---|------|------|-------|
| 1 | Recommendation stability | reliability / BLOCKING trust | NVDA flipped BUY↔PASS between two runs at the same price ($197.58), from Pass 1 LLM variance. Root cause: Pass 1 ran at temperature 1.0 (default, unset). Fix in progress: PASS1_TEMPERATURE=0.2 + 3-run NVDA test. If it still swings at low temp → ensemble Pass 1 (avg drivers over N runs) or show recommendation as a range/confidence, not a single value. Gates whether the headline BUY/PASS can be trusted by a real user. |

## Calibration — "is the judgment right" (separate from "is it stable")
| # | Item | Type | Notes |
|---|------|------|-------|
| 2 | MAX_BASE_GROWTH = 0.35 may be too blunt for genuine high-growers | calibration | AVGO/NVDA came out steeply negative (PASS, −30% to −44%). Capping growth at 35% makes real high-growers look overvalued by construction. Low temperature makes the answer consistent, NOT correct — this is the "correct" half. Read the AVGO/NVDA reports and decide if the cap is doing too much work. |
| 3 | CLS base P/E 28.9× is high for a cyclical EMS name | calibration | Peer-anchored multiple landed above CLS's own ~25× forward via a growth quality-premium. Same family as #2 — the seam where bull-case inflation could re-enter through quality_adj. Confirm the premium is deserved. |

## Hygiene / tech-debt
| # | Item | Type | Notes |
|---|------|------|-------|
| 4 | Forbidden-vocab lists disagree | tech-debt | ai.py _PASS3_FORBIDDEN bans "capture ratio"; smoke_harness.py bans bare "capture". Two audits can disagree on the same report. Reconcile to one source of truth. |
| 5 | "capture" word-check false-alarms on ordinary English | tech-debt | The bare-"capture" check flags normal prose ("the bull captures the upper half"). Tighten so checks stop crying wolf. Related to #4. |
| 6 | citation_check is presence-based, not provenance-based | test-gap / trustworthiness | Matches any $ddd.dd token and searches the WHOLE math blob for presence. False-negative: a hallucinated headline number passes if its value collides with any unrelated float. False-positive: legitimate baseline/pass1 citations flag as misses. The "cite peer multiples from source" prompt rule fixed the AMD case this round — only build the heavier provenance-aware check if mis-citation RECURS. |
| 7 | Tailwind REV. OPPORTUNITY column shows "-" | cosmetic | EPS-impact numbers correct; revenue-opportunity column wired for headwinds only, never tailwinds. Display gap. |
| 8 | Live-validation artifacts overwrite same filename | tooling | _live_out_<TICKER>.json is overwritten each run, so run-vs-run input diffs are impossible (hit this diagnosing the NVDA swing). Fix: timestamp artifact filenames. (Being addressed alongside the temperature change.) |
| 9 | Other expensive AI calls may discard stop-reason metadata | tech-debt | run_ai discarded stop_reason/usage until we fixed it (caused the silent truncation). Scan whether catalysts/Pass 3/other calls swallow their metadata the same way. |
| 10 | No render-crash / headless-Streamlit test | test-gap | section_gating_check covers structural gating, not actual render crashes. Headless Streamlit snapshotting is a rabbit hole — revisit only if render crashes recur. |
| 11 | Auto-retry on truncation not built | deferred-feature | Deliberately not built — only one truncation seen, now fixed by raising budgets. Build retry-with-higher-budget only if truncation recurs at the generous budgets. Auto-retry is also the lever that would raise per-report cost, so hold. |

## Merge / state
| # | Item | Type | Notes |
|---|------|------|-------|
| 12 | Merge scenario-core-rewrite + update CLAUDE.md §1 | process | Engine is strictly better than main and validated on 3 tickers — safe to merge. CLAUDE.md §1 still describes pre-rewrite v2 state; update it at merge. Merging the ENGINE is safe now; TRUSTING the recommendation waits on #1. |

## Carried over from prior backlog
| # | Item | Type | Notes |
|---|------|------|-------|
| 13 | base-case-as-headline gate not built | feature | Needs a real distribution_skew_flag (e.g. bull/base price ratio > 2.5) in the math dict + its own test, then a renderer gate and a section_gating_check assertion. Deliberate math change, not a bug. (Carried from the prior backlog version; not superseded by items 1–12 above.) |

## Architecture / trustworthiness
| # | Item | Type | Notes |
|---|------|------|-------|
| 14 | Operating margin is LLM-assigned, not Python-owned | ARCHITECTURE / trustworthiness | scenario_margin is a revenue-weighted average of per-event op_margin_to_apply values that come from Pass 1 (the LLM). The statement-derived fy_op_margin (8.64%) is only a fallback that never fires when events exist; for CLS the math uses 8.94%, an LLM-driven number. Margin is a direct EPS multiplier — sensitivity is ~−26% base EPS / thesis-flipping (14.36→10.60, +14.6%→−15.4%) if it moved to 6.6%. This violates the "Python owns every number" principle for the single most leveraged input. Fix in a DEDICATED session: drive scenario_margin from a deterministic base±delta rule (like P/E and growth), demote LLM per-event margins to sanity input or remove. Own change, own tests, own live validation. |
| 15 | Peer-set composition is ungoverned and can flip the verdict | reliability / threshold | CLS is WATCH (base_pe 27.23, +12.4%) off the 3-peer test fixture but BUY (28.93, +23.6%) off a 4-peer live capture — the only difference is whether ANET is in the peer set. Peers are re-fetched each live run, so verdict depends on which comparables return that day. Same class as NVDA temperature swing and LLM-margin: an ungoverned input near the BUY/WATCH threshold. Options: (a) deterministic peer-selection rule (fixed criteria for inclusion, e.g. same industry + size band, so the set is reproducible), (b) surface peer set + flag verdict sensitivity when a name is near-threshold, (c) the borderline band. Note: quality_adj CAP is doing the flip work here — ANET trips the 1.30 cap; ties to the quality_adj calibration item. |
