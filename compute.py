"""
Financial metrics computation, scenario math, probability engine, QGLP scoring.

v3 changes:
  • _get_statement_eps_series: self-computed EPS from income_stmt
  • _compute_peg: uses statement-derived EPS for PE, caps Priority 2 at 30%
  • _compute_cagrs: caps at 40% (unchanged) but raw values always preserved
  • validate_post_scenario: new post-scenario rejection gate
  • All existing function signatures preserved — no breaking changes
"""

import re
from formatting import safe_float, fmt_n


# ══════════════════════════════════════════════════════════════
# LATEX SANITIZER (unchanged)
# ══════════════════════════════════════════════════════════════

def clean_latex(text):
    if not text or not isinstance(text, str):
        return text
    text = re.sub(r'\\\((.+?)\\\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    text = re.sub(r'\$([^$\d][^$]*?)\$', r'\1', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


# ══════════════════════════════════════════════════════════════
# SELF-COMPUTED EPS FROM STATEMENTS (v3)
# ══════════════════════════════════════════════════════════════

def _get_statement_eps(data):
    """
    Extract the most recent Diluted EPS from the income statement.

    Used by _compute_peg to get a reliable trailing EPS for PE
    computation, independent of .info["trailingEps"].

    Returns (eps_float, eps_series_dict) or (None, {}).
    eps_series_dict: {year: eps} for diagnostics.
    """
    inc = data.get("inc")
    if inc is None or inc.empty:
        return None, {}

    for lbl in ["Diluted EPS", "Basic EPS"]:
        if lbl in inc.index:
            row = inc.loc[lbl].dropna().sort_index()
            if row.empty:
                continue
            series = {}
            for dt, val in row.items():
                try:
                    yr = dt.year if hasattr(dt, "year") else int(str(dt)[:4])
                    series[yr] = round(float(val), 4)
                except Exception:
                    continue
            if series:
                newest_eps = list(series.values())[-1]  # sorted ascending
                return newest_eps, series

    # Fallback: Net Income / shares
    info = data.get("info", {})
    shares = info.get("sharesOutstanding")
    if not shares or shares <= 0:
        return None, {}

    for lbl in ["Net Income", "Net Income Common Stockholders"]:
        if lbl in inc.index:
            row = inc.loc[lbl].dropna().sort_index()
            if not row.empty:
                ni = float(row.iloc[-1])
                if ni != 0:
                    return round(ni / shares, 4), {}

    return None, {}


# ══════════════════════════════════════════════════════════════
# METRICS COMPUTATION
# ══════════════════════════════════════════════════════════════

def calc(data):
    info = data.get("info", {})
    if isinstance(info, dict) and "error" in info:
        return {"error": info["error"]}
    g = lambda k, d=None: info.get(k, d)

    m = {
        "company_name": g("shortName", g("longName", "Unknown")),
        "sector": g("sector", "N/A"), "industry": g("industry", "N/A"),
        "country": g("country", "N/A"), "currency": g("currency", "USD"),
        "description": g("longBusinessSummary", "N/A"),
        "current_price": g("currentPrice", g("regularMarketPrice")),
        "market_cap": g("marketCap"), "enterprise_value": g("enterpriseValue"),
        "trailing_pe": g("trailingPE"), "forward_pe": g("forwardPE"),
        "peg_ratio": None,
        "price_to_sales": g("priceToSalesTrailing12Months"),
        "ev_to_ebitda": g("enterpriseToEbitda"),
        "gross_margin": g("grossMargins"), "operating_margin": g("operatingMargins"),
        "profit_margin": g("profitMargins"), "roe": g("returnOnEquity"),
        "roa": g("returnOnAssets"),
        "trailing_eps": g("trailingEps"), "forward_eps": g("forwardEps"),
        "earnings_growth": g("earningsGrowth"),
        "total_revenue": g("totalRevenue"), "revenue_growth": g("revenueGrowth"),
        "free_cashflow": g("freeCashflow"), "operating_cashflow": g("operatingCashflow"),
        "total_cash": g("totalCash"), "total_debt": g("totalDebt"),
        "dividend_yield": g("dividendYield"), "payout_ratio": g("payoutRatio"),
        "beta": g("beta"), "week_52_high": g("fiftyTwoWeekHigh"),
        "week_52_low": g("fiftyTwoWeekLow"),
        "ma_50": g("fiftyDayAverage"), "ma_200": g("twoHundredDayAverage"),
        "insider_pct": g("heldPercentInsiders"),
        "institution_pct": g("heldPercentInstitutions"),
        "shares_outstanding": g("sharesOutstanding"),
    }

    # FCF yield
    try:
        m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"]) \
            if m["free_cashflow"] and m["market_cap"] else None
    except Exception:
        m["fcf_yield"] = None

    # ── Self-computed EPS from statements (v3) ────────────────
    stmt_eps, stmt_eps_series = _get_statement_eps(data)
    m["stmt_trailing_eps"] = stmt_eps
    m["stmt_eps_series"]   = stmt_eps_series

    # Cross-validate API trailing_eps against statement EPS
    if stmt_eps and m["trailing_eps"]:
        try:
            api_eps = float(m["trailing_eps"])
            div = abs(api_eps - stmt_eps) / abs(stmt_eps) if stmt_eps != 0 else 0
            if div > 0.30:
                print(f"  EPS DIVERGENCE: API={api_eps:.2f} vs "
                      f"stmt={stmt_eps:.2f} ({div:.0%} gap). "
                      f"Using statement EPS as source of truth.")
                m["trailing_eps"] = stmt_eps
                # Recompute trailing PE from statement EPS
                if m["current_price"] and float(m["current_price"]) > 0:
                    m["trailing_pe"] = round(
                        float(m["current_price"]) / stmt_eps, 2)
        except Exception:
            pass

    m = _compute_debt_equity(m, info, data)
    m = _compute_margins_from_statements(m, data)
    m = _compute_cagrs(m, data)
    m = _cross_validate_forward_pe(m, info)
    m = _compute_peg(m)
    m = _check_growth_consistency(m)
    m = _compute_price_history(m, data)
    m["news"] = [{"title": n.get("title", ""), "publisher": n.get("publisher", "")}
                 for n in data.get("news", [])]
    return m


def _compute_debt_equity(m, info, data):
    raw_de = info.get("debtToEquity")
    bs = data.get("bs")
    computed_de = None
    computed_current_ratio = None

    if bs is not None and not bs.empty:
        def _bs_row(labels):
            for lb in labels:
                if lb in bs.index:
                    row = bs.loc[lb].dropna()
                    if not row.empty:
                        return float(row.iloc[0])
            return None

        total_debt_bs = _bs_row(["Total Debt", "TotalDebt",
                                  "Long Term Debt And Capital Lease Obligation",
                                  "Long Term Debt", "LongTermDebt"])
        total_eq = _bs_row(["Stockholders Equity", "Total Stockholder Equity",
                            "TotalStockholdersEquity", "Common Stock Equity",
                            "CommonStockEquity"])
        current_assets = _bs_row(["Current Assets", "TotalCurrentAssets",
                                  "Total Current Assets"])
        current_liabs = _bs_row(["Current Liabilities", "TotalCurrentLiabilities",
                                 "Total Current Liabilities"])

        if total_debt_bs and total_eq and total_eq != 0:
            computed_de = round(total_debt_bs / total_eq, 3)
        if current_assets and current_liabs and current_liabs != 0:
            computed_current_ratio = round(current_assets / current_liabs, 2)

    if computed_de is not None:
        m["debt_to_equity"] = computed_de
    elif raw_de is not None:
        try:
            raw_de_float = float(raw_de)
            if info.get("_source") == "fmp":
                m["debt_to_equity"] = round(raw_de_float, 3)
            else:
                m["debt_to_equity"] = round(raw_de_float / 100, 3)
        except Exception:
            m["debt_to_equity"] = None
    else:
        m["debt_to_equity"] = None

    m["current_ratio"] = computed_current_ratio if computed_current_ratio is not None \
        else info.get("currentRatio")
    return m


def _compute_margins_from_statements(m, data):
    inc = data.get("inc")
    bs  = data.get("bs")

    if m["gross_margin"] is None and inc is not None:
        try:
            rev_row = gp_row = None
            for lb in ["Total Revenue", "TotalRevenue", "Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Gross Profit", "GrossProfit"]:
                if lb in inc.index:
                    gp_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and gp_row is not None:
                rev = float(rev_row.iloc[-1]); gp = float(gp_row.iloc[-1])
                if rev > 0:
                    m["gross_margin"] = round(gp / rev, 4)
        except Exception:
            pass

    if m["operating_margin"] is None and inc is not None:
        try:
            rev_row = op_row = None
            for lb in ["Total Revenue", "TotalRevenue", "Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Operating Income", "OperatingIncome", "EBIT"]:
                if lb in inc.index:
                    op_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and op_row is not None:
                rev = float(rev_row.iloc[-1]); op = float(op_row.iloc[-1])
                if rev > 0:
                    m["operating_margin"] = round(op / rev, 4)
        except Exception:
            pass

    if m["profit_margin"] is None and inc is not None:
        try:
            rev_row = ni_row = None
            for lb in ["Total Revenue", "TotalRevenue", "Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Net Income", "NetIncome", "Net Income Common Stockholders"]:
                if lb in inc.index:
                    ni_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and ni_row is not None:
                rev = float(rev_row.iloc[-1]); ni = float(ni_row.iloc[-1])
                if rev > 0:
                    m["profit_margin"] = round(ni / rev, 4)
        except Exception:
            pass

    if m["roe"] is None and inc is not None and bs is not None:
        try:
            ni_row = eq_row = None
            for lb in ["Net Income", "NetIncome", "Net Income Common Stockholders"]:
                if lb in inc.index:
                    ni_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Stockholders Equity", "Total Stockholder Equity",
                        "CommonStockEquity"]:
                if lb in bs.index:
                    eq_row = bs.loc[lb].dropna().sort_index(); break
            if ni_row is not None and eq_row is not None:
                ni = float(ni_row.iloc[-1]); eq = float(eq_row.iloc[0])
                if eq > 0:
                    m["roe"] = round(ni / eq, 4)
        except Exception:
            pass

    return m


