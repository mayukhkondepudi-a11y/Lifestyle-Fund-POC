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
# v3 METHODOLOGY CALIBRATION CONSTANTS  (§7.3 + C2)
# Changing any constant requires regenerating the AVGO regression fixture.
# ══════════════════════════════════════════════════════════════

# Correlation multipliers (§8.3) — weight independent driver probs into joint probs
BULL_CORRELATION_MULTIPLIER = 3.0
BEAR_CORRELATION_MULTIPLIER = 4.5

# PEG-anchored P/E band (§7)
PEG_FLOOR_BULL   = 0.7
PEG_CEILING_BULL = 1.0
PEG_BASE_LOW     = 1.3
PEG_BASE_HIGH    = 1.7

# Bear P/E floors (B3: conditional on FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR)
BEAR_PE_NOMINAL_FLOOR = 25.0
BEAR_PE_STRESS_FLOOR  = 15.0

# Consensus backstop calibration (B2)
ANALYST_CONSENSUS_BULL_FLOOR_FRAC = 0.95   # bull EPS ≥ 95% of consensus high
ANALYST_CONSENSUS_HARD_GAP_FRAC   = 0.75   # bear EPS ≤ 75% of consensus low

# DCF defaults
DEFAULT_TAX_RATE            = 0.21
DEFAULT_TERMINAL_GROWTH     = 0.04
DEFAULT_RISK_FREE_RATE      = 0.045
DEFAULT_EQUITY_RISK_PREMIUM = 0.055

# C2 — named calibration switches
FRANCHISE_QUALITY_REQUIRED_FOR_BEAR_FLOOR = True   # B3: bear floor only for quality franchises
SHARE_COUNT_PROJECTION = "trailing_net_change"      # B4: shares evolve via trailing dilution rate
HEADLINE_METRIC = "implied_fcf_cagr"                # B1: reverse-DCF leads the report

# C3 — global LLM call ceiling per pipeline run
# Pass1 uses ≤2, catalysts fallback uses ≤1, Pass2 uses ≤2, Pass3 uses ≤1, bull-below retry uses ≤1 = 7 total.
MAX_PIPELINE_AI_CALLS = 7


# ══════════════════════════════════════════════════════════════
# LATEX SANITIZER (unchanged)
# ══════════════════════════════════════════════════════════════

