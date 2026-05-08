# PickR Codebase Index
> Token-efficient reference. Point the AI here instead of scanning raw files.

> **Refactor 2026-05**: Consolidated 3 duplicate GitHub-API helper sets into a single
> `gh_api.py` module. Extracted the 450-line CSS megablock from `app.py` into
> `styles.py` (`APP_CSS` constant). Centralized `DOMAIN_MAP` + recommendation color
> constants in `config.py`; added `clean_ticker(t)` helper in `formatting.py`.
> Removed the legacy `run_ai_html` and a buggy duplicate `run_pass2` definition
> from `ai.py`.

---

## Architecture Overview

```
User Input (ticker)
  → fmp_api.fetch_full()          # raw yfinance / FMP data
  → compute.calc()                # normalized metrics dict
  → ai.run_two_pass()             # LLM orchestration
      ├─ run_pass1()              # structured JSON assumptions
      ├─ compute_scenario_math()  # Python math (EPS, price targets, probs)
      └─ run_pass2()              # narrative text JSON
  → report_store.save_report()   # persist to GitHub
```

---

## File Map

| File | Role | Key Entry Points |
|------|------|-----------------|
| `app.py` | Streamlit UI (main entry) | `pt_table` helper for repeated `<table class="pt">` markup |
| `styles.py` | Single CSS string for the whole app | `APP_CSS` (inject via `st.markdown(APP_CSS, unsafe_allow_html=True)`) |
| `ai.py` | LLM orchestration | `run_two_pass`, `run_pass1`, `run_pass2`, `thesis_check` |
| `compute.py` | Financial math engine | `calc`, `compute_scenario_math`, `compute_qglp_score` |
| `fmp_api.py` | Data fetching (yf primary, FMP fallback) | `fetch_full`, `get_current_price`, `search_ticker` |
| `config.py` | Constants, API keys, filters | `FREE_MODELS`, `FILTERS`, `SECTOR_PEERS`, `DOMAIN_MAP`, `COLOR_BULL/BEAR/BASE/ADMIN` |
| `formatting.py` | Pure display helpers | `fmt_n`, `fmt_p`, `fmt_c`, `safe_float`, `clean_ticker` |
| `gh_api.py` | Canonical GitHub Contents API helpers | `gh_headers`, `gh_get_json`, `gh_put_json` |
| `report_store.py` | Per-user report persistence (uses `gh_api`) | `save_report`, `load_user_index`, `load_report` |
| `github_store.py` | Tracker + screener results persistence (uses `gh_api`) | `load_tracker`, `save_tracker`, `add_tracked_stock`, `load_screener_results_raw`, `push_screener_results` |
| `screener.py` | QGLP batch screener (GitHub Actions) | `screen_universe`, `main` |
| `auth.py` | Login / register / guest (uses `gh_api`) | `render_auth_modal`, `render_sidebar`, `load_users_github`, `save_users_github`, `load_guest_counts`, `increment_guest_count` |
| `logos.py` | Stock logo HTML (Clearbit + SVG fallback) | `get_logo_html(ticker, …, website="")`, `get_logo_url(ticker, website="")` |
| `universe.py` | Ticker universes | `US_UNIVERSE` (~480), `INDIA_UNIVERSE` (~180) |
| `email_service.py` | Email via Resend → Gmail fallback | `send_email`, `email_confirmation` |
| `check_prices.py` | Daily price alert runner (GitHub Actions) | `main` |
| `prompt_system.txt` | System prompt for all LLM calls | — |
| `prompt_pass1.txt` | Pass-1 user prompt template | — |
| `prompt_pass2.txt` | Pass-2 user prompt template | — |

---

## `ai.py` — LLM Orchestration

