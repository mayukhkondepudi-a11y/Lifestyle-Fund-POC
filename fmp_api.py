"""
fmp_api.py — Shared data fetching layer.
yfinance is PRIMARY for all markets. FMP is FALLBACK for US stocks.
"""

import json
import time as _time
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

from config import FMP_API_KEY

BASE_URL = "https://financialmodelingprep.com/stable"


# ══════════════════════════════════════════════════════════════
# FMP API HELPERS
# ══════════════════════════════════════════════════════════════

def _fmp_get(path, params=None):
    if not FMP_API_KEY:
        return None
    if params is None:
        params = {}
    params["apikey"] = FMP_API_KEY
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PickR/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, dict) and "Error Message" in data:
                print(f"FMP error on {path}: {data['Error Message']}")
                return None
            if isinstance(data, list) and len(data) == 0:
                return None
            return data
    except urllib.error.HTTPError as e:
        print(f"FMP HTTP {e.code} on {path}: {e.reason}")
        return None
    except Exception as e:
        print(f"FMP request failed on {path}: {str(e)[:120]}")
        return None


def _safe_div(a, b):
    try:
        if a is not None and b is not None and b != 0:
            return round(a / b, 4)
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════

def search_ticker(query):
    """Search by company name. yfinance primary, FMP fallback."""
    # ── yfinance (primary) ──
    if HAS_YF:
        try:
            url = (f"https://query2.finance.yahoo.com/v1/finance/search?"
                   f"q={urllib.parse.quote(query)}&quotesCount=6&newsCount=0")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                ydata = json.loads(resp.read().decode())
                results = [
                    {"symbol": q["symbol"],
                     "name": q.get("shortname", q["symbol"]),
                     "exchange": q.get("exchange", "")}
                    for q in ydata.get("quotes", [])
                    if q.get("quoteType") in ("EQUITY", "ETF")
                ]
                if results:
                    print(f"  Search: yfinance found {len(results)} results for '{query}'")
                    return results
        except Exception as e:
            print(f"  yfinance search failed for '{query}': {str(e)[:60]}")

    # ── FMP (fallback) ──
    data = _fmp_get("/search", {"query": query, "limit": 6})
    if data:
        return [
            {"symbol": item.get("symbol", ""),
             "name": item.get("name", item.get("symbol", "")),
             "exchange": item.get("stockExchange",
                                  item.get("exchangeShortName", ""))}
            for item in data if item.get("symbol")
        ]
    return []


# ══════════════════════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════════════════════

def get_profile(ticker):
    """Get company profile. yfinance primary, FMP fallback."""
    # ── yfinance (primary) ──
    if HAS_YF:
        try:
            info = yf.Ticker(ticker).info
            if info and (info.get("shortName") or info.get("longName")):
                info["_source"] = "yfinance"
                print(f"  Profile: yfinance OK for {ticker}")
                return info
            elif info and info.get("quoteType") == "NONE_TYPE":
                print(f"  Profile: yfinance says {ticker} not found")
            else:
                print(f"  Profile: yfinance returned empty for {ticker}")
        except Exception as e:
            print(f"  Profile: yfinance failed for {ticker}: {str(e)[:80]}")

    # ── FMP (fallback) ──
    profile = _fmp_get("/profile", {"symbol": ticker})
    quote   = _fmp_get("/quote", {"symbol": ticker})

    if profile and isinstance(profile, list):
        profile = profile[0]
    if quote and isinstance(quote, list):
        quote = quote[0]

    if profile and quote:
        merged = _merge_profile_quote(profile, quote)
        print(f"  Profile: FMP fallback OK for {ticker}")
        return merged

    print(f"  Profile: all sources failed for {ticker}")
    return None


def _merge_profile_quote(profile, quote):
    p = profile
    q = quote
    return {
        "_source":              "fmp",
        "shortName":            p.get("companyName", ""),
        "longName":             p.get("companyName", ""),
        "symbol":               p.get("symbol", ""),
        "sector":               p.get("sector", ""),
        "industry":             p.get("industry", ""),
        "country":              p.get("country", ""),
        "currency":             p.get("currency", "USD"),
        "longBusinessSummary":  p.get("description", ""),
        "currentPrice":         q.get("price"),
        "regularMarketPrice":   q.get("price"),
        "marketCap":            q.get("marketCap") or p.get("mktCap"),
        "fiftyTwoWeekHigh":     q.get("yearHigh"),
        "fiftyTwoWeekLow":      q.get("yearLow"),
        "volume":               q.get("volume"),
        "avgVolume":            q.get("avgVolume"),
        "trailingPE":           q.get("pe"),
        "forwardPE":            None,
        "priceToBook":          _safe_div(q.get("price"),
                                          p.get("bookValuePerShare")),
        "enterpriseValue":      q.get("marketCap"),
        "trailingEps":          q.get("eps"),
        "forwardEps":           None,
        "dividendYield":        _safe_div(p.get("lastDiv"), q.get("price")),
        "beta":                 p.get("beta"),
        "fiftyDayAverage":      q.get("priceAvg50"),
        "twoHundredDayAverage": q.get("priceAvg200"),
        "sharesOutstanding":    q.get("sharesOutstanding"),
        "heldPercentInsiders":   None,
        "heldPercentInstitutions": None,
        "website":               p.get("website", ""),
    }


