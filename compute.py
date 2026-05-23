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
# Pass1 uses ≤2, Pass2 uses ≤2, Pass3 uses ≤1; orchestrator re-prompts consume remainder.
MAX_PIPELINE_AI_CALLS = 8


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

    # ── Reverse DCF (computed here so it's available for both prompts) ──
    m["reverse_dcf"] = compute_reverse_dcf(m)

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
    _add_depth_metrics(m, data)
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
    five_yr_eps_growth_est = safe_float(g("longTermPotentialGrowthRate")) or \
                             safe_float(g("earningsGrowth"))

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


def _compute_op_margin_band(inc, years=5):
    """Return {min, max, median} of operating margin for last `years` annual periods."""
    if inc is None or inc.empty:
        return None
    try:
        import statistics
        rev_row = _df_row_sorted(inc, ["Total Revenue", "TotalRevenue", "Revenue"])
        op_row  = _df_row_sorted(inc, ["Operating Income", "OperatingIncome", "EBIT"])
        if rev_row is None or op_row is None:
            return None
        common = rev_row.index.intersection(op_row.index)
        if len(common) < 1:
            return None
        margins = []
        for dt in sorted(common)[-years:]:
            rev = float(rev_row[dt])
            op  = float(op_row[dt])
            if rev > 0:
                margins.append(round(op / rev, 4))
        if not margins:
            return None
        return {
            "min":    round(min(margins), 4),
            "max":    round(max(margins), 4),
            "median": round(statistics.median(margins), 4),
            "n":      len(margins),
        }
    except Exception:
        return None


def _compute_tax_rate_band(inc, years=3):
    """Return {min, max, median} of effective tax rate for last `years` annual periods."""
    if inc is None or inc.empty:
        return None
    try:
        import statistics
        tax_row  = _df_row_sorted(inc, ["Tax Provision", "IncomeTaxExpense",
                                        "Income Tax Expense"])
        pret_row = _df_row_sorted(inc, ["Pretax Income", "PreTaxIncome",
                                        "Income Before Tax"])
        if tax_row is None or pret_row is None:
            return None
        common = tax_row.index.intersection(pret_row.index)
        if len(common) < 1:
            return None
        rates = []
        for dt in sorted(common)[-years:]:
            tax  = float(tax_row[dt])
            pret = float(pret_row[dt])
            if pret > 0 and tax >= 0:
                rates.append(round(tax / pret, 4))
        if not rates:
            return None
        return {
            "min":    round(min(rates), 4),
            "max":    round(max(rates), 4),
            "median": round(statistics.median(rates), 4),
            "n":      len(rates),
        }
    except Exception:
        return None


def _compute_pe_band(metrics, hist_df, years=5):
    """Estimate historical P/E band from EPS series × year-end prices."""
    try:
        import statistics
        eps_series = metrics.get("stmt_eps_series", {})  # {year: eps}
        if not eps_series or hist_df is None or hist_df.empty:
            raise ValueError("insufficient data")

        prices = hist_df["Close"]
        annual_prices = {}
        for dt, price in prices.items():
            yr = dt.year if hasattr(dt, "year") else int(str(dt)[:4])
            annual_prices[yr] = float(price)

        pes = []
        for yr, eps in eps_series.items():
            if eps and eps > 0 and yr in annual_prices:
                pe = annual_prices[yr] / eps
                if 3 < pe < 200:
                    pes.append(round(pe, 1))

        pes = pes[-years:]
        if not pes:
            raise ValueError("no valid P/E observations")

        return {
            "min":    round(min(pes), 1),
            "max":    round(max(pes), 1),
            "median": round(statistics.median(pes), 1),
            "n":      len(pes),
        }
    except Exception:
        anchor = metrics.get("forward_pe") or metrics.get("trailing_pe")
        if anchor:
            try:
                a = float(anchor)
                if a > 0:
                    return {"min": round(a * 0.6, 1), "max": round(a * 1.5, 1),
                            "median": round(a, 1), "n": 0}
            except Exception:
                pass
        return None