```
run_ai(messages, max_tokens=4000, model="claude-opus-4-7", free_models=None)
  → (text, model_used, errors)
  # Tries Anthropic first; falls back through FREE_MODELS list

parse_json_response(raw, model="unknown")
  → (dict, error_str)
  # Strips fences, repairs truncated JSON, progressive truncation

run_pass1(ticker, m, reverse_dcf_json)
  → dict  # LLM structured assumptions: segments, scenarios, headwinds, tailwinds, etc.
  # Calls _build_pass1_messages → run_ai → parse_json_response
  # Validates segment revenue total vs actual revenue (reject if >2x or <0.5x divergence)

run_pass2(ticker, m, scenario_math, pass1_output, reverse_dcf_json)
  → dict  # LLM narrative: investment_thesis, business_overview, scenario_commentary, etc.
  # Calls _build_pass2_messages → run_ai → parse_json_response
  # Runs clean_latex() on all narrative fields

run_two_pass(ticker, m)
  → final_dict  # Full merged analysis
  # Pipeline: pass1 → compute_scenario_math → pass2 → merge
  # Applies recommendation override logic (BUY/WATCH/PASS consistency guard)

thesis_check(ticker, company, original_metrics, original_thesis, current_metrics,
             model="claude-opus-4-7", free_models=None)
  → dict  # {thesis_intact, confidence, updated_action, key_changes, rationale}
  # Used by check_prices.py for price-alert thesis re-evaluation

run_ai_html(ticker, m)  [legacy]
  → (html_str, errors)
```

**Pass 1 output keys:** `segments`, `concentration`, `headwinds`, `tailwinds`, `macro_drivers`, `scenarios` (bull/base/bear), `market_expectations`, `sensitivity`, `catalysts`, `peer_tickers`

**Pass 2 output keys:** `recommendation`, `conviction`, `investment_thesis`, `business_overview`, `revenue_architecture`, `growth_drivers`, `margin_analysis`, `financial_health`, `competitive_position`, `headwind_narrative`, `tailwind_narrative`, `market_pricing_commentary`, `scenario_commentary`, `conclusion`, `model_used`

> Note (post-refactor): `run_ai_html` (legacy HTML report generator) was removed.
> A buggy duplicate `run_pass2` definition that shadowed the canonical one (and
> was missing the LaTeX cleaning step) was also removed; reports now correctly
> have currency `$NUMBER` patterns escaped before display.

---

## `compute.py` — Financial Math

```
calc(data)  → metrics dict
  # data = {info, inc, bs, cf, hist, news} from fetch_full()
  # Computes: all valuation ratios, EPS from statements, FCF,
  #           CAGRs, PEG, D/E, margins, price history, reverse DCF

compute_reverse_dcf(metrics, years=5)  → dict
  # Binary search: finds implied FCF CAGR at current price
  # {available, implied_fcf_cagr, wacc_used, terminal_growth, tv_pct_flag, note}
  # Skips Financial Services / Financials sectors

compute_scenario_probabilities(metrics, llm_output)  → dict
  # Signal-derived v2: 8 signals → bull_score → {bull, base, bear} probabilities
  # Signals: EPS revision, revenue CAGR, EPS CAGR, op margin, PEG, D/E, MA200, beta

compute_scenario_math(metrics, llm_output)  → dict
  # Main orchestrator — calls probabilities + _compute_single_scenario x3
  # Enforces monotonicity (bear < base < bull price targets)
  # Returns: {scenarios, expected_value, expected_return, risk_adjusted_score,
  #           upside_downside_ratio, prob_positive_return, sensitivity_table, ...}

validate_post_scenario(metrics, scenario_results)  → (bool, list[str])
  # Post-check: base return > -5%, expected return > 0, risk_adj > 0, EPS sanity

compute_qglp_score(metrics)  → float (0–100)
  # PEG(30) + ROE(25) + EPS CAGR(25) + FCF yield(10) + D/E(10)

compute_sensitivity_table(base_scenario, current_price)  → dict
  # Grid: margin_delta × pe_delta → {adj_eps, adj_pe, price_target, implied_return}

clean_latex(text)  → str
  # Escapes $NUMBER as \$NUMBER; strips LaTeX math from LLM output
```

