"""
screener.py — QGLP hard filter screener.
Runs daily via GitHub Actions. Screens S&P 100 + Nifty 50,
applies QGLP hard filters, scores survivors, saves top 10
from each market.
"""

import json
import time
import base64
import os
import urllib.request
import urllib.error
from datetime import datetime

import yfinance as yf

from universe import SP500_TOP_100, NIFTY_50

# ── Config ──
GITHUB_TOKEN = os.environ.get("GH_PAT", os.environ.get("GITHUB_TOKEN", ""))
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
OUTPUT_FILE  = "screener_results.json"

# ══════════════════════════════════════════════════════════════
# QGLP HARD FILTERS
# ══════════════════════════════════════════════════════════════

FILTERS = {
    "min_roe":           0.15,
    "max_debt_equity":   1.0,
    "min_fcf":           0,
    "max_peg":           1.4,
    "min_earnings_cagr": 0.12,
}

FILTERS_INDIA = {
    "min_roe":           0.12,
    "max_debt_equity":   1.5,
    "min_fcf":           0,
    "max_peg":           1.4,
    "min_earnings_cagr": 0.10,
}

# ══════════════════════════════════════════════════════════════
# SCORING WEIGHTS (composite score out of 100)
# ══════════════════════════════════════════════════════════════

# Lower PEG = better, Higher ROE = better, Higher growth = better,
# Higher FCF yield = better, Lower D/E = better

def compute_score(metrics):
    """
    Composite QGLP score from 0 to 100.
    Weights: PEG (30), ROE (25), Earnings CAGR (25), FCF Yield (10), D/E (10)
    """
    score = 0.0

    # PEG score: 30 points. PEG 0.5 = 30, PEG 1.0 = 20, PEG 1.4 = 10, PEG 2.0 = 0
    peg = metrics.get("peg_ratio", 999)
    if peg > 0:
        peg_score = max(0, min(30, 30 * (1 - (peg - 0.5) / 1.5)))
        score += peg_score

    # ROE score: 25 points. ROE 30% = 25, ROE 15% = 12.5, ROE 50%+ = 25
    roe = metrics.get("roe", 0)
    if roe > 0:
        roe_score = max(0, min(25, 25 * (roe / 0.30)))
        score += roe_score

    # Earnings CAGR score: 25 points. CAGR 25% = 25, CAGR 12% = 12, CAGR 40%+ = 25
    cagr = metrics.get("earnings_cagr", 0)
    if cagr > 0:
        cagr_score = max(0, min(25, 25 * (cagr / 0.25)))
        score += cagr_score

    # FCF Yield score: 10 points. Yield 5% = 10, Yield 2.5% = 5, Yield 0% = 0
    fcf_y = metrics.get("fcf_yield", 0)
    if fcf_y > 0:
        fcf_score = max(0, min(10, 10 * (fcf_y / 0.05)))
        score += fcf_score

    # D/E score: 10 points. D/E 0 = 10, D/E 0.5 = 5, D/E 1.0 = 0
    de = metrics.get("debt_equity", 0)
    if de >= 0:
        de_score = max(0, min(10, 10 * (1 - de)))
        score += de_score

    return round(score, 1)


# ══════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════

def fetch_metrics(ticker):
    """Pull the minimum metrics needed for QGLP screening."""
    try:
        t = yf.Ticker(ticker)
        info = t.info

        if not info or "shortName" not in info:
            return None

        roe = info.get("returnOnEquity")
        fcf = info.get("freeCashflow")
        mcap = info.get("marketCap")
        forward_pe = info.get("forwardPE")
        trailing_pe = info.get("trailingPE")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        forward_eps = info.get("forwardEps")

        # D/E from API
        de = None
        de_api = info.get("debtToEquity")
        if de_api is not None:
            de = de_api / 100 if de_api > 5 else de_api

        # ROE fallback: compute from statements
        if roe is None:
            try:
                inc = t.income_stmt
                bs = t.balance_sheet
                if inc is not None and bs is not None:
                    ni = None
                    for label in ["Net Income", "Net Income Common Stockholders"]:
                        if label in inc.index:
                            row = inc.loc[label].dropna()
                            if not row.empty:
                                ni = float(row.iloc[0])
                                break
                    eq = None
                    for label in ["Stockholders Equity", "Total Stockholder Equity",
                                  "Common Stock Equity", "Stockholders' Equity"]:
                        if label in bs.index:
                            row = bs.loc[label].dropna()
                            if not row.empty:
                                eq = float(row.iloc[0])
                                break
                    if ni and eq and eq > 0:
                        roe = round(ni / eq, 4)
            except Exception:
                pass

        # D/E fallback: compute from statements
        if de is None:
            try:
                bs = t.balance_sheet
                if bs is not None:
                    debt = None
                    for label in ["Total Debt", "Long Term Debt"]:
                        if label in bs.index:
                            row = bs.loc[label].dropna()
                            if not row.empty:
                                debt = float(row.iloc[0])
                                break
                    eq = None
                    for label in ["Stockholders Equity", "Total Stockholder Equity",
                                  "Common Stock Equity", "Stockholders' Equity"]:
                        if label in bs.index:
                            row = bs.loc[label].dropna()
                            if not row.empty:
                                eq = float(row.iloc[0])
                                break
                    if debt is not None and eq and eq > 0:
                        de = round(debt / eq, 3)
            except Exception:
                pass

        # FCF yield
        fcf_yield = None
        if fcf and mcap and mcap > 0:
            fcf_yield = fcf / mcap

        return {
            "ticker":      ticker,
            "name":        info.get("shortName", ticker),
            "sector":      info.get("sector", ""),
            "price":       price,
            "market_cap":  mcap,
            "trailing_pe": trailing_pe,
            "forward_pe":  forward_pe,
            "forward_eps": forward_eps,
            "roe":         roe,
            "debt_equity": de,
            "fcf":         fcf,
            "fcf_yield":   fcf_yield,
        }
    except Exception as e:
        print(f"  {ticker}: fetch error - {str(e)[:80]}")
        return None