def _compute_pe_ranges_per_scenario(metrics, peer_metrics):
    """Return {bull:(lo,hi), base:(lo,hi), bear:(lo,hi)} for pass-1 P/E validation."""
    import statistics as _st
    peer_pes = [float(p["forward_pe"]) for p in (peer_metrics or [])
                if p.get("forward_pe") and float(p["forward_pe"]) > 0]
    if peer_pes:
        peer_median = _st.median(peer_pes)
    else:
        anchor = metrics.get("forward_pe") or metrics.get("trailing_pe") or 20
        try:
            peer_median = float(anchor)
        except Exception:
            peer_median = 20.0

    own_band = metrics.get("pe_5y_band") or {
        "min": round(peer_median * 0.6, 1),
        "max": round(peer_median * 1.4, 1),
    }
    return {
        "bull": (round(peer_median * 1.0, 1),
                 round(max(peer_median * 1.5, own_band["max"]), 1)),
        "base": (round(peer_median * 0.8, 1),
                 round(peer_median * 1.2, 1)),
        "bear": (round(max(peer_median * 0.4, own_band["min"] * 0.7), 1),
                 round(peer_median * 0.85, 1)),
    }


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


def _add_depth_metrics(m, data):
    """Add Phase-2 multi-year and band metrics to the metrics dict in-place."""
    inc  = data.get("inc")
    qinc = data.get("qinc")
    bs   = data.get("bs")
    cf   = data.get("cf")
    hist = data.get("hist")

    m["latest_quarter"]    = _extract_latest_quarter(qinc)
    m["analyst_consensus"] = data.get("analyst_consensus")

    m["multi_year_financials"] = _build_multi_year_financials(inc, bs, cf)

    capex_3y = _extract_capex_history(cf, years=3)
    m["capex_3y"]         = capex_3y
    m["capex_ttm"]        = capex_3y[-1] if capex_3y else None
    m["capex_to_revenue"] = _avg_ratio(capex_3y, m["multi_year_financials"].get("revenue", {}))

    sbc_3y = _extract_sbc_history(cf, years=3)
    m["sbc_3y"]         = sbc_3y
    m["sbc_ttm"]        = sbc_3y[-1] if sbc_3y else None
    m["sbc_to_revenue"] = _avg_ratio(sbc_3y, m["multi_year_financials"].get("revenue", {}))

    shares_3y = _extract_shares_history(bs, years=3)
    if not shares_3y and m.get("shares_outstanding"):
        shares_3y = [m["shares_outstanding"]]
    m["shares_outstanding_3y"] = shares_3y
    m["dilution_rate_3y"]      = _compute_dilution_rate(shares_3y)

    goodwill = 0.0
    try:
        row = _df_row_sorted(bs, ["Goodwill"])
        if row is not None and not row.empty:
            goodwill = float(row.iloc[-1])
    except Exception:
        pass
    m["goodwill"] = goodwill
    total_eq = 0.0
    try:
        eq_row = _df_row_sorted(bs, ["Stockholders Equity", "CommonStockEquity",
                                     "Total Stockholder Equity"])
        if eq_row is not None and not eq_row.empty:
            total_eq = float(eq_row.iloc[-1])
    except Exception:
        pass
    m["goodwill_to_equity"] = round(goodwill / total_eq, 4) if total_eq > 0 else None

    m["op_margin_5y_band"] = _compute_op_margin_band(inc, years=5)
    m["tax_rate_3y_band"]  = _compute_tax_rate_band(inc, years=3)
    m["pe_5y_band"]        = _compute_pe_band(m, hist, years=5)

    return m


# ══════════════════════════════════════════════════════════════
# PHASE-3: DRIVER-DRIVEN SCENARIO MATH
# ══════════════════════════════════════════════════════════════