def _cagr_from(df, labels):
    if df is None:
        return None, {}, 0
    for lb in labels:
        if lb in df.index:
            row = df.loc[lb].dropna()
            if row.empty:
                continue
            row = row.sort_index()
            hist = {str(dt.year) if hasattr(dt, 'year') else str(dt): round(float(v) / 1e9, 2)
                    for dt, v in row.items()}
            if len(row) < 2:
                return None, hist, 0
            if len(row) >= 5:
                oldest = float(row.iloc[-5])
                newest = float(row.iloc[-1])
                years = 4
            else:
                oldest = float(row.iloc[0])
                newest = float(row.iloc[-1])
                years = len(row) - 1
            if oldest <= 0 or years <= 0:
                return None, hist, 0
            cagr = (newest / oldest) ** (1 / years) - 1
            return round(cagr, 4), hist, years
    return None, {}, 0


def _compute_cagrs(m, data):
    inc = data.get("inc")

    m["revenue_cagr"], m["revenue_history"], m["revenue_cagr_years"] = _cagr_from(
        inc, ["Total Revenue", "TotalRevenue", "Revenue", "revenue", "totalRevenue"])

    ni_cagr, ni_hist, ni_years = _cagr_from(
        inc, ["Net Income", "NetIncome", "Net Income Common Stockholders",
              "netIncome", "Net Income From Continuing Operation Net Minority Interest"])
    eps_cagr, _, eps_years = _cagr_from(
        inc, ["Diluted EPS", "Basic EPS", "DilutedEPS", "BasicEPS",
              "EPS", "Earnings Per Share", "epsdiluted", "eps",
              "Diluted NI Availto Com Stockholders"])

    m["net_income_cagr_raw"] = ni_cagr
    m["eps_cagr_raw"]        = eps_cagr

    CAP = 0.40
    m["net_income_cagr"]    = min(ni_cagr,  CAP) if ni_cagr  is not None else None
    m["net_income_history"] = ni_hist
    m["ni_cagr_years"]      = ni_years
    m["eps_cagr"]           = min(eps_cagr, CAP) if eps_cagr is not None else None
    m["eps_cagr_years"]     = eps_years

    if ni_cagr and ni_cagr > CAP:
        print(f"  NI CAGR capped: raw={ni_cagr:.1%} -> {CAP:.0%}")
    if eps_cagr and eps_cagr > CAP:
        print(f"  EPS CAGR capped: raw={eps_cagr:.1%} -> {CAP:.0%}")

    return m


def _cross_validate_forward_pe(m, info):
    computed_forward_pe = None
    if m["current_price"] and m.get("forward_eps"):
        try:
            cp_val = float(m["current_price"])
            fe_val = float(m["forward_eps"])
            if fe_val > 0 and cp_val > 0:
                computed_forward_pe = round(cp_val / fe_val, 2)
        except Exception:
            pass

    api_forward_pe  = m.get("forward_pe")
    api_trailing_pe = m.get("trailing_pe")

    if computed_forward_pe is not None:
        print(f"  Forward PE: using computed {computed_forward_pe} "
              f"(API returned {api_forward_pe})")
        m["forward_pe"] = computed_forward_pe
    elif api_forward_pe is not None:
        try:
            fpe = float(api_forward_pe)
            tpe = float(api_trailing_pe) if api_trailing_pe else 0
            if fpe > 500:
                print(f"  Forward PE {fpe} exceeds 500x, discarding")
                m["forward_pe"] = None
            elif tpe > 0 and fpe > tpe * 1.5 and fpe > 100:
                print(f"  Forward PE {fpe} > 1.5x trailing PE {tpe}, using trailing")
                m["forward_pe"] = tpe
        except Exception:
            pass
    return m


