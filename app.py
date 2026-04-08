import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from openai import OpenAI
import os
import json
import base64
import time
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic
import urllib.request
import urllib.parse

import fmp_api

st.set_page_config(page_title="PickR", page_icon="P", layout="wide")

# ── Session State ─────────────────────────────────────────────
if "report_count" not in st.session_state:
    st.session_state.report_count = 147
if "recent" not in st.session_state:
    st.session_state.recent = []
if "cached_report" not in st.session_state:
    st.session_state.cached_report = None
if "cached_html" not in st.session_state:
    st.session_state.cached_html = None
if "trigger_ticker" not in st.session_state:
    st.session_state.trigger_ticker = None
if "generate_html" not in st.session_state:
    st.session_state.generate_html = False
if "html_just_generated" not in st.session_state:
    st.session_state.html_just_generated = False
if "track_success" not in st.session_state:
    st.session_state.track_success = None

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    html, body, .stApp { background:#0c0c0c !important; color:#e8e8e8 !important; font-family:'Inter',sans-serif !important; font-size:16px !important; }
    .block-container { padding-top:0 !important; max-width:1200px !important; }
    .stApp > div, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] { background:#0c0c0c !important; }
    #MainMenu, footer, header { visibility:hidden !important; }

    .hero { padding:4rem 2rem 1.5rem; text-align:center; }
    .hero h1 { font-size:4.2rem; font-weight:900; letter-spacing:-0.03em; margin:0; }
    .hero h1 .pick {
        background: linear-gradient(180deg,
            #ffffff 0%,
            #ffffff 35%,
            #e0e0e0 55%,
            #c8c8c8 75%,
            #e8e8e8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6)) drop-shadow(0 0 12px rgba(255,255,255,0.08));
    }
    .hero h1 .accent {
        background: linear-gradient(135deg, #a52525 0%, #e04040 30%, #ff8a8a 50%, #e04040 70%, #a52525 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 0 8px rgba(200,50,50,0.3));
    }
    .hero .tag { font-size:1.1rem; color:rgba(255,255,255,0.4); margin-top:0.3rem; }
    .hero .desc { font-size:1rem; color:rgba(255,255,255,0.35); max-width:620px; margin:1rem auto 0; line-height:1.7; }

    .stats-row { display:flex; justify-content:center; gap:3rem; padding:1.3rem 0; margin-top:1.5rem;
        border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); }
    .sr-item { text-align:center; }
    .sr-num { font-size:1.6rem; font-weight:800; color:#fff; display:block; }
    .sr-lbl { font-size:0.65rem; color:rgba(255,255,255,0.22); text-transform:uppercase; letter-spacing:0.14em; font-weight:600; }

    .hiw { padding:2rem 0 1rem; }
    .hiw-title { text-align:center; font-size:0.7rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.18em; color:rgba(255,255,255,0.18); margin-bottom:1.2rem; }
    .hiw-grid { display:flex; justify-content:center; gap:1.5rem; }
    .hiw-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:1.3rem; text-align:center; flex:1; max-width:260px; }
    .hiw-step { font-size:0.6rem; font-weight:800; color:#8b1a1a; text-transform:uppercase;
        letter-spacing:0.16em; margin-bottom:0.4rem; }
    .hiw-title2 { font-size:1.1rem; font-weight:700; color:#fff; margin-bottom:0.3rem; }
    .hiw-desc { font-size:0.88rem; color:rgba(255,255,255,0.35); line-height:1.55; }

    .thesis-section { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:2rem; margin:1.5rem 0; }
    .thesis-title { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.16em;
        color:rgba(255,255,255,0.2); margin-bottom:1rem; }
    .thesis-grid { display:grid; grid-template-columns:1fr 1fr; gap:1.2rem; }
    .thesis-card { background:#1a1a1a; border-radius:6px; padding:1rem 1.2rem; }
    .thesis-card-letter { font-size:1.4rem; font-weight:800; color:#8b1a1a; margin-bottom:0.2rem; }
    .thesis-card-name { font-size:0.95rem; font-weight:700; color:#e0e0e0; margin-bottom:0.3rem; }
    .thesis-card-desc { font-size:0.88rem; color:rgba(255,255,255,0.4); line-height:1.55; }
    .thesis-scoring { margin-top:1.2rem; padding-top:1rem; border-top:1px solid rgba(255,255,255,0.05); }
    .thesis-scoring-title { font-size:0.72rem; font-weight:700; color:rgba(255,255,255,0.3); margin-bottom:0.6rem; }
    .scoring-row { display:flex; gap:1.5rem; }
    .scoring-item { text-align:center; flex:1; }
    .scoring-range { font-size:1.15rem; font-weight:700; }
    .scoring-range.buy { color:#22c55e; }
    .scoring-range.watch { color:#f5c542; }
    .scoring-range.pass { color:#ff4d4d; }
    .scoring-label { font-size:0.62rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.1em; font-weight:600; }

    .params-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:1.2rem 1.5rem; margin-bottom:1.5rem; }
    .params-row { display:flex; justify-content:space-between; padding:0.5rem 0;
        border-bottom:1px solid rgba(255,255,255,0.03); font-size:0.9rem; }
    .params-row:last-child { border-bottom:none; }
    .params-key { color:rgba(255,255,255,0.35); }
    .params-val { color:rgba(255,255,255,0.7); font-weight:500; }

    .rpt-card { background:#1a1a1a; border:1px solid #333; border-radius:12px; padding:2rem 2.5rem; margin-top:1rem; }
    .rpt-head h2 { font-size:2.4rem; font-weight:800; color:#ffffff; margin:0; letter-spacing:-0.02em; }
    .rpt-head .meta { color:rgba(255,255,255,0.6); font-size:0.88rem; letter-spacing:0.04em; margin-top:0.4rem; font-weight:500; }

    .rec-bar { display:flex; justify-content:center; gap:3.5rem; padding:1.5rem 0;
        border-bottom:1px solid rgba(255,255,255,0.1); margin-bottom:0.5rem; }
    .rb-item { text-align:center; }
    .rb-label { font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em;
        color:rgba(255,255,255,0.55); margin-bottom:0.3rem; }
    .rb-val { font-size:1.6rem; font-weight:800; }
    .rb-val.buy { color:#4ade80; }
    .rb-val.watch { color:#fbbf24; }
    .rb-val.pass { color:#f87171; }

    .exec-summary { background:#222; border-left:4px solid #e03030; border-radius:0 8px 8px 0;
        padding:1.2rem 1.6rem; margin:1.2rem 0; font-size:1rem; line-height:1.85;
        color:#eeeeee; font-style:italic; }

    .rationale-text { text-align:center; font-size:0.97rem; color:rgba(255,255,255,0.65);
        font-style:italic; max-width:680px; margin:0 auto; padding-bottom:1.5rem; line-height:1.8; }

    .sec { font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.18em;
        color:#ffffff; margin:2.2rem 0 0.9rem; padding-bottom:0.5rem;
        border-bottom:2px solid #e03030; display:block; }

    [data-testid="stMetricLabel"] { font-size:0.68rem !important; color:rgba(255,255,255,0.6) !important;
        text-transform:uppercase !important; letter-spacing:0.06em !important; font-weight:700 !important; }
    [data-testid="stMetricValue"] { font-size:1.3rem !important; font-weight:700 !important; color:#ffffff !important; }
    [data-testid="stMetricDelta"] { display:none !important; }

    .range-bar-container { margin:0.8rem 0 1.5rem; }
    .range-bar-labels { display:flex; justify-content:space-between; font-size:0.8rem;
        color:rgba(255,255,255,0.65); margin-bottom:0.4rem; font-weight:600; }
    .range-bar { height:7px; background:rgba(255,255,255,0.1); border-radius:4px; position:relative; }
    .range-bar-fill { height:100%; background:linear-gradient(90deg,#8b1a1a,#e03030); border-radius:4px; }
    .range-bar-dot { width:12px; height:12px; background:#fff; border-radius:50%; position:absolute;
        top:-2.5px; transform:translateX(-50%); box-shadow:0 0 8px rgba(224,48,48,0.8); }

    .qglp-s { background:#222; border:1px solid rgba(255,255,255,0.1);
        border-radius:10px; padding:1.4rem 1.5rem; margin:0.8rem 0; }
    .qg { display:flex; justify-content:space-between; }
    .qc { flex:1; text-align:center; padding:0.5rem 0; }
    .qc .ql { font-size:0.65rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em;
        color:rgba(255,255,255,0.55); margin-bottom:0.3rem; }
    .qc .qs { font-size:2.1rem; font-weight:900; color:#ffffff; }
    .qc .qsub { font-size:0.6rem; color:rgba(255,255,255,0.35); font-weight:500; margin-top:0.15rem; }
    .qc.comp { border-left:1px solid rgba(255,255,255,0.1); }
    .qc.comp .qs { color:#e03030; }

    .prose { font-size:1rem; line-height:1.95; color:#dedede; padding:0.3rem 0 0.8rem; }

    .risk-row { padding:0.75rem 0; border-bottom:1px solid rgba(255,255,255,0.07);
        font-size:0.95rem; line-height:1.75; color:#dedede; }
    .risk-row:last-child { border-bottom:none; }
    .rn { display:inline-block; width:24px; height:24px; line-height:24px; text-align:center;
        background:rgba(224,48,48,0.2); border-radius:4px; color:#f07070; font-weight:800;
        font-size:0.68rem; margin-right:0.75rem; vertical-align:middle; }

    .cb { padding:1.2rem 1.5rem; border-radius:8px; font-size:0.95rem; line-height:1.8; color:#dedede; }
    .cb-bull { background:rgba(74,222,128,0.08); border:1px solid rgba(74,222,128,0.28); }
    .cb-bear { background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.25); }
    .cb-title { font-size:0.65rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em; margin-bottom:0.5rem; }
    .cb-bull .cb-title { color:#4ade80; }
    .cb-bear .cb-title { color:#f87171; }

    .sz-box { background:#222; border:1px solid rgba(255,255,255,0.1);
        padding:1.2rem 1.5rem; border-radius:8px; font-size:0.95rem; line-height:1.8; color:#dedede; }

    .pt { width:100%; border-collapse:collapse; font-size:0.88rem; }
    .pt th { text-align:left; font-size:0.65rem; font-weight:800; text-transform:uppercase;
        letter-spacing:0.08em; color:rgba(255,255,255,0.6); padding:0.6rem 0.75rem;
        border-bottom:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.03); }
    .pt td { padding:0.55rem 0.75rem; border-bottom:1px solid rgba(255,255,255,0.06); color:#dedede; }
    .pt tr.hl td { font-weight:700; color:#ffffff; background:rgba(224,48,48,0.1); }

    .vtag { display:inline-block; font-size:0.52rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.08em; color:#e03030; border:1px solid rgba(224,48,48,0.4);
        padding:0.06rem 0.3rem; border-radius:2px; margin-left:0.4rem; vertical-align:middle; }

    .tooltip { position:relative; cursor:help; border-bottom:1px dotted rgba(255,255,255,0.35); }
    .tooltip .tiptext { visibility:hidden; background:#2a2a2a; color:#e0e0e0; font-size:0.82rem;
        padding:0.5rem 0.7rem; border-radius:4px; border:1px solid rgba(255,255,255,0.15);
        position:absolute; z-index:10; bottom:125%; left:50%; transform:translateX(-50%);
        width:220px; text-align:center; line-height:1.5; font-weight:400; font-style:normal; }
    .tooltip:hover .tiptext { visibility:visible; }

    .div { border:none; border-top:1px solid rgba(255,255,255,0.08); margin:1rem 0; }

    .track-box { background:#1e1e1e; border:1px solid rgba(224,48,48,0.35); border-radius:8px;
        padding:1.5rem 2rem; margin-top:1.5rem; }
    .track-box-title { font-size:0.7rem; font-weight:800; text-transform:uppercase; letter-spacing:0.16em;
        color:#e03030; margin-bottom:0.6rem; }
    .track-success { background:rgba(74,222,128,0.1); border:1px solid rgba(74,222,128,0.3);
        border-radius:6px; padding:0.8rem 1.2rem; font-size:0.9rem; color:#4ade80; margin-top:0.8rem; }
    .track-note { font-size:0.75rem; color:rgba(255,255,255,0.4); margin-top:0.6rem; line-height:1.5; }

    .foot-card { background:#1a1a1a; border:1px solid rgba(255,255,255,0.08); border-radius:8px;
        padding:1.5rem 2rem; margin-top:2rem; text-align:center; }
    .foot-name { font-size:1rem; font-weight:600; color:rgba(255,255,255,0.75); }
    .foot-email { font-size:0.85rem; color:rgba(255,255,255,0.45); margin-top:0.2rem; }
    .foot-disclaimer { font-size:0.78rem; color:rgba(255,255,255,0.35); margin-top:1rem;
        line-height:1.65; max-width:700px; margin-left:auto; margin-right:auto; }
    .foot-copy { font-size:0.68rem; color:rgba(255,255,255,0.2); margin-top:0.8rem; }

    .hiw-desc { font-size:0.9rem; color:rgba(255,255,255,0.55); line-height:1.65; }
    .hiw-title2 { font-size:1.1rem; font-weight:700; color:#ffffff; margin-bottom:0.4rem; }
    .thesis-card-desc { font-size:0.9rem; color:rgba(255,255,255,0.55); line-height:1.6; }
    .thesis-card-name { font-size:0.95rem; font-weight:700; color:#ffffff; margin-bottom:0.3rem; }
    .params-key { color:rgba(255,255,255,0.55); font-weight:500; }
    .params-val { color:#ffffff; font-weight:600; }

    .stTextInput > div > div > input { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important;
        border-radius:6px !important; color:#fff !important; font-size:1rem !important;
        padding:0.6rem 1rem !important; caret-color:#fff !important; }
    .stTextInput > div > div > input:focus { border-color:#8b1a1a !important; box-shadow:0 0 0 2px rgba(139,26,26,0.15) !important; }
    .stTextInput > div > div > input::placeholder { color:rgba(255,255,255,0.25) !important; }
    .stSelectbox > div > div { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important;
        border-radius:6px !important; color:#fff !important; }
    .stSelectbox > div > div > div { color:#fff !important; }
    .stSelectbox svg { fill:rgba(255,255,255,0.4) !important; }
    [data-testid="stStatusWidget"], .stAlert, .stStatus { background:#141414 !important;
        border:1px solid rgba(255,255,255,0.06) !important; color:#e8e8e8 !important; border-radius:6px !important; }
    [data-testid="stStatusWidget"] p, [data-testid="stStatusWidget"] span,
    [data-testid="stStatusWidget"] div { color:#e8e8e8 !important; }

    .stButton > button { background:linear-gradient(160deg,#7a1818,#a52525 30%,#c03030 50%,#a52525 70%,#7a1818) !important;
        color:#fff !important; border:none !important; border-radius:6px !important; font-size:0.9rem !important;
        font-weight:700 !important; letter-spacing:0.08em !important; text-transform:uppercase !important;
        padding:0.7rem 2rem !important; transition:all 0.2s ease !important;
        box-shadow:0 2px 8px rgba(139,26,26,0.2), inset 0 1px 0 rgba(255,255,255,0.1) !important; }
    .stButton > button:hover { background:linear-gradient(160deg,#8b1a1a,#c03030 30%,#d44040 50%,#c03030 70%,#8b1a1a) !important;
        transform:translateY(-1px) !important; box-shadow:0 6px 20px rgba(139,26,26,0.4), inset 0 1px 0 rgba(255,255,255,0.15) !important; }
    .stDownloadButton > button { background:transparent !important; color:rgba(255,255,255,0.5) !important;
        border:1px solid rgba(139,26,26,0.35) !important; border-radius:6px !important;
        font-size:0.78rem !important; font-weight:600 !important; letter-spacing:0.08em !important;
        text-transform:uppercase !important; box-shadow:none !important; }
    .stDownloadButton > button:hover { border-color:#8b1a1a !important; color:#fff !important; box-shadow:none !important; }

    [data-testid="stVegaLiteChart"] { background:rgba(255,255,255,0.02) !important;
        border:1px solid rgba(255,255,255,0.04) !important; border-radius:6px !important; }
    .stWarning, .stError, .stInfo { background:#1a1a1a !important; color:#e8e8e8 !important; }
    .stNumberInput > div > div > input { background:#1a1a1a !important;
        border:1px solid rgba(255,255,255,0.1) !important; border-radius:6px !important; color:#fff !important; }
</style>
""", unsafe_allow_html=True)

# ── Config & Secrets ──────────────────────────────────────────
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
if not OPENROUTER_API_KEY or "your" in OPENROUTER_API_KEY:
    st.error("Add your OpenRouter API key to .streamlit/secrets.toml"); st.stop()

FMP_API_KEY = st.secrets.get("FMP_API_KEY", os.getenv("FMP_API_KEY", ""))
if not FMP_API_KEY:
    st.warning("FMP_API_KEY not found — will use yfinance as fallback for all data.")

GMAIL_SENDER   = st.secrets.get("GMAIL_SENDER",   os.getenv("GMAIL_SENDER",   ""))
GMAIL_APP_PASS = st.secrets.get("GMAIL_APP_PASS",  os.getenv("GMAIL_APP_PASS", ""))
RESEND_API_KEY = st.secrets.get("RESEND_API_KEY",  os.getenv("RESEND_API_KEY", ""))
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
print(f"DEBUG: Claude configured: {anthropic_client is not None}, key length: {len(ANTHROPIC_API_KEY)}")
TRACKER_FILE   = "tracked_stocks.json"

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

@st.cache_data
def load_text_file(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return ""

FUND_THESIS   = load_text_file("fund_thesis.md")
REPORT_PROMPT = load_text_file("report_prompt.txt")

POPULAR = {
    "":"", "Apple (AAPL)":"AAPL", "Microsoft (MSFT)":"MSFT", "Nvidia (NVDA)":"NVDA",
    "Broadcom (AVGO)":"AVGO", "Alphabet (GOOGL)":"GOOGL", "Amazon (AMZN)":"AMZN",
    "Meta (META)":"META", "Tesla (TSLA)":"TSLA", "Netflix (NFLX)":"NFLX",
    "AMD (AMD)":"AMD", "ASML (ASML)":"ASML", "Visa (V)":"V", "Mastercard (MA)":"MA",
    "Costco (COST)":"COST", "Adobe (ADBE)":"ADBE", "Salesforce (CRM)":"CRM",
    "Taiwan Semi (TSM)":"TSM", "Reliance (RELIANCE.NS)":"RELIANCE.NS",
    "HDFC Bank (HDFCBANK.NS)":"HDFCBANK.NS", "TCS (TCS.NS)":"TCS.NS", "Infosys (INFY.NS)":"INFY.NS",
}
SECTOR_PEERS = {
    "Technology":["AAPL","MSFT","GOOGL","META","NVDA","AVGO","ADBE","CRM","AMD","INTC","TSM","ASML","ORCL","NOW"],
    "Communication Services":["GOOGL","META","NFLX","DIS","CMCSA","TMUS"],
    "Consumer Cyclical":["AMZN","TSLA","HD","MCD","NKE","SBUX","BKNG"],
    "Consumer Defensive":["COST","WMT","PG","KO","PEP","CL"],
    "Financial Services":["V","MA","JPM","BAC","GS","BLK","AXP","SPGI"],
    "Healthcare":["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","ISRG"],
    "Industrials":["CAT","HON","UNP","RTX","DE","LMT","GE"],
    "Energy":["XOM","CVX","COP","SLB","EOG"],
}
CURRENCY_SYMBOLS = {
    "USD":"$","INR":"₹","EUR":"€","GBP":"£","JPY":"¥","CNY":"¥","KRW":"₩",
    "HKD":"HK$","SGD":"S$","AUD":"A$","CAD":"C$","BRL":"R$","TWD":"NT$","PKR":"₨",
}

def get_sym(c):
    if not c or c=="N/A": return "$"
    return CURRENCY_SYMBOLS.get(c, f"{c} ")

def fmt_n(v,p="",s="",d=2):
    if v is None or v=="N/A" or v=="": return "-"
    try:
        n=float(v)
        if abs(n)>=1e12: return f"{p}{n/1e12:.{d}f}T{s}"
        if abs(n)>=1e9:  return f"{p}{n/1e9:.{d}f}B{s}"
        if abs(n)>=1e6:  return f"{p}{n/1e6:.{d}f}M{s}"
        if abs(n)>=1e3:  return f"{p}{n/1e3:.{d}f}K{s}"
        return f"{p}{n:.{d}f}{s}"
    except: return "-"

def fmt_p(v,d=1):
    if v is None or v=="N/A" or v=="": return "-"
    try:
        n=float(v); return f"{n*100:.{d}f}%" if abs(n)<1 else f"{n:.{d}f}%"
    except: return "-"

def fmt_r(v,d=2):
    if v is None or v=="N/A" or v=="": return "-"
    try: return f"{float(v):.{d}f}"
    except: return "-"

def fmt_c(v,cur="USD",d=2): return fmt_n(v,p=get_sym(cur),d=d)


# ── CHANGED: strip_html utility ───────────────────────────────
def strip_html(text):
    """Remove HTML tags from LLM output to prevent rendering issues."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', str(text))
    return clean.strip()


# ══════════════════════════════════════════════════════════════
# TRACKER — GITHUB API PERSISTENCE
# ══════════════════════════════════════════════════════════════

import urllib.request as _ur
import urllib.error   as _ue

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", ""))
GITHUB_REPO  = st.secrets.get("GITHUB_REPO",  os.getenv("GITHUB_REPO",  ""))

def _gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":  "application/json",
    }

def _gh_get_file():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return [], None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TRACKER_FILE}"
    try:
        req  = _ur.Request(url, headers=_gh_headers())
        with _ur.urlopen(req, timeout=8) as resp:
            data    = json.loads(resp.read().decode())
            content = json.loads(base64.b64decode(data["content"]).decode())
            return content, data["sha"]
    except _ue.HTTPError as e:
        if e.code == 404:
            return [], None
        return [], None
    except Exception:
        return [], None

def _gh_put_file(content_list, sha=None):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False, "GITHUB_TOKEN or GITHUB_REPO not configured"
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TRACKER_FILE}"
    payload = {
        "message": f"chore: update tracker [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
        "content":  base64.b64encode(
            json.dumps(content_list, indent=2, default=str).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        data = json.dumps(payload).encode()
        req  = _ur.Request(url, data=data, headers=_gh_headers(), method="PUT")
        with _ur.urlopen(req, timeout=10):
            pass
        return True, None
    except Exception as e:
        return False, str(e)

def _gh_put_file_tracked(ticker, company_name, recommendation, target_price,
                          entry_price, metrics_snapshot, thesis_summary, user_email):
    if GITHUB_TOKEN and GITHUB_REPO:
        tracker, sha = _gh_get_file()
    else:
        tracker = load_tracker()
        sha     = None

    tracker = [t for t in tracker
               if not (t["ticker"] == ticker and t["user_email"] == user_email)]
    tracker.append({
        "ticker":           ticker,
        "company_name":     company_name,
        "user_email":       user_email,
        "recommendation":   recommendation,
        "target_price":     float(target_price),
        "entry_price":      float(entry_price) if entry_price else None,
        "added_date":       datetime.now().strftime("%Y-%m-%d"),
        "original_metrics": metrics_snapshot,
        "thesis_summary":   thesis_summary,
        "alert_sent":       False,
        "last_checked":     None,
        "last_price":       float(entry_price) if entry_price else None,
    })

    if GITHUB_TOKEN and GITHUB_REPO:
        ok, err = _gh_put_file(tracker, sha)
        return ok, err
    else:
        try:
            with open(TRACKER_FILE, "w") as f:
                json.dump(tracker, f, indent=2, default=str)
            return False, "GitHub not configured — saved locally only"
        except Exception as e:
            return False, str(e)


def load_tracker():
    if GITHUB_TOKEN and GITHUB_REPO:
        content, _ = _gh_get_file()
        return content
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f: return json.load(f)
        except: return []
    return []

def add_tracked_stock(ticker, company_name, recommendation, target_price,
                      entry_price, metrics_snapshot, thesis_summary, user_email):
    if GITHUB_TOKEN and GITHUB_REPO:
        tracker, sha = _gh_get_file()
    else:
        tracker = load_tracker()
        sha     = None

    tracker = [t for t in tracker
               if not (t["ticker"] == ticker and t["user_email"] == user_email)]

    tracker.append({
        "ticker":           ticker,
        "company_name":     company_name,
        "user_email":       user_email,
        "recommendation":   recommendation,
        "target_price":     float(target_price),
        "entry_price":      float(entry_price) if entry_price else None,
        "added_date":       datetime.now().strftime("%Y-%m-%d"),
        "original_metrics": metrics_snapshot,
        "thesis_summary":   thesis_summary,
        "alert_sent":       False,
        "last_checked":     None,
        "last_price":       float(entry_price) if entry_price else None,
    })

    if GITHUB_TOKEN and GITHUB_REPO:
        ok, err = _gh_put_file(tracker, sha)
        if not ok:
            with open(TRACKER_FILE, "w") as f:
                json.dump(tracker, f, indent=2, default=str)
    else:
        with open(TRACKER_FILE, "w") as f:
            json.dump(tracker, f, indent=2, default=str)


# ══════════════════════════════════════════════════════════════
# EMAIL — GMAIL SMTP
# ══════════════════════════════════════════════════════════════

def send_email(to_email, subject, html_body):
    if RESEND_API_KEY:
        try:
            import resend
            resend.api_key = RESEND_API_KEY
            r = resend.Emails.send({
                "from": "PickR <onboarding@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            })
            return True, None
        except Exception as e:
            return False, f"Resend error: {str(e)}"
    if not GMAIL_SENDER or not GMAIL_APP_PASS:
        return False, "No email provider configured."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"PickR Alerts <{GMAIL_SENDER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_SENDER, to_email, msg.as_string())
        return True, None
    except Exception as e: return False, str(e)

def email_confirmation(to_email, ticker, company_name, recommendation, target_price, entry_price):
    color = "#22c55e" if recommendation=="BUY" else "#f5c542"
    sym   = "↑" if recommendation=="BUY" else "◎"
    body  = f"""
    <div style="font-family:Inter,sans-serif;background:#0c0c0c;padding:2rem;max-width:600px;margin:0 auto;">
      <div style="border-bottom:2px solid #8b1a1a;padding-bottom:1rem;margin-bottom:1.5rem;">
        <span style="font-size:1.4rem;font-weight:900;color:#fff;">Pick<span style="color:#c03030;">R</span></span>
        <span style="font-size:0.75rem;color:rgba(255,255,255,0.3);margin-left:1rem;">Stock Alert Confirmation</span>
      </div>
      <p style="color:rgba(255,255,255,0.7);font-size:1rem;line-height:1.7;">
        You're now tracking <strong style="color:#fff;">{company_name} ({ticker})</strong>.
      </p>
      <div style="background:#141414;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:1.2rem 1.5rem;margin:1.2rem 0;">
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Recommendation</span>
          <span style="color:{color};font-weight:700;">{sym} {recommendation}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Alert Target Price</span>
          <span style="color:#fff;font-weight:600;">{target_price}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Entry Price (at report)</span>
          <span style="color:#fff;font-weight:600;">{entry_price}</span>
        </div>
      </div>
      <p style="color:rgba(255,255,255,0.35);font-size:0.8rem;line-height:1.6;margin-top:1.5rem;">
        You'll receive an alert when the price reaches your target, along with a fresh AI thesis evaluation.
        Prices are checked daily. To stop tracking, simply reply STOP to this email.
      </p>
      <p style="color:rgba(255,255,255,0.15);font-size:0.72rem;margin-top:1.5rem;">
        PickR — For informational purposes only. Not financial advice.
      </p>
    </div>
    """
    return send_email(to_email, f"PickR: Now tracking {ticker} ({recommendation})", body)

def email_price_alert(to_email, ticker, company_name, recommendation,
                      target_price, current_price, thesis_eval):
    intact      = thesis_eval.get("thesis_intact", True)
    action      = thesis_eval.get("updated_action", recommendation)
    rationale   = thesis_eval.get("rationale", "")
    key_changes = thesis_eval.get("key_changes", [])
    confidence  = thesis_eval.get("confidence", "Medium")
    color       = "#22c55e" if action=="BUY" else ("#f5c542" if action=="WATCH" else "#ff4d4d")
    intact_color= "#22c55e" if intact else "#ff4d4d"
    intact_text = "INTACT" if intact else "CHANGED"
    changes_html= "".join(
        f"<li style='color:rgba(255,255,255,0.5);font-size:0.88rem;margin:0.3rem 0;'>{c}</li>"
        for c in key_changes
    )
    body = f"""
    <div style="font-family:Inter,sans-serif;background:#0c0c0c;padding:2rem;max-width:600px;margin:0 auto;">
      <div style="border-bottom:2px solid #8b1a1a;padding-bottom:1rem;margin-bottom:1.5rem;">
        <span style="font-size:1.4rem;font-weight:900;color:#fff;">Pick<span style="color:#c03030;">R</span></span>
        <span style="font-size:0.75rem;color:rgba(255,255,255,0.3);margin-left:1rem;">Price Alert</span>
      </div>
      <h2 style="color:#fff;font-size:1.5rem;margin:0 0 0.3rem;">{company_name} ({ticker})</h2>
      <p style="color:rgba(255,255,255,0.4);font-size:0.85rem;">Target reached — {datetime.now().strftime('%B %d, %Y')}</p>
      <div style="background:#141414;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:1.2rem 1.5rem;margin:1.2rem 0;">
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Current Price</span>
          <span style="color:#fff;font-weight:700;">{current_price}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Your Target</span>
          <span style="color:#fff;font-weight:600;">{target_price}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Thesis Status</span>
          <span style="color:{intact_color};font-weight:700;">{intact_text}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Updated Action</span>
          <span style="color:{color};font-weight:700;">{action}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Confidence</span>
          <span style="color:#fff;font-weight:600;">{confidence}</span>
        </div>
      </div>
      <div style="background:#1a1a1a;border-left:3px solid #8b1a1a;padding:1rem 1.2rem;border-radius:0 6px 6px 0;margin:1rem 0;">
        <p style="color:rgba(255,255,255,0.6);font-size:0.92rem;line-height:1.7;margin:0;font-style:italic;">{rationale}</p>
      </div>
      {"<p style='color:rgba(255,255,255,0.4);font-size:0.82rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;margin:1rem 0 0.4rem;'>Key changes since original thesis:</p><ul style='margin:0;padding-left:1.2rem;'>" + changes_html + "</ul>" if key_changes else ""}
      <p style="color:rgba(255,255,255,0.15);font-size:0.72rem;margin-top:1.5rem;">
        PickR — For informational purposes only. Not financial advice.
      </p>
    </div>
    """
    return send_email(to_email, f"PickR Alert: {ticker} hit your target ({current_price})", body)


# ══════════════════════════════════════════════════════════════
# DATA FETCHING — NOW USES fmp_api.py
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400, show_spinner=False)
def search_ticker(query):
    return fmp_api.search_ticker(query)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch(ticker):
    result = fmp_api.fetch_full(ticker)
    if result is None:
        return {"info": {"error": f"Could not fetch data for {ticker}"}, "inc": None, "qinc": None, "bs": None, "cf": None, "hist": None, "news": []}
    return result

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_peers(ticker, sector):
    peer_tickers = [p for p in SECTOR_PEERS.get(sector, []) if p.upper() != ticker.upper()][:4]
    out = []
    for pt in peer_tickers:
        try:
            profile = fmp_api.get_profile(pt)
            if profile:
                c = profile.get("currency", "USD")
                out.append({
                    "Ticker": pt, "Company": profile.get("shortName", pt),
                    "Mkt Cap": fmt_c(profile.get("marketCap"), c),
                    "P/E": fmt_r(profile.get("trailingPE")),
                    "Fwd P/E": fmt_r(profile.get("forwardPE")),
                    "PEG": fmt_r(profile.get("pegRatio")),
                    "Margin": fmt_p(profile.get("operatingMargins")),
                    "ROE": fmt_p(profile.get("returnOnEquity")),
                    "Rev Gr.": fmt_p(profile.get("revenueGrowth")),
                })
            else:
                import yfinance as yf
                i = yf.Ticker(pt).info
                c = i.get("currency", "USD")
                out.append({
                    "Ticker": pt, "Company": i.get("shortName", pt),
                    "Mkt Cap": fmt_c(i.get("marketCap"), c),
                    "P/E": fmt_r(i.get("trailingPE")),
                    "Fwd P/E": fmt_r(i.get("forwardPE")),
                    "PEG": fmt_r(i.get("pegRatio")),
                    "Margin": fmt_p(i.get("operatingMargins")),
                    "ROE": fmt_p(i.get("returnOnEquity")),
                    "Rev Gr.": fmt_p(i.get("revenueGrowth")),
                })
        except:
            continue
    return out

# ══════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════

def calc(data):
    info = data.get("info",{})
    if isinstance(info,dict) and "error" in info: return {"error":info["error"]}
    g = lambda k,d=None: info.get(k,d)

    m = {
        "company_name":g("shortName",g("longName","Unknown")),
        "sector":g("sector","N/A"),"industry":g("industry","N/A"),
        "country":g("country","N/A"),"currency":g("currency","USD"),
        "description":g("longBusinessSummary","N/A"),
        "current_price":g("currentPrice",g("regularMarketPrice")),
        "market_cap":g("marketCap"),"enterprise_value":g("enterpriseValue"),
        "trailing_pe":g("trailingPE"),"forward_pe":g("forwardPE"),
        "peg_ratio":g("pegRatio"),"price_to_book":g("priceToBook"),
        "price_to_sales":g("priceToSalesTrailing12Months"),
        "ev_to_ebitda":g("enterpriseToEbitda"),
        "gross_margin":g("grossMargins"),"operating_margin":g("operatingMargins"),
        "profit_margin":g("profitMargins"),"roe":g("returnOnEquity"),"roa":g("returnOnAssets"),
        "trailing_eps":g("trailingEps"),"forward_eps":g("forwardEps"),
        "earnings_growth":g("earningsGrowth"),
        "total_revenue":g("totalRevenue"),"revenue_growth":g("revenueGrowth"),
        "free_cashflow":g("freeCashflow"),"operating_cashflow":g("operatingCashflow"),
        "total_cash":g("totalCash"),"total_debt":g("totalDebt"),
        "dividend_yield":g("dividendYield"),"payout_ratio":g("payoutRatio"),
        "beta":g("beta"),"week_52_high":g("fiftyTwoWeekHigh"),"week_52_low":g("fiftyTwoWeekLow"),
        "ma_50":g("fiftyDayAverage"),"ma_200":g("twoHundredDayAverage"),
        "insider_pct":g("heldPercentInsiders"),"institution_pct":g("heldPercentInstitutions"),
        "shares_outstanding":g("sharesOutstanding"),
    }

    try:
        m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"]) \
            if m["free_cashflow"] and m["market_cap"] else None
    except: m["fcf_yield"] = None

    raw_de = g("debtToEquity")
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

        total_debt_bs  = _bs_row(["Total Debt","TotalDebt","Long Term Debt And Capital Lease Obligation",
                                   "Long Term Debt","LongTermDebt"])
        total_eq       = _bs_row(["Stockholders Equity","Total Stockholder Equity","TotalStockholdersEquity",
                                   "Common Stock Equity","CommonStockEquity"])
        current_assets = _bs_row(["Current Assets","TotalCurrentAssets","Total Current Assets"])
        current_liabs  = _bs_row(["Current Liabilities","TotalCurrentLiabilities","Total Current Liabilities"])

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
        except:
            m["debt_to_equity"] = None
    else:
        m["debt_to_equity"] = None

    if computed_current_ratio is not None:
        m["current_ratio"] = computed_current_ratio
    else:
        m["current_ratio"] = g("currentRatio")

    inc = data.get("inc")
    m["revenue_history"] = {}
    m["net_income_history"] = {}

    def cagr_from(df, labels):
        if df is None: return None, {}
        for lb in labels:
            if lb in df.index:
                row = df.loc[lb].dropna()
                if row.empty: continue
                row = row.sort_index()
                hist = {str(dt.year) if hasattr(dt, 'year') else str(dt): round(float(v) / 1e9, 2) for dt, v in row.items()}
                if len(row) < 2: return None, hist
                oldest = float(row.iloc[0])
                newest = float(row.iloc[-1])
                years  = len(row) - 1
                if oldest <= 0 or years <= 0:
                    return None, hist
                cagr = (newest / oldest) ** (1 / years) - 1
                return round(cagr, 4), hist
        return None, {}

    m["revenue_cagr"],    m["revenue_history"]    = cagr_from(inc, ["Total Revenue","TotalRevenue","Revenue"])
    m["net_income_cagr"], m["net_income_history"]  = cagr_from(inc, ["Net Income","NetIncome",
                                                                       "Net Income Common Stockholders"])
    m["eps_cagr"], _ = cagr_from(inc, ["Diluted EPS","Basic EPS","DilutedEPS","BasicEPS",
                                        "EPS","Earnings Per Share"])

    if m["gross_margin"] is None and inc is not None:
        try:
            rev_row = None
            gp_row  = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index()
                    break
            for lb in ["Gross Profit","GrossProfit"]:
                if lb in inc.index:
                    gp_row = inc.loc[lb].dropna().sort_index()
                    break
            if rev_row is not None and gp_row is not None:
                rev = float(rev_row.iloc[-1])
                gp  = float(gp_row.iloc[-1])
                if rev > 0:
                    m["gross_margin"] = round(gp / rev, 4)
        except: pass

    if m["operating_margin"] is None and inc is not None:
        try:
            rev_row = None
            op_row  = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index()
                    break
            for lb in ["Operating Income","OperatingIncome","EBIT"]:
                if lb in inc.index:
                    op_row = inc.loc[lb].dropna().sort_index()
                    break
            if rev_row is not None and op_row is not None:
                rev = float(rev_row.iloc[-1])
                op  = float(op_row.iloc[-1])
                if rev > 0:
                    m["operating_margin"] = round(op / rev, 4)
        except: pass

    if m["profit_margin"] is None and inc is not None:
        try:
            rev_row = None
            ni_row  = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index:
                    rev_row = inc.loc[lb].dropna().sort_index()
                    break
            for lb in ["Net Income","NetIncome","Net Income Common Stockholders"]:
                if lb in inc.index:
                    ni_row = inc.loc[lb].dropna().sort_index()
                    break
            if rev_row is not None and ni_row is not None:
                rev = float(rev_row.iloc[-1])
                ni  = float(ni_row.iloc[-1])
                if rev > 0:
                    m["profit_margin"] = round(ni / rev, 4)
        except: pass

    if m["roe"] is None and inc is not None and bs is not None:
        try:
            ni_row = None
            eq_row = None
            for lb in ["Net Income","NetIncome","Net Income Common Stockholders"]:
                if lb in inc.index:
                    ni_row = inc.loc[lb].dropna().sort_index()
                    break
            for lb in ["Stockholders Equity","Total Stockholder Equity","CommonStockEquity"]:
                if lb in bs.index:
                    eq_row = bs.loc[lb].dropna().sort_index()
                    break
            if ni_row is not None and eq_row is not None:
                ni = float(ni_row.iloc[-1])
                eq = float(eq_row.iloc[0])
                if eq > 0:
                    m["roe"] = round(ni / eq, 4)
        except: pass

    h = data.get("hist")
    if h is not None and not h.empty:
        try:
            c = h["Close"]
            m["price_5y_return"] = round(((c.iloc[-1] / c.iloc[0]) - 1) * 100, 2)
            m["price_5y_high"]   = round(float(c.max()), 2)
            m["price_5y_low"]    = round(float(c.min()), 2)
        except:
            m["price_5y_return"] = m["price_5y_high"] = m["price_5y_low"] = None
    else:
        m["price_5y_return"] = m["price_5y_high"] = m["price_5y_low"] = None

    m["news"] = [{"title": n.get("title",""), "publisher": n.get("publisher","")}
                 for n in data.get("news", [])]
    return m


# ── CHANGED: complete rewrite of compute_scenario_math ────────
def compute_scenario_math(metrics, llm_output):
    """
    All financial math happens here. LLM provides narrative + assumptions,
    Python computes every number from revenue fundamentals.
    """
    current_price = metrics.get("current_price") or 0
    trailing_eps = metrics.get("trailing_eps") or 0
    total_revenue = metrics.get("total_revenue") or 0
    shares = metrics.get("shares_outstanding") or 0
    operating_margin = metrics.get("operating_margin") or 0
    profit_margin = metrics.get("profit_margin") or 0
    market_cap = metrics.get("market_cap") or 0
    risk_free_rate = 0.043

    # ── Type coercion ──
    try: current_price = float(current_price)
    except: current_price = 0
    try: trailing_eps = float(trailing_eps)
    except: trailing_eps = 0
    try: total_revenue = float(total_revenue)
    except: total_revenue = 0
    try: shares = float(shares)
    except: shares = 0
    try: market_cap = float(market_cap)
    except: market_cap = 0
    try: operating_margin = float(operating_margin)
    except: operating_margin = 0
    try: profit_margin = float(profit_margin)
    except: profit_margin = 0

    # ── Derive missing fundamentals ──
    if shares == 0 and current_price > 0 and market_cap > 0:
        shares = market_cap / current_price

    # Derive trailing EPS from P/E if missing
    if trailing_eps == 0 and current_price > 0:
        pe = 0
        try:
            pe = float(metrics.get("trailing_pe") or 0)
        except:
            pe = 0
        if pe > 0:
            trailing_eps = current_price / pe

    # Still missing? Try forward P/E
    if trailing_eps == 0 and current_price > 0:
        fpe = 0
        try:
            fpe = float(metrics.get("forward_pe") or 0)
        except:
            fpe = 0
        if fpe > 0:
            trailing_eps = current_price / fpe

    # Derive revenue from market cap and price-to-sales if missing
    if total_revenue == 0 and market_cap > 0:
        ps = 0
        try:
            ps = float(metrics.get("price_to_sales") or 0)
        except:
            ps = 0
        if ps > 0:
            total_revenue = market_cap / ps

    if trailing_eps == 0 and total_revenue > 0 and profit_margin != 0 and shares > 0:
        trailing_eps = (total_revenue * profit_margin) / shares

    if trailing_eps == 0 and total_revenue > 0 and operating_margin != 0 and shares > 0:
        trailing_eps = (total_revenue * operating_margin * 0.79) / shares

    # ── Net-to-operating ratio ──
    # How much of each dollar of operating income becomes net income
    if operating_margin > 0 and profit_margin > 0:
        net_to_op_ratio = profit_margin / operating_margin
    else:
        net_to_op_ratio = 0.79

    net_to_op_ratio = max(0.3, min(net_to_op_ratio, 1.0))

    print(f"DEBUG scenario math: price={current_price}, eps={trailing_eps:.2f}, "
          f"revenue={total_revenue}, shares={shares:.0f}, "
          f"op_margin={operating_margin}, net_to_op={net_to_op_ratio:.3f}")

    scenarios = llm_output.get("scenarios", {})
    results = {}

    for scenario_name, s in scenarios.items():
        try:
            prob = float(s.get("probability", 0))
            rev_growth = float(s.get("revenue_growth", 0))
            pe_mult = float(s.get("pe_multiple", 20))

            # ── Determine projected operating margin ──
            if "margin_delta_pp" in s:
                margin_delta = float(s.get("margin_delta_pp", 0)) / 100.0
                projected_op_margin = operating_margin + margin_delta
            elif "operating_margin" in s:
                raw_margin = float(s.get("operating_margin", operating_margin or 0.15))
                # SAFETY: cap unrealistic absolute margins from LLM
                if operating_margin > 0 and raw_margin > operating_margin + 0.10:
                    projected_op_margin = operating_margin + 0.05
                elif operating_margin > 0 and raw_margin < operating_margin - 0.10:
                    projected_op_margin = operating_margin - 0.05
                else:
                    projected_op_margin = raw_margin
            else:
                projected_op_margin = operating_margin if operating_margin > 0 else 0.15

            projected_op_margin = max(0.01, min(projected_op_margin, 0.60))

            # ── Revenue projection ──
            projected_revenue = total_revenue * (1 + rev_growth)

            # ── EPS projection: ground-up from revenue ──
            if projected_revenue > 0 and shares > 0 and projected_op_margin > 0:
                projected_operating_income = projected_revenue * projected_op_margin
                projected_net_income = projected_operating_income * net_to_op_ratio
                projected_eps = projected_net_income / shares
            elif trailing_eps != 0:
                # Fallback: just grow EPS by revenue growth rate
                projected_eps = trailing_eps * (1 + rev_growth)
            else:
                # Last resort: derive from price and PE
                current_pe = 0
                try:
                    current_pe = float(metrics.get("trailing_pe") or metrics.get("forward_pe") or 0)
                except:
                    current_pe = 0
                if current_pe > 0 and current_price > 0:
                    derived_eps = current_price / current_pe
                    projected_eps = derived_eps * (1 + rev_growth)
                elif current_price > 0:
                    projected_eps = (current_price / 20.0) * (1 + rev_growth)
                else:
                    projected_eps = 0

            # ── Price target ──
            price_target = projected_eps * pe_mult

            # ── Implied return ──
            implied_return = (price_target - current_price) / current_price if current_price > 0 else 0

            # ── Breakeven P/E ──
            breakeven_pe = current_price / projected_eps if projected_eps > 0 else None

            results[scenario_name] = {
                "probability": round(prob, 4),
                "projected_revenue": round(projected_revenue, 0),
                "projected_op_margin": round(projected_op_margin, 4),
                "projected_eps": round(projected_eps, 2),
                "pe_multiple": pe_mult,
                "pe_rationale": s.get("pe_rationale", ""),
                "price_target": round(price_target, 2),
                "implied_return": round(implied_return, 4),
                "breakeven_pe": round(breakeven_pe, 2) if breakeven_pe else None,
                "narrative": s.get("narrative", ""),
            }
        except Exception as e:
            results[scenario_name] = {
                "probability": 0, "projected_revenue": 0, "projected_op_margin": 0,
                "projected_eps": 0, "pe_multiple": 0, "price_target": 0,
                "implied_return": 0, "breakeven_pe": None, "narrative": str(e),
                "pe_rationale": "",
            }

    # ── Sanity check: if ALL scenarios >100% return, fall back to EPS-growth only ──
    returns = [r["implied_return"] for r in results.values() if r["implied_return"] != 0]
    if returns and all(r > 1.0 for r in returns):
        print("WARNING: All scenarios >100% return. Falling back to EPS-growth-only mode.")
        for scenario_name, s in scenarios.items():
            try:
                prob = float(s.get("probability", 0))
                rev_growth = float(s.get("revenue_growth", 0))
                pe_mult = float(s.get("pe_multiple", 20))

                projected_eps = trailing_eps * (1 + rev_growth) if trailing_eps != 0 else 0
                if projected_eps == 0 and current_price > 0:
                    current_pe = 0
                    try:
                        current_pe = float(metrics.get("trailing_pe") or 0)
                    except:
                        current_pe = 0
                    if current_pe > 0:
                        projected_eps = (current_price / current_pe) * (1 + rev_growth)

                price_target = projected_eps * pe_mult
                implied_return = (price_target - current_price) / current_price if current_price > 0 else 0
                breakeven_pe = current_price / projected_eps if projected_eps > 0 else None

                results[scenario_name] = {
                    "probability": round(prob, 4),
                    "projected_revenue": round(total_revenue * (1 + rev_growth), 0),
                    "projected_op_margin": round(operating_margin, 4),
                    "projected_eps": round(projected_eps, 2),
                    "pe_multiple": pe_mult,
                    "pe_rationale": s.get("pe_rationale", ""),
                    "price_target": round(price_target, 2),
                    "implied_return": round(implied_return, 4),
                    "breakeven_pe": round(breakeven_pe, 2) if breakeven_pe else None,
                    "narrative": s.get("narrative", ""),
                }
            except:
                pass

    # ── PE sanity check ──
    current_pe = 0
    try:
        current_pe = float(metrics.get("trailing_pe") or 0)
    except:
        current_pe = 0

    if current_pe > 0:
        for scenario_name, s in results.items():
            if s["pe_multiple"] > 0 and s["price_target"] > 0:
                if scenario_name == "bull" and s["pe_multiple"] < current_pe * 0.6:
                    adjusted_pe = round(current_pe * 0.9, 1)
                    s["pe_multiple"] = adjusted_pe
                    s["price_target"] = round(s["projected_eps"] * adjusted_pe, 2)
                    s["implied_return"] = round((s["price_target"] - current_price) / current_price, 4) if current_price > 0 else 0
                    s["breakeven_pe"] = round(current_price / s["projected_eps"], 2) if s["projected_eps"] > 0 else None
                elif scenario_name == "base" and s["pe_multiple"] < current_pe * 0.5:
                    adjusted_pe = round(current_pe * 0.75, 1)
                    s["pe_multiple"] = adjusted_pe
                    s["price_target"] = round(s["projected_eps"] * adjusted_pe, 2)
                    s["implied_return"] = round((s["price_target"] - current_price) / current_price, 4) if current_price > 0 else 0
                    s["breakeven_pe"] = round(current_price / s["projected_eps"], 2) if s["projected_eps"] > 0 else None
                elif scenario_name == "bear" and s["pe_multiple"] < current_pe * 0.3:
                    adjusted_pe = round(current_pe * 0.5, 1)
                    s["pe_multiple"] = adjusted_pe
                    s["price_target"] = round(s["projected_eps"] * adjusted_pe, 2)
                    s["implied_return"] = round((s["price_target"] - current_price) / current_price, 4) if current_price > 0 else 0
                    s["breakeven_pe"] = round(current_price / s["projected_eps"], 2) if s["projected_eps"] > 0 else None

    # ── Aggregate metrics ──
    expected_value = sum(r["price_target"] * r["probability"] for r in results.values())
    expected_return = (expected_value - current_price) / current_price if current_price > 0 else 0

    variance = sum(
        r["probability"] * (r["implied_return"] - expected_return) ** 2
        for r in results.values()
    )
    std_dev = variance ** 0.5

    sharpe = (expected_return - risk_free_rate) / std_dev if std_dev > 0 else 0

    upside_return = sum(
        r["implied_return"] * r["probability"]
        for r in results.values()
        if r["implied_return"] > 0
    )
    downside_return = sum(
        r["implied_return"] * r["probability"]
        for r in results.values()
        if r["implied_return"] < 0
    )
    upside_downside_ratio = abs(upside_return / downside_return) if downside_return != 0 else float('inf')

    prob_positive = sum(
        r["probability"]
        for r in results.values()
        if r["price_target"] > current_price
    )

    bear = results.get("bear", {})
    max_drawdown_prob = bear.get("probability", 0)
    max_drawdown_magnitude = bear.get("implied_return", 0)

    # ── Risk impacts ──
    risk_impacts = []
    for risk in llm_output.get("risks", []):
        try:
            rev_impact_pct = float(risk.get("revenue_impact_pct", 0))
            eps_impact_pct = float(risk.get("eps_impact_pct", 0))
            rev_impact = total_revenue * rev_impact_pct
            eps_impact = trailing_eps * eps_impact_pct
            risk_impacts.append({
                "name": risk.get("name", "Unknown"),
                "probability": float(risk.get("probability", 0)),
                "revenue_impact": round(rev_impact, 0),
                "revenue_impact_pct": rev_impact_pct,
                "eps_impact": round(eps_impact, 2),
                "eps_impact_pct": eps_impact_pct,
                "scenario_affected": risk.get("scenario_affected", "bear"),
                "description": risk.get("description", ""),
            })
        except:
            continue

    return {
        "scenarios": results,
        "expected_value": round(expected_value, 2),
        "expected_return": round(expected_return, 4),
        "std_dev": round(std_dev, 4),
        "sharpe_ratio": round(sharpe, 2),
        "upside_downside_ratio": round(upside_downside_ratio, 2),
        "prob_positive_return": round(prob_positive, 4),
        "max_drawdown_prob": round(max_drawdown_prob, 4),
        "max_drawdown_magnitude": round(max_drawdown_magnitude, 4),
        "risk_impacts": risk_impacts,
        "risk_free_rate": risk_free_rate,
    }


# ══════════════════════════════════════════════════════════════
# AI — PROMPTS
# ══════════════════════════════════════════════════════════════

# ── CHANGED: updated prompt to use margin_delta_pp ────────────
def ai_prompt_ui(ticker, m):
    ms = json.dumps(
        {k:v for k,v in m.items() if k not in ["description","news","revenue_history","net_income_history"]},
        indent=2, default=str
    )
    return [
        {"role":"system","content":"""You are a senior equity research analyst. Produce a structured investment analysis.

CRITICAL RULES:
1. Use ONLY the financial data provided. Never invent numbers.
2. Do NOT perform any calculations. Provide directional assumptions only. All math will be done externally in Python.
3. Respond with ONLY valid JSON, no fences, no extra text.
4. All narrative text must be PLAIN TEXT. Do NOT include any HTML tags in your response.

JSON STRUCTURE:
{"investment_thesis": "3 sentences. Recommendation (BUY/WATCH/PASS), conviction (High/Medium/Low), and why.",
"recommendation": "BUY",
"conviction": "High",
"business_overview": "1 concise paragraph on what the company does, its market position, and strategic DNA.",
"revenue_architecture": "Detailed analysis of revenue segments, growth trajectories, margin profiles, and concentration risks. Reference specific segment numbers from the provided data. 3-4 paragraphs.",
"growth_drivers": "Primary structural growth vector with TAM estimate. List 3-4 competitive moats with one-line evidence each. 2-3 paragraphs.",
"financial_commentary": "Brief commentary on margin trajectory, cash flow quality, balance sheet health, and any red flags. Reference specific metrics. 2-3 paragraphs.",
"peer_positioning": "One-line summary of how this company compares to peers on valuation, growth, and quality.",
"scenarios": {
  "bull": {
    "probability": 0.20,
    "narrative": "2-3 sentences on what has to go right. PLAIN TEXT ONLY, no HTML.",
    "revenue_growth": 0.15,
    "margin_delta_pp": 3.0,
    "pe_multiple": 32,
    "pe_rationale": "1 sentence justifying the multiple. PLAIN TEXT ONLY."
  },
  "base": {
    "probability": 0.60,
    "narrative": "2-3 sentences on continuation trajectory. PLAIN TEXT ONLY, no HTML.",
    "revenue_growth": 0.08,
    "margin_delta_pp": 1.0,
    "pe_multiple": 26,
    "pe_rationale": "1 sentence justifying the multiple. PLAIN TEXT ONLY."
  },
  "bear": {
    "probability": 0.20,
    "narrative": "2-3 sentences on what goes wrong. PLAIN TEXT ONLY, no HTML.",
    "revenue_growth": -0.02,
    "margin_delta_pp": -2.0,
    "pe_multiple": 18,
    "pe_rationale": "1 sentence justifying the multiple. PLAIN TEXT ONLY."
  }
},
"probability_reasoning": "1-2 sentences explaining why you assigned these specific probabilities. Reference specific metrics that skewed your assessment.",
"risks": [
  {
    "name": "Short name",
    "probability": 0.30,
    "revenue_impact_pct": -0.08,
    "eps_impact_pct": -0.12,
    "scenario_affected": "bear",
    "description": "2 sentence explanation of the risk and transmission mechanism."
  }
],
"catalysts": [
  {
    "date": "July 2026",
    "event": "Q2 Earnings",
    "bull_signal": "What to watch for (positive)",
    "bear_signal": "What to watch for (negative)"
  }
],
"conclusion": "1 paragraph restating the thesis, the key variable all scenarios hinge on, and the single most important upcoming datapoint."}

SCENARIO GUIDELINES:
- Probabilities must sum to 1.0
- Each probability must be between 0.05 and 0.70
- DO NOT default to 20/60/20. Use the data to assign differentiated probabilities.
- You MUST include a "probability_reasoning" field (1-2 sentences) explaining WHY you assigned these specific probabilities based on the data.

PROBABILITY ASSIGNMENT RULES — use these signals to skew probabilities:
  Skew TOWARD bull (bull 25-40%, bear 10-20%) when:
    - Revenue growth is accelerating (current > CAGR)
    - Operating margins are expanding
    - Forward P/E < Trailing P/E (earnings expected to grow)
    - Strong balance sheet (low debt/equity, high current ratio)
    - High ROE with reinvestment runway
  
  Skew TOWARD bear (bear 25-40%, bull 10-20%) when:
    - Revenue growth is decelerating or negative
    - Margins are compressing
    - Forward P/E > Trailing P/E (earnings expected to decline)
    - High leverage (debt/equity > 1.5)
    - Valuation stretched (PEG > 3, EV/EBITDA historically high)
    - Beta > 1.5 (high volatility)
  
  Keep roughly balanced (bull 20-25%, bear 20-25%) when:
    - Metrics are mixed or stable
    - Company is mature with predictable trajectory

  Examples of GOOD probability splits:
    - High-growth accelerating: bull 35%, base 45%, bear 20%
    - Decelerating with high valuation: bull 15%, base 45%, bear 40%
    - Stable compounder: bull 25%, base 55%, bear 20%
    - Turnaround story: bull 30%, base 30%, bear 40%
    - Cyclical at peak: bull 10%, base 40%, bear 50%

- PE multiples anchored to current trailing P/E and peer multiples
- Revenue growth rates realistic for NEXT 12 MONTHS given historical trajectory
- margin_delta_pp is the CHANGE in operating margin in percentage points from current level
  - This is a 12-month forward change, NOT a long-term aspiration
  - Bull: typically +1 to +5 pp improvement
  - Base: typically -1 to +2 pp (near current)
  - Bear: typically -2 to -6 pp compression
  - Example: if current operating margin is 11%, bull margin_delta_pp of +3.0 means 14% projected margin

RISK GUIDELINES:
- Provide 4-6 risks
- Each risk must quantify revenue and EPS impact as a negative percentage
- Probabilities are independent (don't need to sum to anything)

recommendation: exactly BUY, WATCH, or PASS.
conviction: exactly High, Medium, or Low."""},
        {"role":"user","content":f"""Analyze {ticker} ({m.get('company_name',ticker)}).

VERIFIED METRICS:
{ms}

CURRENT VALUATION CONTEXT:
- Current Price: {m.get('current_price')}
- Current Trailing P/E: {m.get('trailing_pe')}
- Current Forward P/E: {m.get('forward_pe')}
- Current EV/EBITDA: {m.get('ev_to_ebitda')}
- Trailing EPS: {m.get('trailing_eps')}
- Current Operating Margin: {m.get('operating_margin')}
- Current Net Margin: {m.get('profit_margin')}

IMPORTANT: Your scenario PE multiples must be anchored to the CURRENT trailing P/E shown above. The bull case PE should be at or above current PE. The base case PE should be near current PE. The bear case PE should be a meaningful discount but still realistic for this company's historical range.

IMPORTANT: margin_delta_pp values represent INCREMENTAL change in percentage points from the current operating margin over the NEXT 12 MONTHS. Do NOT provide long-term aspirational margins. A company with 11% operating margin improving by +2pp means projected margin of 13%, not 30%.

BUSINESS: {m.get('description','N/A')[:500]}

JSON only. No HTML tags anywhere in your response."""}
    ]


def ai_prompt_report(ticker, m):
    ms = json.dumps({k:v for k,v in m.items() if k not in ["news"]}, indent=2, default=str)
    return [
        {"role":"system","content":f"""You are a senior equity research analyst producing a comprehensive investment research report.

{REPORT_PROMPT}

CRITICAL: Use ONLY the financial data provided. Do not invent any figures.
Output clean HTML with inline CSS. White background (#ffffff), dark text (#1a1a2e), professional sans-serif font.
Use proper HTML tables with borders. Include a research masthead at the top."""},
        {"role":"user","content":f"""Produce the full institutional research report for {ticker} ({m.get('company_name',ticker)}).

VERIFIED FINANCIAL DATA:
{ms}

Generate the complete HTML report now. Sections 1-9 plus Annexure."""}
    ]

def ai_prompt_thesis_check(ticker, company_name, original_metrics, original_thesis, current_metrics):
    return [
        {"role":"system","content":"""You are a senior equity research analyst performing a thesis integrity check.
Compare the original investment thesis against current market data.
Respond ONLY with valid JSON, no fences, no extra text."""},
        {"role":"user","content":f"""THESIS CHECK: {ticker} ({company_name})

ORIGINAL THESIS:
{original_thesis}

ORIGINAL METRICS:
{json.dumps(original_metrics, default=str)}

CURRENT METRICS:
{json.dumps(current_metrics, default=str)}

Respond with exactly this JSON:
{{
  "thesis_intact": true,
  "confidence": "High",
  "updated_action": "BUY",
  "key_changes": ["Change 1", "Change 2"],
  "rationale": "2-3 sentence summary of whether the thesis holds and why."
}}

thesis_intact: true if the core investment case is still valid.
updated_action: exactly BUY, WATCH, or PASS.
confidence: High, Medium, or Low."""}
    ]

# ══════════════════════════════════════════════════════════════
# AI — RUNNER
# ══════════════════════════════════════════════════════════════

def run_ai(msgs, max_tokens=3500):
    if anthropic_client:
        try:
            print(f"DEBUG: Attempting Claude with key: {ANTHROPIC_API_KEY[:10]}...")
            system_msg = ""
            user_msgs = []
            for m in msgs:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)

            r = anthropic_client.messages.create(
                model="claude-haiku-3-5-20241022",
                system=system_msg,
                messages=user_msgs,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return r.content[0].text.strip(), "claude-haiku-3.5", None
        except Exception as e:
            err = f"Claude: {str(e)[:120]}"
    else:
        err = "Claude: No API key configured"

    FREE_MODELS = [
        "z-ai/glm-4.5-air:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "qwen/qwen3-coder:free",
        "google/gemma-3-27b-it:free",
    ]
    errors = [err]
    for model in FREE_MODELS:
        try:
            r = client.chat.completions.create(
                model=model, messages=msgs, max_tokens=max_tokens, temperature=0.3,
                extra_headers={"HTTP-Referer":"https://pickr.streamlit.app","X-Title":"PickR"},
            )
            return r.choices[0].message.content.strip(), model, None
        except Exception as e:
            errors.append(f"{model}: {str(e)[:120]}")
            time.sleep(3)
    return None, None, errors

def _parse_json_response(raw, model):
    try:
        if raw.startswith("```"): raw = raw.split("\n",1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()

        try:
            a = json.loads(raw)
            a["model_used"] = model
            return a, None
        except json.JSONDecodeError:
            pass

        last_quote_pair = raw.rfind('","')
        last_bracket = raw.rfind('"]')
        cut_point = max(last_quote_pair + 1, last_bracket + 1) if max(last_quote_pair, last_bracket) > 0 else -1

        if cut_point > len(raw) * 0.5:
            attempt = raw[:cut_point + 1]
            open_brackets = attempt.count("[") - attempt.count("]")
            open_braces = attempt.count("{") - attempt.count("}")
            attempt += "]" * open_brackets
            attempt += "}" * open_braces
            try:
                a = json.loads(attempt)
                a["model_used"] = model
                return a, None
            except json.JSONDecodeError:
                pass

        last_brace = raw.rfind("}")
        if last_brace > 0:
            attempt = raw[:last_brace + 1]
            if attempt.count('"') % 2 != 0: attempt += '"'
            attempt += "]" * (attempt.count("[") - attempt.count("]"))
            attempt += "}" * (attempt.count("{") - attempt.count("}"))
            try:
                a = json.loads(attempt)
                a["model_used"] = model
                return a, None
            except json.JSONDecodeError:
                pass

        for i in range(len(raw) - 1, len(raw) // 2, -1):
            if raw[i] == '"' and (i == 0 or raw[i-1] != '\\'):
                attempt = raw[:i+1]
                open_brackets = attempt.count("[") - attempt.count("]")
                open_braces = attempt.count("{") - attempt.count("}")
                attempt += "]" * open_brackets
                attempt += "}" * open_braces
                try:
                    a = json.loads(attempt)
                    a["model_used"] = model
                    return a, None
                except json.JSONDecodeError:
                    continue

        return None, f"{model}: Bad JSON — could not repair | Raw: {raw[:300]}"
    except Exception as e:
        return None, f"{model}: Parse error — {str(e)[:100]}"


# ── CHANGED: updated defaults to use margin_delta_pp ──────────
@st.cache_data(ttl=86400, show_spinner=False)
def _cached_ai_json(ticker, metrics_json_str):
    m = json.loads(metrics_json_str)
    msgs = ai_prompt_ui(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=4000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = _parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}
    defaults = {
        "investment_thesis": "Analysis not available.",
        "recommendation": "WATCH",
        "conviction": "Medium",
        "business_overview": "Analysis not available.",
        "revenue_architecture": "Analysis not available.",
        "growth_drivers": "Analysis not available.",
        "financial_commentary": "Analysis not available.",
        "peer_positioning": "Analysis not available.",
        "scenarios": {
            "bull": {"probability": 0.20, "narrative": "N/A", "revenue_growth": 0.10,
                     "margin_delta_pp": 2.0, "pe_multiple": 25, "pe_rationale": "N/A"},
            "base": {"probability": 0.60, "narrative": "N/A", "revenue_growth": 0.05,
                     "margin_delta_pp": 0.5, "pe_multiple": 20, "pe_rationale": "N/A"},
            "bear": {"probability": 0.20, "narrative": "N/A", "revenue_growth": -0.05,
                     "margin_delta_pp": -2.0, "pe_multiple": 15, "pe_rationale": "N/A"},
        },
        "risks": [],
        "catalysts": [],
        "conclusion": "Analysis not available.",
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v
    return a

def run_ai_json(ticker, m):
    metrics_json_str = json.dumps(
        {k:v for k,v in m.items() if k not in ["description","news"]},
        sort_keys=True, default=str
    )
    llm_output = _cached_ai_json(ticker, metrics_json_str)

    if isinstance(llm_output, dict) and llm_output.get("error"):
        return llm_output

    scenario_math = compute_scenario_math(m, llm_output)
    llm_output["scenario_math"] = scenario_math

    return llm_output

def run_ai_html(ticker, m):
    msgs = ai_prompt_report(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=5500)
    if raw is None: return None, errors
    if raw.startswith("```"): raw=raw.split("\n",1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):   raw=raw[:-3]
    if raw.startswith("html"): raw=raw[4:]
    return raw.strip(), None

def run_thesis_check(ticker, company_name, original_metrics, original_thesis, current_metrics):
    msgs = ai_prompt_thesis_check(ticker, company_name, original_metrics, original_thesis, current_metrics)
    raw, model, errors = run_ai(msgs, max_tokens=800)
    if raw is None: return None, errors
    a, err = _parse_json_response(raw, model)
    if err: return None, [err]
    return a, None


# ══════════════════════════════════════════════════════════════
# RENDER — MAIN REPORT
# ══════════════════════════════════════════════════════════════

def render(ticker, m, a, data):
    company = m.get("company_name", ticker)
    date = datetime.now().strftime("%B %d, %Y")
    cur = m.get("currency", "USD")
    sym = get_sym(cur)
    sm = a.get("scenario_math", {})

    st.markdown('<div class="rpt-card">', unsafe_allow_html=True)
    st.markdown(f'''<div class="rpt-head"><h2>{company}</h2>
        <div class="meta">{ticker} &nbsp;/&nbsp; {m.get("sector","")} &nbsp;/&nbsp; {m.get("industry","")} &nbsp;/&nbsp; {cur} &nbsp;/&nbsp; {date}</div>
    </div>''', unsafe_allow_html=True)

    # ── Recommendation Bar ──
    rec = a.get("recommendation", "WATCH").upper()
    conv = a.get("conviction", "Medium")
    rc = "buy" if rec == "BUY" else ("pass" if rec == "PASS" else "watch")
    ev = sm.get("expected_value", 0)
    exp_ret = sm.get("expected_return", 0)
    prob_pos = sm.get("prob_positive_return", 0)

    st.markdown(f'''<div class="rec-bar">
        <div class="rb-item"><div class="rb-label">Recommendation</div><div class="rb-val {rc}">{rec}</div></div>
        <div class="rb-item"><div class="rb-label">Conviction</div><div class="rb-val {rc}">{conv}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Value</div><div class="rb-val {rc}">{sym}{ev:,.2f}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Return</div><div class="rb-val {rc}">{exp_ret*100:+.1f}%</div></div>
        <div class="rb-item"><div class="rb-label">P(Positive)</div><div class="rb-val {rc}">{prob_pos*100:.0f}%</div></div>
    </div>''', unsafe_allow_html=True)

    # ── CHANGED: strip_html on investment thesis ──
    if a.get("investment_thesis"):
        st.markdown(f'<div class="exec-summary">{strip_html(a["investment_thesis"])}</div>', unsafe_allow_html=True)

    # ── 52-Week Range ──
    w52h = m.get("week_52_high"); w52l = m.get("week_52_low"); cp = m.get("current_price")
    if w52h and w52l and cp:
        try:
            w52h = float(w52h); w52l = float(w52l); cpf = float(cp)
            if w52h > w52l:
                pct = max(0, min(100, ((cpf - w52l) / (w52h - w52l)) * 100))
                st.markdown(f'''<div class="sec">52-Week Range</div>
                <div class="range-bar-container"><div class="range-bar-labels">
                    <span>{sym}{w52l:,.2f}</span><span style="color:rgba(255,255,255,0.6);font-weight:600;">Current: {sym}{cpf:,.2f}</span><span>{sym}{w52h:,.2f}</span>
                </div><div class="range-bar"><div class="range-bar-fill" style="width:{pct}%"></div><div class="range-bar-dot" style="left:{pct}%"></div></div></div>''', unsafe_allow_html=True)
        except: pass

    # ── 5-Year Price History ──
    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy(); cd.columns = ["Price"]
        st.line_chart(cd, width="stretch", height=250, color="#8b1a1a")

    # ── Key Metrics ──
    st.markdown('<div class="sec">Key Metrics <span class="vtag">Python-Verified</span></div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Market Cap", fmt_c(m.get("market_cap"), cur))
    with c2: st.metric("Price", fmt_c(m.get("current_price"), cur))
    with c3: st.metric("Trailing P/E", fmt_r(m.get("trailing_pe")))
    with c4: st.metric("Forward P/E", fmt_r(m.get("forward_pe")))
    with c5: st.metric("PEG", fmt_r(m.get("peg_ratio")))
    with c6: st.metric("EV/EBITDA", fmt_r(m.get("ev_to_ebitda")))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Revenue", fmt_c(m.get("total_revenue"), cur))
    with c2: st.metric("Gross Margin", fmt_p(m.get("gross_margin")))
    with c3: st.metric("Op. Margin", fmt_p(m.get("operating_margin")))
    with c4: st.metric("Net Margin", fmt_p(m.get("profit_margin")))
    with c5: st.metric("ROE", fmt_p(m.get("roe")))
    with c6: st.metric("FCF Yield", fmt_p(m.get("fcf_yield")))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Rev Growth", fmt_p(m.get("revenue_growth")))
    with c2: st.metric("Rev CAGR", fmt_p(m.get("revenue_cagr")))
    with c3: st.metric("Debt/Equity", fmt_r(m.get("debt_to_equity")))
    with c4: st.metric("Current Ratio", fmt_r(m.get("current_ratio")))
    with c5: st.metric("Beta", fmt_r(m.get("beta")))
    with c6:
        r5 = m.get("price_5y_return")
        st.metric("5Y Return", f"{r5}%" if r5 else "-")

    # ── Revenue & Earnings Trend ──
    rh, nh = m.get("revenue_history", {}), m.get("net_income_history", {})
    if rh or nh:
        st.markdown('<div class="sec">Revenue & Earnings Trend (Billions)</div>', unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            if rh: st.bar_chart(pd.DataFrame({"Revenue": rh}), width="stretch", height=200, color="#8b1a1a")
        with cc2:
            if nh: st.bar_chart(pd.DataFrame({"Net Income": nh}), width="stretch", height=200, color="#d4443a")

    # ── CHANGED: strip_html on all LLM prose sections ─────────
    st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="prose">{strip_html(a.get("business_overview", "Not available."))}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="prose">{strip_html(a.get("revenue_architecture", "Not available."))}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Growth Drivers & Competitive Moats</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="prose">{strip_html(a.get("growth_drivers", "Not available."))}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Financial Commentary</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="prose">{strip_html(a.get("financial_commentary", "Not available."))}</div>', unsafe_allow_html=True)

    # ── Peer Comparison ──
    sector = m.get("sector", "")
    if sector in SECTOR_PEERS:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        if a.get("peer_positioning"):
            st.markdown(f'<div class="rationale-text">{strip_html(a["peer_positioning"])}</div>', unsafe_allow_html=True)
        with st.spinner("Loading peers..."):
            peers = fetch_peers(ticker, sector)
        if peers:
            cur_row = {"Ticker": ticker, "Company": m.get("company_name", ticker), "Mkt Cap": fmt_c(m.get("market_cap"), cur),
                "P/E": fmt_r(m.get("trailing_pe")), "Fwd P/E": fmt_r(m.get("forward_pe")),
                "PEG": fmt_r(m.get("peg_ratio")), "Margin": fmt_p(m.get("operating_margin")),
                "ROE": fmt_p(m.get("roe")), "Rev Gr.": fmt_p(m.get("revenue_growth"))}
            hds = list(cur_row.keys())
            th = "".join(f"<th>{h}</th>" for h in hds)
            tr_c = "<tr class='hl'>" + "".join(f"<td>{cur_row[h]}</td>" for h in hds) + "</tr>"
            tr_p = "".join("<tr>" + "".join(f"<td>{pr.get(h, '-')}</td>" for h in hds) + "</tr>" for pr in peers)
            st.markdown(f'<table class="pt"><thead><tr>{th}</tr></thead><tbody>{tr_c}{tr_p}</tbody></table>', unsafe_allow_html=True)

    # ── CHANGED: Scenario Analysis with strip_html ────────────
    st.markdown('<div class="sec">Scenario Analysis <span class="vtag">Python-Computed</span></div>', unsafe_allow_html=True)

    # ── CHANGED: show probability reasoning ──
    prob_reasoning = a.get("probability_reasoning", "")
    if prob_reasoning:
        st.markdown(f'<div class="rationale-text">{strip_html(prob_reasoning)}</div>', unsafe_allow_html=True)

    scenarios = sm.get("scenarios", {})
    for sname, slabel, scolor in [("bull", "Bull Case", "#4ade80"), ("base", "Base Case", "#fbbf24"), ("bear", "Bear Case", "#f87171")]:
        s = scenarios.get(sname, {})
        if not s: continue
        prob = s.get("probability", 0) * 100
        pt = s.get("price_target", 0)
        ret = s.get("implied_return", 0) * 100
        eps = s.get("projected_eps", 0)
        pe = s.get("pe_multiple", 0)
        bpe = s.get("breakeven_pe")
        proj_margin = s.get("projected_op_margin", 0)
        narrative = strip_html(s.get("narrative", ""))
        pe_rationale = strip_html(s.get("pe_rationale", ""))

        st.markdown(f'''<div style="background:#1a1a1a;border-left:3px solid {scolor};border-radius:0 6px 6px 0;padding:1rem 1.5rem;margin:0.8rem 0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                <span style="color:{scolor};font-weight:800;font-size:0.9rem;text-transform:uppercase;letter-spacing:0.1em;">{slabel} ({prob:.0f}% probability)</span>
                <span style="color:#fff;font-weight:800;font-size:1.3rem;">{sym}{pt:,.2f} <span style="font-size:0.85rem;color:{scolor};">({ret:+.1f}%)</span></span>
            </div>
            <div style="display:flex;gap:2rem;margin-bottom:0.5rem;">
                <span style="color:rgba(255,255,255,0.4);font-size:0.8rem;">EPS: {sym}{eps:.2f}</span>
                <span style="color:rgba(255,255,255,0.4);font-size:0.8rem;">P/E: {pe:.1f}x</span>
                <span style="color:rgba(255,255,255,0.4);font-size:0.8rem;">Op. Margin: {proj_margin*100:.1f}%</span>
                {f"<span style='color:rgba(255,255,255,0.4);font-size:0.8rem;'>Breakeven P/E: {bpe:.1f}x</span>" if bpe else ""}
            </div>
            <p style="color:rgba(255,255,255,0.6);font-size:0.9rem;line-height:1.6;margin:0.3rem 0 0;font-style:italic;">{narrative}</p>
            <p style="color:rgba(255,255,255,0.35);font-size:0.78rem;margin:0.3rem 0 0;">Multiple rationale: {pe_rationale}</p>
        </div>''', unsafe_allow_html=True)

    # ── Risk Impact Table ──
    risk_impacts = sm.get("risk_impacts", [])
    if risk_impacts:
        st.markdown('<div class="sec">Risk Quantification <span class="vtag">Python-Computed</span></div>', unsafe_allow_html=True)
        risk_header = "<tr><th>Risk</th><th>Prob.</th><th>Revenue Impact</th><th>EPS Impact</th><th>Scenario</th></tr>"
        risk_rows = ""
        for ri in risk_impacts:
            rev_imp = ri.get("revenue_impact", 0)
            eps_imp = ri.get("eps_impact", 0)
            rev_pct = ri.get("revenue_impact_pct", 0) * 100
            eps_pct = ri.get("eps_impact_pct", 0) * 100
            risk_rows += f'''<tr>
                <td><strong>{strip_html(ri.get("name",""))}</strong><br><span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">{strip_html(ri.get("description",""))}</span></td>
                <td>{ri.get("probability",0)*100:.0f}%</td>
                <td style="color:#f87171;">{fmt_n(rev_imp, p=sym)} ({rev_pct:+.1f}%)</td>
                <td style="color:#f87171;">{sym}{eps_imp:+.2f} ({eps_pct:+.1f}%)</td>
                <td>{ri.get("scenario_affected","").title()}</td>
            </tr>'''
        st.markdown(f'<table class="pt"><thead>{risk_header}</thead><tbody>{risk_rows}</tbody></table>', unsafe_allow_html=True)

    # ── Risk-Adjusted Metrics ──
    st.markdown('<div class="sec">Risk-Adjusted Metrics <span class="vtag">Python-Computed</span></div>', unsafe_allow_html=True)

    sharpe = sm.get("sharpe_ratio", 0)
    sharpe_color = "#4ade80" if sharpe > 1.0 else ("#fbbf24" if sharpe > 0.5 else "#f87171")
    ud_ratio = sm.get("upside_downside_ratio", 0)
    ud_color = "#4ade80" if ud_ratio > 1.5 else ("#fbbf24" if ud_ratio > 1.0 else "#f87171")
    mdd = sm.get("max_drawdown_magnitude", 0) * 100
    mdd_prob = sm.get("max_drawdown_prob", 0) * 100
    rfr = sm.get("risk_free_rate", 0.043) * 100

    # ── CHANGED: handle inf upside/downside ratio display ─────
    if ud_ratio == float('inf'):
        ud_display = "∞"
    else:
        ud_display = f"{ud_ratio:.2f}x"

    st.markdown(f'''<div class="qglp-s">
        <div class="qg">
            <div class="qc">
                <div class="ql">Expected Return</div>
                <div class="qs" style="color:{sharpe_color};">{exp_ret*100:+.1f}%</div>
            </div>
            <div class="qc">
                <div class="ql">Std. Deviation</div>
                <div class="qs">{sm.get("std_dev",0)*100:.1f}%</div>
            </div>
            <div class="qc">
                <div class="ql">Sharpe Ratio</div>
                <div class="qs" style="color:{sharpe_color};">{sharpe:.2f}</div>
                <div class="qsub">vs {rfr:.1f}% risk-free</div>
            </div>
            <div class="qc">
                <div class="ql">Up/Down Capture</div>
                <div class="qs" style="color:{ud_color};">{ud_display}</div>
            </div>
            <div class="qc">
                <div class="ql">Max Drawdown</div>
                <div class="qs" style="color:#f87171;">{mdd:.1f}%</div>
                <div class="qsub">{mdd_prob:.0f}% probability</div>
            </div>
        </div>
    </div>''', unsafe_allow_html=True)

    # ── Catalysts ──
    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">Catalyst Calendar</div>', unsafe_allow_html=True)
        cat_header = "<tr><th>Date</th><th>Event</th><th style='color:#4ade80;'>Bull Signal</th><th style='color:#f87171;'>Bear Signal</th></tr>"
        cat_rows = ""
        for c in catalysts:
            cat_rows += f'''<tr>
                <td style="font-weight:600;">{strip_html(c.get("date",""))}</td>
                <td>{strip_html(c.get("event",""))}</td>
                <td style="color:#4ade80;">{strip_html(c.get("bull_signal",""))}</td>
                <td style="color:#f87171;">{strip_html(c.get("bear_signal",""))}</td>
            </tr>'''
        st.markdown(f'<table class="pt"><thead>{cat_header}</thead><tbody>{cat_rows}</tbody></table>', unsafe_allow_html=True)

    # ── Conclusion ──
    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["conclusion"])}</div>', unsafe_allow_html=True)

    # ── Footer ──
    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")} &nbsp;/&nbsp; Math computed in Python &nbsp;/&nbsp; Report #{st.session_state.report_count}
    </div>''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# RENDER — TRACK BOX
# ══════════════════════════════════════════════════════════════

def render_track_box(ticker, m, a):
    rec = a.get("recommendation","WATCH").upper()
    if rec not in ("BUY","WATCH"):
        return

    company  = m.get("company_name", ticker)
    cur      = m.get("currency","USD")
    sym      = get_sym(cur)
    cp_raw   = m.get("current_price")
    try:    cp = float(cp_raw) if cp_raw else 0.0
    except: cp = 0.0

    sm = a.get("scenario_math", {})
    base_scenario = sm.get("scenarios", {}).get("base", {})
    suggested_target = base_scenario.get("price_target", 0.0)
    bear_scenario = sm.get("scenarios", {}).get("bear", {})
    suggested_entry = bear_scenario.get("price_target", 0.0)
    try:
        if not suggested_target or float(suggested_target)==0.0:
            suggested_target = round(cp * 1.15, 2)
        if not suggested_entry or float(suggested_entry)==0.0:
            suggested_entry = round(cp * 0.97, 2)
        suggested_target = float(suggested_target)
        suggested_entry  = float(suggested_entry)
    except:
        suggested_target = round(cp*1.15,2)
        suggested_entry  = round(cp*0.97,2)

    rec_color = "#22c55e" if rec=="BUY" else "#f5c542"

    st.markdown(f'''<div class="track-box">
        <div class="track-box-title">📬 Track this stock</div>
        <p style="color:rgba(255,255,255,0.45);font-size:0.9rem;line-height:1.65;margin:0 0 1rem;">
            Get an email when <strong style="color:#fff;">{company}</strong> hits your target price —
            with a live AI thesis check at that moment to tell you if the original case still holds.
            Thesis target: <strong style="color:{rec_color};">{sym}{suggested_target:,.2f}</strong>
        </p>
    </div>''', unsafe_allow_html=True)

    with st.expander("Set up price alert →", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            user_email = st.text_input(
                "Your email",
                placeholder="you@example.com",
                key=f"track_email_{ticker}"
            )
        with col2:
            target_price = st.number_input(
                f"Alert me when price reaches ({sym})",
                min_value=0.01,
                value=suggested_target,
                step=0.50,
                key=f"track_target_{ticker}"
            )

        thesis_snapshot  = f"{a.get('executive_summary','')} {a.get('recommendation_rationale','')}".strip()
        metrics_snapshot = {
            "trailing_pe":     m.get("trailing_pe"),
            "forward_pe":      m.get("forward_pe"),
            "peg_ratio":       m.get("peg_ratio"),
            "operating_margin":m.get("operating_margin"),
            "roe":             m.get("roe"),
            "revenue_growth":  m.get("revenue_growth"),
            "revenue_cagr":    m.get("revenue_cagr"),
            "fcf_yield":       m.get("fcf_yield"),
            "debt_to_equity":  m.get("debt_to_equity"),
            "ev_to_ebitda":    m.get("ev_to_ebitda"),
        }

        if st.button("Start Tracking", key=f"track_btn_{ticker}", type="primary"):
            if not user_email or "@" not in user_email:
                st.error("Please enter a valid email address.")
            elif not GMAIL_SENDER or not GMAIL_APP_PASS:
                st.warning("Email not configured. Add GMAIL_SENDER and GMAIL_APP_PASS to .streamlit/secrets.toml")
            else:
                gh_ok, gh_err = _gh_put_file_tracked(ticker, company, rec,
                    target_price, cp, metrics_snapshot, thesis_snapshot, user_email)
                ok, err = email_confirmation(
                    user_email, ticker, company, rec,
                    f"{sym}{target_price:,.2f}", f"{sym}{cp:,.2f}"
                )
                if gh_ok and ok:
                    st.session_state.track_success = ("green", f"✓ Tracking live! Confirmation sent to {user_email}")
                elif gh_ok and not ok:
                    st.session_state.track_success = ("green", f"✓ Tracking live! (Email failed: {err})")
                elif not gh_ok and ok:
                    st.session_state.track_success = ("yellow", f"⚠ Email sent but GitHub save failed: {gh_err} — tracking won't persist across restarts")
                else:
                    st.session_state.track_success = ("red", f"✗ Both GitHub save and email failed. GitHub: {gh_err} | Email: {err}")

        if st.session_state.track_success:
            colour, msg = st.session_state.track_success
            bg = {"green":"rgba(74,222,128,0.1)","yellow":"rgba(251,191,36,0.1)","red":"rgba(248,113,113,0.1)"}.get(colour,"rgba(74,222,128,0.1)")
            border = {"green":"rgba(74,222,128,0.3)","yellow":"rgba(251,191,36,0.3)","red":"rgba(248,113,113,0.3)"}.get(colour,"rgba(74,222,128,0.3)")
            text = {"green":"#4ade80","yellow":"#fbbf24","red":"#f87171"}.get(colour,"#4ade80")
            st.markdown(f'<div style="background:{bg};border:1px solid {border};border-radius:6px;padding:0.8rem 1.2rem;font-size:0.88rem;color:{text};margin-top:0.8rem;line-height:1.5;">{msg}</div>',
                        unsafe_allow_html=True)
            st.session_state.track_success = None

        st.markdown(
            '<div class="track-note">Your email is only used for price alerts on stocks you choose to track. Never shared.</div>',
            unsafe_allow_html=True
        )


# ══════════════════════════════════════════════════════════════
# MAIN UI
# ══════════════════════════════════════════════════════════════

st.markdown('''<div class="hero">
    <h1><span class="pick">Pick</span><span class="accent">R</span></h1>
    <div class="tag">Intelligent Equity Research</div>
    <div class="desc">Institutional-quality research reports powered by the QGLP framework. Verified financials, scenario analysis, peer comparisons, and AI-driven insights.</div>
</div>''', unsafe_allow_html=True)

st.markdown(f'''<div class="stats-row">
    <div class="sr-item"><span class="sr-num">24</span><span class="sr-lbl">Verified Metrics</span></div>
    <div class="sr-item"><span class="sr-num">4</span><span class="sr-lbl">QGLP Dimensions</span></div>
    <div class="sr-item"><span class="sr-num">5Y</span><span class="sr-lbl">Price History</span></div>
</div>''', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
cl,cm,cr = st.columns([1,2.5,1])
with cm:
    recent_list = st.session_state.recent[-6:]

    l1, l2 = st.columns([3,2])
    with l1:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Search by company name</div>', unsafe_allow_html=True)
    with l2:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Popular stocks</div>', unsafe_allow_html=True)

    s_col1, s_col2 = st.columns([3,2])

    with s_col1:
        sq = st.text_input("Search by name",
                           placeholder="e.g. Apple, Reliance, Broadcom",
                           label_visibility="collapsed", key="s1")
        if sq and len(sq) >= 2:
            res = search_ticker(sq)
            if res:
                opts = {f"{r['name']} ({r['symbol']})": r['symbol'] for r in res}
                sel  = st.selectbox("Pick result", opts.keys(),
                                    label_visibility="collapsed", key="s2")
                if sel:
                    st.session_state["resolved"] = opts[sel]
            else:
                st.caption("No results. Try the ticker box below.")

    with s_col2:
        sp = st.selectbox("Popular", POPULAR.keys(),
                          label_visibility="collapsed", key="s3")
        if sp and POPULAR[sp]:
            st.session_state["resolved"] = POPULAR[sp]

    tl1, tl2 = st.columns([3,2])
    with tl1:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Enter ticker directly</div>', unsafe_allow_html=True)
    with tl2:
        if recent_list:
            st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Recent searches</div>', unsafe_allow_html=True)

    t_col1, t_col2 = st.columns([3,2])
    with t_col1:
        td = st.text_input("Enter ticker directly",
                           placeholder="e.g. AVGO, AAPL, RELIANCE.NS",
                           label_visibility="collapsed", key="s4")
        if td:
            st.session_state["resolved"] = td.strip().upper()
    with t_col2:
        if recent_list:
            sr = st.selectbox("Recent", ["— recent —"] + list(reversed(recent_list)),
                              label_visibility="collapsed", key="s_recent")
            if sr and sr != "— recent —":
                st.session_state["resolved"] = sr
        else:
            st.markdown("<div style='height:2.3rem'></div>", unsafe_allow_html=True)

    resolved_now = st.session_state.get("resolved")
    if resolved_now:
        st.markdown(
            f'<div style="text-align:center;font-size:0.78rem;color:rgba(255,255,255,0.45);'
            f'padding:0.4rem 0 0.1rem;font-weight:600;letter-spacing:0.04em;">'
            f'Selected: <span style="color:#ffffff;">{resolved_now}</span></div>',
            unsafe_allow_html=True
        )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    go = st.button("Generate Report", width="stretch", type="primary")

status_area = st.container()


st.markdown('''<div class="hiw">
    <div class="hiw-title">How It Works</div>
    <div class="hiw-grid">
        <div class="hiw-card">
            <div class="hiw-step">Step 1</div>
            <div class="hiw-title2">Search</div>
            <div class="hiw-desc">Enter a company name or ticker. We support US, Indian, European, and Asian markets.</div>
        </div>
        <div class="hiw-card">
            <div class="hiw-step">Step 2</div>
            <div class="hiw-title2">Analyze</div>
            <div class="hiw-desc">We fetch real-time data, compute 24 financial metrics in Python, and run QGLP scoring via AI.</div>
        </div>
        <div class="hiw-card">
            <div class="hiw-step">Step 3</div>
            <div class="hiw-title2">Report</div>
            <div class="hiw-desc">Get a full research report with scores, charts, peer comparison, and a downloadable institutional analysis.</div>
        </div>
    </div>
</div>''', unsafe_allow_html=True)

st.markdown('''<div class="thesis-section">
    <div class="thesis-title">The QGLP Framework</div>
    <div class="thesis-grid">
        <div class="thesis-card">
            <div class="thesis-card-letter">Q</div>
            <div class="thesis-card-name">Quality</div>
            <div class="thesis-card-desc">Competitive moats, margin durability, return on capital, free cash flow quality, and management's capital allocation track record.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">G</div>
            <div class="thesis-card-name">Growth</div>
            <div class="thesis-card-desc">Revenue and EPS trajectory, organic vs. acquired growth, forward estimates, and whether growth is accelerating or decelerating.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">L</div>
            <div class="thesis-card-name">Longevity</div>
            <div class="thesis-card-desc">Secular tailwinds, total addressable market, management quality, reinvestment runway, and 10-year business durability.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">P</div>
            <div class="thesis-card-name">Price</div>
            <div class="thesis-card-desc">Valuation through multiple lenses: P/E, PEG, EV/EBITDA, FCF yield, historical context, and margin of safety analysis.</div>
        </div>
    </div>
    <div class="thesis-scoring">
        <div class="thesis-scoring-title">Scoring Thresholds</div>
        <div class="scoring-row">
            <div class="scoring-item"><div class="scoring-range buy">7.5 - 10</div><div class="scoring-label">Buy</div></div>
            <div class="scoring-item"><div class="scoring-range watch">5.0 - 7.4</div><div class="scoring-label">Watch</div></div>
            <div class="scoring-item"><div class="scoring-range pass">0 - 4.9</div><div class="scoring-label">Pass</div></div>
        </div>
    </div>
</div>''', unsafe_allow_html=True)

st.markdown('''<div class="params-card">
    <div class="thesis-title">Research Parameters</div>
    <div class="params-row"><span class="params-key">Financial Data</span><span class="params-val">FMP API (with yfinance fallback)</span></div>
    <div class="params-row"><span class="params-key">AI Analysis</span><span class="params-val">Multi-model via OpenRouter (best available)</span></div>
    <div class="params-row"><span class="params-key">Metrics Calculation</span><span class="params-val">Python (verified, not AI-generated)</span></div>
    <div class="params-row"><span class="params-key">CAGR Period</span><span class="params-val">Based on available annual data (typically 3-4 years)</span></div>
    <div class="params-row"><span class="params-key">Peer Selection</span><span class="params-val">FMP peers + sector fallback (top 4)</span></div>
    <div class="params-row"><span class="params-key">Price Tracking</span><span class="params-val">Daily email alerts when target price is reached</span></div>
    <div class="params-row"><span class="params-key">Download Report</span><span class="params-val">Full institutional PDF report with scenario analysis</span></div>
</div>''', unsafe_allow_html=True)

report_area = st.container()

# ══════════════════════════════════════════════════════════════
# GENERATION LOGIC
# ══════════════════════════════════════════════════════════════

should_generate = False
ticker          = None

resolved = st.session_state.get("resolved", None)

if go and resolved:
    ticker          = resolved.strip().upper()
    should_generate = True
elif go and not resolved:
    with status_area:
        st.warning("Select or enter a company first.")

if should_generate and ticker:
    if ticker not in st.session_state.recent:
        st.session_state.recent.append(ticker)
    st.session_state.report_count       += 1
    st.session_state.cached_html         = None
    st.session_state.generate_html       = False
    st.session_state.html_just_generated = False

    with status_area:
        with st.status(f"Analyzing {ticker}...", expanded=True) as status:
            st.write(f"Connecting to FMP API for **{ticker}**...")
            st.caption("Pulling real-time price, fundamentals, financials, and 5-year history")
            try: sd = fetch(ticker)
            except Exception as e: st.error(f"Failed to fetch data: {e}"); st.stop()
            info = sd.get("info",{})
            if isinstance(info,dict) and info.get("error"):
                st.error(f"Ticker '{ticker}' not found or unavailable."); st.stop()

            company_name = info.get("shortName", info.get("longName", ticker))
            data_source = info.get('_source', 'yfinance')
            st.write(f"Loaded **{company_name}** (via {data_source})")

            st.write("Computing 24 verified financial metrics...")
            st.caption("Revenue CAGR, margins, ROE/ROA, FCF yield, valuation ratios, debt metrics")
            m = calc(sd)
            if "error" in m: st.error(m["error"]); st.stop()

            st.write("Running QGLP analysis via AI...")
            st.caption("Scoring Quality, Growth, Longevity, and Price dimensions with institutional-grade prose")
            a = run_ai_json(ticker, m)
            if isinstance(a,dict) and a.get("error"):
                status.update(label="Analysis failed", state="error")
                for d in a.get("details",[]): st.code(d)
                st.stop()

            rec = a.get("recommendation","WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state.cached_report = {"ticker":ticker,"metrics":m,"analysis":a,"data":sd}


# ══════════════════════════════════════════════════════════════
# RENDER FROM CACHE
# ══════════════════════════════════════════════════════════════

if st.session_state.cached_report:
    cached   = st.session_state.cached_report
    c_ticker = cached["ticker"]
    c_m      = cached["metrics"]
    c_a      = cached["analysis"]
    c_data   = cached["data"]

    with report_area:
        render(c_ticker, c_m, c_a, c_data)

        render_track_box(c_ticker, c_m, c_a)

        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('''<div style="text-align:center;padding:1rem 0 0.5rem;">
            <div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div>
        </div>''', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)
        with dl1:
            sm = c_a.get("scenario_math", {})
            scenarios = sm.get("scenarios", {})
            md_lines = [
                f"# {c_m.get('company_name',c_ticker)} ({c_ticker})",
                f"PickR Research / {datetime.now().strftime('%B %d, %Y')}",
                f"{c_m.get('sector','')} / {c_m.get('industry','')} / {c_m.get('currency','USD')}", "",
                f"## {c_a.get('recommendation','N/A')} | {c_a.get('conviction','N/A')}", "",
                strip_html(c_a.get("investment_thesis", "")), "", "---", "",
                "## Business Overview", "", strip_html(c_a.get("business_overview", "")), "",
                "## Revenue Architecture", "", strip_html(c_a.get("revenue_architecture", "")), "",
                "## Growth Drivers & Moats", "", strip_html(c_a.get("growth_drivers", "")), "",
                "## Financial Commentary", "", strip_html(c_a.get("financial_commentary", "")), "",
                "---", "", "## Scenario Analysis", "",
            ]
            for sn, sl in [("bull","Bull"), ("base","Base"), ("bear","Bear")]:
                s = scenarios.get(sn, {})
                md_lines += [
                    f"### {sl} Case ({s.get('probability',0)*100:.0f}%)",
                    f"Price Target: ${s.get('price_target',0):,.2f} ({s.get('implied_return',0)*100:+.1f}%)",
                    f"EPS: ${s.get('projected_eps',0):.2f} | P/E: {s.get('pe_multiple',0):.1f}x | Op. Margin: {s.get('projected_op_margin',0)*100:.1f}%",
                    strip_html(s.get("narrative", "")), "",
                ]
            md_lines += [
                "---", "",
                f"Expected Value: ${sm.get('expected_value',0):,.2f}",
                f"Sharpe Ratio: {sm.get('sharpe_ratio',0):.2f}",
                f"Probability of Positive Return: {sm.get('prob_positive_return',0)*100:.0f}%", "",
                "## Conclusion", "", strip_html(c_a.get("conclusion", "")),
                "", f"*PickR / {datetime.now().strftime('%B %d, %Y')}*"
            ]
            st.download_button("Download (Markdown)", "\n".join(md_lines),
                f"PickR_{c_ticker}.md", "text/markdown", width="stretch")

        with dl2:
            sm = c_a.get("scenario_math", {})
            export_data = {
                "ticker": c_ticker,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "recommendation": c_a.get("recommendation"),
                "conviction": c_a.get("conviction"),
                "expected_value": sm.get("expected_value"),
                "expected_return": sm.get("expected_return"),
                "sharpe_ratio": sm.get("sharpe_ratio"),
                "prob_positive": sm.get("prob_positive_return"),
                "scenarios": sm.get("scenarios"),
                "risk_impacts": sm.get("risk_impacts"),
                "metrics": {k:v for k,v in c_m.items() if k not in ["description","news","revenue_history","net_income_history"]},
            }
            st.download_button("Download (JSON)", json.dumps(export_data, indent=2, default=str),
                f"PickR_{c_ticker}.json", "application/json", width="stretch")

# ── Footer ────────────────────────────────────────────────────
st.markdown(f'''<div class="foot-card">
    <div class="foot-name">Built by Mayukh Kondepudi</div>
    <div class="foot-email">mayukhkondepudi@gmail.com</div>
    <div class="foot-disclaimer">
        PickR is an AI-powered equity research tool for educational and informational purposes only.
        It does not constitute financial advice, investment recommendations, or an offer to buy or sell securities.
        All financial data is sourced from FMP API with Yahoo Finance fallback and may be delayed. AI-generated analysis is based on
        publicly available information and should not be relied upon as the sole basis for investment decisions.
        Past performance does not guarantee future results. Always consult a qualified financial advisor
        before making investment decisions.
    </div>
    <div class="foot-copy">&copy; {datetime.now().year} PickR. All rights reserved.</div>
</div>''', unsafe_allow_html=True)