def validate_pass1_inputs(pass1_dict, metrics, pe_ranges):
    """
    Validate LLM pass-1 output before handing it to the compute layer.
    Returns (ok: bool, errors: list[str]).
    Soft-clamps importance > 0.5 to 0.5 in-place; that does NOT count as an error.
    """
    errors = []

    # ── Required top-level keys ──
    for key in ("drivers", "scenario_inputs", "monitoring_kpis", "catalysts"):
        if key not in pass1_dict:
            errors.append(f"missing top-level key: {key!r}")
    if errors:
        return False, errors  # nothing else can be checked without these

    drivers         = pass1_dict.get("drivers", [])
    scenario_inputs = pass1_dict.get("scenario_inputs", {})
    monitoring_kpis = pass1_dict.get("monitoring_kpis", [])
    catalysts       = pass1_dict.get("catalysts", [])

    # ── Driver count ──
    if not (4 <= len(drivers) <= 6):
        errors.append(f"driver count {len(drivers)} not in [4, 6]")

    # ── Per-driver validation ──
    has_bull_leaning = False
    has_bear_leaning = False
    for i, d in enumerate(drivers):
        name = d.get("name", f"driver[{i}]")
        outcomes = d.get("outcomes", {})
        bp = safe_float(outcomes.get("bull", {}).get("probability", 0))
        mp = safe_float(outcomes.get("base", {}).get("probability", 0))
        wp = safe_float(outcomes.get("bear", {}).get("probability", 0))
        total = bp + mp + wp
        if abs(total - 1.0) > 0.02:
            errors.append(
                f"driver {name!r}: outcome probabilities sum to "
                f"{total:.4f} (must be 1.0 ±0.02)"
            )
        imp = safe_float(d.get("importance", 0))
        if imp > 0.5:
            d["importance"] = 0.5  # soft clamp, no error
        if imp <= 0:
            errors.append(f"driver {name!r}: importance must be > 0")
        if bp > mp:
            has_bull_leaning = True
        if wp > mp:
            has_bear_leaning = True

    if drivers and not has_bull_leaning:
        errors.append("no driver has bull.probability > base.probability")
    if drivers and not has_bear_leaning:
        errors.append("no driver has bear.probability > base.probability")

    # ── Scenario inputs validation ──
    op_band  = metrics.get("op_margin_5y_band")
    tax_band = metrics.get("tax_rate_3y_band")
    bull_op = base_op = bear_op = None

    for sname in ("bull", "base", "bear"):
        si = scenario_inputs.get(sname, {})
        if not si:
            errors.append(f"scenario_inputs missing {sname!r}")
            continue

        op  = safe_float(si.get("op_margin"))
        tax = safe_float(si.get("tax_rate"))
        pe  = safe_float(si.get("pe_multiple_pick"))

        if sname == "bull":  bull_op = op
        if sname == "base":  base_op = op
        if sname == "bear":  bear_op = op

        # Op-margin band
        if op_band and op > 0:
            lo = op_band["min"] * 0.5
            hi = op_band["max"] * 1.5
            if not (lo <= op <= hi):
                errors.append(
                    f"scenario_inputs.{sname}.op_margin {op:.4f} outside "
                    f"[{lo:.4f}, {hi:.4f}] (0.5×hist_min – 1.5×hist_max)"
                )
        elif op <= 0:
            errors.append(f"scenario_inputs.{sname}.op_margin must be > 0")

        # Tax rate band
        if tax_band:
            lo_t = max(0.05, tax_band["min"] * 0.5)
            hi_t = min(0.50, tax_band["max"] * 1.5)
        else:
            lo_t, hi_t = 0.10, 0.35
        if tax > 0 and not (lo_t <= tax <= hi_t):
            errors.append(
                f"scenario_inputs.{sname}.tax_rate {tax:.4f} outside "
                f"[{lo_t:.4f}, {hi_t:.4f}]"
            )
        elif tax <= 0:
            errors.append(f"scenario_inputs.{sname}.tax_rate must be > 0")

        # P/E range
        if pe_ranges and sname in pe_ranges:
            pe_lo, pe_hi = pe_ranges[sname]
            if pe > 0 and not (pe_lo <= pe <= pe_hi):
                errors.append(
                    f"scenario_inputs.{sname}.pe_multiple_pick {pe:.1f} outside "
                    f"[{pe_lo:.1f}, {pe_hi:.1f}]"
                )
        elif pe <= 0:
            errors.append(f"scenario_inputs.{sname}.pe_multiple_pick must be > 0")

    # ── Monotonic op-margin ──
    if bull_op is not None and base_op is not None and bear_op is not None:
        if not (bull_op >= base_op >= bear_op):
            errors.append(
                f"op_margin not monotonic: bull={bull_op:.4f} >= "
                f"base={base_op:.4f} >= bear={bear_op:.4f} required"
            )

    # ── KPI and catalyst counts ──
    if not (5 <= len(monitoring_kpis) <= 7):
        errors.append(f"monitoring_kpis count {len(monitoring_kpis)} not in [5, 7]")
    if not (3 <= len(catalysts) <= 6):
        errors.append(
            f"catalysts count {len(catalysts)} not in [3, 6]. You MUST provide "
            f"3-6 dated catalysts AFTER today, including at minimum: "
            f"(1) the next quarterly earnings release with date, "
            f"(2) any explicit forward guidance update or analyst day, "
            f"(3) one product/program-specific milestone if applicable."
        )

    # ── Analyst-consensus revenue floors (HARD constraint) ──
    ac = metrics.get("analyst_consensus") or {}
    if ac.get("revenue_fy_high") and ac.get("revenue_fy_avg") and ac.get("revenue_fy_low"):
        baseline = safe_float(metrics.get("total_revenue", 0))
        rev_floors = {
            "bull": ac["revenue_fy_high"] * 1.0,         # bull ≥ analyst HIGH
            "base": ac["revenue_fy_avg"]  * 1.0,         # base ≥ analyst AVERAGE
            "bear": ac["revenue_fy_low"]  * 0.85,        # bear allowed 15% below analyst LOW
        }
        for sname, floor in rev_floors.items():
            scen_rev = baseline + sum(
                safe_float(d.get("outcomes", {}).get(sname, {}).get("revenue_impact", 0))
                for d in drivers
            )
            if floor > 0 and scen_rev < floor:
                errors.append(
                    f"{sname}_revenue {scen_rev/1e9:.2f}B is below the analyst "
                    f"consensus floor {floor/1e9:.2f}B. Analyst consensus reflects "
                    f"management's most-recent guidance — your scenario revenue "
                    f"must clear it. Increase driver revenue_impacts on the "
                    f"hyperscaler/AI ramp or other tailwind drivers for {sname}."
                )

    return len(errors) == 0, errors