def _compute_peg(m):
    """
    PEG ratio for reports/scenarios.

    v3 CHANGES:
    - When API trailing_eps diverges >30% from statement EPS, we already
      corrected it in calc(). So trailing_pe here is reliable.
    - Priority 2 (fwd/trail derived growth) capped at 30%
    - Priority 3 (historical CAGR) capped at 25% (unchanged)
    - PE > 200 rejected outright
    """
    m["peg_ratio"]           = None
    m["peg_growth_used"]     = None
    m["peg_growth_source"]   = None
    m["peg_growth_conflict"] = None

    try:
        pe = safe_float(m.get("forward_pe"))
        if pe <= 0:
            pe = safe_float(m.get("trailing_pe"))
        if pe <= 0:
            return m

        # Reject absurd PE
        if pe > 200:
            print(f"  PEG: PE={pe:.1f} exceeds 200x, PEG undefined")
            m["peg_growth_source"] = "pe_too_high"
            return m

        # Collect historical CAGR for comparison
        hist_cagr_raw = None
        if m.get("eps_cagr") and float(m["eps_cagr"]) > 0:
            hist_cagr_raw = float(m["eps_cagr"]) * 100
        elif m.get("net_income_cagr") and float(m["net_income_cagr"]) > 0:
            hist_cagr_raw = float(m["net_income_cagr"]) * 100
        m["peg_historical_cagr"] = round(hist_cagr_raw, 1) if hist_cagr_raw else None

        growth = None
        source = None

        # ── Priority 1: analyst forward consensus ─────────────
        if m.get("earnings_growth") is not None:
            g_val = float(m["earnings_growth"])
            g_pct = g_val * 100 if abs(g_val) < 1 else g_val

            if g_pct <= 0:
                print(f"  PEG: earnings_growth is {g_pct:.1f}% (negative) "
                      f"-- PEG undefined. Not falling through.")
                m["peg_growth_source"] = "earnings_growth_negative"
                m["peg_growth_used"]   = round(g_pct, 1)
                if hist_cagr_raw and hist_cagr_raw > 20:
                    m["peg_growth_conflict"] = (
                        f"Forward analyst growth ({g_pct:.1f}%) is negative "
                        f"but historical CAGR is {hist_cagr_raw:.1f}%. "
                        f"Trough distortion in historical data."
                    )
                return m

            growth = g_pct
            source = "earnings_growth"
            print(f"  PEG: using earnings_growth = {growth:.1f}%")

        # ── Priority 2: derived from forward_eps vs trailing_eps
        if growth is None:
            fwd   = safe_float(m.get("forward_eps"))
            trail = safe_float(m.get("trailing_eps"))
            if fwd > 0 and trail > 0 and trail != fwd:
                derived = ((fwd - trail) / abs(trail)) * 100
                if derived > 0:
                    # CAP at 30% — single-year fwd/trail is noisy
                    growth = min(derived, 30.0)
                    source = "fwd_trail_eps_derived"
                    if derived > 30.0:
                        print(f"  PEG: derived growth {derived:.1f}% "
                              f"capped to 30%")
                    else:
                        print(f"  PEG: derived growth = {growth:.1f}%")

        # ── Priority 3: historical EPS CAGR — capped at 25% ──
        if growth is None and hist_cagr_raw:
            growth = min(hist_cagr_raw, 25.0)
            source = "eps_cagr_historical"
            print(f"  PEG: using historical CAGR = {growth:.1f}% "
                  f"(capped at 25%)")

        if not growth or growth <= 0:
            print(f"  PEG: no usable growth rate available")
            return m

        # ── Conflict detection ────────────────────────────────
        if hist_cagr_raw and source != "eps_cagr_historical":
            divergence = abs(growth - hist_cagr_raw)
            if divergence > 20:
                conflict = (
                    f"Forward growth ({growth:.1f}%, {source}) diverges "
                    f"{divergence:.1f}pp from historical CAGR "
                    f"({hist_cagr_raw:.1f}%). Treat historical with caution."
                )
                m["peg_growth_conflict"] = conflict
                print(f"  PEG CONFLICT: {conflict}")

        # ── Compute PEG ───────────────────────────────────────
        peg = round(pe / growth, 2)
        m["peg_growth_used"]   = round(growth, 1)
        m["peg_growth_source"] = source

        if 0 < peg <= 5.0:
            m["peg_ratio"] = peg
            print(f"  PEG computed: {pe:.1f}x / {growth:.1f}% = {peg:.2f} "
                  f"(source: {source})")
        else:
            print(f"  PEG out of range ({peg:.2f}), discarding")

    except Exception as e:
        print(f"  PEG computation error: {e}")
    return m


def _check_growth_consistency(m):
    if "data_quality_warnings" not in m:
        m["data_quality_warnings"] = []

    rev_g  = m.get("revenue_growth")
    earn_g = m.get("earnings_growth")

    if rev_g is not None and earn_g is not None:
        try:
            rev_pct  = float(rev_g)  * 100 if abs(float(rev_g))  < 1 else float(rev_g)
            earn_pct = float(earn_g) * 100 if abs(float(earn_g)) < 1 else float(earn_g)
            divergence = abs(rev_pct - earn_pct)

            if divergence > 20:
                warning = (
                    f"DATA QUALITY WARNING: revenue_growth ({rev_pct:.1f}%) and "
                    f"earnings_growth ({earn_pct:.1f}%) diverge by {divergence:.1f}pp. "
                    f"Likely stale or scope-mismatched yfinance data."
                )
                m["data_quality_warnings"].append(warning)
                print(f"  {warning}")
        except Exception:
            pass

    hist_cagr = m.get("peg_historical_cagr")
    if hist_cagr and hist_cagr > 40:
        warning = (
            f"DATA QUALITY WARNING: historical EPS CAGR is {hist_cagr:.1f}% "
            f"-- extremely high, almost certainly trough distortion."
        )
        m["data_quality_warnings"].append(warning)
        print(f"  {warning}")

    # v3: Also flag when statement EPS diverges from API EPS
    stmt_eps = m.get("stmt_trailing_eps")
    api_eps  = m.get("trailing_eps")
    if stmt_eps and api_eps:
        try:
            div = abs(float(api_eps) - float(stmt_eps)) / abs(float(stmt_eps))
            if div > 0.30:
                warning = (
                    f"DATA QUALITY WARNING: API trailing EPS ({float(api_eps):.2f}) "
                    f"diverges {div:.0%} from statement EPS ({float(stmt_eps):.2f}). "
                    f"Statement EPS used as source of truth."
                )
                m["data_quality_warnings"].append(warning)
        except Exception:
            pass

    return m


