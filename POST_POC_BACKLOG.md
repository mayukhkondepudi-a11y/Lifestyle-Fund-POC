# Post-POC Backlog

Non-blocking items deferred during the build. Nothing here blocks the POC or current harness work.
Append the moment an item is flagged — do NOT leave deferrals in chat, where they evaporate.
Consult this list before declaring any phase "done".

| # | Item | Type | Where | Notes |
|---|------|------|-------|-------|
| 1 | Forbidden-vocab lists disagree | tech-debt | ai.py `_PASS3_FORBIDDEN` vs smoke_harness.py | Pass 3 bans "capture ratio"; smoke harness bans bare "capture". The two audits can disagree on the same report. Reconcile to one source of truth. |
| 2 | Tailwind REV. OPPORTUNITY column shows "-" | cosmetic | renderer | EPS-impact numbers are correct; revenue-opportunity column wired for headwinds only, never tailwinds. Display gap only. |
| 3 | base-case-as-headline gate not built | feature | run_methodology_math.py + renderer | Needs a real distribution_skew_flag (e.g. bull/base price ratio > 2.5) in the math dict + its own test, then a renderer gate and a section_gating_check assertion. Deliberate math change, not a bug. |
| 4 | No render-crash / headless-Streamlit test | test-gap | harness | section_gating_check covers structural gating but not actual render crashes (F3 class). Headless Streamlit snapshotting is a rabbit hole — revisit only if render crashes recur. |
| 5 | citation_check is presence-based, not provenance-based | test-gap / trustworthiness | audit_checks.py | _FIGURE_RE matches any $?ddd.dd token and searches the WHOLE serialized math blob for presence. Two failure modes, both confirmed: (a) FALSE-NEGATIVE — a hallucinated headline number passes if its value collides with any unrelated float elsewhere in the dict (e.g. a DCF intermediate). Blindest on the highest-stakes figure. (b) FALSE-POSITIVE — legitimate citations from baseline/pass1 flag as misses (check has no visibility into those dicts). FIX: provenance-aware matching — verify a figure against the SPECIFIC field it claims to source from, not blob-wide presence; give the check read access to baseline/pass1. Until fixed: green = "no gross wiring break" only, NOT number-integrity. Real integrity gate remains LLM Pass 3. |