def compute_scenarios_from_drivers(metrics, pass1_inputs, current_price):
    """
    Pure Python compute layer. No LLM calls. No hidden overrides.
    Derives scenario probabilities bottom-up from driver outcome probabilities.
    Returns scenario_math_dict with final_probabilities as the single source of truth.
    """
    drivers         = pass1_inputs.get("drivers", [])
    scenario_inputs = pass1_inputs.get("scenario_inputs", {})
    scenarios       = ("bull", "base", "bear")

    # Step 1: Resolve correlated drivers
    groups = {}
    for d in drivers:
        g = d.get("correlation_group")
        if g:
            groups.setdefault(g, []).append(d)

    active_drivers = list(drivers)
    for group_drivers in groups.values():
        if len(group_drivers) < 2:
            continue
        # Keep most material; zero out others
        def _spread(d):
            b = safe_float(d["outcomes"]["bull"].get("revenue_impact", 0))
            w = safe_float(d["outcomes"]["bear"].get("revenue_impact", 0))
            return abs(b - w)
        most_material = max(group_drivers, key=_spread)
        for d in group_drivers:
            if d is not most_material:
                d["_redundant"] = True
                for s in scenarios:
                    d["outcomes"][s]["revenue_impact"] = 0.0

    # Step 2: Impact-weighted scenario probabilities
    total_importance = sum(
        safe_float(d.get("importance", 0))
        for d in active_drivers if not d.get("_redundant")
    )
    if total_importance <= 0:
        total_importance = 1.0  # avoid division by zero

    raw_p = {}
    for s in scenarios:
        raw_p[s] = sum(
            safe_float(d.get("importance", 0)) *
            safe_float(d["outcomes"][s].get("probability", 0))
            for d in active_drivers if not d.get("_redundant")
        ) / total_importance

    # Step 3: Round to integer percent; allocate remainder to base
    rounded = {s: round(raw_p[s] * 100) for s in scenarios}
    diff = 100 - sum(rounded.values())
    rounded["base"] += diff
    final_probabilities = {s: rounded[s] / 100.0 for s in scenarios}

    # Step 4: Per-scenario revenue
    baseline_revenue = safe_float(metrics.get("total_revenue", 0))
    scenario_revenue = {}
    for s in scenarios:
        delta = sum(
            safe_float(d["outcomes"][s].get("revenue_impact", 0))
            for d in active_drivers
        )
        scenario_revenue[s] = baseline_revenue + delta

    # Step 5: Dilution-adjusted shares
    shares = safe_float(metrics.get("shares_outstanding", 0))
    dilution = safe_float(metrics.get("dilution_rate_3y", 0))
    future_shares = shares * (1 + dilution) ** 1 if shares > 0 else shares

    # Step 6: Per-scenario EPS (Python-deterministic; no LLM EPS anywhere)
    eps = {}
    for s in scenarios:
        si = scenario_inputs.get(s, {})
        op_m = safe_float(si.get("op_margin", 0))
        tax  = safe_float(si.get("tax_rate", 0.21))
        if future_shares > 0 and op_m > 0:
            eps[s] = scenario_revenue[s] * op_m * (1 - tax) / future_shares
        else:
            eps[s] = 0.0

    # Step 7: Per-scenario price target
    price_target = {}
    for s in scenarios:
        si = scenario_inputs.get(s, {})
        pe = safe_float(si.get("pe_multiple_pick", 0))
        price_target[s] = round(eps[s] * pe, 2) if eps[s] > 0 and pe > 0 else 0.0

    # Step 8: Monotonicity check
    monotonicity_violation = False
    violation_msg = None
    if price_target.get("bear", 0) and price_target.get("base", 0) and price_target.get("bull", 0):
        if not (price_target["bear"] < price_target["base"] < price_target["bull"]):
            monotonicity_violation = True
            violation_msg = (
                f"Non-monotonic price targets: "
                f"bear={price_target['bear']:.2f}, "
                f"base={price_target['base']:.2f}, "
                f"bull={price_target['bull']:.2f}. "
                f"Please re-examine your driver impacts and scenario margins so that "
                f"bear < base < bull."
            )

    # Step 8b: Bull-below-current sanity guard — strong signal of stale baselines
    bull_below_current = False
    bull_below_msg = None
    cp_check = safe_float(current_price)
    if cp_check > 0 and price_target.get("bull", 0) > 0:
        if price_target["bull"] < cp_check:
            bull_below_current = True
            bull_below_msg = (
                f"Bull-case price target {price_target['bull']:.2f} is BELOW current "
                f"price {cp_check:.2f}. Your bull-case revenue ({scenario_revenue['bull']/1e9:.2f}B) "
                f"and/or operating margin ({scenario_inputs.get('bull', {}).get('op_margin', 0)*100:.1f}%) "
                f"may be anchored on stale forward baselines (e.g. outdated revenue guidance). "
                f"Reconsider bull-case revenue/margin against the LATEST QUARTERLY DISCLOSURE and "
                f"any recent guidance updates in RECENT NEWS HEADLINES — bull revenue should be "
                f"consistent with or above management's most recent annual guidance."
            )

    # Step 9: Driver-level EPS impact stamps
    for d in active_drivers:
        for s in scenarios:
            si = scenario_inputs.get(s, {})
            op_m = safe_float(si.get("op_margin", 0))
            tax  = safe_float(si.get("tax_rate", 0.21))
            rev_impact = safe_float(d["outcomes"][s].get("revenue_impact", 0))
            if future_shares > 0:
                d["outcomes"][s]["eps_impact"] = round(
                    rev_impact * op_m * (1 - tax) / future_shares, 4
                )

    # Step 10: Aggregates
    cp = safe_float(current_price)
    if cp > 0:
        expected_value   = sum(final_probabilities[s] * price_target[s] for s in scenarios)
        expected_return  = expected_value / cp - 1
        base_implied_ret = price_target["base"] / cp - 1 if price_target.get("base") else 0
        prob_positive    = sum(final_probabilities[s] for s in scenarios
                               if price_target.get(s, 0) > cp)

        upside_sum   = sum(final_probabilities[s] * (price_target[s] / cp - 1)
                           for s in scenarios if price_target.get(s, 0) > cp)
        downside_sum = sum(final_probabilities[s] * (price_target[s] / cp - 1)
                           for s in scenarios if price_target.get(s, 0) < cp)
        upside_downside_ratio = (
            abs(upside_sum / downside_sum) if downside_sum != 0 else float("inf")
        )
    else:
        expected_value = expected_return = base_implied_ret = 0
        prob_positive = upside_downside_ratio = 0

    # Regression guard assertions (downgraded to warnings in production)
    _guard_warnings = []
    try:
        assert abs(sum(final_probabilities.values()) - 1.0) < 1e-9, "final_probabilities do not sum to 1.0"
        assert all((round(p * 100) / 100.0 == p) for p in final_probabilities.values()), \
            "final_probabilities are not integer-percent"
        assert all(0 < d.get("importance", 0) <= 0.5 for d in active_drivers if not d.get("_redundant")), \
            "driver importance out of (0, 0.5] range"
        if not monotonicity_violation:
            if price_target.get("bear") and price_target.get("base") and price_target.get("bull"):
                assert price_target["bear"] < price_target["base"] < price_target["bull"], \
                    "non-monotonic price targets without violation flag"
    except AssertionError as _ae:
        _guard_warnings.append(f"compute_guard:{_ae}")

    return {
        "final_probabilities":    final_probabilities,
        "scenario_revenue":       {s: round(scenario_revenue[s], 0) for s in scenarios},
        "future_shares":          round(future_shares, 0),
        "eps":                    {s: round(eps[s], 4) for s in scenarios},
        "price_target":           price_target,
        "expected_value":         round(expected_value, 2),
        "expected_return":        round(expected_return, 4),
        "base_implied_return":    round(base_implied_ret, 4),
        "prob_positive":          round(prob_positive, 4),
        "upside_downside_ratio":  round(upside_downside_ratio, 4)
                                  if upside_downside_ratio != float("inf") else None,
        "monotonicity_violation": monotonicity_violation,
        "violation_msg":          violation_msg,
        "bull_below_current":     bull_below_current,
        "bull_below_msg":         bull_below_msg,
        "drivers_with_impacts":   active_drivers,
        "guard_warnings":         _guard_warnings,
    }


