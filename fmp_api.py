"""
fmp_api.py — Shared FMP API helper with automatic yfinance fallback.
Used by both app.py and check_prices.py.
"""

import json
import os
import time as _time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

def _get_api_key():
    try:
        import streamlit as st
        key = st.secrets.get("FMP_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("FMP_API_KEY", "")

BASE_URL = "https://financialmodelingprep.com/stable"


def _fmp_get(path, params=None):
    key = _get_api_key()
    if not key:
        print("FMP: No API key found")
        return None

    if params is None:
        params = {}
    params["apikey"] = key

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


def search_ticker(query):
    data = _fmp_get("/search", {"query": query, "limit": 6})
    if data:
        return [
            {
                "symbol":   item.get("symbol", ""),
                "name":     item.get("name", item.get("symbol", "")),
                "exchange": item.get("stockExchange", item.get("exchangeShortName", "")),
            }
            for item in data
            if item.get("symbol")
        ]

    if HAS_YF:
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=6&newsCount=0"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                ydata = json.loads(resp.read().decode())
                return [
                    {"symbol": q["symbol"], "name": q.get("shortname", q["symbol"]), "exchange": q.get("exchange", "")}
                    for q in ydata.get("quotes", [])
                    if q.get("quoteType") in ("EQUITY", "ETF")
                ]
        except Exception:
            pass
    return []


def get_profile(ticker):
    """
    Get company profile. yfinance primary (better forward estimates),
    FMP as fallback.
    """
    # ── yfinance first: better forward PE, forward EPS, analyst estimates ──
    if HAS_YF:
        try:
            info = yf.Ticker(ticker).info
            if info and "shortName" in info:
                info["_source"] = "yfinance"
                print(f"  Profile: yfinance OK for {ticker} "
                      f"(fwd_pe={info.get('forwardPE')}, fwd_eps={info.get('forwardEps')})")
                return info
        except Exception as e:
            print(f"  yfinance profile failed for {ticker}: {str(e)[:80]}")

    # ── FMP fallback ──
    profile = _fmp_get("/profile", {"symbol": ticker})
    quote   = _fmp_get("/quote", {"symbol": ticker})

    if profile and isinstance(profile, list):
        profile = profile[0]
    if quote and isinstance(quote, list):
        quote = quote[0]

    if profile and quote:
        return _merge_profile_quote(profile, quote)

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
        "priceToBook":          _safe_div(q.get("price"), p.get("bookValuePerShare")),
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
    }


def _safe_div(a, b):
    try:
        if a is not None and b is not None and b != 0:
            return round(a / b, 4)
    except Exception:
        pass
    return None


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


def enrich_info_with_ratios(info_dict, ticker):
    if info_dict.get("_source") != "fmp":
        return info_dict

    ratios  = get_ratios_ttm(ticker)
    metrics = get_key_metrics_ttm(ticker)

    # DEBUG: uncomment to see actual FMP field names
    # if ratios:
    #     print(f"DEBUG ratios keys for {ticker}: {list(ratios.keys())}")
    # if metrics:
    #     print(f"DEBUG metrics keys for {ticker}: {list(metrics.keys())}")

    if ratios:
        # P/E: use ratio endpoint as primary, keep quote value as fallback
        pe_from_ratios = ratios.get("peRatioTTM") or ratios.get("priceEarningsRatioTTM")
        if pe_from_ratios:
            info_dict["trailingPE"] = pe_from_ratios

        # PEG: try multiple possible field names
        info_dict["pegRatio"] = (
            ratios.get("pegRatioTTM")
            or ratios.get("priceEarningsToGrowthRatioTTM")
            or ratios.get("pegRatio")
        )

        info_dict["priceToSalesTrailing12Months"] = (
            ratios.get("priceToSalesRatioTTM")
            or ratios.get("priceSalesRatioTTM")
        )
        info_dict["returnOnEquity"]     = ratios.get("returnOnEquityTTM")
        info_dict["returnOnAssets"]     = ratios.get("returnOnAssetsTTM")
        info_dict["grossMargins"]       = ratios.get("grossProfitMarginTTM")
        info_dict["operatingMargins"]   = ratios.get("operatingProfitMarginTTM")
        info_dict["profitMargins"]      = ratios.get("netProfitMarginTTM")
        info_dict["debtToEquity"]       = ratios.get("debtEquityRatioTTM")
        info_dict["currentRatio"]       = ratios.get("currentRatioTTM")
        info_dict["payoutRatio"]        = ratios.get("payoutRatioTTM")
        info_dict["dividendYield"]      = ratios.get("dividendYieldTTM") or info_dict.get("dividendYield")

    if metrics:
        info_dict["enterpriseValue"]    = metrics.get("enterpriseValueTTM") or info_dict.get("enterpriseValue")
        info_dict["enterpriseToEbitda"] = metrics.get("enterpriseValueOverEBITDATTM")
        info_dict["earningsGrowth"]     = metrics.get("earningsYieldTTM")
        info_dict["revenueGrowth"]      = None

        # Forward PE from metrics
        forward_pe = metrics.get("peRatioTTM")
        if not forward_pe:
            earnings_yield = metrics.get("earningsYieldTTM")
            if earnings_yield and float(earnings_yield) > 0:
                try:
                    forward_pe = round(1.0 / float(earnings_yield), 2)
                except:
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


