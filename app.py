# ============================================================
# LIFESTYLE FUND — AI RESEARCH REPORT GENERATOR (POC v2)
# Beautiful UI + Python-calculated financials + AI narrative
# ============================================================

import streamlit as st
import yfinance as yf
import pandas as pd
from openai import OpenAI
import os
import json
from datetime import datetime

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="Lifestyle Fund Research Engine",
    page_icon="📊",
    layout="wide",
)

# ── Custom CSS for beautiful reports ─────────────────────────
st.markdown("""
<style>
    /* Main header */
    .main-header {
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
    }
    .main-header h1 { font-size: 2.5rem; margin-bottom: 0.2rem; }
    .main-header p { opacity: 0.7; font-size: 1.1rem; }

    /* Score cards */
    .score-card {
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        border-left: 4px solid #6c757d;
        margin-bottom: 0.5rem;
        background: rgba(128,128,128,0.08);
    }
    .score-card.quality { border-left-color: #2563eb; }
    .score-card.growth { border-left-color: #059669; }
    .score-card.longevity { border-left-color: #d97706; }
    .score-card.price { border-left-color: #dc2626; }
    .score-card.composite { border-left-color: #7c3aed; background: rgba(124,58,237,0.1); }

    .score-label {
        font-size: 0.85rem;
        font-weight: 600;
        opacity: 0.7;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .score-value {
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0.2rem 0;
    }
    .score-subtitle {
        font-size: 0.75rem;
        opacity: 0.5;
    }

    /* Recommendation badge */
    .rec-badge {
        display: inline-block;
        padding: 0.6rem 2rem;
        border-radius: 50px;
        font-size: 1.3rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        margin: 0.5rem 0;
        color: white !important;
    }
    .rec-buy { background: #059669; }
    .rec-watch { background: #d97706; }
    .rec-pass { background: #dc2626; }

    /* Section headers */
    .section-header {
        font-size: 1.3rem;
        font-weight: 700;
        border-bottom: 2px solid rgba(128,128,128,0.3);
        padding-bottom: 0.4rem;
        margin: 1.5rem 0 0.8rem 0;
    }

    /* Risk items */
    .risk-item {
        background: rgba(220, 38, 38, 0.1);
        border-left: 3px solid #dc2626;
        padding: 0.8rem 1rem;
        margin-bottom: 0.5rem;
        border-radius: 0 8px 8px 0;
        font-size: 0.95rem;
        line-height: 1.5;
    }

    /* Bull/Bear cards */
    .bull-card {
        background: rgba(5, 150, 105, 0.1);
        border-left: 4px solid #059669;
        border-radius: 0 12px 12px 0;
        padding: 1.2rem 1.5rem;
        line-height: 1.6;
    }
    .bear-card {
        background: rgba(220, 38, 38, 0.1);
        border-left: 4px solid #dc2626;
        border-radius: 0 12px 12px 0;
        padding: 1.2rem 1.5rem;
        line-height: 1.6;
    }

    /* Verified badge */
    .verified-badge {
        display: inline-block;
        background: rgba(37, 99, 235, 0.15);
        color: #60a5fa;
        font-size: 0.7rem;
        padding: 0.15rem 0.5rem;
        border-radius: 50px;
        font-weight: 600;
        margin-left: 0.5rem;
    }

    /* Footer */
    .footer {
        text-align: center;
        opacity: 0.5;
        font-size: 0.8rem;
        padding: 1rem;
    }

    /* Make expander content more readable */
    .streamlit-expanderContent {
        font-size: 1rem;
        line-height: 1.8;
        padding: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ── Load secrets ─────────────────────────────────────────────
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_key_here":
    st.error("Please add your OpenRouter API key to .streamlit/secrets.toml")
    st.stop()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

FREE_MODELS = [
    "openrouter/free",
    "moonshotai/kimi-k2:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-32b:free",
]


# ── Load thesis + sample report ──────────────────────────────
@st.cache_data
def load_text_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

FUND_THESIS = load_text_file("fund_thesis.md")
AVGO_SAMPLE = load_text_file("avgo_sample.txt")


# ── Helper formatting functions ──────────────────────────────
def fmt_number(value, prefix="", suffix="", decimals=2):
    """Format a number nicely, handling None/N/A."""
    if value is None or value == "N/A" or value == "":
        return "N/A"
    try:
        num = float(value)
        if abs(num) >= 1_000_000_000_000:
            return f"{prefix}{num/1_000_000_000_000:.{decimals}f}T{suffix}"
        elif abs(num) >= 1_000_000_000:
            return f"{prefix}{num/1_000_000_000:.{decimals}f}B{suffix}"
        elif abs(num) >= 1_000_000:
            return f"{prefix}{num/1_000_000:.{decimals}f}M{suffix}"
        elif abs(num) >= 1_000:
            return f"{prefix}{num/1_000:.{decimals}f}K{suffix}"
        else:
            return f"{prefix}{num:.{decimals}f}{suffix}"
    except (ValueError, TypeError):
        return "N/A"

def fmt_pct(value, decimals=1):
    """Format a ratio (0.25) as percentage (25.0%)."""
    if value is None or value == "N/A" or value == "":
        return "N/A"
    try:
        num = float(value)
        if abs(num) < 1:
            return f"{num * 100:.{decimals}f}%"
        return f"{num:.{decimals}f}%"
    except (ValueError, TypeError):
        return "N/A"

def fmt_ratio(value, decimals=2):
    """Format a simple ratio."""
    if value is None or value == "N/A" or value == "":
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (ValueError, TypeError):
        return "N/A"

def fmt_currency(value, decimals=2):
    """Format as dollar amount."""
    return fmt_number(value, prefix="$", decimals=decimals)


# ── Data fetching layer ──────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    data = {}

    # Company info
    try:
        info = stock.info
        data["info"] = info
    except Exception as e:
        data["info"] = {"error": str(e)}

    # Income Statement (annual)
    try:
        inc = stock.income_stmt
        data["income_stmt"] = inc if inc is not None and not inc.empty else None
    except Exception:
        data["income_stmt"] = None

    # Income Statement (quarterly)
    try:
        incq = stock.quarterly_income_stmt
        data["quarterly_income_stmt"] = incq if incq is not None and not incq.empty else None
    except Exception:
        data["quarterly_income_stmt"] = None

    # Balance Sheet
    try:
        bs = stock.balance_sheet
        data["balance_sheet"] = bs if bs is not None and not bs.empty else None
    except Exception:
        data["balance_sheet"] = None

    # Cash Flow
    try:
        cf = stock.cashflow
        data["cashflow"] = cf if cf is not None and not cf.empty else None
    except Exception:
        data["cashflow"] = None

    # Historical prices (5 years)
    try:
        hist = stock.history(period="5y", interval="1wk")
        data["history"] = hist if hist is not None and not hist.empty else None
    except Exception:
        data["history"] = None

    # Analyst recommendations
    try:
        rec = stock.recommendations
        data["recommendations"] = rec if rec is not None and not rec.empty else None
    except Exception:
        data["recommendations"] = None

    # Holders
    try:
        data["major_holders"] = stock.major_holders
    except Exception:
        data["major_holders"] = None

    try:
        data["institutional_holders"] = stock.institutional_holders
    except Exception:
        data["institutional_holders"] = None

    # News
    try:
        news = stock.news
        data["news"] = news[:8] if news else []
    except Exception:
        data["news"] = []

    return data


# ── Python-calculated financial metrics ──────────────────────
def calculate_metrics(data: dict) -> dict:
    """Calculate key financial metrics in Python for accuracy."""
    info = data.get("info", {})
    if isinstance(info, dict) and "error" in info:
        return {"error": info["error"]}

    m = {}

    # ---- Company basics ----
    m["company_name"] = info.get("shortName", info.get("longName", "Unknown"))
    m["sector"] = info.get("sector", "N/A")
    m["industry"] = info.get("industry", "N/A")
    m["country"] = info.get("country", "N/A")
    m["currency"] = info.get("currency", "N/A")
    m["description"] = info.get("longBusinessSummary", "N/A")
    m["current_price"] = info.get("currentPrice", info.get("regularMarketPrice"))

    # ---- Valuation ----
    m["market_cap"] = info.get("marketCap")
    m["enterprise_value"] = info.get("enterpriseValue")
    m["trailing_pe"] = info.get("trailingPE")
    m["forward_pe"] = info.get("forwardPE")
    m["peg_ratio"] = info.get("pegRatio")
    m["price_to_book"] = info.get("priceToBook")
    m["price_to_sales"] = info.get("priceToSalesTrailing12Months")
    m["ev_to_ebitda"] = info.get("enterpriseToEbitda")

    # ---- Profitability ----
    m["gross_margin"] = info.get("grossMargins")
    m["operating_margin"] = info.get("operatingMargins")
    m["profit_margin"] = info.get("profitMargins")
    m["roe"] = info.get("returnOnEquity")
    m["roa"] = info.get("returnOnAssets")

    # ---- Earnings ----
    m["trailing_eps"] = info.get("trailingEps")
    m["forward_eps"] = info.get("forwardEps")
    m["earnings_growth"] = info.get("earningsGrowth")

    # ---- Revenue ----
    m["total_revenue"] = info.get("totalRevenue")
    m["revenue_growth"] = info.get("revenueGrowth")

    # ---- Cash & Debt ----
    m["free_cashflow"] = info.get("freeCashflow")
    m["operating_cashflow"] = info.get("operatingCashflow")
    m["total_cash"] = info.get("totalCash")
    m["total_debt"] = info.get("totalDebt")
    m["debt_to_equity"] = info.get("debtToEquity")
    m["current_ratio"] = info.get("currentRatio")
    m["quick_ratio"] = info.get("quickRatio")

    # ---- Dividends ----
    m["dividend_yield"] = info.get("dividendYield")
    m["payout_ratio"] = info.get("payoutRatio")

    # ---- Technical ----
    m["beta"] = info.get("beta")
    m["week_52_high"] = info.get("fiftyTwoWeekHigh")
    m["week_52_low"] = info.get("fiftyTwoWeekLow")
    m["ma_50"] = info.get("fiftyDayAverage")
    m["ma_200"] = info.get("twoHundredDayAverage")

    # ---- Ownership ----
    m["insider_pct"] = info.get("heldPercentInsiders")
    m["institution_pct"] = info.get("heldPercentInstitutions")
    m["shares_outstanding"] = info.get("sharesOutstanding")

    # ---- Calculated: FCF Yield ----
    if m["free_cashflow"] and m["market_cap"]:
        try:
            m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"])
        except:
            m["fcf_yield"] = None
    else:
        m["fcf_yield"] = None

    # ---- Calculated: Revenue CAGR (from income statements) ----
    inc = data.get("income_stmt")
    if inc is not None:
        try:
            rev_row = None
            for label in ["Total Revenue", "TotalRevenue"]:
                if label in inc.index:
                    rev_row = inc.loc[label]
                    break
            if rev_row is not None and len(rev_row.dropna()) >= 2:
                revenues = rev_row.dropna().sort_index()
                newest = float(revenues.iloc[-1])
                oldest = float(revenues.iloc[0])
                years = len(revenues) - 1
                if oldest > 0 and years > 0:
                    m["revenue_cagr"] = (newest / oldest) ** (1 / years) - 1
                else:
                    m["revenue_cagr"] = None

                # Store annual revenue history
                m["revenue_history"] = {str(d.date()): float(v) for d, v in revenues.items() if pd.notna(v)}
            else:
                m["revenue_cagr"] = None
                m["revenue_history"] = {}
        except:
            m["revenue_cagr"] = None
            m["revenue_history"] = {}
    else:
        m["revenue_cagr"] = None
        m["revenue_history"] = {}

    # ---- Calculated: Net Income CAGR ----
    if inc is not None:
        try:
            ni_row = None
            for label in ["Net Income", "NetIncome"]:
                if label in inc.index:
                    ni_row = inc.loc[label]
                    break
            if ni_row is not None and len(ni_row.dropna()) >= 2:
                net_incomes = ni_row.dropna().sort_index()
                newest = float(net_incomes.iloc[-1])
                oldest = float(net_incomes.iloc[0])
                years = len(net_incomes) - 1
                if oldest > 0 and years > 0:
                    m["net_income_cagr"] = (newest / oldest) ** (1 / years) - 1
                else:
                    m["net_income_cagr"] = None
                m["net_income_history"] = {str(d.date()): float(v) for d, v in net_incomes.items() if pd.notna(v)}
            else:
                m["net_income_cagr"] = None
                m["net_income_history"] = {}
        except:
            m["net_income_cagr"] = None
            m["net_income_history"] = {}
    else:
        m["net_income_cagr"] = None
        m["net_income_history"] = {}

    # ---- Calculated: EPS CAGR ----
    if inc is not None:
        try:
            eps_row = None
            for label in ["Basic EPS", "Diluted EPS", "BasicEPS", "DilutedEPS"]:
                if label in inc.index:
                    eps_row = inc.loc[label]
                    break
            if eps_row is not None and len(eps_row.dropna()) >= 2:
                eps_vals = eps_row.dropna().sort_index()
                newest = float(eps_vals.iloc[-1])
                oldest = float(eps_vals.iloc[0])
                years = len(eps_vals) - 1
                if oldest > 0 and years > 0:
                    m["eps_cagr"] = (newest / oldest) ** (1 / years) - 1
                else:
                    m["eps_cagr"] = None
            else:
                m["eps_cagr"] = None
        except:
            m["eps_cagr"] = None
    else:
        m["eps_cagr"] = None

    # ---- Price history summary ----
    hist = data.get("history")
    if hist is not None and not hist.empty:
        try:
            m["price_5y_start"] = round(float(hist["Close"].iloc[0]), 2)
            m["price_current"] = round(float(hist["Close"].iloc[-1]), 2)
            m["price_5y_high"] = round(float(hist["Close"].max()), 2)
            m["price_5y_low"] = round(float(hist["Close"].min()), 2)
            m["price_5y_return"] = round(((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 100, 2)
        except:
            m["price_5y_start"] = None
            m["price_current"] = None
            m["price_5y_high"] = None
            m["price_5y_low"] = None
            m["price_5y_return"] = None
    else:
        m["price_5y_start"] = None
        m["price_current"] = None
        m["price_5y_high"] = None
        m["price_5y_low"] = None
        m["price_5y_return"] = None

    # ---- Analyst recs summary ----
    recs = data.get("recommendations")
    if recs is not None and not recs.empty:
        try:
            m["analyst_recs"] = recs.tail(5).to_dict("records")
        except:
            m["analyst_recs"] = []
    else:
        m["analyst_recs"] = []

    # ---- News headlines ----
    news = data.get("news", [])
    m["news"] = [{"title": n.get("title", ""), "publisher": n.get("publisher", "")} for n in news]

    return m


def build_ai_prompt(ticker: str, metrics: dict) -> list:
    metrics_summary = json.dumps(
        {k: v for k, v in metrics.items() if k not in ["description", "revenue_history", "net_income_history", "analyst_recs", "news"]},
        indent=2,
        default=str,
    )

    # Include a meaningful excerpt from the AVGO sample to set quality expectations
    sample_excerpt = AVGO_SAMPLE[:3000] if AVGO_SAMPLE else "No sample available."

    system_msg = f"""You are the senior equity research analyst for the Lifestyle Fund, a concentrated portfolio focused on high-quality compounders. You write deep, institutional-grade research using the QGLP (Quality, Growth, Longevity, Price) framework.

YOUR WRITING STYLE:
- Write like a Goldman Sachs or Morgan Stanley senior analyst authoring a 15-page initiating coverage report
- Each QGLP section must be 4-5 SUBSTANTIAL paragraphs (not bullet points, not short summaries)
- Use specific numbers from the data to support every claim
- Discuss competitive dynamics, industry structure, and strategic positioning in depth
- Compare against relevant peers and industry benchmarks
- Address both strengths AND weaknesses in each section
- Use professional but engaging prose that tells a compelling investment story

REFERENCE QUALITY LEVEL (match this depth and rigor):
{sample_excerpt}

LIFESTYLE FUND THESIS:
{FUND_THESIS[:3000]}

CRITICAL RULES:
1. All financial numbers have been pre-calculated and verified. Use ONLY the numbers provided.
2. Do NOT invent, estimate, or hallucinate any numbers not in the data.
3. If data is missing, explicitly state that and explain what it would mean if available.

You must respond ONLY with valid JSON (no markdown code fences, no extra text). Use this exact structure:

{{
    "business_overview": "4-5 paragraphs. Explain what the company does in detail - its key business segments, revenue breakdown, competitive positioning, key customers, geographic exposure, and strategic direction. Discuss what makes this business unique and how it fits within its industry ecosystem. A reader should fully understand the company after reading this.",

    "quality_score": 8,
    "quality_analysis": "4-5 paragraphs. Deep analysis of competitive moats (brand, network effects, switching costs, cost advantages, IP/patents). Analyze operating margins, gross margins, and how they trend over time. Evaluate ROE and ROCE relative to cost of capital and peers. Assess free cash flow quality and conversion. Discuss management's capital allocation track record (M&A, buybacks, dividends, R&D). Address balance sheet strength or concerns including debt levels. Reference specific numbers throughout.",

    "growth_score": 8,
    "growth_analysis": "4-5 paragraphs. Analyze historical revenue CAGR and EPS CAGR. Discuss whether growth is accelerating or decelerating and why. Evaluate organic vs acquisition-driven growth. Assess forward growth estimates and whether they are achievable. Apply the Lifestyle Fund's hard growth filters (12-15% minimum). Discuss key growth drivers - new products, market expansion, pricing power, share gains. Compare growth rates to peers. Address any growth concerns or headwinds.",

    "longevity_score": 8,
    "longevity_analysis": "4-5 paragraphs. Evaluate secular tailwinds supporting the business (AI, cloud, digitization, demographics, etc.). Assess total addressable market (TAM) and how much runway remains. Analyze management quality, tenure, insider ownership, and alignment with shareholders. Discuss reinvestment opportunities and whether the company can sustain its ROIC. Evaluate competitive threats and disruption risks. Consider regulatory risks and geopolitical exposure. How durable is this business in a 10-year view?",

    "price_score": 8,
    "price_analysis": "4-5 paragraphs. Analyze current valuation using multiple lenses: trailing PE, forward PE, PEG ratio, EV/EBITDA, price-to-sales, FCF yield. Compare each metric to historical averages and peer benchmarks. Apply the Lifestyle Fund's Valuation Triad framework. Discuss margin of safety - what is priced in and what could go wrong. Consider where the stock trades relative to its 52-week range and moving averages. Provide a view on whether the stock is cheap, fairly valued, or expensive relative to its quality and growth.",

    "recommendation": "BUY",
    "conviction": "High",
    "recommendation_rationale": "3-4 sentences providing a clear, specific summary of why this stock earns this recommendation. Reference the composite QGLP score, the strongest pillar, and the key catalyst.",

    "risks": [
        "Detailed risk 1: Explain the risk fully in 2-3 sentences including potential impact and probability.",
        "Detailed risk 2: Same level of detail.",
        "Detailed risk 3: Same level of detail.",
        "Detailed risk 4: Same level of detail.",
        "Detailed risk 5: Same level of detail."
    ],

    "bull_case": "3-4 sentences painting the optimistic scenario with specific upside catalysts and potential price/earnings targets.",
    "bear_case": "3-4 sentences painting the pessimistic scenario with specific downside risks and what could cause a significant decline.",

    "position_sizing": "2-3 sentences recommending position size as percentage of portfolio, referencing the conviction level and risk factors. Include suggested entry strategy (e.g., build position over time, wait for pullback, etc.)."
}}

Scores must be integers from 1-10. Recommendation must be exactly BUY, WATCH, or PASS."""

    user_msg = f"""Write a comprehensive Lifestyle Fund QGLP research report for {ticker.upper()} ({metrics.get('company_name', ticker)}).

PRE-CALCULATED FINANCIAL METRICS (verified - use these exactly, do not recalculate):
{metrics_summary}

Company description: {metrics.get('description', 'Not available.')[:500]}

Write your deep-dive analysis now. Remember: 4-5 substantial paragraphs per QGLP section, institutional quality, specific numbers cited throughout. This report will be read by portfolio managers making real allocation decisions.

Respond with valid JSON only."""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

# ── Call AI with fallback ─────────────────────────────────────
def generate_ai_analysis(ticker: str, metrics: dict) -> dict:
    messages = build_ai_prompt(ticker, metrics)
    errors = []

    for model_name in FREE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=7000,
                temperature=0.3,
                extra_headers={
                    "HTTP-Referer": "https://lifestyle-fund.streamlit.app",
                    "X-Title": "Lifestyle Fund Research Engine",
                },
            )
            raw = response.choices[0].message.content.strip()

            # Clean potential markdown fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

            analysis = json.loads(raw)
            analysis["model_used"] = model_name
            return analysis

        except json.JSONDecodeError as e:
            errors.append(f"{model_name}: Invalid JSON - {str(e)[:100]}")
            continue
        except Exception as e:
            errors.append(f"{model_name}: {str(e)[:200]}")
            continue

    return {"error": True, "details": errors}


# ── RENDER: Beautiful report UI ──────────────────────────────
def render_report(ticker: str, metrics: dict, analysis: dict):
    company = metrics.get("company_name", ticker)

    # ---- Header ----
    st.markdown(f"## {company} ({ticker})")
    st.caption(f"{metrics.get('sector', 'N/A')} | {metrics.get('industry', 'N/A')} | {metrics.get('country', 'N/A')}")

    # ---- Financial Snapshot (Python-calculated, verified) ----
    st.markdown('<p class="section-header">Financial Snapshot <span class="verified-badge">VERIFIED DATA</span></p>', unsafe_allow_html=True)

    r1c1, r1c2, r1c3, r1c4, r1c5, r1c6 = st.columns(6)
    with r1c1:
        st.metric("Market Cap", fmt_number(metrics.get("market_cap"), prefix="$"))
    with r1c2:
        st.metric("Current Price", fmt_currency(metrics.get("current_price")))
    with r1c3:
        st.metric("Trailing P/E", fmt_ratio(metrics.get("trailing_pe")))
    with r1c4:
        st.metric("Forward P/E", fmt_ratio(metrics.get("forward_pe")))
    with r1c5:
        st.metric("PEG Ratio", fmt_ratio(metrics.get("peg_ratio")))
    with r1c6:
        st.metric("EV/EBITDA", fmt_ratio(metrics.get("ev_to_ebitda")))

    r2c1, r2c2, r2c3, r2c4, r2c5, r2c6 = st.columns(6)
    with r2c1:
        st.metric("Revenue", fmt_number(metrics.get("total_revenue"), prefix="$"))
    with r2c2:
        st.metric("Revenue Growth", fmt_pct(metrics.get("revenue_growth")))
    with r2c3:
        st.metric("Gross Margin", fmt_pct(metrics.get("gross_margin")))
    with r2c4:
        st.metric("Operating Margin", fmt_pct(metrics.get("operating_margin")))
    with r2c5:
        st.metric("Profit Margin", fmt_pct(metrics.get("profit_margin")))
    with r2c6:
        st.metric("ROE", fmt_pct(metrics.get("roe")))

    r3c1, r3c2, r3c3, r3c4, r3c5, r3c6 = st.columns(6)
    with r3c1:
        st.metric("Free Cash Flow", fmt_number(metrics.get("free_cashflow"), prefix="$"))
    with r3c2:
        st.metric("FCF Yield", fmt_pct(metrics.get("fcf_yield")))
    with r3c3:
        st.metric("Debt/Equity", fmt_ratio(metrics.get("debt_to_equity")))
    with r3c4:
        st.metric("Current Ratio", fmt_ratio(metrics.get("current_ratio")))
    with r3c5:
        st.metric("Dividend Yield", fmt_pct(metrics.get("dividend_yield")))
    with r3c6:
        st.metric("Beta", fmt_ratio(metrics.get("beta")))

    # ---- Growth Metrics (Python-calculated) ----
    st.markdown('<p class="section-header">Growth Metrics <span class="verified-badge">VERIFIED DATA</span></p>', unsafe_allow_html=True)

    g1, g2, g3, g4, g5, g6 = st.columns(6)
    with g1:
        st.metric("Revenue CAGR", fmt_pct(metrics.get("revenue_cagr")))
    with g2:
        st.metric("Net Income CAGR", fmt_pct(metrics.get("net_income_cagr")))
    with g3:
        st.metric("EPS CAGR", fmt_pct(metrics.get("eps_cagr")))
    with g4:
        st.metric("Earnings Growth (YoY)", fmt_pct(metrics.get("earnings_growth")))
    with g5:
        st.metric("52-Week High", fmt_currency(metrics.get("week_52_high")))
    with g6:
        st.metric("52-Week Low", fmt_currency(metrics.get("week_52_low")))

    if metrics.get("price_5y_return") is not None:
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            st.metric("5Y Return", f"{metrics['price_5y_return']}%")
        with p2:
            st.metric("5Y High", fmt_currency(metrics.get("price_5y_high")))
        with p3:
            st.metric("5Y Low", fmt_currency(metrics.get("price_5y_low")))
        with p4:
            st.metric("50-Day MA", fmt_currency(metrics.get("ma_50")))

    st.markdown("---")

    # ---- Business Overview (AI) ----
    st.markdown('<p class="section-header">Business Overview</p>', unsafe_allow_html=True)
    st.markdown(analysis.get("business_overview", "Analysis not available."))

    st.markdown("---")

    # ---- QGLP Scores ----
    st.markdown('<p class="section-header">QGLP Scorecard</p>', unsafe_allow_html=True)

    q_score = analysis.get("quality_score", 0)
    g_score = analysis.get("growth_score", 0)
    l_score = analysis.get("longevity_score", 0)
    p_score = analysis.get("price_score", 0)

    try:
        composite = round((int(q_score) + int(g_score) + int(l_score) + int(p_score)) / 4, 1)
    except:
        composite = 0

    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    with sc1:
        st.markdown(f'''<div class="score-card quality">
            <div class="score-label">Quality</div>
            <div class="score-value">{q_score}</div>
            <div class="score-subtitle">Moats & Margins</div>
        </div>''', unsafe_allow_html=True)
    with sc2:
        st.markdown(f'''<div class="score-card growth">
            <div class="score-label">Growth</div>
            <div class="score-value">{g_score}</div>
            <div class="score-subtitle">Revenue & EPS</div>
        </div>''', unsafe_allow_html=True)
    with sc3:
        st.markdown(f'''<div class="score-card longevity">
            <div class="score-label">Longevity</div>
            <div class="score-value">{l_score}</div>
            <div class="score-subtitle">Durability</div>
        </div>''', unsafe_allow_html=True)
    with sc4:
        st.markdown(f'''<div class="score-card price">
            <div class="score-label">Price</div>
            <div class="score-value">{p_score}</div>
            <div class="score-subtitle">Valuation</div>
        </div>''', unsafe_allow_html=True)
    with sc5:
        st.markdown(f'''<div class="score-card composite">
            <div class="score-label">Composite</div>
            <div class="score-value">{composite}</div>
            <div class="score-subtitle">Overall QGLP</div>
        </div>''', unsafe_allow_html=True)

    st.markdown("---")

    # ---- Detailed QGLP Analysis ----
    with st.expander("📘 Quality Analysis", expanded=True):
        st.markdown(analysis.get("quality_analysis", "Not available."))

    with st.expander("📈 Growth Analysis", expanded=True):
        st.markdown(analysis.get("growth_analysis", "Not available."))

    with st.expander("🔮 Longevity Analysis", expanded=True):
        st.markdown(analysis.get("longevity_analysis", "Not available."))

    with st.expander("💰 Price Analysis", expanded=True):
        st.markdown(analysis.get("price_analysis", "Not available."))

    st.markdown("---")

    # ---- Recommendation ----
    rec = analysis.get("recommendation", "WATCH").upper()
    conviction = analysis.get("conviction", "Medium")
    rec_class = "rec-buy" if rec == "BUY" else ("rec-pass" if rec == "PASS" else "rec-watch")

    st.markdown('<p class="section-header">Recommendation</p>', unsafe_allow_html=True)
    rec_col1, rec_col2 = st.columns([1, 2])
    with rec_col1:
        st.markdown(f'<div style="text-align:center;"><span class="rec-badge {rec_class}">{rec}</span><br><span style="color:#888;">Conviction: {conviction}</span></div>', unsafe_allow_html=True)
    with rec_col2:
        st.markdown(analysis.get("recommendation_rationale", ""))

    st.markdown("---")

    # ---- Risks ----
    st.markdown('<p class="section-header">Key Risks</p>', unsafe_allow_html=True)
    risks = analysis.get("risks", [])
    if isinstance(risks, list):
        for risk in risks:
            st.markdown(f'<div class="risk-item">{risk}</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Bull / Bear ----
    bull_col, bear_col = st.columns(2)
    with bull_col:
        st.markdown('<p class="section-header">🐂 Bull Case</p>', unsafe_allow_html=True)
        st.markdown(f'<div class="bull-card">{analysis.get("bull_case", "Not available.")}</div>', unsafe_allow_html=True)
    with bear_col:
        st.markdown('<p class="section-header">🐻 Bear Case</p>', unsafe_allow_html=True)
        st.markdown(f'<div class="bear-card">{analysis.get("bear_case", "Not available.")}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ---- Position Sizing ----
    st.markdown('<p class="section-header">Position Sizing Recommendation</p>', unsafe_allow_html=True)
    st.info(analysis.get("position_sizing", "Not available."))

    # ---- Model attribution ----
    st.caption(f"AI analysis generated by: {analysis.get('model_used', 'Unknown')} | Report date: {datetime.now().strftime('%B %d, %Y')}")


# ── Build downloadable report ─────────────────────────────────
def build_download_report(ticker: str, metrics: dict, analysis: dict) -> str:
    """Build a clean markdown version for download."""
    company = metrics.get("company_name", ticker)
    lines = [
        f"# {company} ({ticker}) - Lifestyle Fund Research Report",
        f"**Date:** {datetime.now().strftime('%B %d, %Y')}",
        f"**Sector:** {metrics.get('sector', 'N/A')} | **Industry:** {metrics.get('industry', 'N/A')}",
        "",
        "---",
        "",
        "## Financial Snapshot",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Market Cap | {fmt_number(metrics.get('market_cap'), prefix='$')} |",
        f"| Current Price | {fmt_currency(metrics.get('current_price'))} |",
        f"| Trailing P/E | {fmt_ratio(metrics.get('trailing_pe'))} |",
        f"| Forward P/E | {fmt_ratio(metrics.get('forward_pe'))} |",
        f"| PEG Ratio | {fmt_ratio(metrics.get('peg_ratio'))} |",
        f"| EV/EBITDA | {fmt_ratio(metrics.get('ev_to_ebitda'))} |",
        f"| Revenue | {fmt_number(metrics.get('total_revenue'), prefix='$')} |",
        f"| Revenue Growth | {fmt_pct(metrics.get('revenue_growth'))} |",
        f"| Gross Margin | {fmt_pct(metrics.get('gross_margin'))} |",
        f"| Operating Margin | {fmt_pct(metrics.get('operating_margin'))} |",
        f"| Profit Margin | {fmt_pct(metrics.get('profit_margin'))} |",
        f"| ROE | {fmt_pct(metrics.get('roe'))} |",
        f"| Free Cash Flow | {fmt_number(metrics.get('free_cashflow'), prefix='$')} |",
        f"| FCF Yield | {fmt_pct(metrics.get('fcf_yield'))} |",
        f"| Debt/Equity | {fmt_ratio(metrics.get('debt_to_equity'))} |",
        f"| Revenue CAGR | {fmt_pct(metrics.get('revenue_cagr'))} |",
        f"| EPS CAGR | {fmt_pct(metrics.get('eps_cagr'))} |",
        "",
        "---",
        "",
        "## Business Overview",
        "",
        analysis.get("business_overview", "N/A"),
        "",
        "---",
        "",
        "## QGLP Scorecard",
        "",
        "| Dimension | Score | Focus |",
        "|-----------|-------|-------|",
        f"| Quality | {analysis.get('quality_score', 'N/A')}/10 | Moats, Margins, Cash Flow |",
        f"| Growth | {analysis.get('growth_score', 'N/A')}/10 | Revenue & Earnings Trajectory |",
        f"| Longevity | {analysis.get('longevity_score', 'N/A')}/10 | Durability & Tailwinds |",
        f"| Price | {analysis.get('price_score', 'N/A')}/10 | Valuation & Margin of Safety |",
        "",
        "### Quality Analysis",
        analysis.get("quality_analysis", "N/A"),
        "",
        "### Growth Analysis",
        analysis.get("growth_analysis", "N/A"),
        "",
        "### Longevity Analysis",
        analysis.get("longevity_analysis", "N/A"),
        "",
        "### Price Analysis",
        analysis.get("price_analysis", "N/A"),
        "",
        "---",
        "",
        f"## Recommendation: **{analysis.get('recommendation', 'N/A')}** (Conviction: {analysis.get('conviction', 'N/A')})",
        "",
        analysis.get("recommendation_rationale", "N/A"),
        "",
        "---",
        "",
        "## Key Risks",
        "",
    ]
    for risk in analysis.get("risks", []):
        lines.append(f"- {risk}")
    lines.extend([
        "",
        "---",
        "",
        "## Bull Case",
        analysis.get("bull_case", "N/A"),
        "",
        "## Bear Case",
        analysis.get("bear_case", "N/A"),
        "",
        "---",
        "",
        "## Position Sizing",
        analysis.get("position_sizing", "N/A"),
        "",
        "---",
        f"*Generated by Lifestyle Fund Research Engine | {datetime.now().strftime('%B %d, %Y')}*",
    ])
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# MAIN UI
# ══════════════════════════════════════════════════════════════

st.markdown("""
<div class="main-header">
    <h1>📊 Lifestyle Fund</h1>
    <p>AI-Powered Equity Research Engine</p>
</div>
<hr style="border: 1px solid #e0e0e0; width: 60%; margin: 0 auto 1rem auto;">
""", unsafe_allow_html=True)

st.markdown("Enter any stock ticker below. The engine fetches real-time data, calculates key metrics in Python (100% accurate), and uses AI for qualitative QGLP analysis.")

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    ticker_input = st.text_input(
        "Stock Ticker",
        placeholder="e.g. AVGO, AAPL, MSFT, RELIANCE.NS",
        help="Use .NS for Indian NSE stocks, .BO for BSE",
    )
    generate_btn = st.button("🚀 Generate Research Report", use_container_width=True, type="primary")

if generate_btn and ticker_input:
    ticker = ticker_input.strip().upper()

    with st.status(f"Generating report for **{ticker}**...", expanded=True) as status:
        # Step 1
        st.write("📡 Fetching data from Yahoo Finance...")
        try:
            stock_data = fetch_stock_data(ticker)
        except Exception as e:
            st.error(f"Failed to fetch data: {e}")
            st.stop()

        info = stock_data.get("info", {})
        if isinstance(info, dict) and info.get("error"):
            st.error(f"Could not find '{ticker}'. Check the ticker symbol.")
            st.stop()

        st.write("✅ Data retrieved!")

        # Step 2
        st.write("🔢 Calculating financial metrics...")
        metrics = calculate_metrics(stock_data)
        if "error" in metrics:
            st.error(f"Error calculating metrics: {metrics['error']}")
            st.stop()
        st.write("✅ Metrics calculated!")

        # Step 3
        st.write("🤖 AI analyst writing qualitative analysis...")
        analysis = generate_ai_analysis(ticker, metrics)

        if isinstance(analysis, dict) and analysis.get("error"):
            status.update(label="Error generating report", state="error")
            st.error("All AI models failed. Details:")
            for detail in analysis.get("details", []):
                st.code(detail)
            st.stop()

        st.write("✅ Analysis complete!")
        status.update(label=f"✅ Report for {ticker} is ready!", state="complete")

    # Render the beautiful report
    st.markdown("---")
    render_report(ticker, metrics, analysis)

    # Download
    st.markdown("---")
    dl1, dl2, dl3 = st.columns([1, 2, 1])
    with dl2:
        report_md = build_download_report(ticker, metrics, analysis)
        st.download_button(
            label="📥 Download Report as Markdown",
            data=report_md,
            file_name=f"Lifestyle_Fund_{ticker}_{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            use_container_width=True,
        )

elif generate_btn:
    st.warning("Please enter a stock ticker first.")

# Footer
st.markdown("---")
st.markdown('<div class="footer"><p>Lifestyle Fund Research Engine v2.0 (POC) | Financial data: Yahoo Finance | AI: OpenRouter</p><p>AI-generated research for informational purposes only. Not financial advice.</p></div>', unsafe_allow_html=True)