def derive_recommendation(scenario_math):
    """
    Deterministic recommendation label and conviction from scenario_math output.
    Returns (label: str, conviction: str).
    """
    expected_return  = safe_float(scenario_math.get("expected_return", 0))
    base_implied_ret = safe_float(scenario_math.get("base_implied_return", 0))
    prob_positive    = safe_float(scenario_math.get("prob_positive", 0))
    ud_ratio         = scenario_math.get("upside_downside_ratio")
    ud               = safe_float(ud_ratio) if ud_ratio is not None else float("inf")

    # Recommendation label
    if base_implied_ret < -0.25 or (expected_return < 0 and prob_positive < 0.50):
        label = "PASS"
    elif base_implied_ret < -0.10 or ud < 1.5:
        label = "WATCH"
    elif (expected_return > 0.08 and base_implied_ret > 0
          and prob_positive > 0.65 and ud > 1.5):
        label = "BUY"
    else:
        label = "WATCH"

    # Conviction
    if ud > 3.0 and prob_positive > 0.70:
        conviction = "High"
    elif ud < 1.5 or (0.40 <= prob_positive <= 0.60):
        conviction = "Low"
    else:
        conviction = "Medium"

    return label, conviction


def compute_fundamentals_diagnostic(metrics, driver_probabilities=None):
    """
    Renamed from compute_scenario_probabilities. Runs the 8-signal engine and
    returns signal_implied_probabilities for comparison vs driver-derived probs.
    Does NOT influence any number in the report — diagnostic only.
    """
    result = compute_scenario_probabilities(metrics)
    signal_probs = {
        "bull": result.get("bull", 0.35),
        "base": result.get("base", 0.45),
        "bear": result.get("bear", 0.20),
    }
    divergence_flag = False
    if driver_probabilities:
        for s in ("bull", "base", "bear"):
            diff = abs(signal_probs.get(s, 0) - driver_probabilities.get(s, 0))
            if diff > 0.15:
                divergence_flag = True
                break
    return {
        "signal_implied_probabilities": signal_probs,
        "divergence_flag": divergence_flag,
        "bull_score": result.get("bull_score"),
        "signal_log": result.get("signal_log", []),
    }


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

    # Enforce minimum 10% bear probability
    if final_bear < 0.10:
        deficit    = 0.10 - final_bear
        final_bear = 0.10
        denom      = final_bull + final_base
        if denom > 0:
            final_bull -= deficit * (final_bull / denom)
            final_base -= deficit * (final_base / denom)
        total2     = final_bull + final_base + final_bear
        final_bull = round(final_bull / total2, 3)
        final_base = round(final_base / total2, 3)
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
# REVERSE DCF (v1)
# Solves for the FCF CAGR implied by the current market price.
# Python owns all math. AI only interprets the output.
# ══════════════════════════════════════════════════════════════