def clean_latex(text):
    """Escape dollar-sign currency amounts so Streamlit doesn't parse them as LaTeX."""
    if not text or not isinstance(text, str):
        return text
    # First: escape $NUMBER patterns (currency) → \$NUMBER
    # This catches $7.8B, $1,500, $41.22, $3,200/oz etc.
    text = re.sub(r'\$(\d)', r'\\$\1', text)
    # Then strip any actual LaTeX the LLM injected
    text = re.sub(r'\\\((.+?)\\\)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
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

def _compute_base_fcf(data):
    """
    Compute trailing FCF from cash flow statement.
    More reliable than info["freeCashflow"] which is inconsistently
    populated by yfinance, especially for non-US listings.
    Returns float or None.
    """
    cf = data.get("cf")
    if cf is not None and not cf.empty:
        def _cf_row(labels):
            for lb in labels:
                if lb in cf.index:
                    row = cf.loc[lb].dropna().sort_index()
                    if not row.empty:
                        return float(row.iloc[-1])
            return None

        op_cf = _cf_row([
            "Operating Cash Flow", "Cash Flow From Operations",
            "Total Cash From Operating Activities",
            "Net Cash Provided By Operating Activities",
        ])
        capex = _cf_row([
            "Capital Expenditure", "Purchase Of Plant And Equipment",
            "Capital Expenditures", "Purchases Of Property Plant And Equipment",
            "Capital Expenditure Reported",
        ])

        if op_cf is not None and capex is not None:
            # capex is negative in most statements
            fcf = op_cf + capex if capex < 0 else op_cf - capex
            print(f"  FCF computed from statements: op_cf={op_cf:.0f}, "
                  f"capex={capex:.0f}, fcf={fcf:.0f}")
            return fcf
        elif op_cf is not None:
            print(f"  FCF: no capex row found, using operating CF={op_cf:.0f} as proxy")
            return op_cf

    # Fallback to info field
    info_fcf = safe_float(data.get("info", {}).get("freeCashflow", 0))
    if info_fcf != 0:
        print(f"  FCF: falling back to info['freeCashflow']={info_fcf:.0f}")
        return info_fcf

    return None


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

    # FCF yield — computed once here; updated below after statement FCF override
    try:
        m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"]) \
            if m["free_cashflow"] and m["market_cap"] else None
    except Exception:
        m["fcf_yield"] = None

    # ── Computed FCF from statements (more reliable than info field) ──
    computed_fcf = _compute_base_fcf(data)
    if computed_fcf is not None and computed_fcf > 0:
        info_fcf = safe_float(m.get("free_cashflow", 0))
        if info_fcf and info_fcf != 0:
            divergence = abs(computed_fcf - info_fcf) / abs(info_fcf)
            if divergence > 0.20:
                print(f"  FCF DIVERGENCE: info={info_fcf:.0f} vs "
                      f"computed={computed_fcf:.0f} ({divergence:.0%}). "
                      f"Using computed.")
        m["free_cashflow"] = computed_fcf
        # Recompute FCF yield with updated FCF
        try:
            m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"]) \
                if m["market_cap"] else None
        except Exception:
            pass


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
    m = _compute_price_history(m, data)
    m["news"] = [{"title": n.get("title", ""), "publisher": n.get("publisher", "")}
                 for n in data.get("news", [])]
    return m


# ══════════════════════════════════════════════════════════════
# §7.1  calc_baseline  (Phase B — built ALONGSIDE calc(), not replacing it)
# Produces the §5.1 baseline dict consumed by run_methodology_math and pass1.
# calc() remains intact; deletion deferred to Phase H.
# ══════════════════════════════════════════════════════════════

def calc_baseline(data, consensus_pack=None, peer_tickers=None,
                  sector_peers=None) -> dict:
    """
    Build the §5.1 baseline dict from the raw fetch bundle.

    Parameters
    ----------
    data            : output of fmp_api.fetch_full(ticker)
    consensus_pack  : output of fmp_api.fetch_consensus_pack(ticker) | None
    peer_tickers    : list[str] — tickers for peer_set (enriched if available)
    sector_peers    : list[dict] enriched peers from fmp_api.fetch_peer_enriched | None

    Returns
    -------
    §5.1 baseline dict.  Optional fields are None where data is missing.
    Never raises — logs warnings into data_quality_warnings.
    """
    from fmp_api import (
        fetch_sbc, fetch_contract_assets, fetch_dso,
        fetch_segment_revenue, fetch_peer_enriched,
    )

    info = data.get("info", {})
    if isinstance(info, dict) and "error" in info:
        return {"error": info["error"], "data_quality_warnings": []}

    warnings: list[str] = []
    g = lambda k, d=None: info.get(k, d)

    # ── Identifiers ────────────────────────────────────────────
    ticker      = g("symbol", "")
    company     = g("shortName", g("longName", "Unknown"))
    currency    = g("currency", "USD")

    # ── Price & market ─────────────────────────────────────────
    current_price = safe_float(g("currentPrice") or g("regularMarketPrice"))
    shares_out    = safe_float(g("sharesOutstanding"))
    market_cap    = safe_float(g("marketCap"))

    total_cash  = safe_float(g("totalCash"))
    total_debt  = safe_float(g("totalDebt"))
    net_debt    = None
    if total_debt is not None and total_cash is not None:
        net_debt = total_debt - total_cash

    # ── Income statement metrics ───────────────────────────────
    inc = data.get("inc")
    cf  = data.get("cf")
    bs  = data.get("bs")

    def _inc_row_latest(labels):
        if inc is None or inc.empty:
            return None
        for lb in labels:
            if lb in inc.index:
                row = inc.loc[lb].dropna().sort_index()
                if not row.empty:
                    return float(row.iloc[-1])
        return None

    def _inc_row_prior(labels):
        if inc is None or inc.empty:
            return None
        for lb in labels:
            if lb in inc.index:
                row = inc.loc[lb].dropna().sort_index()
                if len(row) >= 2:
                    return float(row.iloc[-2])
        return None

    fy_revenue_raw = _inc_row_latest(
        ["Total Revenue", "TotalRevenue", "Revenue", "revenue", "totalRevenue"])
    fy_revenue_prior = _inc_row_prior(
        ["Total Revenue", "TotalRevenue", "Revenue", "revenue", "totalRevenue"])
    fy_gross_profit = _inc_row_latest(["Gross Profit", "GrossProfit"])
    fy_op_income    = _inc_row_latest(
        ["Operating Income", "OperatingIncome", "EBIT"])
    fy_net_income_gaap = _inc_row_latest(
        ["Net Income", "NetIncome", "Net Income Common Stockholders",
         "Net Income From Continuing Operation Net Minority Interest"])

    fy_revenue       = fy_revenue_raw / 1e9 if fy_revenue_raw else None
    fy_revenue_yoy   = None
    if fy_revenue_raw and fy_revenue_prior and fy_revenue_prior > 0:
        fy_revenue_yoy = round((fy_revenue_raw - fy_revenue_prior) / fy_revenue_prior, 4)

    fy_gross_margin  = round(fy_gross_profit / fy_revenue_raw, 4) \
        if fy_gross_profit and fy_revenue_raw and fy_revenue_raw > 0 else \
        safe_float(g("grossMargins"))
    fy_op_margin     = round(fy_op_income / fy_revenue_raw, 4) \
        if fy_op_income and fy_revenue_raw and fy_revenue_raw > 0 else \
        safe_float(g("operatingMargins"))
    fy_net_income    = fy_net_income_gaap / 1e9 if fy_net_income_gaap else None

    # Non-GAAP EPS: statement-derived EPS (more reliable than info field)
    stmt_eps, _ = _get_statement_eps(data)
    fy_eps_non_gaap = stmt_eps or safe_float(g("trailingEps"))

    # FCF
    computed_fcf = _compute_base_fcf(data)
    info_fcf     = safe_float(g("freeCashflow", 0))
    fy_fcf_raw   = computed_fcf
    if computed_fcf is not None and info_fcf and info_fcf != 0:
        divergence = abs(computed_fcf - info_fcf) / abs(info_fcf)
        if divergence > 0.20:
            warnings.append(
                f"FCF DIVERGENCE: info={info_fcf:.0f} vs computed={computed_fcf:.0f} "
                f"({divergence:.0%}); using computed value."
            )

    fy_fcf        = fy_fcf_raw / 1e9 if fy_fcf_raw else None
    fy_fcf_margin = round(fy_fcf_raw / fy_revenue_raw, 4) \
        if fy_fcf_raw and fy_revenue_raw and fy_revenue_raw > 0 else None

    ocf_raw = None
    if cf is not None and not cf.empty:
        for lb in ["Operating Cash Flow", "Cash Flow From Operations",
                   "Total Cash From Operating Activities"]:
            if lb in cf.index:
                row = cf.loc[lb].dropna().sort_index()
                if not row.empty:
                    ocf_raw = float(row.iloc[-1])
                    break
    if ocf_raw is None:
        ocf_raw = safe_float(g("operatingCashflow"))
    fy_ocf = ocf_raw / 1e9 if ocf_raw else None

    fy_net_income_gaap_b = fy_net_income_gaap / 1e9 if fy_net_income_gaap else None

    # ── Tax rate ───────────────────────────────────────────────
    tax_rate_guidance = safe_float(g("effectiveTaxRate")) or DEFAULT_TAX_RATE

    # ── P/E, beta ─────────────────────────────────────────────
    beta        = safe_float(g("beta", 1.0))
    trailing_pe = safe_float(g("trailingPE"))
    fwd_pe      = safe_float(g("forwardPE"))
    peg         = safe_float(g("pegRatio"))

    # Recompute trailing PE from statement EPS if API value is suspect
    if fy_eps_non_gaap and current_price and current_price > 0:
        computed_tpe = round(current_price / fy_eps_non_gaap, 2)
        if trailing_pe and abs(computed_tpe - trailing_pe) / trailing_pe > 0.30:
            warnings.append(
                f"PEG CONFLICT: API trailing PE={trailing_pe:.1f} vs "
                f"computed={computed_tpe:.1f}; using computed."
            )
            trailing_pe = computed_tpe

    # ── §8.1 SBC ──────────────────────────────────────────────
    fy_sbc_raw = fetch_sbc(data)
    fy_sbc     = fy_sbc_raw / 1e9 if fy_sbc_raw else None

    # ── §8.1 Contract assets ───────────────────────────────────
    ca_current, ca_prior = fetch_contract_assets(data)
    fy_contract_assets    = ca_current / 1e9 if ca_current else None
    prior_contract_assets = ca_prior   / 1e9 if ca_prior   else None

    # ── §8.1 Software revenue (FMP segments) ──────────────────
    fy_software_revenue = None
    try:
        sw = fetch_software_revenue(data, ticker) if ticker else None
        fy_software_revenue = sw / 1e9 if sw else None
    except Exception:
        pass

    # ── §8.1 DSO ──────────────────────────────────────────────
    fy_dso, prior_dso = fetch_dso(data)

    # ── §8.1 Consensus pack ────────────────────────────────────
    cp = consensus_pack or {}
    consensus_eps_fy1       = cp.get("consensus_eps_fy1")
    consensus_eps_fy2       = cp.get("consensus_eps_fy2")
    consensus_eps_fy3       = cp.get("consensus_eps_fy3")
    consensus_revenue_fy1   = cp.get("consensus_revenue_fy1")
    consensus_revenue_fy2   = cp.get("consensus_revenue_fy2")
    consensus_price_target  = cp.get("consensus_price_target")
    n_analysts              = cp.get("n_analysts")

    # ── Five-year EPS growth estimate ─────────────────────────
    # Priority: 2yr implied CAGR from consensus (capped 60%) → revenueGrowth (capped 40%).
    # earningsGrowth from yfinance is trailing YoY — never use it (NVDA: 214% outlier).
    five_yr_eps_growth_est = None
    _fy2_mid = (consensus_eps_fy2 or {}).get("mid")
    if _fy2_mid and fy_eps_non_gaap and fy_eps_non_gaap > 0:
        try:
            _ratio = _fy2_mid / fy_eps_non_gaap
            if _ratio > 0:
                _implied = _ratio ** 0.5 - 1
                five_yr_eps_growth_est = min(_implied, 0.60)
        except Exception:
            pass
    if five_yr_eps_growth_est is None:
        _rev_growth_raw = g("revenueGrowth")  # None if key absent; safe_float(None)=0.0 falsely
        if _rev_growth_raw is not None:
            five_yr_eps_growth_est = min(safe_float(_rev_growth_raw), 0.40)

    # ── Segments (FMP) ────────────────────────────────────────
    segments = None
    try:
        segments = fetch_segment_revenue(ticker) if ticker else None
    except Exception:
        pass

    # ── 3-year financials history ──────────────────────────────
    history_3y = _build_3y_history(data)

    # ── Peer set ──────────────────────────────────────────────
    if sector_peers is not None:
        peer_set = sector_peers
    elif peer_tickers:
        try:
            peer_set = fetch_peer_enriched(peer_tickers)
        except Exception:
            peer_set = [{"ticker": t, "fwd_pe": None, "growth": None,
                         "op_margin": None, "fcf_margin": None}
                        for t in peer_tickers]
    else:
        peer_set = []

    # ── Recent news ────────────────────────────────────────────
    recent_news = []
    for n in data.get("news", [])[:8]:
        title = n.get("title", "") or ""
        if not title:
            continue
        recent_news.append({
            "date":    n.get("providerPublishTime", n.get("date", "")),
            "title":   title,
            "summary": n.get("summary", ""),
        })

    # ── Data-quality warnings from log-only checks (§8.3) ────
    if fy_revenue is None:
        warnings.append("DATA QUALITY WARNING: revenue unavailable from all sources.")
    if fy_eps_non_gaap is None:
        warnings.append("DATA QUALITY WARNING: EPS unavailable from all sources.")
    if consensus_eps_fy1 is None and consensus_eps_fy2 is None:
        warnings.append("DATA QUALITY WARNING: analyst EPS consensus unavailable.")

    return {
        "ticker":        ticker,
        "company_name":  company,
        "current_price": current_price,
        "shares_out":    shares_out / 1e9 if shares_out else None,  # in billions
        "market_cap":    market_cap / 1e9 if market_cap else None,
        "net_debt":      net_debt / 1e9 if net_debt else None,
        "currency":      currency,

        "fy_revenue":      fy_revenue,
        "fy_revenue_yoy":  fy_revenue_yoy,
        "fy_gross_margin": fy_gross_margin,
        "fy_op_margin":    fy_op_margin,
        "fy_net_income":   fy_net_income,
        "fy_eps_non_gaap": fy_eps_non_gaap,
        "fy_fcf":          fy_fcf,
        "fy_fcf_margin":   fy_fcf_margin,
        "fy_sbc":          fy_sbc,
        "fy_contract_assets":    fy_contract_assets,
        "prior_contract_assets": prior_contract_assets,
        "fy_software_revenue":   fy_software_revenue,
        "fy_dso":          fy_dso,
        "prior_dso":       prior_dso,
        "fy_ocf":          fy_ocf,
        "fy_net_income_gaap": fy_net_income_gaap_b,

        "tax_rate_guidance": tax_rate_guidance,
        "beta":              beta,
        "fwd_pe":            fwd_pe,
        "trailing_pe":       trailing_pe,
        "peg":               peg,

        "consensus_eps_fy1":      consensus_eps_fy1,
        "consensus_eps_fy2":      consensus_eps_fy2,
        "consensus_eps_fy3":      consensus_eps_fy3,
        "consensus_revenue_fy1":  consensus_revenue_fy1,
        "consensus_revenue_fy2":  consensus_revenue_fy2,
        "consensus_price_target": consensus_price_target,
        "n_analysts":             n_analysts,

        "five_yr_eps_growth_est": five_yr_eps_growth_est,
        "segments":               segments,
        "history_3y":             history_3y,
        "peer_set":               peer_set,
        "recent_news":            recent_news,

        "data_quality_warnings":  warnings,
    }


def _build_3y_history(data) -> list[dict]:
    """Build [{fy, revenue, op_margin, fcf, eps}] for up to 3 most recent years."""
    inc = data.get("inc")
    cf  = data.get("cf")
    if inc is None or inc.empty:
        return []

    def _row(df, labels):
        if df is None or df.empty:
            return None
        for lb in labels:
            if lb in df.index:
                row = df.loc[lb].dropna().sort_index()
                if not row.empty:
                    return row
        return None

    rev_row = _row(inc, ["Total Revenue", "TotalRevenue", "Revenue"])
    op_row  = _row(inc, ["Operating Income", "OperatingIncome", "EBIT"])
    eps_row = _row(inc, ["Diluted EPS", "Basic EPS", "DilutedEPS"])
    fcf_row = _row(cf,  ["Free Cash Flow", "FreeCashFlow"])

    if rev_row is None:
        return []

    history = []
    dates = list(rev_row.index[-3:])
    for dt in dates:
        fy = str(dt.year) if hasattr(dt, "year") else str(dt)
        rev = float(rev_row.get(dt, 0) or 0)
        op  = float(op_row.get(dt, 0) or 0) if op_row is not None else None
        eps = float(eps_row.get(dt, 0) or 0) if eps_row is not None else None
        fcf = float(fcf_row.get(dt, 0) or 0) if fcf_row is not None else None
        history.append({
            "fy":        fy,
            "revenue":   round(rev / 1e9, 2) if rev else None,
            "op_margin": round(op / rev, 4) if op and rev and rev > 0 else None,
            "fcf":       round(fcf / 1e9, 2) if fcf else None,
            "eps":       round(eps, 2) if eps else None,
        })
    return history


# The following import is deferred inside calc_baseline to avoid circular imports
def fetch_software_revenue(data, ticker: str):  # noqa: F811 — shim until fmp_api re-export
    from fmp_api import fetch_software_revenue as _fsw
    return _fsw(data, ticker)


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

    m["net_income_cagr"]    = ni_cagr
    m["net_income_history"] = ni_hist
    m["ni_cagr_years"]      = ni_years
    m["eps_cagr"]           = eps_cagr
    m["eps_cagr_years"]     = eps_years

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
    - Priority 3 (historical CAGR) uncapped
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
                    growth = derived
                    source = "fwd_trail_eps_derived"
                    print(f"  PEG: derived growth = {growth:.1f}%")

        # ── Priority 3: historical EPS CAGR (uncapped) ──
        if growth is None and hist_cagr_raw:
            growth = hist_cagr_raw
            source = "eps_cagr_historical"
            print(f"  PEG: using historical CAGR = {growth:.1f}%")

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
# PHASE-2 DEPTH METRICS (multi-year financials, bands, dilution)
# ══════════════════════════════════════════════════════════════

def _df_row_sorted(df, labels):
    """Extract the first matching row from df, sorted ascending by date."""
    if df is None or df.empty:
        return None
    for lb in labels:
        if lb in df.index:
            row = df.loc[lb].dropna()
            if not row.empty:
                return row.sort_index()
    return None


def _extract_n_year_values(df, labels, years=3):
    """Return list of up to `years` most recent raw $ values for the first matching label."""
    row = _df_row_sorted(df, labels)
    if row is None:
        return []
    return [float(v) for v in list(row.values)[-years:]]


def _build_multi_year_financials(inc, bs, cf):
    """Build dict of 3-year annual financial history (values in $B, year-keyed)."""
    def _years_dict(df, labels, years=3):
        row = _df_row_sorted(df, labels)
        if row is None:
            return {}
        items = list(row.items())[-years:]
        return {
            str(dt.year) if hasattr(dt, "year") else str(dt): round(float(v) / 1e9, 2)
            for dt, v in items
        }

    return {
        "revenue":    _years_dict(inc, ["Total Revenue", "TotalRevenue", "Revenue"]),
        "op_income":  _years_dict(inc, ["Operating Income", "OperatingIncome", "EBIT"]),
        "net_income": _years_dict(inc, ["Net Income", "NetIncome",
                                        "Net Income Common Stockholders"]),
        "ocf":        _years_dict(cf,  ["Operating Cash Flow",
                                        "Cash Flow From Continuing Operating Activities"]),
        "fcf":        _years_dict(cf,  ["Free Cash Flow", "FreeCashFlow"]),
        "debt":       _years_dict(bs,  ["Total Debt", "LongTermDebt", "Long Term Debt"]),
        "equity":     _years_dict(bs,  ["Stockholders Equity", "CommonStockEquity",
                                        "Total Stockholder Equity"]),
    }


def _extract_capex_history(cf, years=3):
    """Return list of capex amounts (absolute $) for last `years` periods."""
    vals = _extract_n_year_values(cf, [
        "Capital Expenditure", "CapitalExpenditure",
        "Purchase Of Property Plant And Equipment",
        "Capital Expenditures",
    ], years=years)
    return [abs(v) for v in vals]


def _extract_sbc_history(cf, years=3):
    """Return list of stock-based compensation amounts ($) for last `years` periods."""
    vals = _extract_n_year_values(cf, [
        "Stock Based Compensation", "StockBasedCompensation",
        "Share Based Compensation",
    ], years=years)
    return [abs(v) for v in vals]


def _extract_shares_history(bs, years=3):
    """Return list of shares outstanding for last `years` periods (raw units)."""
    vals = _extract_n_year_values(bs, [
        "Ordinary Shares Number", "Share Issued",
    ], years=years)
    return [v for v in vals if v > 1e6]  # sanity: >1M shares


def _compute_dilution_rate(shares_list):
    """Compute CAGR of share count. Negative = buyback program."""
    if not shares_list or len(shares_list) < 2:
        return 0.0
    oldest, newest = shares_list[0], shares_list[-1]
    if oldest <= 0:
        return 0.0
    years = len(shares_list) - 1
    return round((newest / oldest) ** (1.0 / years) - 1, 4)


def _avg_ratio(numerator_list, denominator):
    """Average ratio of numerator values to denominator values.

    denominator may be a list of raw $ or a {year: $B} dict.
    """
    if not numerator_list:
        return None
    if isinstance(denominator, dict):
        denom_list = [v * 1e9 for v in denominator.values()]
    else:
        denom_list = denominator or []
    if not denom_list:
        return None
    n = min(len(numerator_list), len(denom_list))
    num_tail   = numerator_list[-n:]
    denom_tail = denom_list[-n:]
    ratios = [num_tail[i] / denom_tail[i]
              for i in range(n) if denom_tail[i] > 0]
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 4)