def _compute_price_history(m, data):
    h = data.get("hist")
    if h is not None and not h.empty:
        try:
            c = h["Close"]
            m["price_5y_return"] = round(((c.iloc[-1] / c.iloc[0]) - 1) * 100, 2)
            m["price_5y_high"]   = round(float(c.max()), 2)
            m["price_5y_low"]    = round(float(c.min()), 2)
        except Exception:
            m["price_5y_return"] = m["price_5y_high"] = m["price_5y_low"] = None
    else:
        m["price_5y_return"] = m["price_5y_high"] = m["price_5y_low"] = None
    return m


# ══════════════════════════════════════════════════════════════
# PROBABILITY ENGINE v2 (unchanged — signal-derived, bottoms-up)
# ══════════════════════════════════════════════════════════════

def compute_scenario_probabilities(metrics, llm_output=None):
    rev_cagr      = safe_float(metrics.get("revenue_cagr",     0))
    eps_cagr      = safe_float(metrics.get("eps_cagr",
                    metrics.get("net_income_cagr",             0)))
    op_margin     = safe_float(metrics.get("operating_margin", 0))
    forward_eps   = safe_float(metrics.get("forward_eps",      0))
    trailing_eps  = safe_float(metrics.get("trailing_eps",     0))
    de_ratio      = safe_float(metrics.get("debt_to_equity",   1.0))
    peg           = safe_float(metrics.get("peg_ratio",        0))
    beta          = safe_float(metrics.get("beta",             1.0))
    current_price = safe_float(metrics.get("current_price",    0))
    ma_200        = safe_float(metrics.get("ma_200",           0))

    bull_score  = 50.0
    signal_log  = []

    # Signal 1: EPS revision momentum (+-15)
    if forward_eps > 0 and trailing_eps > 0:
        eps_revision = (forward_eps - trailing_eps) / abs(trailing_eps)
        delta = max(-15.0, min(15.0, eps_revision * 50.0))
        bull_score += delta
        signal_log.append({
            "signal": "EPS revision momentum",
            "value":  round(eps_revision, 3),
            "delta":  round(delta, 1),
            "note":   f"fwd={forward_eps:.2f} vs trail={trailing_eps:.2f}",
        })
    else:
        signal_log.append({
            "signal": "EPS revision momentum",
            "value":  None, "delta": 0.0,
            "note":   "Insufficient EPS data",
        })

    # Signal 2: Revenue growth trajectory (+-15)
    if rev_cagr >= 0.25:
        rev_delta = 15.0
    elif rev_cagr >= 0.15:
        rev_delta = 10.0
    elif rev_cagr >= 0.08:
        rev_delta = 5.0
    elif rev_cagr >= 0.02:
        rev_delta = 0.0
    elif rev_cagr >= -0.05:
        rev_delta = -8.0
    else:
        rev_delta = -15.0
    bull_score += rev_delta
    signal_log.append({
        "signal": "Revenue CAGR",
        "value":  round(rev_cagr, 3),
        "delta":  rev_delta,
        "note":   f"{rev_cagr*100:.1f}%",
    })

    # Signal 3: EPS / earnings growth trajectory (+-12)
    if eps_cagr >= 0.25:
        eps_delta = 12.0
    elif eps_cagr >= 0.15:
        eps_delta = 8.0
    elif eps_cagr >= 0.05:
        eps_delta = 4.0
    elif eps_cagr >= 0:
        eps_delta = 0.0
    elif eps_cagr >= -0.10:
        eps_delta = -6.0
    else:
        eps_delta = -12.0
    bull_score += eps_delta
    signal_log.append({
        "signal": "EPS / NI CAGR",
        "value":  round(eps_cagr, 3),
        "delta":  eps_delta,
        "note":   f"{eps_cagr*100:.1f}%",
    })

    # Signal 4: Operating margin quality (+-12)
    if op_margin >= 0.30:
        margin_delta = 12.0
    elif op_margin >= 0.20:
        margin_delta = 7.0
    elif op_margin >= 0.10:
        margin_delta = 3.0
    elif op_margin >= 0.05:
        margin_delta = 0.0
    elif op_margin >= 0:
        margin_delta = -5.0
    else:
        margin_delta = -12.0
    bull_score += margin_delta
    signal_log.append({
        "signal": "Operating margin",
        "value":  round(op_margin, 3),
        "delta":  margin_delta,
        "note":   f"{op_margin*100:.1f}%",
    })

    # Signal 5: Valuation / PEG (+-12)
    if peg > 0:
        if peg <= 0.75:
            peg_delta = 12.0
        elif peg <= 1.25:
            peg_delta = 7.0
        elif peg <= 2.00:
            peg_delta = 2.0
        elif peg <= 3.00:
            peg_delta = -4.0
        else:
            peg_delta = -12.0
        bull_score += peg_delta
        signal_log.append({
            "signal": "PEG ratio",
            "value":  round(peg, 2),
            "delta":  peg_delta,
            "note":   f"{peg:.2f}x",
        })
    else:
        signal_log.append({
            "signal": "PEG ratio",
            "value":  None, "delta": 0.0,
            "note":   "PEG not available -- neutral",
        })

    # Signal 6: Balance sheet risk (+-8)
    if de_ratio <= 0:
        de_delta = 5.0
    elif de_ratio <= 0.30:
        de_delta = 5.0
    elif de_ratio <= 0.80:
        de_delta = 2.0
    elif de_ratio <= 1.50:
        de_delta = 0.0
    elif de_ratio <= 2.50:
        de_delta = -5.0
    else:
        de_delta = -8.0
    bull_score += de_delta
    signal_log.append({
        "signal": "Debt/Equity",
        "value":  round(de_ratio, 2),
        "delta":  de_delta,
        "note":   f"{de_ratio:.2f}x",
    })

    # Signal 7: Price vs 200-day MA (+-6)
    if current_price > 0 and ma_200 > 0:
        ma_ratio = current_price / ma_200
        if ma_ratio >= 1.10:
            ma_delta = 6.0
        elif ma_ratio >= 1.00:
            ma_delta = 3.0
        elif ma_ratio >= 0.90:
            ma_delta = -2.0
        else:
            ma_delta = -6.0
        bull_score += ma_delta
        signal_log.append({
            "signal": "Price vs 200-day MA",
            "value":  round(ma_ratio, 3),
            "delta":  ma_delta,
            "note":   f"price={current_price:.1f} / MA200={ma_200:.1f}",
        })
    else:
        signal_log.append({
            "signal": "Price vs 200-day MA",
            "value":  None, "delta": 0.0,
            "note":   "MA data unavailable -- neutral",
        })

    # Signal 8: Beta / volatility (+-5)
    if beta > 0:
        if beta >= 2.0:
            beta_delta = -5.0
        elif beta >= 1.5:
            beta_delta = -3.0
        elif beta >= 1.0:
            beta_delta = 0.0
        elif beta >= 0.6:
            beta_delta = 2.0
        else:
            beta_delta = 4.0
        bull_score += beta_delta
        signal_log.append({
            "signal": "Beta",
            "value":  round(beta, 2),
            "delta":  beta_delta,
            "note":   f"beta={beta:.2f}",
        })
    else:
        signal_log.append({
            "signal": "Beta",
            "value":  None, "delta": 0.0,
            "note":   "Beta unavailable -- neutral",
        })

    # Clamp and map
    bull_score = max(5.0, min(95.0, bull_score))

    raw_bull = (bull_score / 100.0) * 0.45
    raw_bear = ((100.0 - bull_score) / 100.0) * 0.50
    raw_base = max(0.30, 1.0 - raw_bull - raw_bear)

    total = raw_bull + raw_base + raw_bear
    final_bull = round(raw_bull / total, 3)
    final_base = round(raw_base / total, 3)
    final_bear = round(1.0 - final_bull - final_base, 3)

    print(f"  Probability engine v2: bull_score={bull_score:.1f} | "
          f"bull={final_bull:.2%}, base={final_base:.2%}, bear={final_bear:.2%}")

    return {
        "bull":          final_bull,
        "base":          final_base,
        "bear":          final_bear,
        "method":        "signal_derived_v2",
        "bull_score":    round(bull_score, 1),
        "signal_detail": signal_log,
        "raw_geometric":             {"bull": round(raw_bull, 4), "bear": round(raw_bear, 4)},
        "correlation_multipliers":   {"bull": 1.0, "bear": 1.0},
        "driver_detail":             [],
    }