# Sector WACC defaults — override per company if needed
SECTOR_WACC = {
    "Technology":             0.10,
    "Communication Services": 0.10,
    "Consumer Discretionary": 0.10,
    "Consumer Staples":       0.09,
    "Healthcare":             0.09,
    "Industrials":            0.09,
    "Materials":              0.09,
    "Energy":                 0.10,
    "Real Estate":            0.08,
    "Utilities":              0.07,
    "Financial Services":     None,  # DCF not appropriate
    "Financials":             None,
}

TERMINAL_GROWTH_RATE = 0.03   # conservative nominal GDP proxy


def compute_reverse_dcf(metrics, years=5):
    """
    Given current price, solve for the FCF CAGR the market is pricing in.

    Returns a dict with implied_fcf_cagr and diagnostics, or None if
    the inputs make DCF inappropriate (negative FCF, financials, etc.).
    """
    sector        = metrics.get("sector", "Technology")
    wacc          = SECTOR_WACC.get(sector, 0.10)

    if wacc is None:
        print(f"  Reverse DCF: skipped — sector '{sector}' not DCF-appropriate")
        return {
            "available":  False,
            "reason":     f"DCF not applicable for {sector} companies. "
                          f"Use price-to-book or PE-based valuation.",
        }

    current_price = safe_float(metrics.get("current_price"))
    shares        = safe_float(metrics.get("shares_outstanding"))
    total_debt    = safe_float(metrics.get("total_debt", 0))
    total_cash    = safe_float(metrics.get("total_cash", 0))
    base_fcf      = safe_float(metrics.get("free_cashflow", 0))

    if current_price <= 0 or shares <= 0:
        return {"available": False, "reason": "Missing price or share count."}

    if base_fcf <= 0:
        return {
            "available": False,
            "reason":    (
                f"Base FCF is {base_fcf:.0f}. Reverse DCF requires "
                f"positive trailing FCF. Company may be in investment "
                f"phase or loss-making."
            ),
        }

    tgr           = TERMINAL_GROWTH_RATE
    target_equity = current_price * shares
    target_ev     = target_equity + total_debt - total_cash

    if target_ev <= 0:
        return {"available": False, "reason": "Enterprise value is non-positive."}

    def ev_at_growth(g):
        fcf = base_fcf
        pv  = 0.0
        for i in range(1, years + 1):
            fcf *= (1 + g)
            pv  += fcf / (1 + wacc) ** i
        # Gordon Growth terminal value
        if wacc <= tgr:
            return float("inf")
        tv  = (fcf * (1 + tgr)) / (wacc - tgr)
        pv += tv / (1 + wacc) ** years
        return pv

    # Binary search for implied growth rate
    lo, hi = -0.30, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        if ev_at_growth(mid) < target_ev:
            lo = mid
        else:
            hi = mid
    implied_growth = round((lo + hi) / 2, 4)

    # Terminal value as pct of total (sensitivity flag)
    final_fcf  = base_fcf * (1 + implied_growth) ** years
    tv         = (final_fcf * (1 + tgr)) / (wacc - tgr)
    pv_tv      = tv / (1 + wacc) ** years
    tv_pct     = pv_tv / target_ev if target_ev > 0 else 0

    result = {
        "available":          True,
        "implied_fcf_cagr":   implied_growth,
        "wacc_used":          wacc,
        "terminal_growth":    tgr,
        "sector":             sector,
        "base_fcf":           round(base_fcf, 0),
        "target_ev":          round(target_ev, 0),
        "terminal_value_pct": round(tv_pct, 4),
        "tv_pct_flag":        tv_pct > 0.80,
        "note": (
            f"At {current_price:.2f}/share, market prices in "
            f"{implied_growth*100:.1f}% FCF CAGR over {years}yr "
            f"({wacc*100:.0f}% WACC, {tgr*100:.1f}% terminal growth). "
            f"Terminal value is {tv_pct*100:.0f}% of EV"
            + (" — high sensitivity to terminal assumptions." if tv_pct > 0.80 else ".")
        ),
    }

    print(f"  Reverse DCF: implied FCF CAGR={implied_growth*100:.1f}%, "
          f"WACC={wacc*100:.0f}%, TV%={tv_pct*100:.0f}%")
    return result