def fetch_earnings_cagr(ticker):
    """
    Compute earnings CAGR from income statement.
    Only called for stocks that pass the cheap filters.
    """
    try:
        t = yf.Ticker(ticker)
        inc = t.income_stmt

        if inc is None or inc.empty:
            return None, 0

        # Look for EPS or Net Income
        for label in ["Diluted EPS", "Basic EPS"]:
            if label in inc.index:
                row = inc.loc[label].dropna().sort_index()
                if len(row) >= 2:
                    # Use exactly 5-year window if available
                    if len(row) >= 5:
                        oldest = float(row.iloc[-5])
                        newest = float(row.iloc[-1])
                        years = 4
                    else:
                        oldest = float(row.iloc[0])
                        newest = float(row.iloc[-1])
                        years = len(row) - 1
                        cagr = (newest / oldest) ** (1 / years) - 1
                        return round(cagr, 4), years

        # Fallback to net income
        for label in ["Net Income", "Net Income Common Stockholders"]:
            if label in inc.index:
                row = inc.loc[label].dropna().sort_index()
                if len(row) >= 2:
                    oldest = float(row.iloc[0])
                    newest = float(row.iloc[-1])
                    years = len(row) - 1
                    cagr = (newest / oldest) ** (1 / years) - 1
                    return round(cagr, 4), years

        return None, 0
    except Exception as e:
        print(f"  {ticker}: earnings CAGR error - {str(e)[:80]}")
        return None, 0

# ══════════════════════════════════════════════════════════════
# SCREENING PIPELINE
# ══════════════════════════════════════════════════════════════

