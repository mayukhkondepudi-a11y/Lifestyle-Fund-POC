"""
screener.py — QGLP hard-filter screener.

Runs daily via GitHub Actions.

Key improvements over v1:
  • Parallel phase-1 (ThreadPoolExecutor) — 5-10× faster
  • Skip cache — tickers that failed recently are skipped for CACHE_TTL_DAYS
  • Phase-1 stores raw yf.Ticker objects so phase-2 reuses them (no re-fetch)
  • Exponential back-off on rate errors instead of fixed sleep
  • Min market-cap pre-filter before any API call
  • Configurable via env vars: PHASE1_WORKERS, MAX_PICKS, CACHE_TTL_DAYS

PEG computation (v2):
  Mirrors the exact same 4-priority chain used in compute._compute_peg so
  screener and report PEG values are always consistent:
    1. earningsGrowth from yfinance (analyst forward consensus)
    2. Derived from forward_eps vs trailing_eps
    3. Historical EPS CAGR from statements — capped at 25%
    4. Historical NI CAGR from statements  — capped at 25%
  Raw historical CAGR without a cap is NEVER used directly for PEG to
  prevent cyclicals / insurers with lumpy earnings from getting false
  low-PEG scores (e.g. TRV showing <1 PEG when forward PEG is 7+).
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
PHASE1_WORKERS = int(os.getenv("PHASE1_WORKERS",  "6"))   # keep ≤8 for yfinance
MIN_MCAP_US    = float(os.getenv("MIN_MCAP_US",   "2e9")) # $2 B
MIN_MCAP_IN    = float(os.getenv("MIN_MCAP_IN",   "3e10"))# ₹30 B


# ══════════════════════════════════════════════════════════════
# SKIP CACHE
# {ticker: {result:"pass"|"fail", reason:str, ts:iso, score:int|null}}
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
    """Return entry if still within TTL, else None."""
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
# FETCH HELPERS
# ══════════════════════════════════════════════════════════════

def _jitter(base: float = 0.5):
    """Sleep base ± 40% to avoid coordinated rate-limit bursts."""
    time.sleep(base * (0.6 + 0.8 * random.random()))


def _retry(fn, retries: int = 3, base_sleep: float = 2.0):
    """
    Call fn() up to `retries` times with exponential back-off.
    Returns (result, error_str).
    """
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
    """Fetch yf info with retry. Returns (ticker_obj, error_str)."""
    def _fetch():
        t    = yf.Ticker(ticker)
        info = t.info
        if not info or len(info) < 5:
            raise ValueError("Empty info")
        return t          # return the full Ticker object — phase 2 can reuse
    return _retry(_fetch, retries=3)


def _de_from_info(de_api):
    """Normalise the debtToEquity field from yfinance (sometimes ×100)."""
    if de_api is None:
        return None
    try:
        v = float(de_api)
        # yfinance sometimes returns value in % form (e.g. 120 means 1.20×)
        return round(v / 100, 4) if v > 10 else round(v, 4)
    except Exception:
        return None


def _roe_from_statements(t):
    """Compute ROE from income + balance sheet when API field is missing."""
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
    """Compute D/E from balance sheet when API field is missing."""
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
# PHASE 1 — one ticker, runs in thread pool
# ══════════════════════════════════════════════════════════════

def _phase1_ticker(ticker: str, filters: dict, min_mcap: float, cache: dict):
    """
    Returns (metrics_dict, None) on pass,
            (None, reason_str) on fail.
    """
    # Check skip cache first
    cached = _cache_fresh(cache, ticker)
    if cached:
        if cached["result"] == "fail":
            return None, f"[cached] {cached['reason']}"

    t_obj, err = _get_info(ticker)
    if t_obj is None:
        return None, f"fetch error: {err}"

    info = t_obj.info

    # Must have a name
    if not info.get("shortName"):
        return None, "no shortName"

    # Market cap pre-filter (cheapest filter, no extra calls)
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

    return {
        "ticker":        ticker,
        "name":          info.get("shortName", ticker),
        "sector":        info.get("sector", ""),
        "price":         info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap":    mcap,
        "trailing_pe":   info.get("trailingPE"),
        "forward_pe":    info.get("forwardPE"),
        "trailing_eps":  info.get("trailingEps"),
        "forward_eps":   info.get("forwardEps"),
        "earnings_growth": info.get("earningsGrowth"),  # analyst forward consensus
        "roe":           roe,
        "debt_equity":   de,
        "fcf":           fcf,
        "fcf_yield":     fcf_yield,
        "_t_obj":        t_obj,   # carry the Ticker object into phase 2
    }, None


# ══════════════════════════════════════════════════════════════
# PHASE 2 — earnings CAGR + PEG (sequential, reuses t_obj)
# ══════════════════════════════════════════════════════════════

def _fetch_earnings_cagr(t_obj):
    """
    Compute historical earnings CAGR from cached Ticker object.
    No new network call — reuses the income_stmt already loaded.
    Returns (cagr_float, years_int).
    """
    try:
        inc = t_obj.income_stmt
        if inc is None or inc.empty:
            return None, 0

        # Try EPS rows first (more accurate than net income)
        for lbl in ["Diluted EPS", "Basic EPS"]:
            if lbl in inc.index:
                row = inc.loc[lbl].dropna().sort_index()
                if len(row) >= 2:
                    if len(row) >= 5:
                        oldest, newest, years = (float(row.iloc[-5]),
                                                  float(row.iloc[-1]), 4)
                    else:
                        oldest, newest, years = (float(row.iloc[0]),
                                                  float(row.iloc[-1]),
                                                  len(row) - 1)
                    if oldest > 0 and years > 0:
                        return round((newest / oldest) ** (1 / years) - 1, 4), years

        # Fall back to net income
        for lbl in ["Net Income", "Net Income Common Stockholders"]:
            if lbl in inc.index:
                row = inc.loc[lbl].dropna().sort_index()
                if len(row) >= 2:
                    oldest = float(row.iloc[0])
                    newest = float(row.iloc[-1])
                    years  = len(row) - 1
                    if oldest > 0 and years > 0:
                        return round((newest / oldest) ** (1 / years) - 1, 4), years
    except Exception:
        pass
    return None, 0


def _compute_screener_peg(m: dict, historical_cagr) -> float | None:
    """
    Compute PEG using the same 4-priority chain as compute._compute_peg
    so screener and report values are always consistent.

    Priority
    --------
    1. earningsGrowth  — yfinance analyst forward consensus (direct field)
    2. Derived from forward_eps vs trailing_eps
    3. Historical EPS/NI CAGR from statements — CAPPED at 25%

    The cap on historical CAGR is critical: without it, a stock like TRV
    with a lumpy earnings base year shows a 30%+ CAGR → PEG < 1 when the
    true forward PEG is 7+.  The cap keeps the screener honest.

    Returns peg float, or None if no valid growth rate or PE is available.
    """
    pe = m.get("forward_pe") or m.get("trailing_pe")
    if not pe or pe <= 0:
        return None

    growth = None

    # Priority 1: analyst forward consensus
    eg = m.get("earnings_growth")
    if eg is not None:
        try:
            g_val = float(eg)
            g_pct = g_val * 100 if abs(g_val) < 1 else g_val
            if g_pct > 0:
                growth = g_pct
                print(f"    PEG [{m['ticker']}]: earnings_growth = {growth:.1f}%")
        except Exception:
            pass

    # Priority 2: derived from forward_eps vs trailing_eps
    if growth is None:
        fwd   = m.get("forward_eps")
        trail = m.get("trailing_eps")
        if fwd and trail:
            try:
                fwd, trail = float(fwd), float(trail)
                if fwd > 0 and trail > 0 and trail != fwd:
                    derived = ((fwd - trail) / abs(trail)) * 100
                    if derived > 0:
                        growth = derived
                        print(f"    PEG [{m['ticker']}]: derived fwd/trail EPS "
                              f"= {growth:.1f}%")
            except Exception:
                pass

    # Priority 3: historical CAGR — capped at 25%
    if growth is None and historical_cagr is not None and historical_cagr > 0:
        growth = min(historical_cagr * 100, 25.0)
        print(f"    PEG [{m['ticker']}]: historical CAGR = {growth:.1f}% "
              f"(capped at 25%)")

    if not growth or growth <= 0:
        return None

    return round(pe / growth, 3)


def _phase2_ticker(m: dict, filters: dict, cache: dict):
    """
    Mutates m in place, adding earnings_cagr, peg_ratio, qglp_score.
    Returns True on pass, False on fail.
    """
    ticker = m["ticker"]
    t_obj  = m.pop("_t_obj", None)   # retrieve and remove the carrier

    cagr, cagr_years = _fetch_earnings_cagr(t_obj) if t_obj else (None, 0)

    if cagr is None or cagr < filters["min_earnings_cagr"]:
        _cache_write(cache, ticker, "fail", f"CAGR {cagr}")
        return False

    m["earnings_cagr"]       = cagr
    m["earnings_cagr_years"] = cagr_years

    # Use corrected PEG computation — same logic as compute._compute_peg
    peg = _compute_screener_peg(m, cagr)
    m["peg_ratio"] = peg

    if peg is None or peg > filters["max_peg"]:
        _cache_write(cache, ticker, "fail", f"PEG {peg}")
        return False

    m["qglp_score"] = compute_qglp_score(m)
    _cache_write(cache, ticker, "pass", score=m["qglp_score"])
    return True


# ══════════════════════════════════════════════════════════════
# SCREENING PIPELINE
# ══════════════════════════════════════════════════════════════

def screen_universe(tickers: list, market_label: str,
                    filters: dict = None, min_mcap: float = 2e9) -> list:
    if filters is None:
        filters = FILTERS

    print(f"\n{'='*60}")
    print(f"Screening {market_label}: {len(tickers)} tickers | "
          f"workers={PHASE1_WORKERS} | cache_ttl={CACHE_TTL_DAYS}d")
    print(f"{'='*60}")

    cache = _load_cache()
    phase1_pass  = []
    phase1_stats = {"pass": 0, "fail": 0, "cached_fail": 0}

    # ── Phase 1: parallel info fetch + quality filters ────────
    print(f"\nPhase 1: quality filters (parallel)...")
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
                      f"ROE={m['roe']:.1%}  D/E={m['debt_equity']:.2f}")
            else:
                if reason and reason.startswith("[cached]"):
                    phase1_stats["cached_fail"] += 1
                else:
                    _cache_write(cache, ticker, "fail", reason or "unknown")
                    phase1_stats["fail"] += 1
                    print(f"  [{i:>3}/{len(tickers)}] {ticker:20s} FAIL  {reason}")

            # Light jitter between completions to avoid burst
            _jitter(0.2)

    _save_cache(cache)
    print(f"\nPhase 1: {phase1_stats['pass']} pass / "
          f"{phase1_stats['fail']} fail / "
          f"{phase1_stats['cached_fail']} skipped (cached)")

    if not phase1_pass:
        print("No phase-1 survivors; aborting.")
        return []

    # ── Phase 2: earnings CAGR + PEG (sequential, uses cached t_obj) ─
    print(f"\nPhase 2: earnings CAGR + PEG...")
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

    _save_cache(cache)   # persist updated pass entries
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
              f"CAGR={m['earnings_cagr']:.1%}")

    return top


# ══════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════

def _clean(m: dict) -> dict:
    """Strip internal fields and round floats for JSON output."""
    return {
        "ticker":              m["ticker"],
        "name":                m["name"],
        "sector":              m.get("sector", ""),
        "price":               m.get("price"),
        "market_cap":          m.get("market_cap"),
        "peg_ratio":           m.get("peg_ratio"),
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
    print(f"PickR QGLP Screener — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"US universe : {len(US_UNIVERSE)} tickers")
    print(f"India universe: {len(INDIA_UNIVERSE)} tickers")

    us_picks    = screen_universe(US_UNIVERSE,    "US",    FILTERS,       MIN_MCAP_US)
    india_picks = screen_universe(INDIA_UNIVERSE, "India", FILTERS_INDIA, MIN_MCAP_IN)

    save_results(us_picks, india_picks)
    print(f"\nDone. US: {len(us_picks)} picks | India: {len(india_picks)} picks.")


if __name__ == "__main__":
    main()