# ══════════════════════════════════════════════════════════════
# HEADWIND / TAILWIND EPS STAMPER (unchanged)
# ══════════════════════════════════════════════════════════════

def stamp_headwind_tailwind_eps(llm_output, scenario_results, shares, op_margin, tax_rate=0.21):
    hw_items = llm_output.get("headwinds", [])
    tw_items = llm_output.get("tailwinds", [])

    for item in hw_items:
        rev = safe_float(
            item.get("revenue_at_risk") or 0
        )
        if rev == 0 or shares == 0 or op_margin == 0:
            item["bull_eps_impact"] = 0.0
            item["base_eps_impact"] = 0.0
            item["bear_eps_impact"] = 0.0
            continue
        for sname in ["bull", "base", "bear"]:
            s = scenario_results.get(sname, {})
            s_margin = s.get("operating_margin", op_margin)
            # NEGATIVE for headwinds — this is EPS you LOSE
            eps = -round((rev * s_margin * (1 - tax_rate)) / shares, 2)
            item[f"{sname}_eps_impact"] = eps

    for item in tw_items:
        rev = safe_float(
            item.get("revenue_opportunity") or 0
        )
        if rev == 0 or shares == 0 or op_margin == 0:
            item["bull_eps_impact"] = 0.0
            item["base_eps_impact"] = 0.0
            item["bear_eps_impact"] = 0.0
            continue
        for sname in ["bull", "base", "bear"]:
            s = scenario_results.get(sname, {})
            s_margin = s.get("operating_margin", op_margin)
            # POSITIVE for tailwinds — this is EPS you GAIN
            eps = round((rev * s_margin * (1 - tax_rate)) / shares, 2)
            item[f"{sname}_eps_impact"] = eps


