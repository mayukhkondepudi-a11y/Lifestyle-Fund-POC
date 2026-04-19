"""Financial metrics computation, scenario math, probability engine, QGLP scoring."""
import re
from formatting import safe_float, fmt_n


# ══════════════════════════════════════════════════════════════
# LATEX SANITIZER
# ══════════════════════════════════════════════════════════════

def clean_latex(text):
    """Strip LaTeX math delimiters that LLMs sometimes embed in prose."""
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

    m = _compute_debt_equity(m, info, data)
    m = _compute_margins_from_statements(m, data)
    m = _compute_cagrs(m, data)
    m = _cross_validate_forward_pe(m, info)
    m = _compute_peg(m)
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
    """Compute CAGR from financial statement rows. Always returns (cagr, hist, years)."""
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
    m["net_income_cagr"], m["net_income_history"], m["ni_cagr_years"] = _cagr_from(
        inc, ["Net Income", "NetIncome", "Net Income Common Stockholders",
              "netIncome", "Net Income From Continuing Operation Net Minority Interest"])
    m["eps_cagr"], _, m["eps_cagr_years"] = _cagr_from(
        inc, ["Diluted EPS", "Basic EPS", "DilutedEPS", "BasicEPS",
              "EPS", "Earnings Per Share", "epsdiluted", "eps",
              "Diluted NI Availto Com Stockholders"])
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
    """PEG ratio from multi-year earnings CAGR against forward PE."""
    m["peg_ratio"] = None
    try:
        pe = safe_float(m.get("forward_pe"))
        if pe <= 0:
            pe = safe_float(m.get("trailing_pe"))
        if pe <= 0:
            return m

        growth = None

        if m.get("eps_cagr") and float(m["eps_cagr"]) > 0:
            growth = float(m["eps_cagr"]) * 100

        if growth is None and m.get("net_income_cagr") and float(m["net_income_cagr"]) > 0:
            growth = float(m["net_income_cagr"]) * 100

        if growth is None and m.get("earnings_growth"):
            g_val = float(m["earnings_growth"])
            g_pct = g_val * 100 if abs(g_val) < 1 else g_val
            if g_pct > 0:
                growth = g_pct

        if growth and growth > 0:
            peg = round(pe / growth, 2)
            if 0 < peg <= 5.0:
                m["peg_ratio"] = peg
                print(f"  PEG computed: {pe:.1f}x PE / {growth:.1f}% growth = {peg:.2f}")
            else:
                print(f"  PEG computed but out of range ({peg:.2f}), discarding")
        else:
            print(f"  PEG: no positive earnings growth available")

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
# PROBABILITY ENGINE
# ══════════════════════════════════════════════════════════════