**`calc()` output keys (partial):** `company_name`, `sector`, `currency`, `current_price`, `market_cap`, `trailing_pe`, `forward_pe`, `peg_ratio`, `ev_to_ebitda`, `gross_margin`, `operating_margin`, `profit_margin`, `roe`, `trailing_eps`, `forward_eps`, `earnings_growth`, `total_revenue`, `revenue_growth`, `free_cashflow`, `debt_to_equity`, `beta`, `week_52_high/low`, `ma_50`, `ma_200`, `revenue_cagr`, `eps_cagr`, `net_income_cagr`, `stmt_trailing_eps`, `reverse_dcf`, `data_quality_warnings`

**EPS accuracy chain (v3):**
- Statement EPS (`_get_statement_eps`) overrides `info["trailingEps"]` if >30% divergence
- PEG uses forward consensus → fwd/trail derived (capped 30%) → historical CAGR (capped 25%)
- Scenario EPS reconciles Python vs LLM; GAAP suppression detection; 3x trailing EPS clamp

---

## `fmp_api.py` — Data Fetching

```
fetch_full(ticker)  → {info, inc, bs, cf, hist, news}
  # yfinance first; FMP fallback for US-only (not .NS/.BO)
  # Parallel fetch: income_stmt, balance_sheet, cashflow, history, news

search_ticker(query)  → [{symbol, name, exchange}]
  # yfinance Yahoo search primary; FMP /search fallback

get_profile(ticker)  → info dict
  # yfinance primary; FMP /profile + /quote fallback + _merge_profile_quote

get_current_price(ticker)  → float | None
  # yfinance primary; FMP /quote fallback

get_current_metrics(ticker)  → dict
  # For thesis_check: trailing_pe, forward_pe, peg_ratio, roe, operating_margin, etc.

get_historical_prices(ticker, period="5y")  → DataFrame | None
  # Always yfinance; weekly interval

enrich_info_with_ratios(info_dict, ticker, ratios=None, metrics=None)  → dict
  # FMP-only enrichment: fills forward_pe, grossMargins, EV/EBITDA, FCF, etc.

# Statement fetchers (FMP):
get_income_statement(ticker) / get_balance_sheet(ticker) / get_cashflow(ticker)
statements_to_dataframe(statements, key_mapping)  → DataFrame

# Key maps:
INCOME_KEY_MAP   # revenue→Total Revenue, eps→Basic EPS, epsdiluted→Diluted EPS, ...
BALANCE_KEY_MAP  # totalDebt→Total Debt, totalStockholdersEquity→Stockholders Equity, ...
CASHFLOW_KEY_MAP # operatingCashFlow→Operating Cash Flow, capitalExpenditure→Capital Expenditure, ...
```

---

## `config.py` — Constants

```python
# API keys (read from st.secrets or env):
ANTHROPIC_API_KEY, OPENROUTER_API_KEY, FMP_API_KEY
GMAIL_SENDER, GMAIL_APP_PASS, RESEND_API_KEY
GITHUB_TOKEN, GITHUB_REPO

# Files:
TRACKER_FILE  = "tracked_stocks.json"
SCREENER_FILE = "screener_results.json"

# Models:
FREE_MODELS          # 5 OpenRouter free models (primary fallback list)
FREE_MODELS_EXTENDED # 10 models (used for thesis_check)

# Screener filters:
FILTERS        # US: min_roe=0.15, max_debt_equity=1.0, max_peg=1.4, min_earnings_cagr=0.12
FILTERS_INDIA  # IN: min_roe=0.12, max_debt_equity=1.5, max_peg=1.4, min_earnings_cagr=0.10

# Display:
CURRENCY_SYMBOLS  # {USD→$, INR→Rs., EUR→E, ...}
POPULAR           # {display_name → ticker} for dropdown
SECTOR_PEERS      # {sector → [tickers]} for peer comparison
```

---

## `formatting.py` — Display Helpers

```python
safe_float(val, default=0.0)     # None-safe float cast
get_sym(currency)                # currency → symbol string
fmt_n(v, p="", s="", d=2)       # number → "1.23B" / "456.78M" / "1.23K"
fmt_p(v, d=1)                    # fraction or pct → "12.3%"
fmt_r(v, d=2)                    # raw float → "12.34"
fmt_c(v, cur="USD", d=2)         # currency amount → "$1.23B"
strip_html(text)                 # remove HTML tags + markdown from text
```