# ══════════════════════════════════════════════════════════════
# SCENARIO MATH ENGINE
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
        lo, hi = anchor_pe * 0.20, anchor_pe * 0.85

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

        op_margin_s = llm_op_margin  if llm_op_margin  > 0 else operating_margin
        net_margin  = llm_net_margin if llm_net_margin > 0 else profit_margin

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

    # ── Scenario monotonicity guard ──
    # Enforce bear < base < bull on price targets. The LLM can produce
    # internally inconsistent assumptions (e.g. bear preserves margin
    # while base compresses, yielding bear_eps > base_eps). When the
    # ordering breaks, scenario_math becomes effectively bimodal and
    # the report misrepresents risk distribution.
    def _enforce_below(result, ceiling_pt, gap, label):
        if not result or ceiling_pt <= 0:
            return
        pt = result.get("price_target", 0)
        pe = result.get("pe_multiple", 0)
        if pt > 0 and pt >= ceiling_pt:
            new_pt = round(ceiling_pt * (1 - gap), 2)
            flag = (f"MONOTONICITY: {label} price target ({pt:.2f}) was "
                    f">= ceiling ({ceiling_pt:.2f}); clamped to {new_pt:.2f}.")
            result["price_target"] = new_pt
            if pe > 0:
                result["projected_eps"] = round(new_pt / pe, 2)
            if current_price > 0:
                result["implied_return"] = round(
                    (new_pt - current_price) / current_price, 4)
            existing = result.get("monotonicity_flag") or ""
            result["monotonicity_flag"] = (existing + " " + flag).strip()
            print(f"  {flag}")

    bull_result = results.get("bull", {})
    base_result = results.get("base", {})
    bear_result = results.get("bear", {})

    bull_pt_now = bull_result.get("price_target", 0) if bull_result else 0
    _enforce_below(base_result, bull_pt_now, gap=0.10, label="base")
    base_pt_now = base_result.get("price_target", 0) if base_result else 0
    _enforce_below(bear_result, base_pt_now, gap=0.10, label="bear")

    # ── Bear price target floor: must be below current price ──
    if bear_result:
        bear_pt = bear_result.get("price_target", 0)
        if bear_pt >= current_price and current_price > 0:
            new_pt = round(current_price * 0.70, 2)
            bear_result["price_target"] = new_pt
            pe = bear_result.get("pe_multiple", 0)
            if pe > 0:
                bear_result["projected_eps"] = round(new_pt / pe, 2)
            bear_result["implied_return"] = round(
                (new_pt - current_price) / current_price, 4)
            existing = bear_result.get("monotonicity_flag") or ""
            floor_flag = (f"BEAR FLOOR: target ({bear_pt:.2f}) was >= "
                          f"current price; forced to {new_pt:.2f} "
                          f"(current * 0.70).")
            bear_result["monotonicity_flag"] = (existing + " " + floor_flag).strip()
            print(f"  {floor_flag}")

    # ── Bear minimum decline: a <12% bear case is implausibly mild ──
    if bear_result and current_price > 0:
        bear_ir = bear_result.get("implied_return", 0)
        if bear_ir > -0.12:
            min_bear_return = -0.20
            new_bear_pt = round(current_price * (1 + min_bear_return), 2)
            bear_result["price_target"] = new_bear_pt
            bear_result["implied_return"] = round(min_bear_return, 4)
            existing = bear_result.get("monotonicity_flag") or ""
            min_flag = (f"BEAR MINIMUM: implied_return was {bear_ir:.3f} "
                        f"(< -12%); forced to -20% ({new_bear_pt:.2f}).")
            bear_result["monotonicity_flag"] = (existing + " " + min_flag).strip()
            print(f"  {min_flag}")

    stamp_headwind_tailwind_eps(llm_output, results, shares, operating_margin)

    sensitivity_table = compute_sensitivity_table(
        results.get("base", {}), current_price)

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
    """
    reasons = []

    scenarios = scenario_results.get("scenarios", {})
    base = scenarios.get("base", {})

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
    base_eps     = safe_float(base.get("projected_eps", 0))
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