def compute_scenario_probabilities(llm_output):
    MIN_SCENARIO_PROB = 0.08
    MAX_SCENARIO_PROB = 0.55

    drivers = llm_output.get("macro_drivers", [])
    valid_drivers = []
    for d in drivers:
        try:
            bull_p = float(d.get("bull_outcome", {}).get("probability", 0))
            base_p = float(d.get("base_outcome", {}).get("probability", 0))
            bear_p = float(d.get("bear_outcome", {}).get("probability", 0))
            total = bull_p + base_p + bear_p
            if total <= 0:
                continue
            valid_drivers.append({
                "name": d.get("name", "Unknown Driver"),
                "bull_p": bull_p / total, "base_p": base_p / total,
                "bear_p": bear_p / total,
            })
        except (TypeError, ValueError):
            continue

    if not valid_drivers:
        return {
            "bull": 0.25, "base": 0.50, "bear": 0.25,
            "method": "fallback", "driver_detail": [],
            "raw_geometric": {"bull": 0.25, "bear": 0.25},
            "correlation_multipliers": {"bull": 1.0, "bear": 1.0},
        }

    n = len(valid_drivers)
    bull_product = bear_product = 1.0
    for d in valid_drivers:
        bull_product *= d["bull_p"]
        bear_product *= d["bear_p"]

    geo_bull = bull_product ** (1.0 / n)
    geo_bear = bear_product ** (1.0 / n)

    BULL_BOOST = 1.2
    BEAR_BOOST = 1.4
    adjusted_bull = max(MIN_SCENARIO_PROB, min(MAX_SCENARIO_PROB, geo_bull * BULL_BOOST))
    adjusted_bear = max(MIN_SCENARIO_PROB, min(MAX_SCENARIO_PROB, geo_bear * BEAR_BOOST))

    if adjusted_bull + adjusted_bear > 0.85:
        scale = 0.85 / (adjusted_bull + adjusted_bear)
        adjusted_bull *= scale
        adjusted_bear *= scale

    adjusted_base = max(MIN_SCENARIO_PROB, 1.0 - adjusted_bull - adjusted_bear)
    total = adjusted_bull + adjusted_base + adjusted_bear
    final_bull = round(adjusted_bull / total, 4)
    final_bear = round(adjusted_bear / total, 4)
    final_base = round(1.0 - final_bull - final_bear, 4)

    print(f"  Probability engine: geo_bull={geo_bull:.4f}, geo_bear={geo_bear:.4f} | "
          f"final: bull={final_bull:.2%}, base={final_base:.2%}, bear={final_bear:.2%}")

    return {
        "bull": final_bull, "base": final_base, "bear": final_bear,
        "method": "geometric_mean_probability",
        "driver_detail": [
            {"name": d["name"], "bull_p": round(d["bull_p"], 3),
             "base_p": round(d["base_p"], 3), "bear_p": round(d["bear_p"], 3)}
            for d in valid_drivers
        ],
        "raw_geometric": {"bull": round(geo_bull, 4), "bear": round(geo_bear, 4)},
        "correlation_multipliers": {"bull": BULL_BOOST, "bear": BEAR_BOOST},
    }


# ══════════════════════════════════════════════════════════════
# SCENARIO MATH ENGINE
# ══════════════════════════════════════════════════════════════

def _sum_item_eps(items):
    """
    FIX B: Sum eps_impact from individual headwind/tailwind item dicts.
    The LLM puts eps_impact inside each item, not at the scenario level.
    Headwinds are negative by convention; tailwinds positive.
    Falls back to zero gracefully when the field is absent.
    """
    total = 0.0
    for item in (items or []):
        val = safe_float(item.get("eps_impact", item.get("eps_delta", 0)))
        total += val
    return total


def _detect_gaap_suppression(python_eps, llm_eps, forward_eps, trailing_eps):
    """
    FIX A: Detect whether GAAP acquisition amortisation is suppressing EPS.

    This is the AVGO/VMware problem: GAAP net income is crushed by intangible
    amortisation from the $69B acquisition, making GAAP EPS (~$5) look nothing
    like the non-GAAP consensus forward EPS (~$18) that the market prices on.

    The thesis explicitly states: "Non-GAAP and FCF metrics better represent
    underlying operational performance through this transition period."
    (AVGO-Thesis.docx, Section 6 Financial Analysis)

    Detection criteria — all three must be true:
      1. forward_eps exists and is meaningfully positive
      2. Both python_eps AND llm_eps are less than 60% of forward_eps
         (i.e. neither computation is anywhere near what the market prices)
      3. The gap between trailing_pe and forward_pe implies a large GAAP/non-GAAP
         wedge (trailing EPS << forward EPS consensus)

    Returns: (is_suppressed: bool, non_gaap_ratio: float)
      non_gaap_ratio = forward_eps / trailing_eps, capped at 4.0
      This is used to scale scenario EPS up to non-GAAP territory.
    """
    if forward_eps <= 0 or trailing_eps <= 0:
        return False, 1.0

    # Both computations are below 60% of consensus forward EPS
    py_below  = python_eps  > 0 and python_eps  < forward_eps * 0.60
    llm_below = (llm_eps <= 0) or (llm_eps < forward_eps * 0.60)

    if not (py_below and llm_below):
        return False, 1.0

    # The forward/trailing EPS ratio must be >1.3x to confirm a real GAAP wedge
    # (not just a stock that's simply losing money)
    non_gaap_ratio = forward_eps / trailing_eps
    if non_gaap_ratio < 1.3:
        return False, 1.0

    # Cap the ratio at 4.0x to prevent runaway scaling on truly broken data
    non_gaap_ratio = min(non_gaap_ratio, 4.0)
    return True, non_gaap_ratio