# ══════════════════════════════════════════════════════════════
# HEADWIND / TAILWIND EPS STAMPER (unchanged)
# ══════════════════════════════════════════════════════════════

def stamp_headwind_tailwind_eps(llm_output, scenario_results, shares, op_margin, tax_rate=0.21):
    hw_items = llm_output.get("headwinds", [])
    tw_items = llm_output.get("tailwinds", [])

    for items in [hw_items, tw_items]:
        for item in items:
            rev = safe_float(item.get("revenue_at_risk") or item.get("revenue_opportunity") or 0)
            if rev == 0 or shares == 0 or op_margin == 0:
                item["bull_eps_impact"] = 0.0
                item["base_eps_impact"] = 0.0
                item["bear_eps_impact"] = 0.0
                continue
            for sname in ["bull", "base", "bear"]:
                s = scenario_results.get(sname, {})
                s_margin = s.get("operating_margin", op_margin)
                eps = round((rev * s_margin * (1 - tax_rate)) / shares, 2)
                item[f"{sname}_eps_impact"] = eps


# ══════════════════════════════════════════════════════════════
# SCENARIO MATH ENGINE (unchanged except _detect_gaap_suppression)
# ══════════════════════════════════════════════════════════════

def _sum_item_eps(items):
    total = 0.0
    for item in (items or []):
        val = safe_float(item.get("eps_impact", item.get("eps_delta", 0)))
        total += val
    return total


def _stamp_item_eps(items, scenario_key, shares, operating_margin, tax_rate, total_revenue):
    for item in (items or []):
        rev_field = (item.get("revenue_at_risk") or item.get("revenue_opportunity") or 0)
        rev = safe_float(rev_field)
        if rev == 0 or shares == 0 or operating_margin == 0:
            item[f"{scenario_key}_eps_impact"] = 0.0
            continue
        eps_impact = round((rev * operating_margin * (1 - tax_rate)) / shares, 2)
        item[f"{scenario_key}_eps_impact"] = eps_impact


def _detect_gaap_suppression(python_eps, llm_eps, forward_eps, trailing_eps):
    if forward_eps <= 0 or trailing_eps <= 0:
        return False, 1.0

    py_below  = python_eps  > 0 and python_eps  < forward_eps * 0.60
    llm_below = (llm_eps <= 0) or (llm_eps < forward_eps * 0.60)

    if not (py_below and llm_below):
        return False, 1.0

    non_gaap_ratio = forward_eps / trailing_eps
    if non_gaap_ratio < 1.3:
        return False, 1.0

    non_gaap_ratio = min(non_gaap_ratio, 4.0)
    return True, non_gaap_ratio


def _apply_pe_guardrails(pe_mult, scenario_name, anchor_pe):
    if anchor_pe <= 0:
        return max(3.0, min(pe_mult, 80.0))

    if scenario_name == "bull":
        lo, hi = anchor_pe * 0.90, anchor_pe * 1.60
    elif scenario_name == "base":
        lo, hi = anchor_pe * 0.75, anchor_pe * 1.25
    else:
        lo, hi = anchor_pe * 0.40, anchor_pe * 1.00

    clamped = max(lo, min(pe_mult, hi))
    if clamped != pe_mult:
        print(f"  PE guardrail [{scenario_name}]: LLM={pe_mult:.1f}x "
              f"-> clamped to {clamped:.1f}x "
              f"(band {lo:.1f}x - {hi:.1f}x, anchor={anchor_pe:.1f}x)")
    return clamped


