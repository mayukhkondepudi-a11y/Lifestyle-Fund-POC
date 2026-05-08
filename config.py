"""Shared constants and configuration for all PickR modules."""
import os


def _env(key, default=""):
    try:
        import streamlit as st
        val = st.secrets.get(key, "")
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key, default)


OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
ANTHROPIC_API_KEY  = _env("ANTHROPIC_API_KEY")
FMP_API_KEY        = _env("FMP_API_KEY")
GMAIL_SENDER       = _env("GMAIL_SENDER")
GMAIL_APP_PASS     = _env("GMAIL_APP_PASS")
RESEND_API_KEY     = _env("RESEND_API_KEY")
GITHUB_TOKEN       = _env("GH_PAT") or _env("GITHUB_TOKEN")
GITHUB_REPO        = _env("GITHUB_REPO")

TRACKER_FILE  = "tracked_stocks.json"
SCREENER_FILE = "screener_results.json"

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3-coder:free",
    "google/gemma-3-27b-it:free",
]

FREE_MODELS_EXTENDED = FREE_MODELS + [
    "z-ai/glm-4.5-air:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "arcee-ai/trinity-large-preview:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-3-12b-it:free",
]

FILTERS = {
    "min_roe": 0.15, "max_debt_equity": 1.0,
    "min_fcf": 0, "max_peg": 1.4, "min_earnings_cagr": 0.12,
}
FILTERS_INDIA = {
    "min_roe": 0.12, "max_debt_equity": 1.5,
    "min_fcf": 0, "max_peg": 1.4, "min_earnings_cagr": 0.10,
}

CURRENCY_SYMBOLS = {
    "USD": "$", "INR": "Rs.", "EUR": "E", "GBP": "L", "JPY": "Y",
    "CNY": "Y", "KRW": "W", "HKD": "HK$", "SGD": "S$", "AUD": "A$",
    "CAD": "C$", "BRL": "R$", "TWD": "NT$", "PKR": "Rs.",
}

POPULAR = {
    "": "", "Apple (AAPL)": "AAPL", "Microsoft (MSFT)": "MSFT",
    "Nvidia (NVDA)": "NVDA", "Broadcom (AVGO)": "AVGO",
    "Alphabet (GOOGL)": "GOOGL", "Amazon (AMZN)": "AMZN",
    "Meta (META)": "META", "Tesla (TSLA)": "TSLA",
    "Netflix (NFLX)": "NFLX", "AMD (AMD)": "AMD", "ASML (ASML)": "ASML",
    "Visa (V)": "V", "Mastercard (MA)": "MA", "Costco (COST)": "COST",
    "Adobe (ADBE)": "ADBE", "Salesforce (CRM)": "CRM",
    "Taiwan Semi (TSM)": "TSM", "Reliance (RELIANCE.NS)": "RELIANCE.NS",
    "HDFC Bank (HDFCBANK.NS)": "HDFCBANK.NS", "TCS (TCS.NS)": "TCS.NS",
    "Infosys (INFY.NS)": "INFY.NS",
}

ADMIN_USERS = {"mayukhk"}  # unlimited reports; MayukhK lowercases to same key

DOMAIN_MAP = {
    # Tech
    "NVDA":"nvidia.com","AAPL":"apple.com","MSFT":"microsoft.com","AMZN":"amazon.com",
    "GOOGL":"google.com","META":"meta.com","TSLA":"tesla.com","NFLX":"netflix.com",
    "ADBE":"adobe.com","INTU":"intuit.com","NOW":"servicenow.com","PYPL":"paypal.com",
    "AVGO":"broadcom.com","ORCL":"oracle.com","CRM":"salesforce.com","PH":"parker.com",
    "AMD":"amd.com","QCOM":"qualcomm.com","ASML":"asml.com","TSM":"tsmc.com",
    # Financials
    "V":"visa.com","MA":"mastercard.com","JPM":"jpmorganchase.com","BAC":"bankofamerica.com",
    "GS":"goldmansachs.com","BLK":"blackrock.com","AXP":"americanexpress.com",
    "PGR":"progressive.com","TRV":"travelers.com","HIG":"thehartford.com",
    "SPGI":"spglobal.com","MCO":"moodys.com","ICE":"intercontinentalexchange.com",
    # Healthcare
    "UNH":"unitedhealthgroup.com","JNJ":"jnj.com","LLY":"lilly.com","MRK":"merck.com",
    "ABBV":"abbvie.com","TMO":"thermofisher.com","ABT":"abbott.com","ISRG":"intuitive.com",
    # Consumer / Industrials / Energy
    "WMT":"walmart.com","COST":"costco.com","HD":"homedepot.com","NKE":"nike.com",
    "MCD":"mcdonalds.com","SBUX":"starbucks.com","KO":"coca-cola.com","PEP":"pepsico.com",
    "PG":"pg.com","XOM":"exxonmobil.com","CVX":"chevron.com","CAT":"caterpillar.com",
    "HON":"honeywell.com","UNP":"union-pacific.com","RTX":"rtx.com","DE":"deere.com",
    "LMT":"lockheedmartin.com","GE":"ge.com",
    # India
    "BHARTIARTL":"airtel.in","DRREDDY":"drreddys.com","RELIANCE":"ril.com","TCS":"tcs.com",
    "INFY":"infosys.com","HDFCBANK":"hdfcbank.com","ICICIBANK":"icicibank.com",
    "WIPRO":"wipro.com","HINDUNILVR":"hul.co.in","KOTAKBANK":"kotak.com",
    "AXISBANK":"axisbank.com","TITAN":"titancompany.in","NESTLEIND":"nestle.in",
    "SUNPHARMA":"sunpharma.com","BAJFINANCE":"bajajfinserv.in","LT":"larsentoubro.com",
    "ASIANPAINT":"asianpaints.com",
}

# Recommendation / scenario colors used across the app
COLOR_BULL  = "#4ade80"   # green - buy / positive / bull case
COLOR_BEAR  = "#f87171"   # red   - pass / negative / bear case
COLOR_BASE  = "#fbbf24"   # amber - watch / neutral / base case
COLOR_ADMIN = "#c084fc"   # purple - admin badge

SECTOR_PEERS = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "ADBE",
                   "CRM", "AMD", "INTC", "TSM", "ASML", "ORCL", "NOW"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "TMUS"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG"],
    "Consumer Defensive": ["COST", "WMT", "PG", "KO", "PEP", "CL"],
    "Financial Services": ["V", "MA", "JPM", "BAC", "GS", "BLK", "AXP", "SPGI"],
    "Healthcare": ["UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "ISRG"],
    "Industrials": ["CAT", "HON", "UNP", "RTX", "DE", "LMT", "GE"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
}