---

## `gh_api.py` — Canonical GitHub Contents API

Single source of truth for all GitHub repo file reads/writes. Used by
`report_store.py`, `github_store.py`, and `auth.py`.

```
gh_headers()                                          → dict
gh_get_json(filepath)                                 → (content, sha)  # (None, None) on error
gh_put_json(filepath, content, sha=None, message=None) → (ok: bool, error: str | None)
```

Callers default missing/error responses themselves: `users, sha = gh_get_json("users.json"); users = users or {}`.

---

## `report_store.py` — GitHub Report Persistence

```
save_report(username, ticker, metrics, analysis)  → report_id ("TICKER_DATE")
  # Writes reports/{username}/{ticker}_{date}.json (via gh_put_json)
  # Updates reports/{username}/index.json (max 50 entries)
  # Stores: ticker, date, recommendation, expected_return, risk_adjusted_score,
  #         metrics (minus description/news/history), full analysis

load_user_index(username)  → list[{report_id, ticker, company_name, date, recommendation, expected_return}]

load_report(username, report_id)  → full report dict | None
```

---

## `screener.py` — QGLP Batch Screener

Runs as a GitHub Action daily. Two-phase pipeline:

```
screen_universe(tickers, market_label, filters, min_mcap)  → list[metrics_dict]
  Phase 1 (parallel, PHASE1_WORKERS=6):
    _phase1_ticker(ticker, filters, min_mcap, cache)
      → quality filters: mcap, ROE, D/E, FCF
      → self-computed EPS from income_stmt (Diluted EPS row)
      → compute trailing_pe = price / stmt_eps
      → reject if PE > 100

  Phase 2 (sequential):
    _phase2_ticker(m, filters, cache)
      → 2-year EPS CAGR from statements (SCREENER_CAGR_LOOKBACK=2)
      → PEG = PE / CAGR (capped at 20%, floor 0.3)
      → cross-validate: reject if analyst consensus negative but CAGR positive
      → compute_qglp_score(m)

  Sort by qglp_score desc → top MAX_PICKS=10

save_results(us_picks, india_picks)
  → writes screener_results.json + pushes to GitHub via github_store

main()  → screens US_UNIVERSE + INDIA_UNIVERSE, saves results
```

**Skip cache:** `screener_cache.json`, TTL=5 days (`CACHE_TTL_DAYS` env)

---

## `auth.py` — Authentication

```
render_auth_modal()  → (name, username, is_authenticated)
  # Streamlit tabs: Sign In / Create Account / Guest
  # Guest: 1 free report, identified by IP fingerprint
  # Registered: 3 free reports, report history

render_sidebar(username, name)
  # Shows username + sign-out button

# GitHub persistence:
load_users_github()          → (users_dict, sha)
save_users_github(users, sha) → bool
# users.json format: {username: {name, email, password_hash, report_count}}

# Guest rate limiting:
load_guest_counts()                   → {fingerprint: count}
increment_guest_count(fingerprint)    → count_int
# Stored in guest_counts.json on GitHub
```

---

## `logos.py` — Stock Logo Utilities

```
get_logo_url(ticker)               → URL string (Clearbit) or None
get_logo_html(ticker, size=32)     → <img> or styled SVG monogram
get_logo_and_name_html(ticker, name, size=32) → combined HTML block

TICKER_DOMAIN  # {ticker → domain} for Clearbit lookup
```

---

## `universe.py` — Ticker Universes

```python
SP500_TOP_100        # top 100 S&P by sector
SP500_NEXT_200       # next 200 S&P tickers
SP500_REMAINING      # rest of S&P 500
US_UNIVERSE          # = SP500_TOP_100 + SP500_NEXT_200 + SP500_REMAINING (~480 total)
INDIA_UNIVERSE       # Nifty 50 + Nifty Next 150 key constituents (~180 tickers, all .NS suffix)
```

---

## `email_service.py` — Email Dispatch