def _compute_single_scenario(s, scenario_name, scenario_probs, current_price,
                              trailing_eps, forward_eps, total_revenue, shares,
                              operating_margin, profit_margin, fcf_margin,
                              anchor_pe=0):
    try:
        prob     = scenario_probs.get(scenario_name, 0.20)
        tax_rate = safe_float(s.get("tax_rate"), default=0.21)

        segment_builds        = s.get("segment_builds", [])
        segment_revenue_total = sum(safe_float(seg.get("projected_revenue"))
                                    for seg in segment_builds)

        hw_items = s.get("headwinds", [])
        tw_items = s.get("tailwinds", [])

        hw_revenue      = safe_float(s.get("total_headwind_revenue"))
        tw_revenue      = safe_float(s.get("total_tailwind_revenue"))
        hw_eps_scenario = safe_float(s.get("total_headwind_eps"))
        tw_eps_scenario = safe_float(s.get("total_tailwind_eps"))
        hw_eps_items    = _sum_item_eps(hw_items)
        tw_eps_items    = _sum_item_eps(tw_items)

        hw_eps = hw_eps_scenario if hw_eps_scenario != 0 else hw_eps_items
        tw_eps = tw_eps_scenario if tw_eps_scenario != 0 else tw_eps_items

        llm_total_revenue    = safe_float(s.get("total_revenue"))
        python_total_revenue = segment_revenue_total + hw_revenue + tw_revenue

        if python_total_revenue > 0:
            total_rev = python_total_revenue
        elif llm_total_revenue > 0:
            total_rev = llm_total_revenue
        else:
            total_rev = total_revenue

        if llm_total_revenue > 0 and python_total_revenue > 0:
            rev_diff = abs(python_total_revenue - llm_total_revenue) / llm_total_revenue
            if rev_diff > 0.05:
                print(f"  {scenario_name}: Revenue discrepancy -- "
                      f"Python={python_total_revenue:.0f}, LLM={llm_total_revenue:.0f} "
                      f"({rev_diff*100:.1f}% diff)")

        rev_growth = ((total_rev / total_revenue) - 1) if total_revenue > 0 else 0.0

        llm_op_margin    = safe_float(s.get("operating_margin"))
        llm_net_margin   = safe_float(s.get("net_margin"))
        margin_rationale = clean_latex(s.get("margin_rationale", ""))

        if operating_margin > 0 and llm_op_margin > 0:
            margin_ratio = llm_op_margin / operating_margin
            if margin_ratio > 3.0 or margin_ratio < 0.1:
                llm_op_margin = max(operating_margin * 0.3,
                                    min(llm_op_margin, operating_margin * 2.5))

        op_margin_s  = llm_op_margin  if llm_op_margin  > 0 else operating_margin
        net_margin = llm_net_margin if llm_net_margin > 0 else profit_margin

        if net_margin == 0 and op_margin_s > 0:
            net_margin = op_margin_s * (1 - tax_rate)
        if op_margin_s > 0 and net_margin > op_margin_s:
            net_margin = op_margin_s * (1 - tax_rate)

        # EPS computation
        if total_rev > 0 and net_margin > 0 and shares > 0:
            python_eps = (total_rev * net_margin) / shares
        elif total_rev > 0 and op_margin_s > 0 and shares > 0:
            python_eps = (total_rev * op_margin_s * (1 - tax_rate)) / shares
        else:
            python_eps = 0.0

        llm_eps  = safe_float(s.get("projected_eps"))
        eps_flag = None

        gaap_suppressed, non_gaap_ratio = _detect_gaap_suppression(
            python_eps, llm_eps, forward_eps, trailing_eps)

        if gaap_suppressed:
            scenario_margin_ratio = (llm_op_margin / operating_margin
                                     if operating_margin > 0 and llm_op_margin > 0
                                     else 1.0)
            scenario_margin_ratio = max(0.50, min(2.0, scenario_margin_ratio))
            final_eps = forward_eps * (1 + rev_growth) * scenario_margin_ratio
            eps_flag  = (
                f"GAAP EPS suppressed by acquisition amortisation "
                f"(Python GAAP={python_eps:.2f}, LLM={llm_eps:.2f}, "
                f"forward_eps non-GAAP consensus={forward_eps:.2f}). "
                f"Scaled to non-GAAP using forward_eps x rev_growth "
                f"({1+rev_growth:.2f}x) x margin ratio ({scenario_margin_ratio:.2f}x) "
                f"= {final_eps:.2f}."
            )
            print(f"  {scenario_name}: {eps_flag}")

        elif python_eps > 0 and llm_eps > 0:
            eps_diff = abs(python_eps - llm_eps) / llm_eps
            if eps_diff > 0.10:
                if forward_eps > 0:
                    py_dist  = abs(python_eps - forward_eps) / forward_eps
                    llm_dist = abs(llm_eps    - forward_eps) / forward_eps
                    if llm_dist < py_dist and llm_dist < 0.40:
                        final_eps = llm_eps
                        eps_flag  = (
                            f"LLM EPS ({llm_eps:.2f}) closer to forward consensus "
                            f"({forward_eps:.2f}) than Python EPS ({python_eps:.2f}). "
                            f"Using LLM."
                        )
                        print(f"  {scenario_name}: {eps_flag}")
                    else:
                        final_eps = python_eps
                        eps_flag  = (
                            f"Python EPS ({python_eps:.2f}) differs from "
                            f"LLM EPS ({llm_eps:.2f}) by {eps_diff*100:.1f}%. "
                            f"Using Python."
                        )
                        print(f"  {scenario_name}: {eps_flag}")
                else:
                    final_eps = python_eps
                    eps_flag  = (
                        f"Python EPS ({python_eps:.2f}) differs from "
                        f"LLM EPS ({llm_eps:.2f}) by {eps_diff*100:.1f}%. "
                        f"Using Python."
                    )
                    print(f"  {scenario_name}: {eps_flag}")
            else:
                final_eps = python_eps

        elif python_eps > 0:
            final_eps = python_eps
        elif llm_eps > 0:
            final_eps = llm_eps
            eps_flag  = "Python could not compute EPS. Using LLM."
        else:
            final_eps = trailing_eps * (1 + rev_growth) if trailing_eps > 0 else 0
            eps_flag  = "Both computations failed. Using trailing EPS grown by revenue growth."

        # ── EPS SANITY CHECK (v3) ─────────────────────────────
        # If final_eps is >3x trailing, something is likely wrong.
        # Clamp to 3x trailing and flag.
        if trailing_eps > 0 and final_eps > trailing_eps * 3.0:
            old_eps = final_eps
            final_eps = trailing_eps * 3.0
            eps_flag = (
                f"EPS CLAMPED: computed {old_eps:.2f} was >3x trailing "
                f"({trailing_eps:.2f}). Clamped to {final_eps:.2f}. "
                f"Original flag: {eps_flag or 'none'}"
            )
            print(f"  {scenario_name}: {eps_flag}")

        # Price target
        raw_pe_mult  = max(safe_float(s.get("pe_multiple"), default=20.0), 3.0)
        pe_mult      = _apply_pe_guardrails(raw_pe_mult, scenario_name, anchor_pe)
        pe_rationale = clean_latex(s.get("pe_rationale", ""))
        price_target = final_eps * pe_mult
        implied_return = ((price_target - current_price) / current_price
                          if current_price > 0 else 0.0)
        breakeven_pe = (current_price / final_eps) if final_eps > 0 else None

        fcf_yield_at_target = None
        if fcf_margin > 0 and total_rev > 0 and price_target > 0 and shares > 0:
            implied_market_cap  = price_target * shares
            projected_fcf       = total_rev * fcf_margin
            fcf_yield_at_target = projected_fcf / implied_market_cap

        _stamp_item_eps(hw_items, scenario_name, shares, op_margin_s, tax_rate, total_rev)
        _stamp_item_eps(tw_items, scenario_name, shares, op_margin_s, tax_rate, total_rev)
        s["headwinds"] = hw_items
        s["tailwinds"] = tw_items

        return {
            "probability":            round(prob, 4),
            "segment_builds":         segment_builds,
            "segment_revenue_total":  round(segment_revenue_total, 0),
            "total_headwind_revenue": round(hw_revenue, 0),
            "total_headwind_eps":     round(hw_eps, 2),
            "total_tailwind_revenue": round(tw_revenue, 0),
            "total_tailwind_eps":     round(tw_eps, 2),
            "total_revenue":          round(total_rev, 0),
            "revenue_growth":         round(rev_growth, 4),
            "operating_margin":       round(op_margin_s, 4),
            "net_margin":             round(net_margin, 4),
            "margin_rationale":       margin_rationale,
            "projected_eps":          round(final_eps, 2),
            "llm_eps":                round(llm_eps, 2) if llm_eps else None,
            "eps_flag":               eps_flag,
            "pe_multiple":            round(pe_mult, 1),
            "pe_multiple_raw_llm":    round(raw_pe_mult, 1),
            "pe_rationale":           pe_rationale,
            "price_target":           round(price_target, 2),
            "implied_return":         round(implied_return, 4),
            "breakeven_pe":           round(breakeven_pe, 2) if breakeven_pe else None,
            "fcf_yield_at_target":    round(fcf_yield_at_target, 4) if fcf_yield_at_target else None,
            "narrative":              clean_latex(s.get("narrative", "")),
        }

    except Exception as e:
        print(f"  Scenario {scenario_name} math error: {e}")
        return {
            "probability":            scenario_probs.get(scenario_name, 0.20),
            "segment_builds":         [], "segment_revenue_total": 0,
            "total_headwind_revenue": 0,  "total_headwind_eps":    0,
            "total_tailwind_revenue": 0,  "total_tailwind_eps":    0,
            "total_revenue":          0,  "revenue_growth":        0,
            "operating_margin":       0,  "net_margin":            0,
            "margin_rationale":       "", "projected_eps":         0,
            "llm_eps":                None, "eps_flag":            str(e),
            "pe_multiple":            0,  "pe_multiple_raw_llm":   0,
            "pe_rationale":           "",
            "price_target":           0,  "implied_return":        0,
            "breakeven_pe":           None, "fcf_yield_at_target": None,
            "narrative":              str(e),
        }


