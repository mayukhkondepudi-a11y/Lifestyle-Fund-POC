# ============================================================
# LIFESTYLE FUND — AI RESEARCH REPORT GENERATOR (POC)
# Single-file Streamlit app — OpenRouter Edition
# ============================================================

import streamlit as st
import yfinance as yf
import pandas as pd
from openai import OpenAI
import os
from datetime import datetime

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="Lifestyle Fund Research Engine",
    page_icon="📊",
    layout="wide",
)

# ── Load secrets ─────────────────────────────────────────────
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_key_here":
    st.error("⚠️ Please add your OpenRouter API key to .streamlit/secrets.toml")
    st.stop()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ── Available free models (fallback chain) ────────────────────
FREE_MODELS = [
    "openrouter/free",
    "moonshotai/kimi-k2:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-32b:free",
]

# ── Load thesis + sample report from disk ────────────────────
@st.cache_data
def load_text_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"[File not found: {filepath}]"


FUND_THESIS = load_text_file("fund_thesis.md")
AVGO_SAMPLE = load_text_file("avgo_sample.txt")


# ── Data fetching layer ──────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    data = {}

    try:
        info = stock.info
        data["info"] = {
            "shortName": info.get("shortName", ticker),
            "longName": info.get("longName", ""),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "country": info.get("country", "N/A"),
            "currency": info.get("currency", "N/A"),
            "marketCap": info.get("marketCap", "N/A"),
            "enterpriseValue": info.get("enterpriseValue", "N/A"),
            "trailingPE": info.get("trailingPE", "N/A"),
            "forwardPE": info.get("forwardPE", "N/A"),
            "pegRatio": info.get("pegRatio", "N/A"),
            "priceToBook": info.get("priceToBook", "N/A"),
            "priceToSalesTrailing12Months": info.get("priceToSalesTrailing12Months", "N/A"),
            "enterpriseToEbitda": info.get("enterpriseToEbitda", "N/A"),
            "trailingEps": info.get("trailingEps", "N/A"),
            "forwardEps": info.get("forwardEps", "N/A"),
            "bookValue": info.get("bookValue", "N/A"),
            "returnOnEquity": info.get("returnOnEquity", "N/A"),
            "returnOnAssets": info.get("returnOnAssets", "N/A"),
            "operatingMargins": info.get("operatingMargins", "N/A"),
            "grossMargins": info.get("grossMargins", "N/A"),
            "profitMargins": info.get("profitMargins", "N/A"),
            "debtToEquity": info.get("debtToEquity", "N/A"),
            "currentRatio": info.get("currentRatio", "N/A"),
            "quickRatio": info.get("quickRatio", "N/A"),
            "totalRevenue": info.get("totalRevenue", "N/A"),
            "revenueGrowth": info.get("revenueGrowth", "N/A"),
            "earningsGrowth": info.get("earningsGrowth", "N/A"),
            "freeCashflow": info.get("freeCashflow", "N/A"),
            "operatingCashflow": info.get("operatingCashflow", "N/A"),
            "totalCash": info.get("totalCash", "N/A"),
            "totalDebt": info.get("totalDebt", "N/A"),
            "dividendYield": info.get("dividendYield", "N/A"),
            "payoutRatio": info.get("payoutRatio", "N/A"),
            "beta": info.get("beta", "N/A"),
            "52WeekHigh": info.get("fiftyTwoWeekHigh", "N/A"),
            "52WeekLow": info.get("fiftyTwoWeekLow", "N/A"),
            "50DayMA": info.get("fiftyDayAverage", "N/A"),
            "200DayMA": info.get("twoHundredDayAverage", "N/A"),
            "sharesOutstanding": info.get("sharesOutstanding", "N/A"),
            "heldPercentInsiders": info.get("heldPercentInsiders", "N/A"),
            "heldPercentInstitutions": info.get("heldPercentInstitutions", "N/A"),
            "longBusinessSummary": info.get("longBusinessSummary", "N/A"),
            "currentPrice": info.get("currentPrice", info.get("regularMarketPrice", "N/A")),
        }
    except Exception as e:
        data["info"] = {"error": str(e)}

    try:
        inc = stock.income_stmt
        if inc is not None and not inc.empty:
            data["income_statement_annual"] = inc.to_string()
        else:
            data["income_statement_annual"] = "No data available"
    except Exception:
        data["income_statement_annual"] = "No data available"

    try:
        incq = stock.quarterly_income_stmt
        if incq is not None and not incq.empty:
            data["income_statement_quarterly"] = incq.to_string()
        else:
            data["income_statement_quarterly"] = "No data available"
    except Exception:
        data["income_statement_quarterly"] = "No data available"

    try:
        bs = stock.balance_sheet
        if bs is not None and not bs.empty:
            data["balance_sheet"] = bs.to_string()
        else:
            data["balance_sheet"] = "No data available"
    except Exception:
        data["balance_sheet"] = "No data available"

    try:
        cf = stock.cashflow
        if cf is not None and not cf.empty:
            data["cashflow"] = cf.to_string()
        else:
            data["cashflow"] = "No data available"
    except Exception:
        data["cashflow"] = "No data available"

    try:
        hist = stock.history(period="5y", interval="1wk")
        if hist is not None and not hist.empty:
            data["price_history_summary"] = {
                "5y_start_price": round(hist["Close"].iloc[0], 2),
                "current_price": round(hist["Close"].iloc[-1], 2),
                "5y_high": round(hist["Close"].max(), 2),
                "5y_low": round(hist["Close"].min(), 2),
                "5y_return_pct": round(((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 100, 2),
            }
        else:
            data["price_history_summary"] = "No data available"
    except Exception:
        data["price_history_summary"] = "No data available"

    try:
        rec = stock.recommendations
        if rec is not None and not rec.empty:
            data["analyst_recommendations"] = rec.tail(10).to_string()
        else:
            data["analyst_recommendations"] = "No data available"
    except Exception:
        data["analyst_recommendations"] = "No data available"

    try:
        mh = stock.major_holders
        if mh is not None and not mh.empty:
            data["major_holders"] = mh.to_string()
        else:
            data["major_holders"] = "No data available"
    except Exception:
        data["major_holders"] = "No data available"

    try:
        ih = stock.institutional_holders
        if ih is not None and not ih.empty:
            data["institutional_holders"] = ih.head(15).to_string()
        else:
            data["institutional_holders"] = "No data available"
    except Exception:
        data["institutional_holders"] = "No data available"

    try:
        news = stock.news
        if news:
            data["recent_news"] = [
                {"title": n.get("title", ""), "publisher": n.get("publisher", "")}
                for n in news[:8]
            ]
        else:
            data["recent_news"] = "No news available"
    except Exception:
        data["recent_news"] = "No news available"

    return data


# ── Convert data dict to readable text ────────────────────────
def data_to_text(ticker: str, data: dict) -> str:
    lines = [f"=== STOCK DATA FOR {ticker.upper()} ===\n"]

    info = data.get("info", {})
    if isinstance(info, dict) and "error" not in info:
        lines.append("--- COMPANY OVERVIEW ---")
        for k, v in info.items():
            if v not in ("N/A", None, ""):
                lines.append(f"  {k}: {v}")
        lines.append("")

    for section_key, section_title in [
        ("income_statement_annual", "ANNUAL INCOME STATEMENT"),
        ("income_statement_quarterly", "QUARTERLY INCOME STATEMENT"),
        ("balance_sheet", "BALANCE SHEET"),
        ("cashflow", "CASH FLOW STATEMENT"),
        ("analyst_recommendations", "ANALYST RECOMMENDATIONS"),
        ("major_holders", "MAJOR HOLDERS"),
        ("institutional_holders", "TOP INSTITUTIONAL HOLDERS"),
    ]:
        val = data.get(section_key, "No data available")
        if val and val != "No data available":
            lines.append(f"--- {section_title} ---")
            lines.append(str(val))
            lines.append("")

    ph = data.get("price_history_summary", {})
    if isinstance(ph, dict):
        lines.append("--- 5-YEAR PRICE HISTORY SUMMARY ---")
        for k, v in ph.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    news = data.get("recent_news", [])
    if isinstance(news, list) and news:
        lines.append("--- RECENT NEWS HEADLINES ---")
        for n in news:
            lines.append(f"  - {n.get('title', '')} ({n.get('publisher', '')})")
        lines.append("")

    return "\n".join(lines)


# ── Build the prompt ──────────────────────────────────────────
def build_prompt(ticker: str, stock_data_text: str) -> list:
    system_msg = f"""You are the senior research analyst for the Lifestyle Fund. You produce comprehensive, institutional-quality equity research reports using the QGLP framework.

CRITICAL RULES:
- Follow the Lifestyle Fund thesis and QGLP scoring EXACTLY
- Match the structure, tone, depth, and section ordering of the sample report
- Use actual numbers from the data provided. NEVER fabricate figures.
- If data is missing, note it explicitly.
- Output clean Markdown. Start with company name as level-1 heading.

============================
LIFESTYLE FUND THESIS & RULES
============================
{FUND_THESIS}

============================
REFERENCE SAMPLE REPORT FORMAT
============================
{AVGO_SAMPLE}"""

    user_msg = f"""Generate a complete Lifestyle Fund QGLP research report for {ticker.upper()} using this data:

{stock_data_text}

============================
REQUIRED SECTIONS (match the AVGO sample exactly):
1. Company name heading + Financial Snapshot table
2. Business Overview (what they do, segments, revenue mix)
3. QUALITY analysis (Score 1-10): moats, ROE, ROCE, margins, cash flow quality
4. GROWTH analysis (Score 1-10): Revenue CAGR, EPS CAGR, forward estimates, hard filters
5. LONGEVITY analysis (Score 1-10): secular tailwinds, TAM, management, reinvestment
6. PRICE analysis (Score 1-10): PEG, PE vs growth, valuation triad, margin of safety
7. QGLP Scorecard table with composite score
8. Valuation Triad table
9. Key Risks section
10. Bull/Bear Case summary
11. BUY / WATCH / PASS recommendation with conviction level
12. Position Sizing Recommendation

Write in professional analyst prose with tables in Markdown format."""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


# ── Call OpenRouter API with fallback ─────────────────────────
def generate_report(ticker: str, stock_data_text: str) -> str:
    messages = build_prompt(ticker, stock_data_text)
    errors = []

    for model_name in FREE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=8000,
                temperature=0.3,
                extra_headers={
                    "HTTP-Referer": "https://lifestyle-fund.streamlit.app",
                    "X-Title": "Lifestyle Fund Research Engine",
                },
            )
            result = response.choices[0].message.content
            if result and len(result) > 100:
                return f"*Report generated using: {model_name}*\n\n{result}"
            else:
                errors.append(f"{model_name}: Empty or short response")
        except Exception as e:
            errors.append(f"{model_name}: {str(e)[:200]}")
            continue

    error_details = "\n".join([f"- {e}" for e in errors])
    return f"## Error Generating Report\n\nAll free models failed. Details:\n\n{error_details}\n\nPlease try again in a few minutes."



# ── STREAMLIT UI ──────────────────────────────────────────────

st.markdown(
    """
    <div style="text-align: center; padding: 2rem 0 1rem 0;">
        <h1 style="color: #1a1a2e; font-size: 2.5rem; margin-bottom: 0.2rem;">📊 Lifestyle Fund</h1>
        <p style="color: #555; font-size: 1.2rem; margin-top: 0;">AI-Powered Equity Research Engine</p>
        <hr style="border: 1px solid #e0e0e0; width: 60%; margin: 1rem auto;">
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    Enter any stock ticker below and the engine will fetch real-time financial data,
    apply the **Lifestyle Fund QGLP framework**, and generate a full institutional-quality
    research report modeled after our internal format.
    """
)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    ticker_input = st.text_input(
        "Stock Ticker",
        placeholder="e.g. AVGO, AAPL, RELIANCE.NS, HDFCBANK.NS",
        help="Use .NS suffix for Indian NSE stocks, .BO for BSE stocks",
    )
    generate_btn = st.button(
        "🚀 Generate Research Report",
        use_container_width=True,
        type="primary",
    )

if generate_btn and ticker_input:
    ticker = ticker_input.strip().upper()

    with st.status(f"Generating report for **{ticker}**...", expanded=True) as status:
        st.write("📡 Fetching financial data from Yahoo Finance...")
        try:
            stock_data = fetch_stock_data(ticker)
        except Exception as e:
            st.error(f"Failed to fetch data for {ticker}: {e}")
            st.stop()

        info = stock_data.get("info", {})
        if isinstance(info, dict) and info.get("error"):
            st.error(f"Could not find stock data for '{ticker}'. Please check the ticker symbol.")
            st.stop()
        if isinstance(info, dict) and info.get("shortName", ticker) == ticker and info.get("sector") == "N/A":
            st.warning(f"Limited data found for '{ticker}'. The report may be incomplete.")

        st.write("✅ Financial data retrieved successfully!")

        st.write("🔄 Preparing data for analysis...")
        stock_data_text = data_to_text(ticker, stock_data)

        st.write("🤖 AI analyst is writing your report (may take 30-90 seconds)...")
        st.write("   Trying multiple free models for best results...")
        report = generate_report(ticker, stock_data_text)

        status.update(label=f"✅ Report for {ticker} is ready!", state="complete")

    st.markdown("---")
    st.markdown(report)

    st.markdown("---")
    col_dl1, col_dl2, col_dl3 = st.columns([1, 2, 1])
    with col_dl2:
        st.download_button(
            label="📥 Download Report as Markdown",
            data=report,
            file_name=f"Lifestyle_Fund_{ticker}_Report_{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            use_container_width=True,
        )

elif generate_btn and not ticker_input:
    st.warning("Please enter a stock ticker first.")

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #999; font-size: 0.85rem; padding: 1rem;">
        <p>Lifestyle Fund Research Engine v0.2 (POC) | Powered by Yahoo Finance + OpenRouter AI</p>
        <p>This is an AI-generated research report for informational purposes only. Not financial advice.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