def _extract_latest_quarter(qinc):
    """Extract revenue / op_income / op_margin / net_income / EPS for the most
    recent reported quarter from quarterly income statement.
    Returns dict with period_label, period_end_date, and key numbers — or None
    if qinc is missing/empty."""
    if qinc is None or qinc.empty or len(qinc.columns) == 0:
        return None
    try:
        latest_col = sorted(qinc.columns)[-1]
        period_end_date = (latest_col.strftime("%Y-%m-%d")
                           if hasattr(latest_col, "strftime") else str(latest_col))
        try:
            year   = latest_col.year
            month  = latest_col.month
            quarter = (month - 1) // 3 + 1
            period_label = f"Q{quarter} {year}"
        except Exception:
            period_label = period_end_date

        def _val(labels):
            for lb in labels:
                if lb in qinc.index:
                    v = qinc.loc[lb, latest_col]
                    if v is not None and not (isinstance(v, float) and v != v):
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            continue
            return None

        revenue  = _val(["Total Revenue", "TotalRevenue", "Revenue"])
        op_inc   = _val(["Operating Income", "OperatingIncome", "EBIT"])
        net_inc  = _val(["Net Income", "NetIncome", "Net Income Common Stockholders"])
        diluted_eps = _val(["Diluted EPS", "DilutedEPS", "Basic EPS", "BasicEPS"])
        op_margin = round(op_inc / revenue, 4) if (op_inc and revenue and revenue > 0) else None

        return {
            "period_label":      period_label,
            "period_end_date":   period_end_date,
            "revenue":           revenue,
            "operating_income":  op_inc,
            "operating_margin":  op_margin,
            "net_income":        net_inc,
            "diluted_eps":       diluted_eps,
        }
    except Exception:
        return None


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