# ══════════════════════════════════════════════════════════════
# SENSITIVITY TABLE (unchanged)
# ══════════════════════════════════════════════════════════════

def compute_sensitivity_table(base_scenario, current_price):
    base_eps    = safe_float(base_scenario.get("projected_eps",   0))
    base_pe     = safe_float(base_scenario.get("pe_multiple",     0))
    base_margin = safe_float(base_scenario.get("net_margin",      0))

    if base_eps <= 0 or base_pe <= 0:
        return {"rows": [], "base_eps": base_eps,
                "base_pe": base_pe, "base_net_margin": base_margin}

    margin_deltas = [-0.04, -0.02, -0.01, 0.0, +0.01, +0.02, +0.04]
    pe_deltas     = [-8,    -4,     -2,   0,    +2,    +4,    +8   ]

    rows = []
    for md in margin_deltas:
        if base_margin > 0:
            margin_factor = (base_margin + md) / base_margin
        else:
            margin_factor = 1.0
        margin_factor = max(0.0, margin_factor)
        adj_eps = base_eps * margin_factor

        for pd in pe_deltas:
            adj_pe = max(3.0, base_pe + pd)
            adj_pt = round(adj_eps * adj_pe, 2)
            adj_ret = round((adj_pt - current_price) / current_price, 4) \
                      if current_price > 0 else 0.0
            rows.append({
                "margin_delta":    md,
                "pe_delta":        pd,
                "adj_eps":         round(adj_eps, 2),
                "adj_pe":          round(adj_pe, 1),
                "price_target":    adj_pt,
                "implied_return":  adj_ret,
            })

    return {
        "rows":             rows,
        "base_eps":         round(base_eps,    2),
        "base_pe":          round(base_pe,     1),
        "base_net_margin":  round(base_margin, 4),
        "margin_deltas":    margin_deltas,
        "pe_deltas":        pe_deltas,
    }


# ══════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