# ══════════════════════════════════════════════════════════════
# FMP ENRICHMENT (only used when FMP is data source)
# ══════════════════════════════════════════════════════════════

def get_ratios_ttm(ticker):
    data = _fmp_get("/ratios-ttm", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def get_key_metrics_ttm(ticker):
    data = _fmp_get("/key-metrics-ttm", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def enrich_info_with_ratios(info_dict, ticker, ratios=None, metrics=None):
    """Enrich FMP profile with ratios and metrics. Accepts pre-fetched data."""
    if info_dict.get("_source") != "fmp":
        return info_dict

    if ratios is None:
        ratios = get_ratios_ttm(ticker)
    if metrics is None:
        metrics = get_key_metrics_ttm(ticker)

    if ratios:
        pe_from_ratios = (ratios.get("peRatioTTM")
                          or ratios.get("priceEarningsRatioTTM"))
        if pe_from_ratios:
            info_dict["trailingPE"] = pe_from_ratios

        info_dict["pegRatio"] = (
            ratios.get("pegRatioTTM")
            or ratios.get("priceEarningsToGrowthRatioTTM")
            or ratios.get("pegRatio"))
        info_dict["priceToSalesTrailing12Months"] = (
            ratios.get("priceToSalesRatioTTM")
            or ratios.get("priceSalesRatioTTM"))
        info_dict["returnOnEquity"]   = ratios.get("returnOnEquityTTM")
        info_dict["returnOnAssets"]   = ratios.get("returnOnAssetsTTM")
        info_dict["grossMargins"]     = ratios.get("grossProfitMarginTTM")
        info_dict["operatingMargins"] = ratios.get("operatingProfitMarginTTM")
        info_dict["profitMargins"]    = ratios.get("netProfitMarginTTM")
        info_dict["debtToEquity"]     = ratios.get("debtEquityRatioTTM")
        info_dict["currentRatio"]     = ratios.get("currentRatioTTM")
        info_dict["payoutRatio"]      = ratios.get("payoutRatioTTM")
        info_dict["dividendYield"]    = (ratios.get("dividendYieldTTM")
                                         or info_dict.get("dividendYield"))

    if metrics:
        info_dict["enterpriseValue"] = (metrics.get("enterpriseValueTTM")
                                        or info_dict.get("enterpriseValue"))
        info_dict["enterpriseToEbitda"] = metrics.get(
            "enterpriseValueOverEBITDATTM")
        info_dict["earningsGrowth"] = metrics.get("earningsYieldTTM")
        info_dict["revenueGrowth"]  = None

        forward_pe = metrics.get("peRatioTTM")
        if not forward_pe:
            earnings_yield = metrics.get("earningsYieldTTM")
            if earnings_yield and float(earnings_yield) > 0:
                try:
                    forward_pe = round(1.0 / float(earnings_yield), 2)
                except Exception:
                    forward_pe = None
        info_dict["forwardPE"] = forward_pe

        shares = info_dict.get("sharesOutstanding")
        fcf_ps = metrics.get("freeCashFlowPerShareTTM")
        if shares and fcf_ps:
            try:
                info_dict["freeCashflow"] = float(fcf_ps) * float(shares)
            except Exception:
                info_dict["freeCashflow"] = None
        else:
            info_dict["freeCashflow"] = None

        info_dict.setdefault("operatingCashflow", None)
        info_dict.setdefault("totalCash", None)
        info_dict.setdefault("totalDebt", None)
        info_dict.setdefault("totalRevenue", None)

    return info_dict


# ══════════════════════════════════════════════════════════════
# FMP STATEMENTS
# ══════════════════════════════════════════════════════════════

def get_income_statement(ticker, period="annual", limit=5):
    data = _fmp_get("/income-statement",
                    {"symbol": ticker, "period": period, "limit": limit})
    return data if data else []


def get_balance_sheet(ticker, period="annual", limit=5):
    data = _fmp_get("/balance-sheet-statement",
                    {"symbol": ticker, "period": period, "limit": limit})
    return data if data else []


def get_cashflow(ticker, period="annual", limit=5):
    data = _fmp_get("/cash-flow-statement",
                    {"symbol": ticker, "period": period, "limit": limit})
    return data if data else []


def statements_to_dataframe(statements, key_mapping=None):
    import pandas as pd
    if not statements:
        return None
    statements = list(reversed(statements))
    dates = []
    for s in statements:
        d = s.get("date", s.get("calendarYear", ""))
        try:
            dates.append(pd.Timestamp(d))
        except Exception:
            dates.append(d)
    skip_keys = {"date", "symbol", "reportedCurrency", "cik", "fillingDate",
                 "acceptedDate", "calendarYear", "period", "link", "finalLink"}
    row_keys = [k for k in statements[0].keys() if k not in skip_keys]
    data = {}
    for key in row_keys:
        label = key_mapping.get(key, key) if key_mapping else key
        values = [s.get(key) for s in statements]
        data[label] = values
    df = pd.DataFrame(data, index=dates).T
    return df


INCOME_KEY_MAP = {
    "revenue": "Total Revenue", "grossProfit": "Gross Profit",
    "operatingIncome": "Operating Income", "netIncome": "Net Income",
    "eps": "Basic EPS", "epsdiluted": "Diluted EPS",
    "ebitda": "EBITDA", "costOfRevenue": "Cost Of Revenue",
}
BALANCE_KEY_MAP = {
    "totalDebt": "Total Debt",
    "totalStockholdersEquity": "Stockholders Equity",
    "totalCurrentAssets": "Current Assets",
    "totalCurrentLiabilities": "Current Liabilities",
    "longTermDebt": "Long Term Debt", "commonStock": "Common Stock",
    "totalAssets": "Total Assets", "totalLiabilities": "Total Liabilities",
    "cashAndCashEquivalents": "Cash And Cash Equivalents",
}
CASHFLOW_KEY_MAP = {
    "operatingCashFlow": "Operating Cash Flow",
    "capitalExpenditure": "Capital Expenditure",
    "freeCashFlow": "Free Cash Flow", "dividendsPaid": "Dividends Paid",
    "netCashUsedForInvestingActivites": "Investing Cash Flow",
    "netCashUsedProvidedByFinancingActivities": "Financing Cash Flow",
}


# ══════════════════════════════════════════════════════════════
# HISTORICAL PRICES (always yfinance)
# ══════════════════════════════════════════════════════════════

def get_historical_prices(ticker, period="5y"):
    import pandas as pd
    if HAS_YF:
        try:
            h = yf.Ticker(ticker).history(period=period, interval="1wk")
            if h is not None and not h.empty:
                return h
        except Exception as e:
            print(f"yfinance historical fetch failed: {e}")
    return None


# ══════════════════════════════════════════════════════════════
# FULL FETCH — yfinance PRIMARY, FMP FALLBACK
# ══════════════════════════════════════════════════════════════

def fetch_full(ticker):
    """
    Full data fetch for a ticker.
    Priority: yfinance first, FMP fallback for US stocks.
    """
    print(f"  fetch_full({ticker}): starting")

    # ── Try yfinance first (works for all markets) ──
    if HAS_YF:
        result = _yf_full_fetch(ticker)
        if result is not None:
            info = result.get("info", {})
            if isinstance(info, dict) and "error" not in info:
                print(f"  fetch_full({ticker}): yfinance OK")
                return result
            else:
                print(f"  fetch_full({ticker}): yfinance returned error, "
                      f"trying FMP fallback")

    # ── FMP profile+quote fallback for Indian tickers ──
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        print(f"  fetch_full({ticker}): yfinance failed; trying FMP profile/quote only")
        profile = get_profile(ticker)
        if profile and isinstance(profile, dict) and "error" not in profile:
            profile["_source"] = profile.get("_source", "fmp")
            print(f"  fetch_full({ticker}): FMP profile fallback OK "
                  f"(statements unavailable — report will be INCOMPLETE)")
            return {
                "info":  profile,
                "inc":   None, "qinc": None,
                "bs":    None, "cf":   None,
                "hist":  None, "news": [],
            }
        print(f"  fetch_full({ticker}): all sources failed")
        return None

    return _fmp_full_fetch(ticker)


def _yf_full_fetch(ticker, existing_info=None):
    """Full yfinance fetch with parallel statement loading."""
    if not HAS_YF:
        return None

    print(f"  _yf_full_fetch({ticker}): starting")
    s = yf.Ticker(ticker)
    d = {}

    # ── Info ──
    if existing_info and "shortName" in existing_info:
        d["info"] = existing_info
    else:
        for attempt in range(2):
            try:
                info = s.info
                if info and (info.get("shortName") or info.get("longName")):
                    info["_source"] = "yfinance"
                    d["info"] = info
                    break
                elif info and info.get("quoteType") == "NONE_TYPE":
                    d["info"] = {"error": f"Ticker '{ticker}' not found "
                                 f"on Yahoo Finance"}
                    break
                else:
                    d["info"] = {"error": f"Empty response for {ticker}"}
            except Exception as e:
                d["info"] = {"error": f"Yahoo Finance error: {str(e)[:200]}"}
                if attempt == 0:
                    _time.sleep(2)

    if "info" not in d:
        d["info"] = {"error": f"All attempts to fetch {ticker} failed"}

    if isinstance(d["info"], dict) and "error" in d["info"]:
        d.update({"inc": None, "qinc": None, "bs": None,
                  "cf": None, "hist": None, "news": []})
        return d

    # ── Parallel statement + history fetch ──
    def _get_attr(attr_name):
        try:
            df = getattr(s, attr_name)
            return df if df is not None and not df.empty else None
        except Exception:
            return None

    def _get_history():
        try:
            h = s.history(period="5y", interval="1wk")
            return h if h is not None and not h.empty else None
        except Exception:
            return None

    def _get_news():
        try:
            return s.news[:8] if s.news else []
        except Exception:
            return []

    def _get_analyst_consensus():
        """Extract forward analyst consensus from yfinance.
        Returns dict with revenue/EPS estimates and price targets, or None.
        Free data, refreshed within days of earnings beats/raises."""
        out = {}
        try:
            re_df = getattr(s, "revenue_estimate", None)
            if re_df is not None and not re_df.empty and "0y" in re_df.index:
                r = re_df.loc["0y"]
                out["revenue_fy_avg"]        = float(r.get("avg") or 0)
                out["revenue_fy_low"]        = float(r.get("low") or 0)
                out["revenue_fy_high"]       = float(r.get("high") or 0)
                out["revenue_fy_n_analysts"] = int(r.get("numberOfAnalysts") or 0)
        except Exception:
            pass
        try:
            ee_df = getattr(s, "earnings_estimate", None)
            if ee_df is not None and not ee_df.empty and "0y" in ee_df.index:
                e = ee_df.loc["0y"]
                out["eps_fy_avg"]  = float(e.get("avg") or 0)
                out["eps_fy_low"]  = float(e.get("low") or 0)
                out["eps_fy_high"] = float(e.get("high") or 0)
        except Exception:
            pass
        try:
            pt = getattr(s, "analyst_price_targets", None)
            if isinstance(pt, dict):
                out["price_target_mean"]   = float(pt.get("mean") or 0)
                out["price_target_median"] = float(pt.get("median") or 0)
                out["price_target_low"]    = float(pt.get("low") or 0)
                out["price_target_high"]   = float(pt.get("high") or 0)
        except Exception:
            pass
        return out or None

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {
            pool.submit(_get_attr, "income_stmt"):           "inc",
            pool.submit(_get_attr, "quarterly_income_stmt"): "qinc",
            pool.submit(_get_attr, "balance_sheet"):         "bs",
            pool.submit(_get_attr, "cashflow"):              "cf",
            pool.submit(_get_history):                       "hist",
            pool.submit(_get_news):                          "news",
            pool.submit(_get_analyst_consensus):             "analyst_consensus",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                d[key] = future.result()
            except Exception:
                d[key] = None if key != "news" else []

    # Ensure all keys exist
    for key in ["inc", "qinc", "bs", "cf", "hist"]:
        if key not in d:
            d[key] = None
    if "news" not in d:
        d["news"] = []
    if "analyst_consensus" not in d:
        d["analyst_consensus"] = None

    print(f"  _yf_full_fetch({ticker}): complete "
          f"(inc={'OK' if d['inc'] is not None else 'None'}, "
          f"bs={'OK' if d['bs'] is not None else 'None'}, "
          f"hist={'OK' if d['hist'] is not None else 'None'})")
    return d


def _fmp_full_fetch(ticker):
    """Full FMP fetch with parallel API calls. Fallback for US stocks."""
    print(f"  _fmp_full_fetch({ticker}): starting")

    # Profile + quote first (need source check)
    profile = _fmp_get("/profile", {"symbol": ticker})
    quote   = _fmp_get("/quote", {"symbol": ticker})

    if profile and isinstance(profile, list):
        profile = profile[0]
    if quote and isinstance(quote, list):
        quote = quote[0]

    if not profile or not quote:
        print(f"  _fmp_full_fetch({ticker}): no profile/quote from FMP")
        return None

    info = _merge_profile_quote(profile, quote)
    name = info.get("shortName") or info.get("longName") or ""
    if not name.strip():
        print(f"  _fmp_full_fetch({ticker}): empty company name from FMP")
        return None

    # ── Parallel fetch: ratios, metrics, statements, history ──
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(get_ratios_ttm, ticker):         "ratios",
            pool.submit(get_key_metrics_ttm, ticker):    "metrics",
            pool.submit(get_income_statement, ticker):   "inc_raw",
            pool.submit(get_balance_sheet, ticker):      "bs_raw",
            pool.submit(get_cashflow, ticker):           "cf_raw",
            pool.submit(get_historical_prices, ticker):  "hist",
        }
        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = None if key != "hist" else None

    # Enrich info with pre-fetched ratios/metrics
    info = enrich_info_with_ratios(info, ticker,
                                    ratios=results.get("ratios"),
                                    metrics=results.get("metrics"))

    # Convert statements to DataFrames
    inc_raw = results.get("inc_raw") or []
    bs_raw  = results.get("bs_raw") or []
    cf_raw  = results.get("cf_raw") or []

    inc = statements_to_dataframe(inc_raw, INCOME_KEY_MAP)
    bs  = statements_to_dataframe(bs_raw, BALANCE_KEY_MAP)
    cf  = statements_to_dataframe(cf_raw, CASHFLOW_KEY_MAP)

    # Enrich info from statements
    if cf_raw:
        latest_cf = cf_raw[0]
        if not info.get("operatingCashflow"):
            info["operatingCashflow"] = latest_cf.get("operatingCashFlow")
        if not info.get("freeCashflow") or info["freeCashflow"] == 0:
            info["freeCashflow"] = latest_cf.get("freeCashFlow")

    if bs_raw:
        latest_bs = bs_raw[0]
        info["totalCash"] = latest_bs.get("cashAndCashEquivalents")
        info["totalDebt"] = latest_bs.get("totalDebt")

    if inc_raw:
        info["totalRevenue"] = inc_raw[0].get("revenue")
        if len(inc_raw) >= 2:
            rev_new = inc_raw[0].get("revenue")
            rev_old = inc_raw[1].get("revenue")
            if rev_new and rev_old and rev_old > 0:
                info["revenueGrowth"] = round((rev_new - rev_old) / rev_old, 4)

    print(f"  _fmp_full_fetch({ticker}): complete")
    return {
        "info": info, "inc": inc, "qinc": None,
        "bs": bs, "cf": cf, "hist": results.get("hist"), "news": [],
        "analyst_consensus": None,
    }


# ══════════════════════════════════════════════════════════════
# CURRENT PRICE — yfinance PRIMARY, FMP FALLBACK
# ══════════════════════════════════════════════════════════════

def get_current_price(ticker):
    """Get latest price. yfinance primary, FMP fallback."""
    # ── yfinance (primary) ──
    if HAS_YF:
        try:
            info = yf.Ticker(ticker).info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price:
                print(f"  Price: yfinance OK for {ticker} (${price:.2f})")
                return float(price)
        except Exception as e:
            print(f"  Price: yfinance failed for {ticker}: {str(e)[:60]}")

    # ── FMP (fallback) ──
    data = _fmp_get("/quote", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        price = data[0].get("price")
        if price:
            print(f"  Price: FMP fallback OK for {ticker} (${float(price):.2f})")
            return float(price)

    return None


# ══════════════════════════════════════════════════════════════
# CURRENT METRICS — yfinance PRIMARY, FMP FALLBACK
# ══════════════════════════════════════════════════════════════

def get_current_metrics(ticker):
    """Get current key metrics for thesis check. yfinance primary."""
    # ── yfinance (primary) ──
    if HAS_YF:
        try:
            info = yf.Ticker(ticker).info
            fcf  = info.get("freeCashflow")
            mcap = info.get("marketCap")
            return {
                "trailing_pe":      info.get("trailingPE"),
                "forward_pe":       info.get("forwardPE"),
                "peg_ratio":        info.get("pegRatio"),
                "operating_margin": info.get("operatingMargins"),
                "roe":              info.get("returnOnEquity"),
                "revenue_growth":   info.get("revenueGrowth"),
                "fcf_yield":        _safe_div(fcf, mcap),
                "debt_to_equity":   info.get("debtToEquity"),
                "ev_to_ebitda":     info.get("enterpriseToEbitda"),
            }
        except Exception as e:
            print(f"  Metrics: yfinance failed for {ticker}: {str(e)[:60]}")

    # ── FMP (fallback) ──
    ratios  = get_ratios_ttm(ticker)
    metrics = get_key_metrics_ttm(ticker)

    if ratios or metrics:
        r = ratios or {}
        m = metrics or {}

        fcf = None
        mcap = None
        quote = _fmp_get("/quote", {"symbol": ticker})
        if quote and isinstance(quote, list):
            mcap = quote[0].get("marketCap")
            shares = quote[0].get("sharesOutstanding")
            fcf_ps = m.get("freeCashFlowPerShareTTM")
            if fcf_ps and shares:
                try:
                    fcf = float(fcf_ps) * float(shares)
                except Exception:
                    fcf = None

        return {
            "trailing_pe":      r.get("priceEarningsRatioTTM"),
            "forward_pe":       r.get("priceEarningsToGrowthRatioTTM"),
            "peg_ratio":        (r.get("pegRatioTTM")
                                 or r.get("priceEarningsToGrowthRatioTTM")
                                 or r.get("pegRatio")),
            "operating_margin": r.get("operatingProfitMarginTTM"),
            "roe":              r.get("returnOnEquityTTM"),
            "revenue_growth":   None,
            "fcf_yield":        _safe_div(fcf, mcap),
            "debt_to_equity":   r.get("debtEquityRatioTTM"),
            "ev_to_ebitda":     m.get("enterpriseValueOverEBITDATTM"),
        }

    return {}

# ══════════════════════════════════════════════════════════════
# PEERS (placeholder - FMP free tier doesn't support)
# ══════════════════════════════════════════════════════════════

def get_peers(ticker):
    return []


# ══════════════════════════════════════════════════════════════
# §8.1 NEW BEST-EFFORT FETCHES (Phase B)
# All return None on any miss — never raise.
# ══════════════════════════════════════════════════════════════

def _row_latest(df, labels):
    """Return the most recent value from the first matching row in a DataFrame."""
    if df is None or df.empty:
        return None
    for lb in labels:
        if lb in df.index:
            row = df.loc[lb].dropna().sort_index()
            if not row.empty:
                return float(row.iloc[-1])
    return None


def _row_prior(df, labels):
    """Return the second-most-recent value from the first matching row."""
    if df is None or df.empty:
        return None
    for lb in labels:
        if lb in df.index:
            row = df.loc[lb].dropna().sort_index()
            if len(row) >= 2:
                return float(row.iloc[-2])
    return None


def fetch_sbc(data) -> Optional[float]:
    """Stock-based compensation: cashflow primary, FMP fallback via data dict."""
    cf = data.get("cf")
    sbc = _row_latest(cf, [
        "Stock Based Compensation", "StockBasedCompensation",
        "Share Based Compensation", "ShareBasedCompensation",
    ])
    if sbc is not None:
        return sbc
    # FMP raw statements fallback
    for stmt in (data.get("cf_raw") or []):
        val = stmt.get("stockBasedCompensation")
        if val is not None:
            try:
                return float(val)
            except Exception:
                pass
    return None


def fetch_contract_assets(data) -> tuple:
    """
    Current and prior-year contract assets from balance sheet.
    Returns (current, prior) — either may be None.
    """
    bs = data.get("bs")
    labels = [
        "Contract Assets", "ContractAssets",
        "Contract Asset", "Contracts Receivable", "ContractsReceivable",
    ]
    current = _row_latest(bs, labels)
    prior   = _row_prior(bs, labels)

    # FMP raw fallback
    if current is None:
        for stmt in (data.get("bs_raw") or [])[:2]:
            val = stmt.get("contractAssets") or stmt.get("contractAssetsCurrentAssets")
            if val is not None:
                try:
                    current = float(val)
                    break
                except Exception:
                    pass

    return current, prior


def fetch_dso(data) -> tuple:
    """
    Days Sales Outstanding (current and prior year).
    DSO = accounts_receivable / revenue × 365.
    Returns (dso_current, dso_prior) — either may be None.
    """
    inc = data.get("inc")
    bs  = data.get("bs")

    rev_labels = ["Total Revenue", "TotalRevenue", "Revenue"]
    ar_labels  = [
        "Accounts Receivable", "Net Receivables", "AccountsReceivable",
        "Receivables", "Trade And Other Receivables",
    ]

    rev_latest = _row_latest(inc, rev_labels)
    rev_prior  = _row_prior(inc, rev_labels)
    ar_latest  = _row_latest(bs, ar_labels)
    ar_prior   = _row_prior(bs, ar_labels)

    dso_current = round(ar_latest / rev_latest * 365, 1) \
        if ar_latest and rev_latest and rev_latest > 0 else None
    dso_prior = round(ar_prior / rev_prior * 365, 1) \
        if ar_prior and rev_prior and rev_prior > 0 else None

    return dso_current, dso_prior


def fetch_software_revenue(data, ticker: str) -> Optional[float]:
    """
    Software / subscription revenue: FMP revenue-product-segmentation primary.
    Returns the largest software-like segment revenue, or None.
    """
    raw = _fmp_get("/revenue-product-segmentation", {"symbol": ticker})
    if not raw or not isinstance(raw, list):
        return None
    software_keys = {"software", "subscription", "saas", "cloud", "services"}
    try:
        latest = raw[0]
        if isinstance(latest, dict):
            for key, val in latest.items():
                if any(sw in key.lower() for sw in software_keys):
                    return float(val) if val is not None else None
    except Exception:
        pass
    return None


def fetch_segment_revenue(ticker: str) -> Optional[list]:
    """
    Revenue by product/geographic segment from FMP.
    Returns [{name, revenue, share_pct}] or None.
    """
    raw = _fmp_get("/revenue-product-segmentation", {"symbol": ticker})
    if not raw or not isinstance(raw, list):
        return None
    try:
        latest = raw[0]
        if not isinstance(latest, dict):
            return None
        items = {k: v for k, v in latest.items()
                 if k not in ("date", "symbol") and v is not None}
        total = sum(float(v) for v in items.values() if v)
        if total <= 0:
            return None
        segs = []
        for name, val in items.items():
            try:
                rev = float(val)
                segs.append({
                    "name":      name,
                    "revenue":   rev,
                    "share_pct": round(rev / total, 4),
                })
            except Exception:
                pass
        return segs or None
    except Exception:
        return None


def fetch_peer_enriched(peer_tickers: list[str]) -> list[dict]:
    """
    Fetch fwd_pe, growth, op_margin, fcf_margin for each peer.
    Best-effort: missing fields set to None; failed tickers skipped.
    """
    if not HAS_YF:
        return [{"ticker": t, "fwd_pe": None, "growth": None,
                 "op_margin": None, "fcf_margin": None}
                for t in peer_tickers]

    def _fetch_one(ticker: str) -> dict:
        out = {"ticker": ticker, "fwd_pe": None, "growth": None,
               "op_margin": None, "fcf_margin": None}
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            out["fwd_pe"]    = info.get("forwardPE")
            out["growth"]    = info.get("earningsGrowth") or info.get("revenueGrowth")
            out["op_margin"] = info.get("operatingMargins")
            fcf  = info.get("freeCashflow")
            rev  = info.get("totalRevenue")
            if fcf and rev and rev > 0:
                out["fcf_margin"] = round(float(fcf) / float(rev), 4)
        except Exception:
            pass
        return out

    results = []
    with ThreadPoolExecutor(max_workers=min(len(peer_tickers), 6)) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in peer_tickers}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                results.append({"ticker": futures[future], "fwd_pe": None,
                                 "growth": None, "op_margin": None, "fcf_margin": None})
    # Preserve input order
    order = {t: i for i, t in enumerate(peer_tickers)}
    return sorted(results, key=lambda x: order.get(x["ticker"], 999))


def fetch_peer_metrics(peer_tickers: list[str]) -> list[dict]:
    """
    Fetch fwd_pe and analyst-estimate growth for each peer.

    Growth sourced from earnings_estimate '+1y' row (confirmed yfinance index key).
    Falls back to earningsGrowth/revenueGrowth from info if estimate unavailable.
    op_margin and fcf_margin are always None — reserved for §5.1 contract shape.

    Never raises. Failed tickers are skipped silently.
    """
    if not peer_tickers:
        return []
    if not HAS_YF:
        return [{"ticker": t, "fwd_pe": None, "growth": None,
                 "op_margin": None, "fcf_margin": None}
                for t in peer_tickers]

    def _fetch_one(t: str) -> dict:
        out = {"ticker": t, "fwd_pe": None, "growth": None,
               "op_margin": None, "fcf_margin": None}
        try:
            import yfinance as yf
            s    = yf.Ticker(t)
            info = s.info
            out["fwd_pe"] = info.get("forwardPE")
            ee = getattr(s, "earnings_estimate", None)
            if ee is not None and not ee.empty and "+1y" in ee.index:
                g = ee.loc["+1y"].get("growth")
                if g is not None:
                    out["growth"] = float(g)
            if out["growth"] is None:
                out["growth"] = info.get("earningsGrowth") or info.get("revenueGrowth")
        except Exception:
            pass
        return out

    results = []
    with ThreadPoolExecutor(max_workers=min(len(peer_tickers), 6)) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in peer_tickers}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                results.append({"ticker": futures[future], "fwd_pe": None,
                                 "growth": None, "op_margin": None, "fcf_margin": None})
    order = {t: i for i, t in enumerate(peer_tickers)}
    return sorted(results, key=lambda x: order.get(x["ticker"], 999))


# ══════════════════════════════════════════════════════════════
# §8.2 CONSENSUS PACK (Phase B)
# ══════════════════════════════════════════════════════════════

def fetch_consensus_pack(ticker: str) -> dict:
    """
    Returns consensus_eps_fy1/2/3, consensus_revenue_fy1/2,
    consensus_price_target, n_analysts.

    Never raises. Missing fields are None.
    Sources: yfinance primary, FMP analyst-estimates fallback.
    """
    out = {
        "consensus_eps_fy1":       None,
        "consensus_eps_fy2":       None,
        "consensus_eps_fy3":       None,
        "consensus_revenue_fy1":   None,
        "consensus_revenue_fy2":   None,
        "consensus_price_target":  None,
        "n_analysts":              None,
    }

    # ── yfinance primary ────────────────────────────────────────
    if HAS_YF:
        try:
            import yfinance as yf
            s = yf.Ticker(ticker)

            # EPS estimates (earnings_estimate table: rows = "0q","+1q","0y","+1y","+2y")
            try:
                ee = getattr(s, "earnings_estimate", None)
                if ee is not None and not ee.empty:
                    _yf_fy_map = {"0y": "consensus_eps_fy1", "+1y": "consensus_eps_fy2",
                                  "+2y": "consensus_eps_fy3"}
                    for row_idx, key in _yf_fy_map.items():
                        if row_idx in ee.index:
                            r = ee.loc[row_idx]
                            lo  = r.get("low")
                            mid = r.get("avg")
                            hi  = r.get("high")
                            n   = r.get("numberOfAnalysts")
                            if mid is not None:
                                out[key] = {
                                    "low":  float(lo)  if lo  is not None else None,
                                    "mid":  float(mid),
                                    "high": float(hi)  if hi  is not None else None,
                                }
                                if n is not None and out["n_analysts"] is None:
                                    try:
                                        out["n_analysts"] = int(n)
                                    except Exception:
                                        pass
            except Exception:
                pass

            # Revenue estimates (revenue_estimate table)
            try:
                re = getattr(s, "revenue_estimate", None)
                if re is not None and not re.empty:
                    _yf_rev_map = {"0y": "consensus_revenue_fy1", "+1y": "consensus_revenue_fy2"}
                    for row_idx, key in _yf_rev_map.items():
                        if row_idx in re.index:
                            r = re.loc[row_idx]
                            lo  = r.get("low")
                            mid = r.get("avg")
                            hi  = r.get("high")
                            if mid is not None:
                                out[key] = {
                                    "low":  float(lo)  if lo  is not None else None,
                                    "mid":  float(mid),
                                    "high": float(hi)  if hi  is not None else None,
                                }
            except Exception:
                pass

            # Price targets
            try:
                pt = getattr(s, "analyst_price_targets", None)
                if isinstance(pt, dict):
                    lo  = pt.get("low")
                    med = pt.get("median") or pt.get("mean")
                    hi  = pt.get("high")
                    if med:
                        out["consensus_price_target"] = {
                            "low":    float(lo)  if lo  is not None else None,
                            "median": float(med),
                            "high":   float(hi)  if hi  is not None else None,
                        }
                n_analysts_pt = getattr(s, "analyst_price_targets", {})
                if isinstance(n_analysts_pt, dict) and out["n_analysts"] is None:
                    count = n_analysts_pt.get("numberOfAnalysts")
                    if count is not None:
                        try:
                            out["n_analysts"] = int(count)
                        except Exception:
                            pass
            except Exception:
                pass

            # If yfinance gave us anything useful, return now
            if any(out[k] is not None for k in (
                    "consensus_eps_fy1", "consensus_eps_fy2",
                    "consensus_revenue_fy1", "consensus_price_target")):
                return out

        except Exception:
            pass

    # ── FMP analyst-estimates fallback ─────────────────────────
    try:
        data = _fmp_get("/analyst-estimates", {"symbol": ticker, "limit": 4})
        if data and isinstance(data, list):
            fy_entries = [d for d in data if d.get("period") == "annual"]
            fy_entries.sort(key=lambda x: x.get("date", ""), reverse=True)

            fy_keys = ["consensus_eps_fy1", "consensus_eps_fy2", "consensus_eps_fy3"]
            rv_keys = ["consensus_revenue_fy1", "consensus_revenue_fy2"]

            for i, entry in enumerate(fy_entries[:3]):
                if i < len(fy_keys) and out[fy_keys[i]] is None:
                    lo  = entry.get("estimatedEpsLow")
                    mid = entry.get("estimatedEpsAvg")
                    hi  = entry.get("estimatedEpsHigh")
                    if mid:
                        out[fy_keys[i]] = {
                            "low":  float(lo) if lo is not None else None,
                            "mid":  float(mid),
                            "high": float(hi) if hi is not None else None,
                        }
                if i < len(rv_keys) and out[rv_keys[i]] is None:
                    lo  = entry.get("estimatedRevenueLow")
                    mid = entry.get("estimatedRevenueAvg")
                    hi  = entry.get("estimatedRevenueHigh")
                    if mid:
                        out[rv_keys[i]] = {
                            "low":  float(lo) / 1e9 if lo is not None else None,
                            "mid":  float(mid) / 1e9,
                            "high": float(hi) / 1e9 if hi is not None else None,
                        }
                if out["n_analysts"] is None:
                    n = entry.get("numberAnalystEstimatedEps")
                    if n:
                        try:
                            out["n_analysts"] = int(n)
                        except Exception:
                            pass
    except Exception:
        pass

    # FMP price-target-consensus fallback
    try:
        ptc = _fmp_get("/price-target-consensus", {"symbol": ticker})
        if ptc and isinstance(ptc, list) and ptc:
            p = ptc[0]
            lo  = p.get("priceTargetLow")
            med = p.get("priceTargetConsensus") or p.get("priceTargetMedian")
            hi  = p.get("priceTargetHigh")
            if med and out["consensus_price_target"] is None:
                out["consensus_price_target"] = {
                    "low":    float(lo)  if lo  is not None else None,
                    "median": float(med),
                    "high":   float(hi)  if hi  is not None else None,
                }
    except Exception:
        pass

    return out
