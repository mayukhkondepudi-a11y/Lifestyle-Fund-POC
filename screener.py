"""
screener.py — QGLP hard-filter screener (v3).

Runs daily via GitHub Actions.

v3 changes (EPS accuracy overhaul):
  • Self-computed EPS from income_stmt Diluted EPS row (never trust .info)
  • 2-year lookback for CAGR (avoids COVID trough distortion)
  • Screener growth cap = 20% (conservative gate-keeping)
  • PEG floor of 0.3 (anything below is almost certainly data error)
  • Cross-validation: reject if analyst consensus is negative but CAGR positive
  • Trailing PE computed from price / statement EPS (not API field)

Retained from v2:
  • Parallel phase-1 (ThreadPoolExecutor)
  • Skip cache with TTL
  • Exponential back-off on rate errors
  • Min market-cap pre-filter
  • Configurable via env vars
"""

import json
import os
import time
import random
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from universe import US_UNIVERSE, INDIA_UNIVERSE
from config import FILTERS, FILTERS_INDIA
from compute import compute_qglp_score
from github_store import push_screener_results

# ── Runtime knobs (override via env) ─────────────────────────
OUTPUT_FILE    = "screener_results.json"
CACHE_FILE     = "screener_cache.json"
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS",  "5"))
MAX_PICKS      = int(os.getenv("MAX_PICKS",       "10"))
PHASE1_WORKERS = int(os.getenv("PHASE1_WORKERS",  "6"))
MIN_MCAP_US    = float(os.getenv("MIN_MCAP_US",   "2e9"))
MIN_MCAP_IN    = float(os.getenv("MIN_MCAP_IN",   "3e10"))

# ── Screener-specific constants (hardcoded, not configurable) ─
SCREENER_CAGR_LOOKBACK = 2       # years
SCREENER_GROWTH_CAP    = 20.0    # max growth % used in PEG
SCREENER_PEG_FLOOR     = 0.3     # below this = data error
SCREENER_PE_CEILING    = 100.0   # above this = not a value candidate


# ══════════════════════════════════════════════════════════════
# SKIP CACHE (unchanged from v2)
# ══════════════════════════════════════════════════════════════

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2, default=str)
    except Exception as e:
        print(f"  Cache save failed: {e}")


def _cache_fresh(cache: dict, ticker: str):
    entry = cache.get(ticker)
    if not entry:
        return None
    try:
        ts  = datetime.fromisoformat(entry["ts"]).replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        if age < timedelta(days=CACHE_TTL_DAYS):
            return entry
    except Exception:
        pass
    return None