def get_income_statement(ticker, period="annual", limit=5):
    data = _fmp_get("/income-statement", {"symbol": ticker, "period": period, "limit": limit})
    return data if data else []


def get_balance_sheet(ticker, period="annual", limit=5):
    data = _fmp_get("/balance-sheet-statement", {"symbol": ticker, "period": period, "limit": limit})
    return data if data else []


def get_cashflow(ticker, period="annual", limit=5):
    data = _fmp_get("/cash-flow-statement", {"symbol": ticker, "period": period, "limit": limit})
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
        label = key
        if key_mapping and key in key_mapping:
            label = key_mapping[key]
        values = [s.get(key) for s in statements]
        data[label] = values

    df = pd.DataFrame(data, index=dates).T
    return df


INCOME_KEY_MAP = {
    "revenue":                  "Total Revenue",
    "grossProfit":              "Gross Profit",
    "operatingIncome":          "Operating Income",
    "netIncome":                "Net Income",
    "eps":                      "Basic EPS",
    "epsdiluted":               "Diluted EPS",
    "ebitda":                   "EBITDA",
    "costOfRevenue":            "Cost Of Revenue",
}

BALANCE_KEY_MAP = {
    "totalDebt":                    "Total Debt",
    "totalStockholdersEquity":      "Stockholders Equity",
    "totalCurrentAssets":           "Current Assets",
    "totalCurrentLiabilities":      "Current Liabilities",
    "longTermDebt":                 "Long Term Debt",
    "commonStock":                  "Common Stock",
    "totalAssets":                  "Total Assets",
    "totalLiabilities":             "Total Liabilities",
    "cashAndCashEquivalents":       "Cash And Cash Equivalents",
}

CASHFLOW_KEY_MAP = {
    "operatingCashFlow":            "Operating Cash Flow",
    "capitalExpenditure":           "Capital Expenditure",
    "freeCashFlow":                 "Free Cash Flow",
    "dividendsPaid":                "Dividends Paid",
    "netCashUsedForInvestingActivites": "Investing Cash Flow",
    "netCashUsedProvidedByFinancingActivities": "Financing Cash Flow",
}


def get_historical_prices(ticker, period="5y"):
    """
    FMP free tier doesn't include historical prices.
    Go straight to yfinance.
    """
    import pandas as pd

    if HAS_YF:
        try:
            h = yf.Ticker(ticker).history(period=period, interval="1wk")
            if h is not None and not h.empty:
                return h
        except Exception as e:
            print(f"yfinance historical fetch failed: {e}")

    return None


def get_peers(ticker):
    """FMP free tier doesn't support peers endpoint. Returns empty list."""
    return []


