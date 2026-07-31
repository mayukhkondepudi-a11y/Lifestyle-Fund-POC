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
# ── GitHub configuration ──────────────────────────────────────
#
# IMPORTANT: Streamlit Cloud REJECTS secret names beginning with "GITHUB_"
# (reserved prefix). So every GitHub setting must also be readable under a
# non-reserved alias, or it simply cannot be configured in production.
#
#   Cloud-safe name   ->  also accepted (local / CI)
#   GH_PAT            ->  GITHUB_TOKEN
#   PICKR_REPO        ->  GITHUB_REPO
#   PICKR_DATA_REPO   ->  GITHUB_DATA_REPO
#
# Use the Cloud-safe names everywhere; the GITHUB_* forms are kept only so
# existing local secrets.toml files and the GitHub Actions env keep working.
GITHUB_TOKEN       = _env("GH_PAT") or _env("GITHUB_TOKEN")

# Two repos, deliberately separated by sensitivity:
#   PICKR_REPO      — public. Code and screener_results.json (stock picks are
#                     not sensitive and the nightly Action pushes them here).
#   PICKR_DATA_REPO — PRIVATE. users.json (emails + password hashes),
#                     guest_counts.json, reports/, tracked_stocks.json.
#
# These lived in one public repo until 2026-07-31, which left real emails and
# bcrypt hashes world-readable. Keep them apart. When the data repo is unset the
# code falls back to the public repo so single-repo dev setups still run — but
# preflight.py FAILS on that fallback, because in deployment it means user data
# is back in a public repo (and, since users.json was removed from it, that
# sign-in and report saving are both silently broken).
GITHUB_REPO        = _env("PICKR_REPO") or _env("GITHUB_REPO")
GITHUB_DATA_REPO   = _env("PICKR_DATA_REPO") or _env("GITHUB_DATA_REPO")

# Secret used to HMAC-sign the persisted session cookie (session_cookie.py).
# Override in deployment via st.secrets / env. The dev fallback only keeps
# local runs working; it is NOT secure for production.
PICKR_SESSION_SECRET = _env("PICKR_SESSION_SECRET", "pickr-dev-insecure-session-secret")

TRACKER_FILE  = "tracked_stocks.json"
SCREENER_FILE = "screener_results.json"

# Methodology version flag for the v3 rewrite. "v1" routes to the existing
# analytical pipeline and renderer; "v2" routes to the v3 pipeline being
# built behind this flag. Default stays "v1" until Phase G cutover.
METHODOLOGY_VERSION = "v2"

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