def _cache_write(cache: dict, ticker: str, result: str,
                 reason: str = "", score=None):
    cache[ticker] = {
        "result": result,
        "reason": reason,
        "score":  score,
        "ts":     datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# FETCH HELPERS (unchanged from v2)
# ══════════════════════════════════════════════════════════════

def _jitter(base: float = 0.5):
    time.sleep(base * (0.6 + 0.8 * random.random()))


def _retry(fn, retries: int = 3, base_sleep: float = 2.0):
    for attempt in range(retries):
        try:
            return fn(), None
        except Exception as e:
            err = str(e)
            if attempt < retries - 1:
                time.sleep(base_sleep * (2 ** attempt) * (0.8 + 0.4 * random.random()))
            else:
                return None, err
    return None, "unknown"


def _get_info(ticker: str):
    def _fetch():
        t    = yf.Ticker(ticker)
        info = t.info
        if not info or len(info) < 5:
            raise ValueError("Empty info")
        return t
    return _retry(_fetch, retries=3)


def _de_from_info(de_api):
    if de_api is None:
        return None
    try:
        v = float(de_api)
        return round(v / 100, 4) if v > 10 else round(v, 4)
    except Exception:
        return None


def _roe_from_statements(t):
    try:
        inc = t.income_stmt
        bs  = t.balance_sheet
        if inc is None or bs is None:
            return None
        ni = None
        for lbl in ["Net Income", "Net Income Common Stockholders"]:
            if lbl in inc.index:
                row = inc.loc[lbl].dropna()
                if not row.empty:
                    ni = float(row.iloc[0]); break
        eq = None
        for lbl in ["Stockholders Equity", "Total Stockholder Equity",
                    "Common Stock Equity", "Stockholders' Equity"]:
            if lbl in bs.index:
                row = bs.loc[lbl].dropna()
                if not row.empty:
                    eq = float(row.iloc[0]); break
        if ni and eq and eq > 0:
            return round(ni / eq, 4)
    except Exception:
        pass
    return None


def _de_from_statements(t):
    try:
        bs = t.balance_sheet
        if bs is None:
            return None
        debt = None
        for lbl in ["Total Debt", "Long Term Debt"]:
            if lbl in bs.index:
                row = bs.loc[lbl].dropna()
                if not row.empty:
                    debt = float(row.iloc[0]); break
        eq = None
        for lbl in ["Stockholders Equity", "Total Stockholder Equity",
                    "Common Stock Equity", "Stockholders' Equity"]:
            if lbl in bs.index:
                row = bs.loc[lbl].dropna()
                if not row.empty:
                    eq = float(row.iloc[0]); break
        if debt is not None and eq and eq > 0:
            return round(debt / eq, 4)
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# SELF-COMPUTED EPS (v3 — core of the accuracy fix)
# ══════════════════════════════════════════════════════════════

def _get_eps_series(t_obj):
    """
    Extract annual Diluted EPS series from the income statement.

    Returns list of (year_int, eps_float) sorted ascending by year.
    Empty list on failure.

    WHY THIS EXISTS:
    .info["trailingEps"] and .info["forwardEps"] from yfinance are
    frequently stale, scope-mismatched (standalone vs consolidated for
    Indian stocks), or silently non-GAAP. The income_stmt DataFrame
    contains the actual filed GAAP numbers.

    yfinance income_stmt has columns = dates (newest-first by default)
    and rows = line items. We sort columns ascending so index 0 = oldest.
    """
    try:
        inc = t_obj.income_stmt
        if inc is None or inc.empty:
            return []

        # ── Priority 1: Diluted EPS row (directly from filings) ───
        for lbl in ["Diluted EPS", "Basic EPS"]:
            if lbl in inc.index:
                row = inc.loc[lbl].dropna()
                if row.empty:
                    continue
                # Sort ascending by date (columns are Timestamp objects)
                row = row.sort_index()
                result = []
                for dt, val in row.items():
                    try:
                        yr = dt.year if hasattr(dt, "year") else int(str(dt)[:4])
                        eps = float(val)
                        result.append((yr, eps))
                    except Exception:
                        continue
                if len(result) >= 2:
                    return result

        # ── Priority 2: Net Income / Shares Outstanding ───────────
        # Less accurate (uses current share count for all years) but
        # better than trusting the API .info field.
        ni_row = None
        for lbl in ["Net Income", "Net Income Common Stockholders"]:
            if lbl in inc.index:
                ni_row = inc.loc[lbl].dropna().sort_index()
                if not ni_row.empty:
                    break

        if ni_row is None or ni_row.empty:
            return []

        # Get share count: prefer balance sheet, fall back to .info
        shares = None
        try:
            bs = t_obj.balance_sheet
            if bs is not None and not bs.empty:
                for lbl in ["Ordinary Shares Number", "Share Issued",
                            "Common Stock Shares Outstanding"]:
                    if lbl in bs.index:
                        s_row = bs.loc[lbl].dropna()
                        if not s_row.empty:
                            shares = float(s_row.iloc[0])
                            break
        except Exception:
            pass

        if shares is None or shares <= 0:
            shares = t_obj.info.get("sharesOutstanding")

        if not shares or shares <= 0:
            return []

        result = []
        for dt, ni in ni_row.items():
            try:
                yr = dt.year if hasattr(dt, "year") else int(str(dt)[:4])
                eps = float(ni) / shares
                result.append((yr, round(eps, 4)))
            except Exception:
                continue
        return result if len(result) >= 2 else []

    except Exception:
        return []


def _trailing_eps_from_series(eps_series):
    """Most recent annual EPS from our self-computed series."""
    if not eps_series:
        return None
    return eps_series[-1][1]


def _eps_cagr_from_series(eps_series, lookback_years=2):
    """
    Compute EPS CAGR over `lookback_years` from self-derived series.

    RULES:
    - Both endpoints must be POSITIVE (no trough-to-recovery nonsense)
    - Returns (cagr_float, years_int) or (None, 0)
    - Does NOT cap — caller is responsible for capping

    The series is sorted ascending: index 0 = oldest, index -1 = newest.
    """
    if not eps_series or len(eps_series) < 2:
        return None, 0

    n = len(eps_series)
    lookback = min(lookback_years, n - 1)

    newest_eps = eps_series[-1][1]
    oldest_eps = eps_series[-(lookback + 1)][1]
    years = lookback

    # Both must be positive
    if oldest_eps <= 0 or newest_eps <= 0 or years <= 0:
        return None, 0

    cagr = (newest_eps / oldest_eps) ** (1.0 / years) - 1.0

    if cagr <= 0:
        return None, 0

    return round(cagr, 4), years


# ══════════════════════════════════════════════════════════════
# PHASE 1 — parallel, one ticker per thread
# ══════════════════════════════════════════════════════════════

def _phase1_ticker(ticker: str, filters: dict, min_mcap: float, cache: dict):
    """
    Quality gate + self-computed EPS.
    Returns (metrics_dict, None) on pass, (None, reason_str) on fail.
    """
    cached = _cache_fresh(cache, ticker)
    if cached:
        if cached["result"] == "fail":
            return None, f"[cached] {cached['reason']}"

    t_obj, err = _get_info(ticker)
    if t_obj is None:
        return None, f"fetch error: {err}"

    info = t_obj.info

    if not info.get("shortName"):
        return None, "no shortName"

    # Market cap pre-filter
    mcap = info.get("marketCap")
    if not mcap or mcap < min_mcap:
        return None, f"mcap {mcap}"

    # ── Quality filters ───────────────────────────────────────
    roe = info.get("returnOnEquity")
    if roe is None:
        roe = _roe_from_statements(t_obj)
    if roe is None or roe < filters["min_roe"]:
        return None, f"ROE {roe}"

    de = _de_from_info(info.get("debtToEquity"))
    if de is None:
        de = _de_from_statements(t_obj)
    if de is None or de > filters["max_debt_equity"]:
        return None, f"D/E {de}"

    fcf = info.get("freeCashflow")
    if fcf is None or fcf <= filters["min_fcf"]:
        return None, f"FCF {fcf}"

    fcf_yield = round(fcf / mcap, 4) if mcap and mcap > 0 else None

    # ── Self-computed EPS ─────────────────────────────────────
    eps_series = _get_eps_series(t_obj)
    trailing_eps = _trailing_eps_from_series(eps_series)

    if trailing_eps is None or trailing_eps <= 0:
        return None, "EPS not computable from statements"

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price or price <= 0:
        return None, f"no price"

    trailing_pe = round(price / trailing_eps, 2)

    # PE sanity: too high = not a screener candidate
    if trailing_pe > SCREENER_PE_CEILING:
        return None, f"PE {trailing_pe:.0f} > {SCREENER_PE_CEILING:.0f}"
    if trailing_pe <= 0:
        return None, f"PE {trailing_pe:.1f} non-positive"

    # ── Cross-validation logging ──────────────────────────────
    api_trailing_eps = info.get("trailingEps")
    if api_trailing_eps:
        try:
            div = abs(float(api_trailing_eps) - trailing_eps) / abs(trailing_eps)
            if div > 0.30:
                print(f"  EPS DIVERGENCE [{ticker}]: "
                      f"API={float(api_trailing_eps):.2f} vs "
                      f"stmt={trailing_eps:.2f} ({div:.0%} gap)")
        except Exception:
            pass

    return {
        "ticker":              ticker,
        "name":                info.get("shortName", ticker),
        "sector":              info.get("sector", ""),
        "price":               price,
        "market_cap":          mcap,
        "trailing_eps":        trailing_eps,
        "trailing_pe":         trailing_pe,
        "eps_series":          eps_series,
        "api_earnings_growth": info.get("earningsGrowth"),
        "roe":                 roe,
        "debt_equity":         de,
        "fcf":                 fcf,
        "fcf_yield":           fcf_yield,
        "_t_obj":              t_obj,
    }, None


# ══════════════════════════════════════════════════════════════
# PHASE 2 — CAGR + PEG (sequential)
# ══════════════════════════════════════════════════════════════

def _compute_screener_peg(m: dict) -> tuple:
    """
    PEG from self-computed EPS only. No API dependency.

    PE  = price / statement Diluted EPS  (computed in phase 1)
    G   = 2-year EPS CAGR from statements, capped at 20%

    Returns (peg, source_str, conflict_str_or_None)
    """
    ticker = m.get("ticker", "?")
    pe = m.get("trailing_pe")

    if not pe or pe <= 0:
        return None, "no_pe", None

    eps_series = m.get("eps_series", [])
    cagr, years = _eps_cagr_from_series(eps_series, SCREENER_CAGR_LOOKBACK)

    if cagr is None or cagr <= 0:
        return None, "no_positive_2yr_cagr", None

    growth_pct = cagr * 100.0
    source = f"stmt_eps_cagr_{years}yr"
    conflict = None

    # Cap growth for PEG
    if growth_pct > SCREENER_GROWTH_CAP:
        print(f"    PEG [{ticker}]: {years}yr CAGR={growth_pct:.1f}% "
              f"capped to {SCREENER_GROWTH_CAP:.0f}%")
        growth_pct = SCREENER_GROWTH_CAP
        source += "_capped"

    # ── Cross-validate against analyst consensus ──────────────
    # If analysts see NEGATIVE growth but our CAGR is positive,
    # the historical number is almost certainly trough-inflated.
    api_eg = m.get("api_earnings_growth")
    if api_eg is not None:
        try:
            api_g = float(api_eg)
            api_g_pct = api_g * 100 if abs(api_g) < 1 else api_g
            if api_g_pct < -5.0 and growth_pct > 10.0:
                conflict = (
                    f"Analyst consensus NEGATIVE ({api_g_pct:.1f}%) but "
                    f"2yr CAGR is {cagr*100:.1f}%. Rejecting — historical "
                    f"is likely trough-inflated."
                )
                print(f"    PEG REJECTED [{ticker}]: {conflict}")
                return None, "forward_negative_conflict", conflict
        except Exception:
            pass

    peg = round(pe / growth_pct, 3)

    # Floor check
    if peg < SCREENER_PEG_FLOOR:
        conflict = f"PEG {peg:.2f} < {SCREENER_PEG_FLOOR} floor — likely data error"
        print(f"    PEG REJECTED [{ticker}]: {conflict}")
        return None, "peg_below_floor", conflict

    print(f"    PEG [{ticker}]: {pe:.1f}x / {growth_pct:.1f}% = {peg:.2f} "
          f"({source})")

    return peg, source, conflict


def _phase2_ticker(m: dict, filters: dict, cache: dict):
    """
    CAGR filter + PEG computation + QGLP score.
    Mutates m in place. Returns True on pass, False on fail.
    """
    ticker = m["ticker"]
    _ = m.pop("_t_obj", None)   # release the Ticker object

    eps_series = m.get("eps_series", [])
    cagr, cagr_years = _eps_cagr_from_series(eps_series, SCREENER_CAGR_LOOKBACK)

    if cagr is None or cagr < filters["min_earnings_cagr"]:
        _cache_write(cache, ticker, "fail", f"2yr_CAGR {cagr}")
        return False

    m["earnings_cagr"]       = min(cagr, 0.40)
    m["earnings_cagr_raw"]   = cagr
    m["earnings_cagr_years"] = cagr_years

    if cagr > 0.40:
        print(f"  CAGR [{ticker}]: raw={cagr:.1%} capped display to 40%")

    # PEG
    peg, peg_source, peg_conflict = _compute_screener_peg(m)
    m["peg_ratio"]    = peg
    m["peg_source"]   = peg_source
    m["peg_conflict"] = peg_conflict

    if peg is None or peg > filters["max_peg"]:
        reason = f"PEG {peg} ({peg_source})"
        if peg_conflict:
            reason += f" | {peg_conflict[:80]}"
        _cache_write(cache, ticker, "fail", reason)
        return False

    m["qglp_score"] = compute_qglp_score(m)
    _cache_write(cache, ticker, "pass", score=m["qglp_score"])
    return True


# ══════════════════════════════════════════════════════════════
# SCREENING PIPELINE (structure unchanged from v2)
# ══════════════════════════════════════════════════════════════

def screen_universe(tickers: list, market_label: str,
                    filters: dict = None, min_mcap: float = 2e9) -> list:
    if filters is None:
        filters = FILTERS

    print(f"\n{'='*60}")
    print(f"Screening {market_label}: {len(tickers)} tickers | "
          f"workers={PHASE1_WORKERS} | cache_ttl={CACHE_TTL_DAYS}d | "
          f"cagr_lookback={SCREENER_CAGR_LOOKBACK}yr | "
          f"growth_cap={SCREENER_GROWTH_CAP}%")
    print(f"{'='*60}")

    cache = _load_cache()
    phase1_pass  = []
    phase1_stats = {"pass": 0, "fail": 0, "cached_fail": 0}

    # ── Phase 1: parallel info fetch + quality filters ────────
    print(f"\nPhase 1: quality + self-computed EPS (parallel)...")
    with ThreadPoolExecutor(max_workers=PHASE1_WORKERS) as pool:
        futures = {
            pool.submit(_phase1_ticker, t, filters, min_mcap, cache): t
            for t in tickers
        }
        for i, future in enumerate(as_completed(futures), 1):
            ticker = futures[future]
            try:
                m, reason = future.result()
            except Exception as exc:
                m, reason = None, str(exc)

            if m is not None:
                phase1_pass.append(m)
                phase1_stats["pass"] += 1
                print(f"  [{i:>3}/{len(tickers)}] {ticker:20s} PASS  "
                      f"ROE={m['roe']:.1%}  D/E={m['debt_equity']:.2f}  "
                      f"EPS={m['trailing_eps']:.2f}  "
                      f"PE={m['trailing_pe']:.1f}")
            else:
                if reason and reason.startswith("[cached]"):
                    phase1_stats["cached_fail"] += 1
                else:
                    _cache_write(cache, ticker, "fail", reason or "unknown")
                    phase1_stats["fail"] += 1
                    print(f"  [{i:>3}/{len(tickers)}] {ticker:20s} FAIL  {reason}")

            _jitter(0.2)

    _save_cache(cache)
    print(f"\nPhase 1: {phase1_stats['pass']} pass / "
          f"{phase1_stats['fail']} fail / "
          f"{phase1_stats['cached_fail']} skipped (cached)")

    if not phase1_pass:
        print("No phase-1 survivors; aborting.")
        return []

    # ── Phase 2: 2yr CAGR + PEG (sequential) ─────────────────
    print(f"\nPhase 2: 2yr CAGR + self-computed PEG...")
    phase2_pass = []
    for m in phase1_pass:
        ticker = m["ticker"]
        passed = _phase2_ticker(m, filters, cache)
        if passed:
            print(f"  {ticker:20s} PASS  "
                  f"CAGR={m['earnings_cagr']:.1%}  "
                  f"PEG={m['peg_ratio']:.2f}  "
                  f"Score={m['qglp_score']}")
            phase2_pass.append(m)
        else:
            print(f"  {ticker:20s} FAIL  "
                  f"CAGR={m.get('earnings_cagr')}  "
                  f"PEG={m.get('peg_ratio')}")
        _jitter(0.3)

    _save_cache(cache)
    print(f"\nPhase 2: {len(phase2_pass)} survivors")

    # ── Sort + top N ──────────────────────────────────────────
    phase2_pass.sort(key=lambda x: x.get("qglp_score", 0), reverse=True)
    top = phase2_pass[:MAX_PICKS]

    print(f"\nTop {len(top)} {market_label} picks:")
    for i, m in enumerate(top, 1):
        print(f"  {i:2}. {m['ticker']:20s}  "
              f"Score={m['qglp_score']:>3}  "
              f"PEG={m['peg_ratio']:.2f}  "
              f"ROE={m['roe']:.1%}  "
              f"CAGR={m['earnings_cagr']:.1%}  "
              f"PE={m['trailing_pe']:.1f}")

    return top


# ══════════════════════════════════════════════════════════════
# OUTPUT (unchanged from v2)
# ══════════════════════════════════════════════════════════════

def _clean(m: dict) -> dict:
    return {
        "ticker":              m["ticker"],
        "name":                m["name"],
        "sector":              m.get("sector", ""),
        "price":               m.get("price"),
        "market_cap":          m.get("market_cap"),
        "trailing_pe":         m.get("trailing_pe"),
        "peg_ratio":           m.get("peg_ratio"),
        "peg_source":          m.get("peg_source", ""),
        "roe":                 round(m.get("roe", 0), 4),
        "earnings_cagr":       round(m.get("earnings_cagr", 0), 4),
        "earnings_cagr_years": m.get("earnings_cagr_years", 0),
        "fcf_yield":           (round(m["fcf_yield"], 4)
                                if m.get("fcf_yield") else None),
        "debt_equity":         round(m.get("debt_equity", 0), 4),
        "qglp_score":          m.get("qglp_score"),
    }


def save_results(us_picks: list, india_picks: list):
    results = {
        "last_updated":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "filters_us":    FILTERS,
        "filters_india": FILTERS_INDIA,
        "us_picks":      [_clean(m) for m in us_picks],
        "india_picks":   [_clean(m) for m in india_picks],
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved to {OUTPUT_FILE}")

    ok, err = push_screener_results(results)
    if ok:
        print("Pushed to GitHub.")
    else:
        print(f"GitHub push failed: {err}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print(f"PickR QGLP Screener v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"US universe : {len(US_UNIVERSE)} tickers")
    print(f"India universe: {len(INDIA_UNIVERSE)} tickers")
    print(f"EPS source: income_stmt (self-computed)")
    print(f"CAGR lookback: {SCREENER_CAGR_LOOKBACK}yr | "
          f"Growth cap: {SCREENER_GROWTH_CAP}% | "
          f"PEG floor: {SCREENER_PEG_FLOOR}")

    us_picks    = screen_universe(US_UNIVERSE,    "US",    FILTERS,       MIN_MCAP_US)
    india_picks = screen_universe(INDIA_UNIVERSE, "India", FILTERS_INDIA, MIN_MCAP_IN)

    save_results(us_picks, india_picks)
    print(f"\nDone. US: {len(us_picks)} picks | India: {len(india_picks)} picks.")


if __name__ == "__main__":
    main()