def _compute_single_scenario(s, scenario_name, scenario_probs, current_price,
                              trailing_eps, forward_eps, total_revenue, shares,
                              operating_margin, profit_margin, fcf_margin):
    try:
        prob     = scenario_probs.get(scenario_name, 0.20)
        tax_rate = safe_float(s.get("tax_rate"), default=0.21)

        # ── Segment revenue build ──────────────────────────────────────────
        segment_builds        = s.get("segment_builds", [])
        segment_revenue_total = sum(safe_float(seg.get("projected_revenue"))
                                    for seg in segment_builds)

        # ── FIX B: headwind/tailwind EPS ──────────────────────────────────
        # The LLM puts eps_impact inside each individual item dict.
        # The scenario-level total fields (total_headwind_eps etc.) are often
        # absent or zero. Sum from items first; fall back to scenario-level.
        hw_items = s.get("headwinds", [])
        tw_items = s.get("tailwinds", [])

        hw_revenue          = safe_float(s.get("total_headwind_revenue"))
        tw_revenue          = safe_float(s.get("total_tailwind_revenue"))
        hw_eps_scenario     = safe_float(s.get("total_headwind_eps"))
        tw_eps_scenario     = safe_float(s.get("total_tailwind_eps"))
        hw_eps_items        = _sum_item_eps(hw_items)
        tw_eps_items        = _sum_item_eps(tw_items)

        # Use per-item sum when scenario-level total is zero
        hw_eps = hw_eps_scenario if hw_eps_scenario != 0 else hw_eps_items
        tw_eps = tw_eps_scenario if tw_eps_scenario != 0 else tw_eps_items

        # ── Revenue total ──────────────────────────────────────────────────
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
                print(f"  {scenario_name}: Revenue discrepancy — "
                      f"Python={python_total_revenue:.0f}, LLM={llm_total_revenue:.0f} "
                      f"({rev_diff*100:.1f}% diff)")

        rev_growth = ((total_rev / total_revenue) - 1) if total_revenue > 0 else 0.0

        # ── Margins ────────────────────────────────────────────────────────
        llm_op_margin    = safe_float(s.get("operating_margin"))
        llm_net_margin   = safe_float(s.get("net_margin"))
        margin_rationale = clean_latex(s.get("margin_rationale", ""))

        # Sanity-check the LLM operating margin against trailing (cap at 3x/floor at 0.1x)
        if operating_margin > 0 and llm_op_margin > 0:
            margin_ratio = llm_op_margin / operating_margin
            if margin_ratio > 3.0 or margin_ratio < 0.1:
                llm_op_margin = max(operating_margin * 0.3,
                                    min(llm_op_margin, operating_margin * 2.5))

        op_margin  = llm_op_margin  if llm_op_margin  > 0 else operating_margin
        net_margin = llm_net_margin if llm_net_margin > 0 else profit_margin

        if net_margin == 0 and op_margin > 0:
            net_margin = op_margin * (1 - tax_rate)
        if op_margin > 0 and net_margin > op_margin:
            net_margin = op_margin * (1 - tax_rate)

        # ── EPS: FIX A — Non-GAAP / GAAP wedge detection ──────────────────
        #
        # The thesis (AVGO-Thesis.docx §6) is explicit: AVGO's GAAP EPS (~$4.76
        # in FY2025) is depressed by ~$10B/year of VMware intangible amortisation.
        # The market prices the stock on non-GAAP EPS (~$8.10 trailing, ~$14.40
        # FY2027E consensus). PE multiples in the LLM scenarios (28-37x bull,
        # 28-35x base, 25-30x bear) are ALL calibrated to non-GAAP EPS.
        #
        # Python computes GAAP EPS (revenue × GAAP net margin ÷ shares).
        # If we apply a 30x PE to a $8.69 GAAP EPS we get $260 — not the $406-537
        # the thesis projects. The fix: detect GAAP suppression and scale up.
        #
        # Detection: both Python and LLM EPS are <60% of forward_eps (non-GAAP
        # consensus from the API). When detected, we use forward_eps scaled by
        # the scenario's operating margin improvement ratio as the EPS anchor.
        # This mirrors exactly what the thesis does: start from non-GAAP baseline,
        # apply scenario-specific margin assumptions, divide by shares.

        if total_rev > 0 and net_margin > 0 and shares > 0:
            python_eps = (total_rev * net_margin) / shares
        elif total_rev > 0 and op_margin > 0 and shares > 0:
            python_eps = (total_rev * op_margin * (1 - tax_rate)) / shares
        else:
            python_eps = 0.0

        llm_eps  = safe_float(s.get("projected_eps"))
        eps_flag = None

        # Check for GAAP suppression
        gaap_suppressed, non_gaap_ratio = _detect_gaap_suppression(
            python_eps, llm_eps, forward_eps, trailing_eps)

        if gaap_suppressed:
            # Scale up to non-GAAP territory.
            # Formula: forward_eps (non-GAAP consensus) × scenario op margin ratio
            # × (1 + revenue growth). This is the same methodology the thesis uses
            # when it projects non-GAAP EPS of $10.25/$8.63/$6.13 across scenarios.
            scenario_margin_ratio = (llm_op_margin / operating_margin
                                     if operating_margin > 0 and llm_op_margin > 0
                                     else 1.0)
            scenario_margin_ratio = max(0.50, min(2.0, scenario_margin_ratio))

            final_eps = forward_eps * (1 + rev_growth) * scenario_margin_ratio
            eps_flag  = (
                f"GAAP EPS suppressed by acquisition amortisation "
                f"(Python GAAP={python_eps:.2f}, LLM={llm_eps:.2f}, "
                f"forward_eps non-GAAP consensus={forward_eps:.2f}). "
                f"Scaled to non-GAAP using forward_eps × rev_growth "
                f"({1+rev_growth:.2f}x) × margin ratio ({scenario_margin_ratio:.2f}x) "
                f"= {final_eps:.2f}. Consistent with thesis non-GAAP methodology."
            )
            print(f"  {scenario_name}: {eps_flag}")

        elif python_eps > 0 and llm_eps > 0:
            eps_diff = abs(python_eps - llm_eps) / llm_eps
            if eps_diff > 0.10:
                # Not GAAP-suppressed — Python and LLM just disagree.
                # Check which is closer to forward_eps consensus.
                if forward_eps > 0:
                    py_dist  = abs(python_eps - forward_eps) / forward_eps
                    llm_dist = abs(llm_eps    - forward_eps) / forward_eps
                    if llm_dist < py_dist and llm_dist < 0.40:
                        final_eps = llm_eps
                        eps_flag  = (
                            f"LLM EPS ({llm_eps:.2f}) is closer to forward consensus "
                            f"({forward_eps:.2f}) than Python EPS ({python_eps:.2f}). "
                            f"Using LLM's figure."
                        )
                        print(f"  {scenario_name}: {eps_flag}")
                    else:
                        final_eps = python_eps
                        eps_flag  = (
                            f"Python EPS ({python_eps:.2f}) differs from "
                            f"LLM EPS ({llm_eps:.2f}) by {eps_diff*100:.1f}%. "
                            f"Using Python's number."
                        )
                        print(f"  {scenario_name}: {eps_flag}")
                else:
                    final_eps = python_eps
                    eps_flag  = (
                        f"Python EPS ({python_eps:.2f}) differs from "
                        f"LLM EPS ({llm_eps:.2f}) by {eps_diff*100:.1f}%. "
                        f"Using Python's number."
                    )
                    print(f"  {scenario_name}: {eps_flag}")
            else:
                final_eps = python_eps  # agree within 10%

        elif python_eps > 0:
            final_eps = python_eps
        elif llm_eps > 0:
            final_eps = llm_eps
            eps_flag  = "Python could not compute EPS. Using LLM's number."
        else:
            final_eps = trailing_eps * (1 + rev_growth) if trailing_eps > 0 else 0
            eps_flag  = "Both computations failed. Using trailing EPS grown by revenue growth."

        # ── Price target ───────────────────────────────────────────────────
        pe_mult      = max(safe_float(s.get("pe_multiple"), default=20.0), 3.0)
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
            "operating_margin":       round(op_margin, 4),
            "net_margin":             round(net_margin, 4),
            "margin_rationale":       margin_rationale,
            "projected_eps":          round(final_eps, 2),
            "llm_eps":                round(llm_eps, 2) if llm_eps else None,
            "eps_flag":               eps_flag,
            "pe_multiple":            round(pe_mult, 1),
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
            "pe_multiple":            0,  "pe_rationale":          "",
            "price_target":           0,  "implied_return":        0,
            "breakeven_pe":           None, "fcf_yield_at_target": None,
            "narrative":              str(e),
        }


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

    # If forward_eps not directly available from API, derive from price / forward_pe.
    # This gives us the non-GAAP consensus EPS the market is pricing on —
    # exactly the anchor the thesis uses for all scenario price targets.
    if forward_eps <= 0 and forward_pe > 0 and current_price > 0:
        forward_eps = round(current_price / forward_pe, 2)
        print(f"  forward_eps derived from price/forward_pe: {forward_eps:.2f}")

    fcf_margin = (free_cashflow / total_revenue) if total_revenue > 0 and free_cashflow > 0 else 0.0
    anchor_pe  = forward_pe if forward_pe > 0 else (trailing_pe if trailing_pe > 0 else 0)

    print(f"  Scenario math inputs: price={current_price}, trailing_eps={trailing_eps:.2f}, "
          f"forward_eps={forward_eps:.2f}, shares={shares:.0f}, "
          f"op_margin={operating_margin:.3f}, net_margin={profit_margin:.3f}, "
          f"fcf_margin={fcf_margin:.3f}, anchor_pe={anchor_pe:.1f}")

    prob_output    = compute_scenario_probabilities(llm_output)
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
            operating_margin, profit_margin, fcf_margin)

    # ── Aggregates ─────────────────────────────────────────────────────────
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
    }