def fetch_full(ticker):
    print(f"DEBUG fetch_full({ticker}): starting")

    info = get_profile(ticker)

    print(f"DEBUG fetch_full({ticker}): info is None = {info is None}")
    if info is not None:
        print(f"DEBUG fetch_full({ticker}): source = {info.get('_source')}, "
              f"name = {info.get('shortName', 'N/A')}")

    if info is None:
        print(f"FMP: No profile for {ticker}, trying yfinance full fetch")
        if HAS_YF:
            return _yf_full_fetch(ticker)
        return None

    # Verify we got a valid company name from FMP
    if info.get("_source") == "fmp":
        name = info.get("shortName") or info.get("longName") or ""
        if not name or name.strip() == "":
            print(f"FMP: Empty company name for {ticker}, trying yfinance")
            if HAS_YF:
                return _yf_full_fetch(ticker)
            return None

    if info.get("_source") == "fmp":
        info = enrich_info_with_ratios(info, ticker)

        inc_raw = get_income_statement(ticker)
        bs_raw  = get_balance_sheet(ticker)
        cf_raw  = get_cashflow(ticker)

        inc = statements_to_dataframe(inc_raw, INCOME_KEY_MAP)
        bs  = statements_to_dataframe(bs_raw, BALANCE_KEY_MAP)
        cf  = statements_to_dataframe(cf_raw, CASHFLOW_KEY_MAP)

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

        hist = get_historical_prices(ticker)
        news = []

        return {
            "info": info,
            "inc":  inc,
            "qinc": None,
            "bs":   bs,
            "cf":   cf,
            "hist": hist,
            "news": news,
        }

    # If yfinance was source from get_profile, do full yfinance fetch
    return _yf_full_fetch(ticker, existing_info=info)

def _yf_full_fetch(ticker, existing_info=None):
    """Full yfinance fetch. Can reuse existing info dict to avoid duplicate calls."""
    if not HAS_YF:
        return None

    print(f"DEBUG _yf_full_fetch({ticker}): starting")

    s = yf.Ticker(ticker)
    d = {}

    # ── Reuse existing info if provided, otherwise fetch ──
    if existing_info and "shortName" in existing_info:
        d["info"] = existing_info
        print(f"DEBUG _yf_full_fetch({ticker}): reusing existing info, "
              f"name = {existing_info.get('shortName')}")
    else:
        for attempt in range(2):
            try:
                info = s.info
                if info and "shortName" in info:
                    info["_source"] = "yfinance"
                    d["info"] = info
                    print(f"DEBUG _yf_full_fetch({ticker}): got info on attempt {attempt+1}")
                    break
                elif info and info.get("quoteType") == "NONE_TYPE":
                    d["info"] = {"error": f"Ticker '{ticker}' not found on Yahoo Finance"}
                    break
                else:
                    d["info"] = {"error": f"Empty response for {ticker} from Yahoo Finance"}
            except Exception as e:
                d["info"] = {"error": f"Yahoo Finance error: {str(e)[:200]}"}
                if attempt == 0:
                    _time.sleep(2)

    if "info" not in d:
        d["info"] = {"error": f"All attempts to fetch {ticker} failed"}

    for attr, key in [("income_stmt", "inc"), ("quarterly_income_stmt", "qinc"),
                      ("balance_sheet", "bs"), ("cashflow", "cf")]:
        try:
            df = getattr(s, attr)
            d[key] = df if df is not None and not df.empty else None
        except Exception:
            d[key] = None

    try:
        h = s.history(period="5y", interval="1wk")
        d["hist"] = h if h is not None and not h.empty else None
    except Exception:
        d["hist"] = None

    try:
        d["news"] = s.news[:8] if s.news else []
    except Exception:
        d["news"] = []

    return d

def get_current_price(ticker):
    data = _fmp_get("/quote", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        price = data[0].get("price")
        if price:
            return float(price)

    if HAS_YF:
        try:
            info = yf.Ticker(ticker).info
            return info.get("currentPrice") or info.get("regularMarketPrice")
        except Exception:
            pass
    return None


def get_current_metrics(ticker):
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
            "peg_ratio":        (
                r.get("pegRatioTTM")
                or r.get("priceEarningsToGrowthRatioTTM")
                or r.get("pegRatio")
            ),
            "operating_margin": r.get("operatingProfitMarginTTM"),
            "roe":              r.get("returnOnEquityTTM"),
            "revenue_growth":   None,
            "fcf_yield":        _safe_div(fcf, mcap),
            "debt_to_equity":   r.get("debtEquityRatioTTM"),
            "ev_to_ebitda":     m.get("enterpriseValueOverEBITDATTM"),
        }

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
        except Exception:
            pass
    return {}