def compute_scenario_math(metrics, llm_output):
    current_price    = safe_float(metrics.get("current_price"))
    trailing_eps     = safe_float(metrics.get("trailing_eps"))
    forward_eps      = safe_float(metrics.get("forward_eps"))
    total_revenue    = safe_float(metrics.get("total_revenue"))
    shares           = safe_float(metrics.get("shares_outstanding"))
    operating_margin = safe_float(metrics.get("operating_margin"))
    profit_margin    = safe_float(metrics.get("profit_margin"))
    market_cap       = safe_float(metrics.get("market_cap"))
    trailing_pe      = safe_float(metrics.get("trailing_pe"))
    forward_pe       = safe_float(metrics.get("forward_pe"))
    free_cashflow    = safe_float(metrics.get("free_cashflow"))
    risk_free_rate   = 0.06

    if shares == 0 and current_price > 0 and market_cap > 0:
        shares = market_cap / current_price

    if forward_eps <= 0 and forward_pe > 0 and current_price > 0:
        forward_eps = round(current_price / forward_pe, 2)
        print(f"  forward_eps derived from price/forward_pe: {forward_eps:.2f}")

    fcf_margin = (free_cashflow / total_revenue) if total_revenue > 0 and free_cashflow > 0 else 0.0
    anchor_pe  = forward_pe if forward_pe > 0 else (trailing_pe if trailing_pe > 0 else 0)

    print(f"  Scenario math inputs: price={current_price}, trailing_eps={trailing_eps:.2f}, "
          f"forward_eps={forward_eps:.2f}, shares={shares:.0f}, "
          f"op_margin={operating_margin:.3f}, net_margin={profit_margin:.3f}, "
          f"fcf_margin={fcf_margin:.3f}, anchor_pe={anchor_pe:.1f}")

    prob_output    = compute_scenario_probabilities(metrics, llm_output)
    scenario_probs = {
        "bull": prob_output["bull"],
        "base": prob_output["base"],
        "bear": prob_output["bear"],
    }

    scenarios_input = llm_output.get("scenarios", {})
    results = {}
    for sname in ["bull", "base", "bear"]:
        s = scenarios_input.get(sname, {})
        if not s:
            continue
        results[sname] = _compute_single_scenario(
            s, sname, scenario_probs, current_price,
            trailing_eps, forward_eps, total_revenue, shares,
            operating_margin, profit_margin, fcf_margin,
            anchor_pe=anchor_pe)

    # Aggregates
    expected_value  = sum(r["price_target"] * r["probability"] for r in results.values())
    expected_return = ((expected_value - current_price) / current_price
                       if current_price > 0 else 0)
    variance = sum(r["probability"] * (r["implied_return"] - expected_return) ** 2
                   for r in results.values())
    std_dev        = variance ** 0.5
    risk_adj_score = ((expected_return - risk_free_rate) / std_dev if std_dev > 0 else 0)

    upside_return   = sum(r["implied_return"] * r["probability"]
                          for r in results.values() if r["implied_return"] > 0)
    downside_return = sum(r["implied_return"] * r["probability"]
                          for r in results.values() if r["implied_return"] < 0)
    upside_downside_ratio = (abs(upside_return / downside_return)
                             if downside_return != 0 else float("inf"))
    prob_positive = sum(r["probability"] for r in results.values()
                        if r["price_target"] > current_price)

    bear = results.get("bear", {})

    stamp_headwind_tailwind_eps(llm_output, results, shares, operating_margin)

    sensitivity_table = compute_sensitivity_table(
        results.get("base", {}), current_price)

    return {
        "scenarios":              results,
        "scenario_probabilities": prob_output,
        "expected_value":         round(expected_value, 2),
        "expected_return":        round(expected_return, 4),
        "std_dev":                round(std_dev, 4),
        "risk_adjusted_score":    round(risk_adj_score, 2),
        "upside_downside_ratio":  round(upside_downside_ratio, 2),
        "prob_positive_return":   round(prob_positive, 4),
        "max_drawdown_prob":      round(bear.get("probability", 0), 4),
        "max_drawdown_magnitude": round(bear.get("implied_return", 0), 4),
        "risk_free_rate":         risk_free_rate,
        "anchor_pe":              anchor_pe,
        "trailing_eps_used":      round(trailing_eps, 2),
        "forward_eps_used":       round(forward_eps, 2),
        "fcf_margin_used":        round(fcf_margin, 4),
        "market_expectations":    llm_output.get("market_expectations", {}),
        "sensitivity":            llm_output.get("sensitivity", {}),
        "sensitivity_table":      sensitivity_table,
    }


# ══════════════════════════════════════════════════════════════
# POST-SCENARIO VALIDATION GATE (v3 — new)
# ══════════════════════════════════════════════════════════════

def validate_post_scenario(metrics, scenario_results):
    """
    After the scenario engine runs, check whether the stock still
    passes fundamental quality checks.

    Called by app.py / pipeline AFTER compute_scenario_math.
    Returns (passes: bool, reasons: list[str]).

    This function is the "throw out the possibility" gate.
    It exists because the scenario engine can reveal problems
    that the initial metrics alone could not:
    - Base case shows negative return (stock is overvalued NOW)
    - Expected return is negative (bad risk/reward)
    - Scenario EPS was clamped (LLM hallucinated margins)
    - Risk-adjusted score is negative (not enough reward for the risk)
    """
    reasons = []

    scenarios = scenario_results.get("scenarios", {})
    base = scenarios.get("base", {})
    bull = scenarios.get("bull", {})
    bear = scenarios.get("bear", {})

    if not base:
        reasons.append("No base scenario computed")
        return False, reasons

    # ── Check 1: Base-case return ─────────────────────────────
    base_return = safe_float(base.get("implied_return", 0))
    if base_return < -0.05:
        reasons.append(
            f"Base-case implies {base_return:.1%} return. "
            f"Stock appears overvalued at current price."
        )

    # ── Check 2: Expected return must be positive ─────────────
    expected_return = safe_float(scenario_results.get("expected_return", 0))
    if expected_return < 0:
        reasons.append(
            f"Probability-weighted expected return is negative "
            f"({expected_return:.1%})."
        )

    # ── Check 3: Risk-adjusted score ──────────────────────────
    risk_adj = safe_float(scenario_results.get("risk_adjusted_score", 0))
    if risk_adj < 0:
        reasons.append(
            f"Risk-adjusted score is negative ({risk_adj:.2f}). "
            f"Expected return does not compensate for volatility."
        )

    # ── Check 4: EPS sanity ───────────────────────────────────
    trailing_eps = safe_float(metrics.get("trailing_eps", 0))
    base_eps = safe_float(base.get("projected_eps", 0))
    if trailing_eps > 0 and base_eps > trailing_eps * 3.0:
        reasons.append(
            f"Base-case EPS ({base_eps:.2f}) is >3x trailing "
            f"({trailing_eps:.2f}). Likely overestimated."
        )

    # ── Check 5: EPS was clamped (flag from scenario engine) ──
    base_flag = base.get("eps_flag") or ""
    if "EPS CLAMPED" in base_flag:
        reasons.append(
            f"Base-case EPS was clamped by sanity check: {base_flag[:120]}"
        )

    passes = len(reasons) == 0

    if passes:
        print(f"  Post-scenario validation: PASS")
    else:
        print(f"  Post-scenario validation: FAIL")
        for r in reasons:
            print(f"    - {r}")

    return passes, reasons


# ══════════════════════════════════════════════════════════════
# QGLP SCORING (shared utility — used by both screener and compute)
# ══════════════════════════════════════════════════════════════

def compute_qglp_score(metrics):
    score = 0.0

    # PEG -- 30 pts
    peg = metrics.get("peg_ratio", 999)
    if peg and peg > 0:
        score += max(0, min(30, 30 * (1 - (peg - 0.5) / 1.5)))

    # ROE -- 25 pts
    roe = metrics.get("roe", 0)
    if roe and roe > 0:
        score += max(0, min(25, 25 * (roe / 0.30)))

    # Earnings CAGR -- 25 pts
    cagr = (metrics.get("eps_cagr")
            or metrics.get("net_income_cagr")
            or metrics.get("revenue_cagr")
            or metrics.get("earnings_cagr")
            or 0)
    if cagr and cagr > 0:
        score += max(0, min(25, 25 * (cagr / 0.25)))

    # FCF yield -- 10 pts
    fcf_y = metrics.get("fcf_yield", 0)
    if fcf_y and fcf_y > 0:
        score += max(0, min(10, 10 * (fcf_y / 0.05)))

    # Debt/equity -- 10 pts
    de = metrics.get("debt_to_equity", metrics.get("debt_equity"))
    if de is not None and de >= 0:
        score += max(0, min(10, 10 * (1 - de)))

    return round(score, 1)