# ══════════════════════════════════════════════════════════════
# QGLP SCORING (shared with screener.py)
# ══════════════════════════════════════════════════════════════

def compute_qglp_score(metrics):
    score = 0.0

    # PEG — 30 pts. Thesis: AVGO PEG=0.60, "most compelling valuation metric"
    peg = metrics.get("peg_ratio", 999)
    if peg and peg > 0:
        score += max(0, min(30, 30 * (1 - (peg - 0.5) / 1.5)))

    # ROE — 25 pts
    roe = metrics.get("roe", 0)
    if roe and roe > 0:
        score += max(0, min(25, 25 * (roe / 0.30)))

    # Earnings CAGR — 25 pts.
    # FIX C: key was "earnings_cagr" but dict uses "eps_cagr" / "net_income_cagr".
    # Falls back through all available CAGR keys so AVGO's ~21% CAGR scores correctly.
    cagr = (metrics.get("eps_cagr")
            or metrics.get("net_income_cagr")
            or metrics.get("revenue_cagr")
            or metrics.get("earnings_cagr")
            or 0)
    if cagr and cagr > 0:
        score += max(0, min(25, 25 * (cagr / 0.25)))

    # FCF yield — 10 pts
    fcf_y = metrics.get("fcf_yield", 0)
    if fcf_y and fcf_y > 0:
        score += max(0, min(10, 10 * (fcf_y / 0.05)))

    # Debt/equity — 10 pts
    # FIX C (secondary): key was "debt_equity" but calc() stores "debt_to_equity"
    de = metrics.get("debt_to_equity", metrics.get("debt_equity"))
    if de is not None and de >= 0:
        score += max(0, min(10, 10 * (1 - de)))

    return round(score, 1)