```
send_email(to_email, subject, html_body)  → (bool, error_str)
  # Resend API primary; Gmail SMTP fallback

email_confirmation(to_email, ticker, company_name, recommendation, target_price, entry_price)
  # Sends formatted HTML confirmation email when user tracks a stock

build_alert_email(ticker, company, price, target, thesis_eval)
  # Builds HTML for price-alert emails (used by check_prices.py)
```

---

## `check_prices.py` — Daily Price Alert Runner

```
main()
  # Loads tracked_stocks.json from GitHub (via github_store.load_tracker)
  # For each stock: get_current_price → compare to target
  # On target hit: get_current_metrics → ai.thesis_check → send alert email
  # Updates last_checked, last_price, alert_sent in tracker
  # Saves updated tracker back to GitHub
```

---

## Data Schemas

### `tracked_stocks.json` entries
```json
{
  "ticker": "AAPL", "company_name": "Apple Inc.",
  "user_email": "user@example.com",
  "target_price": 200.0, "recommendation": "BUY",
  "original_metrics": {...}, "thesis_summary": "...",
  "alert_sent": false, "last_checked": "2026-05-08", "last_price": 185.0
}
```

### `screener_results.json`
```json
{
  "last_updated": "2026-05-08 10:00 UTC",
  "filters_us": {...}, "filters_india": {...},
  "us_picks": [{ticker, name, sector, price, trailing_pe, peg_ratio, roe,
                earnings_cagr, fcf_yield, debt_equity, qglp_score}],
  "india_picks": [...]
}
```

### Scenario output (inside `scenario_math.scenarios.{bull|base|bear}`)
```
probability, segment_builds, total_revenue, revenue_growth,
operating_margin, net_margin, projected_eps, llm_eps, eps_flag,
pe_multiple, pe_rationale, price_target, implied_return,
breakeven_pe, fcf_yield_at_target, narrative, monotonicity_flag
```

---

## Dependency Graph

```
app.py
  ├── styles.py      (APP_CSS)
  ├── ai.py          → compute.py, formatting.py, config.py
  ├── compute.py     → formatting.py
  ├── fmp_api.py     → config.py
  ├── report_store.py → gh_api.py
  ├── github_store.py → gh_api.py, config.py
  ├── auth.py        → gh_api.py, config.py
  ├── logos.py
  ├── formatting.py  → config.py
  └── config.py

gh_api.py     → config.py
screener.py   → universe.py, config.py, compute.py, github_store.py
check_prices.py → github_store.py, email_service.py, ai.py, fmp_api.py, config.py
```

---

## GitHub Actions Integration

| Script | Trigger | What it does |
|--------|---------|-------------|
| `screener.py` | Daily cron | Screens US + India universes, writes `screener_results.json` |
| `check_prices.py` | Daily cron | Checks price alerts, runs thesis checks, sends emails |

Both use `github_store.py` (not in source dir — likely in a separate Actions workflow file) for reading/writing `tracked_stocks.json` and `screener_results.json` to the repo.

---

## Common Patterns

**Adding a new computed metric:**
1. Add to `calc()` in `compute.py` (reads from `data["info"]`, `data["inc"]`, `data["bs"]`, `data["cf"]`)
2. It's automatically passed to both LLM prompts via `metrics_json` placeholder

**Adding a new scenario signal:**
1. Edit `compute_scenario_probabilities()` in `compute.py`
2. Add signal to `signal_log` with `{signal, value, delta, note}`

**Changing LLM behavior:**
- System-level: edit `prompt_system.txt`
- Pass 1 (assumptions/segments/scenarios): edit `prompt_pass1.txt`
- Pass 2 (narrative/recommendation): edit `prompt_pass2.txt`
- Available template vars: `{ticker}`, `{company_name}`, `{metrics_json}`, `{description}`, `{current_price}`, `{trailing_pe}`, `{forward_pe}`, `{total_revenue}`, `{reverse_dcf_json}`, etc.

**Report storage path:** `reports/{username}/{TICKER}_{YYYY-MM-DD}.json`