def screen_universe(tickers, market_label, filters=None):
    if filters is None:
        filters = FILTERS
    """Screen a list of tickers through QGLP hard filters."""
    print(f"\n{'='*60}")
    print(f"Screening {market_label}: {len(tickers)} tickers")
    print(f"{'='*60}")

    # Phase 1: Cheap filters (info only, no statements)
    phase1_pass = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {ticker}...", end=" ")
        m = fetch_metrics(ticker)

        if m is None:
            print("SKIP (no data)")
            time.sleep(0.3)
            continue

        # Hard filter: ROE
        if m.get("roe") is None or m["roe"] < filters["min_roe"]:
            print(f"FAIL ROE ({m.get('roe')})")
            time.sleep(0.3)
            continue

        # Hard filter: Debt/Equity
        if m.get("debt_equity") is None or m["debt_equity"] > filters["max_debt_equity"]:
            print(f"FAIL D/E ({m.get('debt_equity')})")
            time.sleep(0.3)
            continue

        # Hard filter: Positive FCF
        if m.get("fcf") is None or m["fcf"] <= filters["min_fcf"]:
            print(f"FAIL FCF ({m.get('fcf')})")
            time.sleep(0.3)
            continue

        print(f"PASS phase 1 (ROE={m['roe']:.1%}, D/E={m['debt_equity']:.2f})")
        phase1_pass.append(m)
        time.sleep(0.3)

    print(f"\nPhase 1 survivors: {len(phase1_pass)} / {len(tickers)}")

    # Phase 2: Compute earnings CAGR and PEG for survivors
    phase2_pass = []
    for m in phase1_pass:
        ticker = m["ticker"]
        print(f"  {ticker}: computing earnings CAGR...", end=" ")

        cagr, cagr_years = fetch_earnings_cagr(ticker)
        if cagr is None or cagr < filters["min_earnings_cagr"]:
            print(f"FAIL CAGR ({cagr})")
            time.sleep(0.5)
            continue

        m["earnings_cagr"] = cagr
        m["earnings_cagr_years"] = cagr_years


        # Compute PEG
        pe = m.get("forward_pe") or m.get("trailing_pe")
        if pe and pe > 0 and cagr > 0:
            # Cap CAGR at 50% for PEG computation to avoid
            # backward-looking supercycles distorting the ratio
            cagr_for_peg = cagr
            peg = pe / (cagr_for_peg * 100)
            m["peg_ratio"] = round(peg, 2)
        else:
            m["peg_ratio"] = None

        # Hard filter: PEG
        if m["peg_ratio"] is None or m["peg_ratio"] > filters["max_peg"]:
            print(f"FAIL PEG ({m.get('peg_ratio')})")
            time.sleep(0.5)
            continue

        # Compute composite score
        m["qglp_score"] = compute_score(m)
        print(f"PASS (CAGR={cagr:.1%}, PEG={m['peg_ratio']:.2f}, Score={m['qglp_score']})")
        phase2_pass.append(m)
        time.sleep(0.5)

    print(f"\nPhase 2 survivors: {len(phase2_pass)} / {len(phase1_pass)}")

    # Sort by composite score, take top 10
    phase2_pass.sort(key=lambda x: x["qglp_score"], reverse=True)
    top = phase2_pass[:10]

    print(f"\nTop {len(top)} {market_label} picks:")
    for i, m in enumerate(top):
        print(f"  {i+1}. {m['ticker']} ({m['name']}) - "
              f"Score: {m['qglp_score']} | PEG: {m['peg_ratio']} | "
              f"ROE: {m['roe']:.1%} | CAGR: {m['earnings_cagr']:.1%}")

    return top

# ══════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════

def save_results(us_picks, india_picks):
    """Save results to JSON, push to GitHub if configured."""
    results = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "filters": FILTERS,
        "us_picks": [
            {
                "ticker":        m["ticker"],
                "name":          m["name"],
                "sector":        m["sector"],
                "price":         m.get("price"),
                "market_cap":    m.get("market_cap"),
                "peg_ratio":     m.get("peg_ratio"),
                "roe":           round(m.get("roe", 0), 4),
                "earnings_cagr": round(m.get("earnings_cagr", 0), 4),
                "earnings_cagr_years": m.get("earnings_cagr_years", 0),
                "fcf_yield":     round(m.get("fcf_yield", 0), 4) if m.get("fcf_yield") else None,
                "debt_equity":   round(m.get("debt_equity", 0), 3),
                "qglp_score":    m.get("qglp_score"),
            }
            for m in us_picks
        ],
        "india_picks": [
            {
                "ticker":        m["ticker"],
                "name":          m["name"],
                "sector":        m["sector"],
                "price":         m.get("price"),
                "market_cap":    m.get("market_cap"),
                "peg_ratio":     m.get("peg_ratio"),
                "roe":           round(m.get("roe", 0), 4),
                "earnings_cagr": round(m.get("earnings_cagr", 0), 4),
                "earnings_cagr_years": m.get("earnings_cagr_years", 0),
                "fcf_yield":     round(m.get("fcf_yield", 0), 4) if m.get("fcf_yield") else None,
                "debt_equity":   round(m.get("debt_equity", 0), 3),
                "qglp_score":    m.get("qglp_score"),
            }
            for m in india_picks
        ],
    }

    # Save locally
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved to {OUTPUT_FILE}")

    # Push to GitHub
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{OUTPUT_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }

            # Get current SHA if file exists
            sha = None
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    sha = json.loads(resp.read().decode()).get("sha")
            except urllib.error.HTTPError:
                pass

            payload = {
                "message": f"screener: update {datetime.now().strftime('%Y-%m-%d')}",
                "content": base64.b64encode(
                    json.dumps(results, indent=2, default=str).encode()
                ).decode(),
            }
            if sha:
                payload["sha"] = sha

            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
            with urllib.request.urlopen(req, timeout=10):
                pass
            print("Pushed to GitHub successfully.")
        except Exception as e:
            print(f"GitHub push failed: {e}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print(f"PickR QGLP Screener — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Filters: {FILTERS}")

    us_picks    = screen_universe(SP500_TOP_100, "US (S&P 100)", FILTERS)
    india_picks = screen_universe(NIFTY_50, "India (Nifty 50)", FILTERS_INDIA)

    save_results(us_picks, india_picks)

    print(f"\nDone. US: {len(us_picks)} picks, India: {len(india_picks)} picks.")


if __name__ == "__main__":
    main()
