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
        background: linear-gradient(180deg, #ffffff 0%, #ffffff 35%, #e0e0e0 55%, #c8c8c8 75%, #e8e8e8 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
        filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6)) drop-shadow(0 0 12px rgba(255,255,255,0.08));
    }
    .hero h1 .accent {
        background: linear-gradient(135deg, #a52525 0%, #e04040 30%, #ff8a8a 50%, #e04040 70%, #a52525 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
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
    .hiw-desc { font-size:0.9rem; color:rgba(255,255,255,0.55); line-height:1.65; }

    .thesis-section { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:2rem; margin:1.5rem 0; }
    .thesis-title { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.16em;
        color:rgba(255,255,255,0.2); margin-bottom:1rem; }
    .thesis-grid { display:grid; grid-template-columns:1fr 1fr; gap:1.2rem; }
    .thesis-card { background:#1a1a1a; border-radius:6px; padding:1rem 1.2rem; }
    .thesis-card-letter { font-size:1.4rem; font-weight:800; color:#8b1a1a; margin-bottom:0.2rem; }
    .thesis-card-name { font-size:0.95rem; font-weight:700; color:#ffffff; margin-bottom:0.3rem; }
    .thesis-card-desc { font-size:0.9rem; color:rgba(255,255,255,0.55); line-height:1.6; }
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
    .params-key { color:rgba(255,255,255,0.55); font-weight:500; }
    .params-val { color:#ffffff; font-weight:600; }

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

    .prose { font-size:1rem; line-height:1.95; color:#dedede; padding:0.3rem 0 0.8rem; }

    .risk-row { padding:0.75rem 0; border-bottom:1px solid rgba(255,255,255,0.07);
        font-size:0.95rem; line-height:1.75; color:#dedede; }
    .risk-row:last-child { border-bottom:none; }

    .cb { padding:1.2rem 1.5rem; border-radius:8px; font-size:0.95rem; line-height:1.8; color:#dedede; }
    .cb-bull { background:rgba(74,222,128,0.08); border:1px solid rgba(74,222,128,0.28); }
    .cb-bear { background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.25); }
    .cb-title { font-size:0.65rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em; margin-bottom:0.5rem; }
    .cb-bull .cb-title { color:#4ade80; }
    .cb-bear .cb-title { color:#f87171; }

    .pt { width:100%; border-collapse:collapse; font-size:0.88rem; }
    .pt th { text-align:left; font-size:0.65rem; font-weight:800; text-transform:uppercase;
        letter-spacing:0.08em; color:rgba(255,255,255,0.6); padding:0.6rem 0.75rem;
        border-bottom:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.03); }
    .pt td { padding:0.55rem 0.75rem; border-bottom:1px solid rgba(255,255,255,0.06); color:#dedede; }
    .pt tr.hl td { font-weight:700; color:#ffffff; background:rgba(224,48,48,0.1); }

    .vtag { display:inline-block; font-size:0.52rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.08em; color:#e03030; border:1px solid rgba(224,48,48,0.4);
        padding:0.06rem 0.3rem; border-radius:2px; margin-left:0.4rem; vertical-align:middle; }

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

    .driver-card { background:#141414; border:1px solid rgba(255,255,255,0.06);
        border-radius:8px; padding:1rem 1.2rem; margin:0.5rem 0; }
    .driver-card-name { font-weight:700; color:#fff; font-size:0.95rem; margin-bottom:0.2rem; }
    .driver-card-desc { font-size:0.82rem; color:rgba(255,255,255,0.45); margin-bottom:0.8rem; }

    .hw-grid { display:grid; grid-template-columns:1fr 1fr; gap:0.8rem; margin:0.8rem 0 1.2rem; }
    .hw-card { background:#141414; border:1px solid rgba(248,113,113,0.2); border-radius:8px; padding:1rem 1.2rem; }
    .tw-card { background:#141414; border:1px solid rgba(74,222,128,0.2); border-radius:8px; padding:1rem 1.2rem; }
    .hw-card-title { font-size:0.78rem; font-weight:800; text-transform:uppercase;
        letter-spacing:0.1em; color:#f87171; margin-bottom:0.3rem; }
    .tw-card-title { font-size:0.78rem; font-weight:800; text-transform:uppercase;
        letter-spacing:0.1em; color:#4ade80; margin-bottom:0.3rem; }
    .hw-card-desc { font-size:0.85rem; color:rgba(255,255,255,0.5); line-height:1.55; margin-bottom:0.6rem; }
    .hw-prob-badge { display:inline-block; font-size:0.65rem; font-weight:700;
        text-transform:uppercase; letter-spacing:0.08em; padding:0.15rem 0.4rem;
        border-radius:3px; background:rgba(248,113,113,0.15); color:#f87171;
        border:1px solid rgba(248,113,113,0.3); margin-bottom:0.4rem; }
    .tw-prob-badge { display:inline-block; font-size:0.65rem; font-weight:700;
        text-transform:uppercase; letter-spacing:0.08em; padding:0.15rem 0.4rem;
        border-radius:3px; background:rgba(74,222,128,0.1); color:#4ade80;
        border:1px solid rgba(74,222,128,0.25); margin-bottom:0.4rem; }

    .scenario-card { background:#1a1a1a; border-radius:8px; padding:1.2rem 1.5rem; margin:0.8rem 0; }
    .scenario-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.8rem; }
    .scenario-label { font-weight:800; font-size:0.9rem; text-transform:uppercase; letter-spacing:0.1em; }
    .scenario-target { text-align:right; }
    .scenario-target-price { font-size:1.4rem; font-weight:900; color:#fff; }
    .scenario-return { font-size:0.88rem; font-weight:700; margin-top:0.1rem; }
    .scenario-stats { display:flex; gap:1.8rem; margin-bottom:0.6rem; flex-wrap:wrap; }
    .scenario-stat { font-size:0.8rem; color:rgba(255,255,255,0.4); }
    .scenario-stat strong { color:rgba(255,255,255,0.75); }
    .scenario-narrative { font-size:0.9rem; color:rgba(255,255,255,0.6); line-height:1.7; font-style:italic; margin:0.4rem 0 0.3rem; }
    .scenario-pe-note { font-size:0.76rem; color:rgba(255,255,255,0.3); margin-top:0.3rem; }

    .ev-bar { display:flex; justify-content:center; gap:2.5rem; background:#141414;
        border:1px solid rgba(255,255,255,0.06); border-radius:8px;
        padding:1.2rem 1.5rem; margin:1rem 0; flex-wrap:wrap; }
    .ev-item { text-align:center; }
    .ev-label { font-size:0.62rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.12em; color:rgba(255,255,255,0.3); margin-bottom:0.3rem; }
    .ev-val { font-size:1.3rem; font-weight:800; color:#fff; }
    .ev-val.positive { color:#4ade80; }
    .ev-val.negative { color:#f87171; }
    .ev-val.neutral  { color:#fbbf24; }

    .plain-callout { background:rgba(139,26,26,0.12); border-left:3px solid #8b1a1a;
        border-radius:0 6px 6px 0; padding:0.9rem 1.2rem; margin:0.8rem 0;
        font-size:0.9rem; color:rgba(255,255,255,0.65); line-height:1.7; }
    .plain-callout-label { font-size:0.62rem; font-weight:800; text-transform:uppercase;
        letter-spacing:0.14em; color:#c03030; margin-bottom:0.3rem; }

    .prob-explainer { background:#141414; border:1px solid rgba(255,255,255,0.06);
        border-radius:8px; padding:1.2rem 1.5rem; margin:1rem 0; font-size:0.88rem;
        color:rgba(255,255,255,0.55); line-height:1.7; }
    .prob-explainer strong { color:#fff; }
    .prob-math-row { display:flex; gap:1rem; align-items:center; flex-wrap:wrap;
        margin:0.6rem 0; font-size:0.85rem; }
    .prob-math-chip { background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1);
        border-radius:4px; padding:0.25rem 0.6rem; color:#e0e0e0; font-weight:600; }
    .prob-math-chip.bull { border-color:rgba(74,222,128,0.4); color:#4ade80; background:rgba(74,222,128,0.06); }
    .prob-math-chip.bear { border-color:rgba(248,113,113,0.4); color:#f87171; background:rgba(248,113,113,0.06); }
    .prob-math-chip.base { border-color:rgba(251,191,36,0.4); color:#fbbf24; background:rgba(251,191,36,0.06); }
    .prob-math-arrow { color:rgba(255,255,255,0.3); font-size:0.9rem; }

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
    st.warning("FMP_API_KEY not found - will use yfinance as fallback for all data.")

GMAIL_SENDER   = st.secrets.get("GMAIL_SENDER",   os.getenv("GMAIL_SENDER",   ""))
GMAIL_APP_PASS = st.secrets.get("GMAIL_APP_PASS",  os.getenv("GMAIL_APP_PASS", ""))
RESEND_API_KEY = st.secrets.get("RESEND_API_KEY",  os.getenv("RESEND_API_KEY", ""))
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
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
    "USD":"$","INR":"Rs.","EUR":"E","GBP":"L","JPY":"Y","CNY":"Y","KRW":"W",
    "HKD":"HK$","SGD":"S$","AUD":"A$","CAD":"C$","BRL":"R$","TWD":"NT$","PKR":"Rs.",
}


# ══════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════

def safe_float(val, default=0.0):
    """Safely convert any value to float."""
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default

def get_sym(c):
    if not c or c == "N/A": return "$"
    return CURRENCY_SYMBOLS.get(c, f"{c} ")

def fmt_n(v, p="", s="", d=2):
    if v is None or v == "N/A" or v == "": return "-"
    try:
        n = float(v)
        if abs(n) >= 1e12: return f"{p}{n/1e12:.{d}f}T{s}"
        if abs(n) >= 1e9:  return f"{p}{n/1e9:.{d}f}B{s}"
        if abs(n) >= 1e6:  return f"{p}{n/1e6:.{d}f}M{s}"
        if abs(n) >= 1e3:  return f"{p}{n/1e3:.{d}f}K{s}"
        return f"{p}{n:.{d}f}{s}"
    except: return "-"

def fmt_p(v, d=1):
    if v is None or v == "N/A" or v == "": return "-"
    try:
        n = float(v); return f"{n*100:.{d}f}%" if abs(n) < 1 else f"{n:.{d}f}%"
    except: return "-"

def fmt_r(v, d=2):
    if v is None or v == "N/A" or v == "": return "-"
    try: return f"{float(v):.{d}f}"
    except: return "-"

def fmt_c(v, cur="USD", d=2):
    return fmt_n(v, p=get_sym(cur), d=d)

def strip_html(text):
    """Remove HTML tags, markdown formatting, and escape remaining special chars."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'<[^>]*$', ' ', s)
    s = re.sub(r'^[^<]*>', ' ', s)
    s = re.sub(r'```[a-z]*\n?', '', s)
    s = re.sub(r'```', '', s)
    s = re.sub(r'`([^`]*)`', r'\1', s)
    s = re.sub(r'\*\*([^*]*)\*\*', r'\1', s)
    s = re.sub(r'\*([^*]*)\*', r'\1', s)
    s = s.replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r' {2,}', ' ', s)
    return s.strip()

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
            return False, "GitHub not configured - saved locally only"
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
# EMAIL
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
    color = "#22c55e" if recommendation == "BUY" else "#f5c542"
    sym   = "^" if recommendation == "BUY" else "o"
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
        Prices are checked daily.
      </p>
      <p style="color:rgba(255,255,255,0.15);font-size:0.72rem;margin-top:1.5rem;">
        PickR - For informational purposes only. Not financial advice.
      </p>
    </div>
    """
    return send_email(to_email, f"PickR: Now tracking {ticker} ({recommendation})", body)


# ══════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def search_ticker(query):
    return fmp_api.search_ticker(query)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch(ticker):
    result = fmp_api.fetch_full(ticker)
    if result is None:
        return {"info": {"error": f"Could not fetch data for {ticker}"},
                "inc": None, "qinc": None, "bs": None, "cf": None, "hist": None, "news": []}
    return result

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_peers(ticker, sector, llm_peers=None):
    """Fetch peer data. Uses LLM-suggested peers first, sector fallback second."""
    if llm_peers and len(llm_peers) > 0:
        peer_tickers = [p.upper() for p in llm_peers if p.upper() != ticker.upper()][:5]
    else:
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
        "peg_ratio": g("pegRatio"), "price_to_book": g("priceToBook"),
        "price_to_sales": g("priceToSalesTrailing12Months"),
        "ev_to_ebitda": g("enterpriseToEbitda"),
        "gross_margin": g("grossMargins"), "operating_margin": g("operatingMargins"),
        "profit_margin": g("profitMargins"), "roe": g("returnOnEquity"), "roa": g("returnOnAssets"),
        "trailing_eps": g("trailingEps"), "forward_eps": g("forwardEps"),
        "earnings_growth": g("earningsGrowth"),
        "total_revenue": g("totalRevenue"), "revenue_growth": g("revenueGrowth"),
        "free_cashflow": g("freeCashflow"), "operating_cashflow": g("operatingCashflow"),
        "total_cash": g("totalCash"), "total_debt": g("totalDebt"),
        "dividend_yield": g("dividendYield"), "payout_ratio": g("payoutRatio"),
        "beta": g("beta"), "week_52_high": g("fiftyTwoWeekHigh"), "week_52_low": g("fiftyTwoWeekLow"),
        "ma_50": g("fiftyDayAverage"), "ma_200": g("twoHundredDayAverage"),
        "insider_pct": g("heldPercentInsiders"), "institution_pct": g("heldPercentInstitutions"),
        "shares_outstanding": g("sharesOutstanding"),
    }

    try:
        m["fcf_yield"] = float(m["free_cashflow"]) / float(m["market_cap"]) \
            if m["free_cashflow"] and m["market_cap"] else None
    except: m["fcf_yield"] = None

    # ── Debt to equity ──
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

    # ── Revenue and income history ──
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
                hist = {str(dt.year) if hasattr(dt, 'year') else str(dt): round(float(v) / 1e9, 2)
                        for dt, v in row.items()}
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

    # ── Compute margins from statements if missing ──
    if m["gross_margin"] is None and inc is not None:
        try:
            rev_row = gp_row = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index: rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Gross Profit","GrossProfit"]:
                if lb in inc.index: gp_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and gp_row is not None:
                rev = float(rev_row.iloc[-1]); gp = float(gp_row.iloc[-1])
                if rev > 0: m["gross_margin"] = round(gp / rev, 4)
        except: pass

    if m["operating_margin"] is None and inc is not None:
        try:
            rev_row = op_row = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index: rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Operating Income","OperatingIncome","EBIT"]:
                if lb in inc.index: op_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and op_row is not None:
                rev = float(rev_row.iloc[-1]); op = float(op_row.iloc[-1])
                if rev > 0: m["operating_margin"] = round(op / rev, 4)
        except: pass

    if m["profit_margin"] is None and inc is not None:
        try:
            rev_row = ni_row = None
            for lb in ["Total Revenue","TotalRevenue","Revenue"]:
                if lb in inc.index: rev_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Net Income","NetIncome","Net Income Common Stockholders"]:
                if lb in inc.index: ni_row = inc.loc[lb].dropna().sort_index(); break
            if rev_row is not None and ni_row is not None:
                rev = float(rev_row.iloc[-1]); ni = float(ni_row.iloc[-1])
                if rev > 0: m["profit_margin"] = round(ni / rev, 4)
        except: pass

    if m["roe"] is None and inc is not None and bs is not None:
        try:
            ni_row = eq_row = None
            for lb in ["Net Income","NetIncome","Net Income Common Stockholders"]:
                if lb in inc.index: ni_row = inc.loc[lb].dropna().sort_index(); break
            for lb in ["Stockholders Equity","Total Stockholder Equity","CommonStockEquity"]:
                if lb in bs.index: eq_row = bs.loc[lb].dropna().sort_index(); break
            if ni_row is not None and eq_row is not None:
                ni = float(ni_row.iloc[-1]); eq = float(eq_row.iloc[0])
                if eq > 0: m["roe"] = round(ni / eq, 4)
        except: pass

    # ── Price history ──
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
    
        # ── Cross-validate forward PE ──
    # FMP sometimes returns trailing PE as forward PE, or inflated values
    # Compute it ourselves if we have the data
    computed_forward_pe = None
    if m["current_price"] and m.get("forward_eps"):
        try:
            cp_val = float(m["current_price"])
            fe_val = float(m["forward_eps"])
            if fe_val > 0 and cp_val > 0:
                computed_forward_pe = round(cp_val / fe_val, 2)
        except:
            pass

    api_forward_pe = m.get("forward_pe")
    api_trailing_pe = m.get("trailing_pe")

    if computed_forward_pe is not None:
        # We trust our own computation over the API
        m["forward_pe"] = computed_forward_pe
        print(f"  Forward PE: using computed {computed_forward_pe} "
              f"(API returned {api_forward_pe})")
    elif api_forward_pe is not None:
        try:
            fpe = float(api_forward_pe)
            tpe = float(api_trailing_pe) if api_trailing_pe else 0
            # Sanity: forward PE should generally be less than trailing PE
            # for growing companies. If it's higher AND above 500, it's suspect
            if fpe > 500:
                print(f"  Forward PE {fpe} exceeds 500x, discarding as unreliable")
                m["forward_pe"] = None
            elif tpe > 0 and fpe > tpe * 1.5 and fpe > 100:
                # Forward PE much higher than trailing = likely data error
                print(f"  Forward PE {fpe} > 1.5x trailing PE {tpe}, "
                      f"using trailing as forward estimate")
                m["forward_pe"] = tpe
        except:
            pass

    # ── PEG fallback: only use earnings growth, never revenue ──
    if m["peg_ratio"] is None:
        try:
            pe = safe_float(m.get("trailing_pe"))
            if pe <= 0:
                pe = safe_float(m.get("forward_pe"))
            growth = None
            # Priority 1: earnings growth (YoY)
            if m.get("earnings_growth"):
                g_val = float(m["earnings_growth"])
                growth = g_val * 100 if abs(g_val) < 1 else g_val
            # Priority 2: EPS CAGR
            if growth is None and m.get("eps_cagr") and float(m["eps_cagr"]) != 0:
                g_val = float(m["eps_cagr"])
                growth = g_val * 100 if abs(g_val) < 1 else g_val
            # Priority 3: Net income CAGR
            if growth is None and m.get("net_income_cagr") and float(m["net_income_cagr"]) != 0:
                g_val = float(m["net_income_cagr"])
                growth = g_val * 100 if abs(g_val) < 1 else g_val
            # Never fall back to revenue CAGR - show "-" instead
            if pe and pe > 0 and growth and growth > 0:
                m["peg_ratio"] = round(pe / growth, 2)
        except Exception:
            pass

    m["news"] = [{"title": n.get("title",""), "publisher": n.get("publisher","")}
                 for n in data.get("news", [])]
    return m

# ══════════════════════════════════════════════════════════════
# PROBABILITY ENGINE
# ══════════════════════════════════════════════════════════════

def compute_scenario_probabilities(llm_output):
    """
    Derives bull/base/bear probabilities from macro driver outcomes.
    Uses geometric mean to prevent degenerate distributions with 3+ drivers.
    """

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
                "bull_p": bull_p / total,
                "base_p": base_p / total,
                "bear_p": bear_p / total,
            })
        except (TypeError, ValueError):
            continue

    if not valid_drivers:
        return {
            "bull": 0.25, "base": 0.50, "bear": 0.25,
            "method": "fallback",
            "driver_detail": [],
            "raw_geometric": {"bull": 0.25, "bear": 0.25},
            "correlation_multipliers": {"bull": 1.0, "bear": 1.0},
        }

    n = len(valid_drivers)

    # Geometric mean of each outcome across drivers
    bull_product = 1.0
    bear_product = 1.0
    for d in valid_drivers:
        bull_product *= d["bull_p"]
        bear_product *= d["bear_p"]

    geo_bull = bull_product ** (1.0 / n)
    geo_bear = bear_product ** (1.0 / n)

    # Mild correlation boost (outcomes tend to cluster in reality)
    BULL_BOOST = 1.2
    BEAR_BOOST = 1.4
    adjusted_bull = geo_bull * BULL_BOOST
    adjusted_bear = geo_bear * BEAR_BOOST

    # Clamp
    adjusted_bull = max(MIN_SCENARIO_PROB, min(MAX_SCENARIO_PROB, adjusted_bull))
    adjusted_bear = max(MIN_SCENARIO_PROB, min(MAX_SCENARIO_PROB, adjusted_bear))

    if adjusted_bull + adjusted_bear > 0.85:
        scale = 0.85 / (adjusted_bull + adjusted_bear)
        adjusted_bull *= scale
        adjusted_bear *= scale

    adjusted_base = 1.0 - adjusted_bull - adjusted_bear
    adjusted_base = max(MIN_SCENARIO_PROB, adjusted_base)

    total = adjusted_bull + adjusted_base + adjusted_bear
    final_bull = round(adjusted_bull / total, 4)
    final_bear = round(adjusted_bear / total, 4)
    final_base = round(1.0 - final_bull - final_bear, 4)

    print(f"  Probability engine: geo_bull={geo_bull:.4f}, geo_bear={geo_bear:.4f} | "
          f"final: bull={final_bull:.2%}, base={final_base:.2%}, bear={final_bear:.2%}")

    return {
        "bull": final_bull,
        "base": final_base,
        "bear": final_bear,
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

def compute_scenario_math(metrics, llm_output):
    """
    All financial math lives here. The LLM provides qualitative assumptions
    (revenue growth, margin delta, PE multiple per scenario). Python computes
    every number from fundamentals.

    Key design decisions:
    - EPS is anchored to trailing EPS and grown, never rebuilt from scratch
    - Forward PE is the primary valuation anchor
    - Headwinds/tailwinds are display-only, not applied to scenario math
    - Risk-free rate is 6%
    """

    # ── Step 1: Extract all base metrics upfront ──
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
    ev_ebitda        = safe_float(metrics.get("ev_to_ebitda"))
    risk_free_rate   = 0.06

    # ── Step 2: Derive missing fundamentals ──
    if shares == 0 and current_price > 0 and market_cap > 0:
        shares = market_cap / current_price

    if trailing_eps == 0 and current_price > 0:
        if trailing_pe > 0:
            trailing_eps = current_price / trailing_pe
        elif forward_pe > 0:
            trailing_eps = current_price / forward_pe

    if trailing_eps == 0 and forward_eps > 0:
        trailing_eps = forward_eps

    if total_revenue == 0 and market_cap > 0:
        ps = safe_float(metrics.get("price_to_sales"))
        if ps > 0:
            total_revenue = market_cap / ps

    if trailing_eps == 0 and total_revenue > 0 and shares > 0 and profit_margin > 0:
        trailing_eps = (total_revenue * profit_margin) / shares

    # ── Step 3: Net-to-operating ratio ──
    if operating_margin > 0 and profit_margin > 0:
        net_to_op_ratio = profit_margin / operating_margin
    else:
        net_to_op_ratio = 0.79
    net_to_op_ratio = max(0.3, min(net_to_op_ratio, 1.0))

    # ── Step 4: PE anchor (forward PE primary) ──
    if forward_pe > 0:
        anchor_pe = forward_pe
    elif trailing_pe > 0:
        anchor_pe = trailing_pe
    else:
        # No PE available at all - trust LLM multiples without clamping
        anchor_pe = 0

    print(f"  Scenario math inputs: price={current_price}, eps={trailing_eps:.2f}, "
          f"forward_eps={forward_eps:.2f}, revenue={total_revenue:.0f}, shares={shares:.0f}, "
          f"op_margin={operating_margin:.3f}, net_to_op={net_to_op_ratio:.3f}, "
          f"trailing_pe={trailing_pe:.1f}, forward_pe={forward_pe:.1f}, anchor_pe={anchor_pe:.1f}")

    # ── Step 5: Compute probabilities from macro driver engine ──
    prob_output = compute_scenario_probabilities(llm_output)
    scenario_probs = {
        "bull": prob_output["bull"],
        "base": prob_output["base"],
        "bear": prob_output["bear"],
    }

    # ── Step 6: PE floor and ceiling bands ──
    # Only apply if we have a valid anchor PE
    if anchor_pe > 0:
        # Normalize to prevent extreme PEs from distorting bands
        normalized_pe = min(anchor_pe, 50.0)
        pe_floors = {
            "bull": normalized_pe * 0.70,
            "base": normalized_pe * 0.55,
            "bear": normalized_pe * 0.25,
        }
        pe_ceilings = {
            "bull": normalized_pe * 1.60,
            "base": normalized_pe * 1.25,
            "bear": normalized_pe * 0.90,
        }
        apply_pe_clamp = True
    else:
        pe_floors = {"bull": 5.0, "base": 5.0, "bear": 5.0}
        pe_ceilings = {"bull": 80.0, "base": 60.0, "bear": 40.0}
        apply_pe_clamp = True

    # ── Step 7: Compute each scenario ──
    scenarios = llm_output.get("scenarios", {})
    results   = {}

    for scenario_name, s in scenarios.items():
        try:
            prob       = scenario_probs.get(scenario_name, 0.20)
            rev_growth = safe_float(s.get("revenue_growth"))
            pe_mult    = safe_float(s.get("pe_multiple"), default=20.0)

            # Clamp PE to floor/ceiling
            if apply_pe_clamp:
                floor   = pe_floors.get(scenario_name, 5.0)
                ceiling = pe_ceilings.get(scenario_name, 80.0)
                pe_mult = max(floor, min(pe_mult, ceiling))
            pe_mult = max(pe_mult, 3.0)  # absolute floor

            # ── Projected operating margin ──
            if "margin_delta_pp" in s:
                margin_delta        = safe_float(s.get("margin_delta_pp")) / 100.0
                projected_op_margin = operating_margin + margin_delta
            else:
                projected_op_margin = operating_margin if operating_margin > 0 else 0.15
            projected_op_margin = max(0.01, min(projected_op_margin, 0.65))

            # ── EPS projection: anchored to trailing EPS ──
            # Core formula: earnings grow with revenue AND margin changes
            # earnings_growth = (1 + rev_growth) * (new_margin / old_margin) - 1
            if trailing_eps != 0 and operating_margin > 0:
                margin_effect     = projected_op_margin / operating_margin
                effective_growth  = (1 + rev_growth) * margin_effect - 1
                projected_eps     = trailing_eps * (1 + effective_growth)
            elif trailing_eps != 0:
                # No margin data, just grow EPS by revenue growth
                projected_eps = trailing_eps * (1 + rev_growth)
            elif current_price > 0 and anchor_pe > 0:
                # Derive EPS from price/PE, then grow
                implied_eps   = current_price / anchor_pe
                projected_eps = implied_eps * (1 + rev_growth)
            elif current_price > 0:
                # Last resort: assume 20x PE
                implied_eps   = current_price / 20.0
                projected_eps = implied_eps * (1 + rev_growth)
            else:
                projected_eps = 0.0

            # ── Projected revenue (for display only) ──
            projected_revenue = total_revenue * (1 + rev_growth) if total_revenue > 0 else 0

            # ── Price target and return ──
            price_target   = projected_eps * pe_mult
            implied_return = ((price_target - current_price) / current_price
                              if current_price > 0 else 0.0)

            # ── Breakeven PE ──
            breakeven_pe = (current_price / projected_eps
                            if projected_eps > 0 else None)

            results[scenario_name] = {
                "probability":          round(prob, 4),
                "projected_revenue":    round(projected_revenue, 0),
                "projected_op_margin":  round(projected_op_margin, 4),
                "projected_eps":        round(projected_eps, 2),
                "effective_growth":     round(effective_growth if trailing_eps != 0 and operating_margin > 0
                                              else rev_growth, 4),
                "pe_multiple":          round(pe_mult, 1),
                "pe_rationale":         s.get("pe_rationale", ""),
                "price_target":         round(price_target, 2),
                "implied_return":       round(implied_return, 4),
                "effective_rev_growth": round(rev_growth, 4),
                "breakeven_pe":         round(breakeven_pe, 2) if breakeven_pe else None,
                "narrative":            s.get("narrative", ""),
            }

        except Exception as e:
            print(f"  Scenario {scenario_name} math error: {e}")
            results[scenario_name] = {
                "probability": scenario_probs.get(scenario_name, 0.20),
                "projected_revenue": 0, "projected_op_margin": 0,
                "projected_eps": 0, "effective_growth": 0,
                "pe_multiple": 0, "pe_rationale": "",
                "price_target": 0, "implied_return": 0,
                "effective_rev_growth": 0, "breakeven_pe": None,
                "narrative": str(e),
            }

    # ── Step 8: Sanity check - if all returns are absurd, fall back ──
    returns = [r["implied_return"] for r in results.values() if r["implied_return"] != 0]
    if returns and all(abs(r) > 5.0 for r in returns):
        print("  WARNING: All scenarios >500% magnitude. Using simple EPS growth fallback.")
        for scenario_name, s in scenarios.items():
            try:
                prob       = scenario_probs.get(scenario_name, 0.20)
                rev_growth = safe_float(s.get("revenue_growth"))
                pe_mult    = safe_float(s.get("pe_multiple"), default=20.0)
                if apply_pe_clamp:
                    floor   = pe_floors.get(scenario_name, 5.0)
                    ceiling = pe_ceilings.get(scenario_name, 80.0)
                    pe_mult = max(floor, min(pe_mult, ceiling))

                if trailing_eps != 0:
                    projected_eps = trailing_eps * (1 + rev_growth)
                elif current_price > 0 and anchor_pe > 0:
                    projected_eps = (current_price / anchor_pe) * (1 + rev_growth)
                else:
                    projected_eps = 0

                price_target   = projected_eps * pe_mult
                implied_return = ((price_target - current_price) / current_price
                                  if current_price > 0 else 0)
                breakeven_pe   = (current_price / projected_eps
                                  if projected_eps > 0 else None)
                results[scenario_name].update({
                    "probability":   prob,
                    "projected_eps": round(projected_eps, 2),
                    "pe_multiple":   round(pe_mult, 1),
                    "price_target":  round(price_target, 2),
                    "implied_return": round(implied_return, 4),
                    "breakeven_pe":  round(breakeven_pe, 2) if breakeven_pe else None,
                })
            except Exception:
                pass

    # ── Step 9: Aggregate metrics ──
    expected_value  = sum(r["price_target"] * r["probability"] for r in results.values())
    expected_return = ((expected_value - current_price) / current_price
                       if current_price > 0 else 0)

    variance = sum(
        r["probability"] * (r["implied_return"] - expected_return) ** 2
        for r in results.values()
    )
    std_dev = variance ** 0.5

    # Risk-Adjusted Score (similar to Sharpe but from 3 scenarios, with 6% risk-free)
    risk_adj_score = ((expected_return - risk_free_rate) / std_dev if std_dev > 0 else 0)

    upside_return = sum(
        r["implied_return"] * r["probability"]
        for r in results.values() if r["implied_return"] > 0
    )
    downside_return = sum(
        r["implied_return"] * r["probability"]
        for r in results.values() if r["implied_return"] < 0
    )
    upside_downside_ratio = (abs(upside_return / downside_return)
                             if downside_return != 0 else float("inf"))
    prob_positive = sum(
        r["probability"] for r in results.values() if r["price_target"] > current_price
    )

    bear = results.get("bear", {})

    # ── Step 10: Risk impacts (display-only, for the risk table) ──
    risk_impacts = []
    for risk in llm_output.get("risks", []):
        try:
            rev_impact_pct = safe_float(risk.get("revenue_impact_pct"))
            eps_impact_pct = safe_float(risk.get("eps_impact_pct"))
            risk_impacts.append({
                "name":               risk.get("name", "Unknown"),
                "probability":        safe_float(risk.get("probability")),
                "revenue_impact":     round(total_revenue * rev_impact_pct, 0),
                "revenue_impact_pct": rev_impact_pct,
                "eps_impact":         round(trailing_eps * eps_impact_pct, 2),
                "eps_impact_pct":     eps_impact_pct,
                "scenario_affected":  risk.get("scenario_affected", "bear"),
                "description":        risk.get("description", ""),
            })
        except Exception:
            continue

    return {
        "scenarios":               results,
        "scenario_probabilities":  prob_output,
        "expected_value":          round(expected_value, 2),
        "expected_return":         round(expected_return, 4),
        "std_dev":                 round(std_dev, 4),
        "risk_adjusted_score":     round(risk_adj_score, 2),
        "upside_downside_ratio":   round(upside_downside_ratio, 2),
        "prob_positive_return":    round(prob_positive, 4),
        "max_drawdown_prob":       round(bear.get("probability", 0), 4),
        "max_drawdown_magnitude":  round(bear.get("implied_return", 0), 4),
        "risk_impacts":            risk_impacts,
        "risk_free_rate":          risk_free_rate,
        "anchor_pe":               anchor_pe,
        "trailing_eps_used":       round(trailing_eps, 2),
    }

# ══════════════════════════════════════════════════════════════
# AI — TWO-PASS ARCHITECTURE
#
# Pass 1: LLM provides structured assumptions only (no narratives)
# Python: Computes all scenario math from those assumptions
# Pass 2: LLM writes full narrative report seeing the computed math
#
# This eliminates contradictions between narrative and numbers.
# ══════════════════════════════════════════════════════════════

# ── AI Runner ─────────────────────────────────────────────────

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3-coder:free",
    "google/gemma-3-27b-it:free",
]

def run_ai(msgs, max_tokens=4000):
    """Try Anthropic first, then fall back to OpenRouter free models."""
    if anthropic_client:
        try:
            system_msg = ""
            user_msgs = []
            for m in msgs:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)
            r = anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                system=system_msg,
                messages=user_msgs,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return r.content[0].text.strip(), "claude-haiku-4.5", None
        except Exception as e:
            err = f"Claude: {str(e)[:120]}"
    else:
        err = "Claude: No API key configured"

    errors = [err]
    for model in FREE_MODELS:
        try:
            r = client.chat.completions.create(
                model=model, messages=msgs, max_tokens=max_tokens, temperature=0.3,
                extra_headers={"HTTP-Referer": "https://pickr.streamlit.app", "X-Title": "PickR"},
            )
            return r.choices[0].message.content.strip(), model, None
        except Exception as e:
            errors.append(f"{model}: {str(e)[:120]}")
            time.sleep(3)
    return None, None, errors


def _parse_json_response(raw, model):
    """Parse JSON from LLM response, with repair attempts."""
    try:
        if raw.startswith("```"): raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()

        try:
            a = json.loads(raw)
            a["model_used"] = model
            return a, None
        except json.JSONDecodeError:
            pass

        # Try to repair truncated JSON
        last_brace = raw.rfind("}")
        if last_brace > len(raw) * 0.5:
            attempt = raw[:last_brace + 1]
            if attempt.count('"') % 2 != 0:
                attempt += '"'
            attempt += "]" * (attempt.count("[") - attempt.count("]"))
            attempt += "}" * (attempt.count("{") - attempt.count("}"))
            try:
                a = json.loads(attempt)
                a["model_used"] = model
                return a, None
            except json.JSONDecodeError:
                pass

        # Try progressive truncation
        for i in range(len(raw) - 1, len(raw) // 2, -1):
            if raw[i] == '"' and (i == 0 or raw[i-1] != '\\'):
                attempt = raw[:i+1]
                attempt += "]" * (attempt.count("[") - attempt.count("]"))
                attempt += "}" * (attempt.count("{") - attempt.count("}"))
                try:
                    a = json.loads(attempt)
                    a["model_used"] = model
                    return a, None
                except json.JSONDecodeError:
                    continue

        return None, f"{model}: Bad JSON - could not repair | Raw: {raw[:300]}"
    except Exception as e:
        return None, f"{model}: Parse error - {str(e)[:100]}"


# ══════════════════════════════════════════════════════════════
# PASS 1 PROMPT: STRUCTURED ASSUMPTIONS ONLY
# ══════════════════════════════════════════════════════════════

def ai_prompt_pass1(ticker, m):
    """Ask the LLM for structured assumptions. No prose, no recommendation."""
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str
    )
    description_snippet = (m.get("description") or "N/A")[:600]

    return [
        {"role": "system", "content": """You are a senior equity research analyst. Your job is to provide STRUCTURED ASSUMPTIONS for a stock analysis. You do NOT write prose or make recommendations - that comes later after the math is computed.

CRITICAL RULES:
1. Use ONLY the financial data provided plus your training knowledge about this company.
2. Respond with ONLY valid JSON. No markdown fences, no extra text.
3. All text fields must be PLAIN TEXT. No HTML tags anywhere.
4. Be specific with numbers. "Revenue grew 24% driven by AI chip demand" not "strong growth."
5. Your scenario assumptions (revenue_growth, margin_delta_pp, pe_multiple) will be used by Python to compute price targets. The LLM does NOT compute any numbers.

MACRO DRIVER RULES:
- Identify exactly 2-4 drivers that are the REAL swing factors for THIS company.
- Each driver's outcomes (bull + base + bear probabilities) must sum to 1.0.
- Bear probability on any single driver should be between 0.10 and 0.45.

SCENARIO RULES:
- revenue_growth: realistic 12-month forward rate.
- margin_delta_pp: INCREMENTAL change in operating margin in percentage points.
  Bull: typically +1 to +5 pp. Base: -1 to +2 pp. Bear: -2 to -8 pp.
- pe_multiple: anchored to Forward P/E provided below. 
  Bull: at or above forward P/E. Base: near forward P/E. Bear: meaningful discount.
  If no forward P/E available, use trailing P/E as anchor.

HEADWIND/TAILWIND RULES:
- These are for DISPLAY ONLY. They do not modify the scenario math.
- They explain WHY the scenarios have the growth rates they do.
- revenue_impact_pct values are informational context, not applied to calculations.

PEER RULES:
- Suggest exactly 4-5 US-listed ticker symbols that are the most relevant comparisons.
- Choose peers based on actual business model overlap, NOT just sector classification.
- For a company like Tesla, include EV competitors AND tech/AI comparables, not generic Consumer Cyclical stocks.
- For a company like Broadcom, include semiconductor peers AND infrastructure software peers.

CATALYST RULES:
- Only include events that are in the FUTURE (after today's date provided below).
- Do not include any past events. Focus on the next 6-12 months.
- Include earnings dates, product launches, regulatory decisions, and macro events.

RISK RULES:
- revenue_impact_pct and eps_impact_pct describe the POTENTIAL impact if the risk materializes.
- These are display-only for the risk quantification table."""},

        {"role": "user", "content": f"""Provide structured assumptions for {ticker} ({m.get('company_name', ticker)}).

VERIFIED FINANCIAL METRICS:
{ms}

VALUATION ANCHORS (use these to calibrate PE multiples):
- Current Price: {m.get('current_price')}
- Trailing P/E: {m.get('trailing_pe')} 
- Forward P/E: {m.get('forward_pe')} <-- PRIMARY ANCHOR for PE multiples
- EV/EBITDA: {m.get('ev_to_ebitda')}
- Trailing EPS: {m.get('trailing_eps')}
- Forward EPS: {m.get('forward_eps')}
- Current Operating Margin: {m.get('operating_margin')}
- Current Net Margin: {m.get('profit_margin')}
- Revenue Growth (YoY): {m.get('revenue_growth')}
- Revenue CAGR: {m.get('revenue_cagr')}

TODAY'S DATE: {datetime.now().strftime('%B %d, %Y')}
All catalyst dates must be AFTER this date. Do not include past events.

BUSINESS DESCRIPTION:
{description_snippet}

Return this EXACT JSON structure:
{{
  "macro_drivers": [
    {{
      "name": "Short name",
      "description": "1-2 sentences. Plain text only.",
      "bull_outcome": {{
        "narrative": "1-2 sentences. Plain text only.",
        "probability": 0.30
      }},
      "base_outcome": {{
        "narrative": "1-2 sentences. Plain text only.",
        "probability": 0.50
      }},
      "bear_outcome": {{
        "narrative": "1-2 sentences. Plain text only.",
        "probability": 0.20
      }}
    }}
  ],

  "headwinds": [
    {{
      "name": "Short name",
      "description": "2-3 sentences. Plain text only.",
      "probability": 0.40,
      "base_revenue_impact_pct": -0.05,
      "bear_revenue_impact_pct": -0.12,
      "base_eps_impact_pct": -0.08,
      "bear_eps_impact_pct": -0.18
    }}
  ],

  "tailwinds": [
    {{
      "name": "Short name",
      "description": "2 sentences. Plain text only.",
      "probability": 0.60,
      "bull_revenue_impact_pct": 0.08
    }}
  ],

  "scenarios": {{
    "bull": {{
      "revenue_growth": 0.25,
      "margin_delta_pp": 3.0,
      "pe_multiple": 35,
      "pe_rationale": "1 sentence justifying this multiple. Plain text only.",
      "narrative": "2-3 sentences on what has to go right. Plain text only."
    }},
    "base": {{
      "revenue_growth": 0.10,
      "margin_delta_pp": 0.5,
      "pe_multiple": 28,
      "pe_rationale": "1 sentence. Plain text only.",
      "narrative": "2-3 sentences. Plain text only."
    }},
    "bear": {{
      "revenue_growth": -0.05,
      "margin_delta_pp": -3.0,
      "pe_multiple": 18,
      "pe_rationale": "1 sentence. Plain text only.",
      "narrative": "2-3 sentences. Plain text only."
    }}
  }},

  "risks": [
    {{
      "name": "Short name",
      "probability": 0.30,
      "revenue_impact_pct": -0.08,
      "eps_impact_pct": -0.12,
      "scenario_affected": "bear",
      "description": "2 sentences. Plain text only."
    }}
  ],

  "catalysts": [
    {{
      "date": "Q3 2026",
      "event": "Specific event name",
      "bull_signal": "What positive signal to watch for",
      "bear_signal": "What negative signal to watch for"
    }}
  ],

  "peer_tickers": ["AAPL", "MSFT", "GOOGL", "NVDA"]
}}

Return ONLY valid JSON. No HTML. No markdown fences."""}
    ]


# ══════════════════════════════════════════════════════════════
# PASS 2 PROMPT: NARRATIVE WITH COMPUTED MATH
# ══════════════════════════════════════════════════════════════

def ai_prompt_pass2(ticker, m, scenario_math):
    """Ask the LLM to write the full narrative seeing the computed numbers."""
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str
    )
    description_snippet = (m.get("description") or "N/A")[:600]

    # Build a clean summary of computed results for the LLM
    scenarios = scenario_math.get("scenarios", {})
    math_summary = {
        "expected_value":        scenario_math.get("expected_value"),
        "expected_return":       f"{scenario_math.get('expected_return', 0) * 100:.1f}%",
        "prob_positive_return":  f"{scenario_math.get('prob_positive_return', 0) * 100:.0f}%",
        "risk_adjusted_score":   scenario_math.get("risk_adjusted_score"),
        "upside_downside_ratio": scenario_math.get("upside_downside_ratio"),
    }
    for sname in ["bull", "base", "bear"]:
        s = scenarios.get(sname, {})
        math_summary[f"{sname}_price_target"] = s.get("price_target")
        math_summary[f"{sname}_implied_return"] = f"{s.get('implied_return', 0) * 100:.1f}%"
        math_summary[f"{sname}_probability"] = f"{s.get('probability', 0) * 100:.0f}%"
        math_summary[f"{sname}_eps"] = s.get("projected_eps")
        math_summary[f"{sname}_pe"] = s.get("pe_multiple")

    return [
        {"role": "system", "content": """You are a senior equity research analyst writing for a mixed audience: institutional investors AND engaged non-professionals who want to understand a company deeply without needing an MBA.

You are writing the NARRATIVE sections of a research report. The MATH HAS ALREADY BEEN COMPUTED and is provided to you below. Your job is to:

1. Write a recommendation (BUY, WATCH, or PASS) that is CONSISTENT with the computed math
2. Write clear, specific narrative sections that explain the numbers
3. Use plain English - explain financial concepts briefly when you use them
4. Be specific with numbers, names, and evidence - not generic statements

CRITICAL RULES:
- Your recommendation MUST be consistent with the math. If expected return is positive and probability of positive return is above 50%, lean toward BUY. If expected return is negative, lean toward WATCH or PASS.
- All text must be PLAIN TEXT. No HTML tags anywhere.
- Do not invent metrics. Use only what is provided.
- Respond with ONLY valid JSON. No markdown fences."""},

        {"role": "user", "content": f"""Write the narrative analysis for {ticker} ({m.get('company_name', ticker)}).

VERIFIED FINANCIAL METRICS:
{ms}

BUSINESS DESCRIPTION:
{description_snippet}

COMPUTED SCENARIO MATH (already calculated - your narrative must be consistent with these):
{json.dumps(math_summary, indent=2, default=str)}

RECOMMENDATION GUIDELINES based on the computed math:
- Expected return: {math_summary['expected_return']}
- Probability of positive return: {math_summary['prob_positive_return']}
- Risk-adjusted score: {math_summary['risk_adjusted_score']}
- Upside/downside ratio: {math_summary['upside_downside_ratio']}

If expected return > 10% AND prob positive > 55%: recommend BUY
If expected return > 0% AND prob positive > 40%: recommend WATCH or BUY depending on conviction
If expected return < 0% OR prob positive < 40%: recommend WATCH or PASS
If expected return < -15% AND prob positive < 30%: recommend PASS

Return this EXACT JSON structure:
{{
  "recommendation": "BUY",
  "conviction": "High",
  "investment_thesis": "3 sentences. State the recommendation, conviction level, and single most important reason. Briefly identify what the company does. Must be consistent with the computed expected return of {math_summary['expected_return']} and probability of positive return of {math_summary['prob_positive_return']}. Plain text only.",

  "business_overview": "2 paragraphs. What does this company do and how does it make money? Plain text only.",

  "revenue_architecture": "3-4 paragraphs. Break down revenue by segment with specific numbers. Plain text only.",

  "growth_drivers": "2-3 paragraphs. What are the 2-3 biggest structural forces driving growth? Plain text only.",

  "financial_commentary": "2-3 paragraphs. Assess margins, cash flow, balance sheet. Use actual metrics provided. Plain text only.",

  "peer_positioning": "2-3 sentences. How does this company compare to closest peers? Plain text only.",

  "conclusion": "1 paragraph. Restate the thesis consistent with the computed math. Name the single variable all scenarios hinge on. State the most important upcoming datapoint. Plain text only."
}}

CRITICAL: Your recommendation and all narrative text MUST be consistent with the computed math above. Do not say BUY if the math shows negative expected returns. Do not say PASS if the math shows strong positive returns.

Return ONLY valid JSON. No HTML. No markdown fences."""}
    ]


# ══════════════════════════════════════════════════════════════
# AI — ORCHESTRATOR (TWO-PASS)
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass1(ticker, metrics_json_str):
    """Pass 1: Get structured assumptions from LLM."""
    m = json.loads(metrics_json_str)
    msgs = ai_prompt_pass1(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=4000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = _parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    # Apply defaults for missing fields
    defaults = {
        "macro_drivers": [],
        "headwinds": [],
        "tailwinds": [],
        "scenarios": {
            "bull": {"revenue_growth": 0.15, "margin_delta_pp": 2.0,
                     "pe_multiple": 25, "pe_rationale": "N/A", "narrative": "N/A"},
            "base": {"revenue_growth": 0.08, "margin_delta_pp": 0.5,
                     "pe_multiple": 20, "pe_rationale": "N/A", "narrative": "N/A"},
            "bear": {"revenue_growth": -0.05, "margin_delta_pp": -2.0,
                     "pe_multiple": 14, "pe_rationale": "N/A", "narrative": "N/A"},
        },
        "risks": [],
        "catalysts": [],
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v
    return a


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass2(ticker, metrics_json_str, math_json_str):
    """Pass 2: Get narrative from LLM seeing computed math."""
    m = json.loads(metrics_json_str)
    sm = json.loads(math_json_str)
    msgs = ai_prompt_pass2(ticker, m, sm)
    raw, model, errors = run_ai(msgs, max_tokens=4000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = _parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    defaults = {
        "recommendation": "WATCH",
        "conviction": "Medium",
        "investment_thesis": "Analysis not available.",
        "business_overview": "Analysis not available.",
        "revenue_architecture": "Analysis not available.",
        "growth_drivers": "Analysis not available.",
        "financial_commentary": "Analysis not available.",
        "peer_positioning": "Analysis not available.",
        "conclusion": "Analysis not available.",
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v
    a["model_used"] = model
    return a


def run_ai_two_pass(ticker, m):
    """
    Main orchestrator:
    1. Pass 1: Get structured assumptions
    2. Python: Compute all scenario math
    3. Pass 2: Get narrative consistent with math
    4. Merge everything into final output
    """

    # ── Pass 1: Assumptions ──
    metrics_json_str = json.dumps(
        {k: v for k, v in m.items() if k not in ["description", "news"]},
        sort_keys=True, default=str
    )

    pass1 = _cached_pass1(ticker, metrics_json_str)
    if isinstance(pass1, dict) and pass1.get("error"):
        return pass1

    # ── Python: Compute scenario math ──
    scenario_math = compute_scenario_math(m, pass1)

    # ── Pass 2: Narrative ──
    math_json_str = json.dumps(scenario_math, sort_keys=True, default=str)
    pass2 = _cached_pass2(ticker, metrics_json_str, math_json_str)
    if isinstance(pass2, dict) and pass2.get("error"):
        return pass2

    # ── Merge: Combine pass1 assumptions + pass2 narrative + computed math ──
    final = {}

    # From pass2 (narrative)
    final["recommendation"]       = pass2.get("recommendation", "WATCH")
    final["conviction"]           = pass2.get("conviction", "Medium")
    final["investment_thesis"]    = pass2.get("investment_thesis", "")
    final["business_overview"]    = pass2.get("business_overview", "")
    final["revenue_architecture"] = pass2.get("revenue_architecture", "")
    final["growth_drivers"]       = pass2.get("growth_drivers", "")
    final["financial_commentary"] = pass2.get("financial_commentary", "")
    final["peer_positioning"]     = pass2.get("peer_positioning", "")
    final["conclusion"]           = pass2.get("conclusion", "")
    final["model_used"]           = pass2.get("model_used", "")

    # From pass1 (structured data)
    final["macro_drivers"]  = pass1.get("macro_drivers", [])
    final["headwinds"]      = pass1.get("headwinds", [])
    final["tailwinds"]      = pass1.get("tailwinds", [])
    final["scenarios"]      = pass1.get("scenarios", {})
    final["risks"]          = pass1.get("risks", [])
    final["catalysts"]      = pass1.get("catalysts", [])
    final["peer_tickers"]   = pass1.get("peer_tickers", [])

    # Computed math
    final["scenario_math"] = scenario_math

    # ── Final consistency check ──
    # Only override if LLM made a clearly wrong recommendation despite seeing the math
    exp_ret  = scenario_math.get("expected_return", 0)
    prob_pos = scenario_math.get("prob_positive_return", 0)
    rec      = final["recommendation"].upper()

    if rec == "BUY" and exp_ret < -0.20 and prob_pos < 0.25:
        final["recommendation"] = "PASS"
        final["conviction"] = "High"
        final["rec_override_reason"] = (
            f"Override: LLM recommended BUY despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."
        )
    elif rec == "PASS" and exp_ret > 0.20 and prob_pos > 0.70:
        final["recommendation"] = "BUY"
        final["conviction"] = "Medium"
        final["rec_override_reason"] = (
            f"Override: LLM recommended PASS despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."
        )

    return final


# ══════════════════════════════════════════════════════════════
# LEGACY: HTML REPORT GENERATOR
# ══════════════════════════════════════════════════════════════

def ai_prompt_report(ticker, m):
    ms = json.dumps({k: v for k, v in m.items() if k not in ["news"]}, indent=2, default=str)
    return [
        {"role": "system", "content": f"""You are a senior equity research analyst producing a comprehensive investment research report.

{REPORT_PROMPT}

CRITICAL: Use ONLY the financial data provided. Do not invent any figures.
Output clean HTML with inline CSS. White background (#ffffff), dark text (#1a1a2e), professional sans-serif font.
Use proper HTML tables with borders. Include a research masthead at the top."""},
        {"role": "user", "content": f"""Produce the full institutional research report for {ticker} ({m.get('company_name', ticker)}).

VERIFIED FINANCIAL DATA:
{ms}

Generate the complete HTML report now."""}
    ]


def run_ai_html(ticker, m):
    msgs = ai_prompt_report(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=5500)
    if raw is None: return None, errors
    if raw.startswith("```"): raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):   raw = raw[:-3]
    if raw.startswith("html"): raw = raw[4:]
    return raw.strip(), None


# ══════════════════════════════════════════════════════════════
# THESIS CHECK (for price alert emails)
# ══════════════════════════════════════════════════════════════

def ai_prompt_thesis_check(ticker, company_name, original_metrics, original_thesis, current_metrics):
    return [
        {"role": "system", "content": """You are a senior equity research analyst performing a thesis integrity check.
Compare the original investment thesis against current market data.
Respond ONLY with valid JSON, no fences, no extra text."""},
        {"role": "user", "content": f"""THESIS CHECK: {ticker} ({company_name})

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
    company  = m.get("company_name", ticker)
    date     = datetime.now().strftime("%B %d, %Y")
    cur      = m.get("currency", "USD")
    sym      = get_sym(cur)
    sm       = a.get("scenario_math", {})
    prob_out = sm.get("scenario_probabilities", {})

    st.markdown('<div class="rpt-card">', unsafe_allow_html=True)

    # ── Masthead ──
    st.markdown(f'''<div class="rpt-head">
        <h2>{strip_html(company)}</h2>
        <div class="meta">{ticker} &nbsp;/&nbsp; {m.get("sector","")} &nbsp;/&nbsp;
        {m.get("industry","")} &nbsp;/&nbsp; {cur} &nbsp;/&nbsp; {date}</div>
    </div>''', unsafe_allow_html=True)

    # ── Recommendation Bar ──
    rec      = a.get("recommendation", "WATCH").upper()
    conv     = a.get("conviction", "Medium")
    rc       = "buy" if rec == "BUY" else ("pass" if rec == "PASS" else "watch")
    ev       = sm.get("expected_value", 0)
    exp_ret  = sm.get("expected_return", 0)
    prob_pos = sm.get("prob_positive_return", 0)

    st.markdown(f'''<div class="rec-bar">
        <div class="rb-item"><div class="rb-label">Recommendation</div>
            <div class="rb-val {rc}">{rec}</div></div>
        <div class="rb-item"><div class="rb-label">Conviction</div>
            <div class="rb-val {rc}">{conv}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Value</div>
            <div class="rb-val {rc}">{sym}{ev:,.2f}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Return</div>
            <div class="rb-val {rc}">{exp_ret*100:+.1f}%</div></div>
        <div class="rb-item"><div class="rb-label">P(Positive)</div>
            <div class="rb-val {rc}">{prob_pos*100:.0f}%</div></div>
    </div>''', unsafe_allow_html=True)

    # ── Investment Thesis ──
    if a.get("investment_thesis"):
        st.markdown(
            f'<div class="exec-summary">{strip_html(a["investment_thesis"])}</div>',
            unsafe_allow_html=True
        )

    # ── Override warning (only in extreme edge cases now) ──
    if a.get("rec_override_reason"):
        st.markdown(
            f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);'
            f'border-radius:6px;padding:0.8rem 1.2rem;font-size:0.85rem;color:#fbbf24;'
            f'margin:0.8rem 0;line-height:1.5;">{strip_html(a["rec_override_reason"])}</div>',
            unsafe_allow_html=True
        )

    # ════════════════════════════════════════════════════════
    # SECTION: 52-WEEK RANGE
    # ════════════════════════════════════════════════════════
    w52h = m.get("week_52_high")
    w52l = m.get("week_52_low")
    cp   = m.get("current_price")
    if w52h and w52l and cp:
        try:
            w52h = float(w52h); w52l = float(w52l); cpf = float(cp)
            if w52h > w52l:
                pct = max(0, min(100, ((cpf - w52l) / (w52h - w52l)) * 100))
                st.markdown(f'''<div class="sec">52-Week Range</div>
                <div class="range-bar-container">
                    <div class="range-bar-labels">
                        <span>{sym}{w52l:,.2f}</span>
                        <span style="color:rgba(255,255,255,0.6);font-weight:600;">
                            Current: {sym}{cpf:,.2f}</span>
                        <span>{sym}{w52h:,.2f}</span>
                    </div>
                    <div class="range-bar">
                        <div class="range-bar-fill" style="width:{pct}%"></div>
                        <div class="range-bar-dot" style="left:{pct}%"></div>
                    </div>
                </div>''', unsafe_allow_html=True)
        except:
            pass

    # ════════════════════════════════════════════════════════
    # SECTION: 5-YEAR PRICE HISTORY
    # ════════════════════════════════════════════════════════
    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy()
        cd.columns = ["Price"]
        st.line_chart(cd, height=250, color="#8b1a1a")

    # ════════════════════════════════════════════════════════
    # SECTION: KEY METRICS
    # ════════════════════════════════════════════════════════
    st.markdown(
        '<div class="sec">Key Metrics <span class="vtag">Python-Verified</span></div>',
        unsafe_allow_html=True
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Market Cap",    fmt_c(m.get("market_cap"), cur))
    with c2: st.metric("Price",         fmt_c(m.get("current_price"), cur))
    with c3: st.metric("Trailing P/E",  fmt_r(m.get("trailing_pe")))
    with c4: st.metric("Forward P/E",   fmt_r(m.get("forward_pe")))
    with c5: st.metric("PEG",           fmt_r(m.get("peg_ratio")))
    with c6: st.metric("EV/EBITDA",     fmt_r(m.get("ev_to_ebitda")))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Revenue",       fmt_c(m.get("total_revenue"), cur))
    with c2: st.metric("Gross Margin",  fmt_p(m.get("gross_margin")))
    with c3: st.metric("Op. Margin",    fmt_p(m.get("operating_margin")))
    with c4: st.metric("Net Margin",    fmt_p(m.get("profit_margin")))
    with c5: st.metric("ROE",           fmt_p(m.get("roe")))
    with c6: st.metric("FCF Yield",     fmt_p(m.get("fcf_yield")))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.metric("Rev Growth",    fmt_p(m.get("revenue_growth")))
    with c2: st.metric("Rev CAGR",      fmt_p(m.get("revenue_cagr")))
    with c3: st.metric("Debt/Equity",   fmt_r(m.get("debt_to_equity")))
    with c4: st.metric("Current Ratio", fmt_r(m.get("current_ratio")))
    with c5: st.metric("Beta",          fmt_r(m.get("beta")))
    with c6:
        r5 = m.get("price_5y_return")
        st.metric("5Y Return", f"{r5}%" if r5 else "-")

    # ════════════════════════════════════════════════════════
    # SECTION: REVENUE & EARNINGS TREND
    # ════════════════════════════════════════════════════════
    rh = m.get("revenue_history", {})
    nh = m.get("net_income_history", {})
    if rh or nh:
        st.markdown(
            '<div class="sec">Revenue & Earnings Trend (Billions)</div>',
            unsafe_allow_html=True
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if rh:
                st.bar_chart(pd.DataFrame({"Revenue": rh}), height=200, color="#8b1a1a")
        with cc2:
            if nh:
                st.bar_chart(pd.DataFrame({"Net Income": nh}), height=200, color="#d4443a")

    # ════════════════════════════════════════════════════════
    # SECTION: BUSINESS OVERVIEW
    # ════════════════════════════════════════════════════════
    st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("business_overview", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ════════════════════════════════════════════════════════
    # SECTION: REVENUE ARCHITECTURE
    # ════════════════════════════════════════════════════════
    st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("revenue_architecture", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ════════════════════════════════════════════════════════
    # SECTION: GROWTH DRIVERS
    # ════════════════════════════════════════════════════════
    st.markdown(
        '<div class="sec">Growth Drivers &amp; Competitive Moats</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        f'<div class="prose">{strip_html(a.get("growth_drivers", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ════════════════════════════════════════════════════════
    # SECTION: FINANCIAL COMMENTARY
    # ════════════════════════════════════════════════════════
    st.markdown('<div class="sec">Financial Commentary</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("financial_commentary", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ════════════════════════════════════════════════════════
    # SECTION: PEER COMPARISON
    # ════════════════════════════════════════════════════════
    sector = m.get("sector", "")
    llm_peers = a.get("peer_tickers", [])
    if sector in SECTOR_PEERS or llm_peers:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        if a.get("peer_positioning"):
            st.markdown(
                f'<div class="rationale-text">{strip_html(a["peer_positioning"])}</div>',
                unsafe_allow_html=True
            )
        with st.spinner("Loading peers..."):
            peers = fetch_peers(ticker, sector, llm_peers=llm_peers)
        if peers:
            cur_row = {
                "Ticker": ticker, "Company": m.get("company_name", ticker),
                "Mkt Cap": fmt_c(m.get("market_cap"), cur),
                "P/E": fmt_r(m.get("trailing_pe")),
                "Fwd P/E": fmt_r(m.get("forward_pe")),
                "PEG": fmt_r(m.get("peg_ratio")),
                "Margin": fmt_p(m.get("operating_margin")),
                "ROE": fmt_p(m.get("roe")),
                "Rev Gr.": fmt_p(m.get("revenue_growth")),
            }
            hds  = list(cur_row.keys())
            th   = "".join(f"<th>{hd}</th>" for hd in hds)
            tr_c = "<tr class='hl'>" + "".join(f"<td>{cur_row[hd]}</td>" for hd in hds) + "</tr>"
            tr_p = "".join(
                "<tr>" + "".join(f"<td>{pr.get(hd, '-')}</td>" for hd in hds) + "</tr>"
                for pr in peers
            )
            st.markdown(
                f'<table class="pt"><thead><tr>{th}</tr></thead><tbody>{tr_c}{tr_p}</tbody></table>',
                unsafe_allow_html=True
            )

    # ════════════════════════════════════════════════════════
    # SECTION: WHAT DRIVES THE OUTCOME — MACRO DRIVERS
    # ════════════════════════════════════════════════════════
    macro_drivers = a.get("macro_drivers", [])
    if macro_drivers:
        st.markdown(
            '<div class="sec">What Drives the Outcome '
            '<span class="vtag">Bottom-Up Framework</span></div>',
            unsafe_allow_html=True
        )

        st.markdown('''<div class="plain-callout">
            <div class="plain-callout-label">How this works</div>
            Instead of guessing that the bull case has a 35% chance of happening,
            we identify the 2-4 specific events that actually determine this
            company's outcome. We assign a probability to each one independently,
            then let the math compute the final scenario probabilities.
        </div>''', unsafe_allow_html=True)

        # Render each driver as separate st.markdown to prevent cascade failure
        for d in macro_drivers:
            dname = strip_html(d.get("name", ""))
            ddesc = strip_html(d.get("description", ""))

            bull_p = safe_float(d.get("bull_outcome", {}).get("probability"))
            base_p = safe_float(d.get("base_outcome", {}).get("probability"))
            bear_p = safe_float(d.get("bear_outcome", {}).get("probability"))
            bull_n = strip_html(d.get("bull_outcome", {}).get("narrative", ""))[:100]
            base_n = strip_html(d.get("base_outcome", {}).get("narrative", ""))[:100]
            bear_n = strip_html(d.get("bear_outcome", {}).get("narrative", ""))[:100]

            bull_w = max(2, min(100, round(bull_p * 100)))
            base_w = max(2, min(100, round(base_p * 100)))
            bear_w = max(2, min(100, round(bear_p * 100)))

            st.markdown(f'''<div class="driver-card">
                <div class="driver-card-name">{dname}</div>
                <div class="driver-card-desc">{ddesc}</div>
                <div style="margin:0.3rem 0;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
                        <div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;">
                            <div style="width:{bull_w}%;height:100%;background:#4ade80;border-radius:3px;"></div>
                        </div>
                        <span style="font-size:0.75rem;color:#4ade80;font-weight:700;min-width:35px;">{bull_p*100:.0f}%</span>
                        <span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{bull_n}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
                        <div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;">
                            <div style="width:{base_w}%;height:100%;background:#fbbf24;border-radius:3px;"></div>
                        </div>
                        <span style="font-size:0.75rem;color:#fbbf24;font-weight:700;min-width:35px;">{base_p*100:.0f}%</span>
                        <span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{base_n}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;">
                            <div style="width:{bear_w}%;height:100%;background:#f87171;border-radius:3px;"></div>
                        </div>
                        <span style="font-size:0.75rem;color:#f87171;font-weight:700;min-width:35px;">{bear_p*100:.0f}%</span>
                        <span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{bear_n}</span>
                    </div>
                </div>
            </div>''', unsafe_allow_html=True)

        # Probability math explainer
        if prob_out.get("method") == "geometric_mean_probability":
            raw_bull  = prob_out.get("raw_geometric", {}).get("bull", 0)
            raw_bear  = prob_out.get("raw_geometric", {}).get("bear", 0)
            bull_mult = prob_out.get("correlation_multipliers", {}).get("bull", 1.2)
            bear_mult = prob_out.get("correlation_multipliers", {}).get("bear", 1.4)
            final_bull = prob_out.get("bull", 0)
            final_base = prob_out.get("base", 0)
            final_bear = prob_out.get("bear", 0)

            st.markdown(f'''<div class="prob-explainer">
                <strong>How the final probabilities were computed:</strong><br><br>
                We take the geometric mean of each driver's bull/bear probabilities,
                then apply a mild clustering adjustment: <strong>{bull_mult:.1f}x</strong> for
                the bull tail and <strong>{bear_mult:.1f}x</strong> for the bear tail, reflecting
                the empirical reality that outcomes tend to correlate.
                <div class="prob-math-row" style="margin-top:0.8rem;">
                    <span style="color:rgba(255,255,255,0.4);font-size:0.82rem;">Geometric mean:</span>
                    <span class="prob-math-chip bull">Bull {raw_bull*100:.1f}%</span>
                    <span class="prob-math-chip bear">Bear {raw_bear*100:.1f}%</span>
                    <span class="prob-math-arrow">after clustering</span>
                    <span class="prob-math-chip bull">Bull {final_bull*100:.1f}%</span>
                    <span class="prob-math-chip base">Base {final_base*100:.1f}%</span>
                    <span class="prob-math-chip bear">Bear {final_bear*100:.1f}%</span>
                </div>
            </div>''', unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # SECTION: HEADWINDS & TAILWINDS (display-only)
    # ════════════════════════════════════════════════════════
    headwinds = a.get("headwinds", [])
    tailwinds = a.get("tailwinds", [])

    if headwinds or tailwinds:
        st.markdown(
            '<div class="sec">Headwinds &amp; Tailwinds</div>',
            unsafe_allow_html=True
        )

        st.markdown('''<div class="plain-callout">
            <div class="plain-callout-label">Context</div>
            Headwinds are specific risks that could reduce revenue or profits.
            Tailwinds are opportunities that could accelerate growth.
            These factors are already reflected in the scenario growth rates
            and margin assumptions above.
        </div>''', unsafe_allow_html=True)

        hw_cards = ""
        for hw in headwinds:
            hname = strip_html(hw.get("name", ""))
            hdesc = strip_html(hw.get("description", ""))
            hprob = safe_float(hw.get("probability"))
            hw_cards += f'''<div class="hw-card">
                <div class="hw-prob-badge">{hprob*100:.0f}% probability</div>
                <div class="hw-card-title">{hname}</div>
                <div class="hw-card-desc">{hdesc}</div>
            </div>'''

        tw_cards = ""
        for tw in tailwinds:
            tname = strip_html(tw.get("name", ""))
            tdesc = strip_html(tw.get("description", ""))
            tprob = safe_float(tw.get("probability"))
            tw_cards += f'''<div class="tw-card">
                <div class="tw-prob-badge">{tprob*100:.0f}% probability</div>
                <div class="tw-card-title">{tname}</div>
                <div class="hw-card-desc">{tdesc}</div>
            </div>'''

        all_cards = hw_cards + tw_cards
        st.markdown(f'<div class="hw-grid">{all_cards}</div>', unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # SECTION: SCENARIO ANALYSIS
    # ════════════════════════════════════════════════════════
    st.markdown(
        '<div class="sec">Scenario Analysis '
        '<span class="vtag">Python-Computed</span></div>',
        unsafe_allow_html=True
    )

    st.markdown('''<div class="plain-callout">
        <div class="plain-callout-label">How to read this</div>
        Each scenario shows what the stock could be worth in 12 months under
        different conditions. The price target is computed from projected
        earnings multiplied by a valuation multiple. Probabilities were derived
        mathematically from the driver analysis above.
    </div>''', unsafe_allow_html=True)

    scenarios = sm.get("scenarios", {})
    scenario_configs = [
        ("bull", "Bull Case",  "#4ade80", "What goes right"),
        ("base", "Base Case",  "#fbbf24", "Most likely path"),
        ("bear", "Bear Case",  "#f87171", "What goes wrong"),
    ]

    for sname, slabel, scolor, stag in scenario_configs:
        s = scenarios.get(sname, {})
        if not s:
            continue

        prob        = s.get("probability", 0) * 100
        pt          = s.get("price_target", 0)
        ret         = s.get("implied_return", 0) * 100
        eps         = s.get("projected_eps", 0)
        pe          = s.get("pe_multiple", 0)
        bpe         = s.get("breakeven_pe")
        proj_margin = s.get("projected_op_margin", 0)
        eff_growth  = s.get("effective_rev_growth", 0)
        narrative   = strip_html(s.get("narrative", ""))
        pe_rat      = strip_html(s.get("pe_rationale", ""))

        bpe_html = (f'<span class="scenario-stat">Breakeven P/E: '
                    f'<strong>{bpe:.1f}x</strong></span>') if bpe else ""

        st.markdown(f'''<div class="scenario-card" style="border-left:3px solid {scolor};">
            <div class="scenario-header">
                <div>
                    <span class="scenario-label" style="color:{scolor};">
                        {slabel}</span>
                    <span style="color:rgba(255,255,255,0.35);font-size:0.8rem;
                        font-weight:600;margin-left:0.6rem;">
                        {prob:.0f}% probability</span>
                    <div style="font-size:0.72rem;color:rgba(255,255,255,0.3);
                        margin-top:0.2rem;font-style:italic;">{stag}</div>
                </div>
                <div class="scenario-target">
                    <div class="scenario-target-price">{sym}{pt:,.2f}</div>
                    <div class="scenario-return" style="color:{scolor};">
                        {ret:+.1f}%</div>
                </div>
            </div>
            <div class="scenario-stats">
                <span class="scenario-stat">Revenue growth:
                    <strong>{eff_growth*100:+.1f}%</strong></span>
                <span class="scenario-stat">EPS:
                    <strong>{sym}{eps:.2f}</strong></span>
                <span class="scenario-stat">P/E multiple:
                    <strong>{pe:.1f}x</strong></span>
                <span class="scenario-stat">Op. margin:
                    <strong>{proj_margin*100:.1f}%</strong></span>
                {bpe_html}
            </div>
            <div class="scenario-narrative">{narrative}</div>
            <div class="scenario-pe-note">Valuation: {pe_rat}</div>
        </div>''', unsafe_allow_html=True)

    # ── Expected Value Summary Bar ──
    ras      = sm.get("risk_adjusted_score", 0)
    ud_ratio = sm.get("upside_downside_ratio", 0)
    mdd      = sm.get("max_drawdown_magnitude", 0) * 100
    mdd_prob = sm.get("max_drawdown_prob", 0) * 100
    rfr      = sm.get("risk_free_rate", 0.06) * 100
    std_dev  = sm.get("std_dev", 0) * 100

    ras_color  = "#4ade80" if ras > 1.0 else ("#fbbf24" if ras > 0.3 else "#f87171")
    ret_color  = "positive" if exp_ret > 0.05 else ("neutral" if exp_ret > 0 else "negative")
    ud_display = "inf" if ud_ratio == float("inf") else f"{ud_ratio:.2f}x"
    ud_color   = "#4ade80" if ud_ratio > 1.5 or ud_ratio == float("inf") \
                 else ("#fbbf24" if ud_ratio > 1.0 else "#f87171")

    st.markdown(f'''<div class="ev-bar">
        <div class="ev-item">
            <div class="ev-label">Expected Value</div>
            <div class="ev-val">{sym}{ev:,.2f}</div>
        </div>
        <div class="ev-item">
            <div class="ev-label">Expected Return</div>
            <div class="ev-val {ret_color}">{exp_ret*100:+.1f}%</div>
        </div>
        <div class="ev-item">
            <div class="ev-label">Std. Deviation</div>
            <div class="ev-val">{std_dev:.1f}%</div>
        </div>
        <div class="ev-item">
            <div class="ev-label">Risk-Adjusted Score</div>
            <div class="ev-val" style="color:{ras_color};">{ras:.2f}</div>
            <div style="font-size:0.65rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">
                vs {rfr:.0f}% risk-free</div>
        </div>
        <div class="ev-item">
            <div class="ev-label">Up/Down Capture</div>
            <div class="ev-val" style="color:{ud_color};">{ud_display}</div>
        </div>
        <div class="ev-item">
            <div class="ev-label">Max Drawdown</div>
            <div class="ev-val" style="color:#f87171;">{mdd:.1f}%</div>
            <div style="font-size:0.65rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">
                {mdd_prob:.0f}% probability</div>
        </div>
    </div>''', unsafe_allow_html=True)

    # Explainer
    st.markdown(f'''<div class="plain-callout">
        <div class="plain-callout-label">What these numbers mean</div>
        <strong>Expected Return</strong> is the probability-weighted average return
        across all three scenarios. <strong>Risk-Adjusted Score</strong> measures
        return per unit of risk relative to a {rfr:.0f}% risk-free rate: above 1.0
        is strong, above 0.3 is acceptable. <strong>Up/Down Capture</strong>
        compares upside potential to downside risk: above 1.5x means upside
        materially outweighs the downside.
    </div>''', unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # SECTION: RISK QUANTIFICATION
    # ════════════════════════════════════════════════════════
    risk_impacts = sm.get("risk_impacts", [])
    if risk_impacts:
        st.markdown(
            '<div class="sec">Risk Quantification '
            '<span class="vtag">Python-Computed</span></div>',
            unsafe_allow_html=True
        )
        risk_header = ("<tr><th>Risk</th><th>Prob.</th>"
                       "<th>Revenue Impact</th><th>EPS Impact</th><th>Scenario</th></tr>")
        risk_rows = ""
        for ri in risk_impacts:
            rev_imp = ri.get("revenue_impact", 0)
            eps_imp = ri.get("eps_impact", 0)
            rev_pct = ri.get("revenue_impact_pct", 0) * 100
            eps_pct = ri.get("eps_impact_pct", 0) * 100
            risk_rows += f'''<tr>
                <td><strong>{strip_html(ri.get("name",""))}</strong><br>
                <span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">
                    {strip_html(ri.get("description",""))}</span></td>
                <td>{ri.get("probability",0)*100:.0f}%</td>
                <td style="color:#f87171;">
                    {fmt_n(rev_imp, p=sym)} ({rev_pct:+.1f}%)</td>
                <td style="color:#f87171;">
                    {sym}{eps_imp:+.2f} ({eps_pct:+.1f}%)</td>
                <td>{strip_html(ri.get("scenario_affected","")).title()}</td>
            </tr>'''
        st.markdown(
            f'<table class="pt"><thead>{risk_header}</thead>'
            f'<tbody>{risk_rows}</tbody></table>',
            unsafe_allow_html=True
        )

    # ════════════════════════════════════════════════════════
    # SECTION: CATALYST CALENDAR
    # ════════════════════════════════════════════════════════
    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">Catalyst Calendar</div>', unsafe_allow_html=True)
        cat_header = ("<tr><th>Date</th><th>Event</th>"
                      "<th style='color:#4ade80;'>Positive Signal</th>"
                      "<th style='color:#f87171;'>Negative Signal</th></tr>")
        cat_rows = ""
        for c in catalysts:
            cat_rows += f'''<tr>
                <td style="font-weight:600;">{strip_html(c.get("date",""))}</td>
                <td>{strip_html(c.get("event",""))}</td>
                <td style="color:#4ade80;">{strip_html(c.get("bull_signal",""))}</td>
                <td style="color:#f87171;">{strip_html(c.get("bear_signal",""))}</td>
            </tr>'''
        st.markdown(
            f'<table class="pt"><thead>{cat_header}</thead>'
            f'<tbody>{cat_rows}</tbody></table>',
            unsafe_allow_html=True
        )

    # ════════════════════════════════════════════════════════
    # SECTION: CONCLUSION
    # ════════════════════════════════════════════════════════
    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="prose">{strip_html(a["conclusion"])}</div>',
            unsafe_allow_html=True
        )

    # ── Report footer ──
    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;
        font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")}
        &nbsp;/&nbsp; Math computed in Python
        &nbsp;/&nbsp; Report #{st.session_state.report_count}
    </div>''', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# RENDER — TRACK BOX
# ══════════════════════════════════════════════════════════════

def render_track_box(ticker, m, a):
    rec = a.get("recommendation", "WATCH").upper()
    if rec not in ("BUY", "WATCH"):
        return

    company  = m.get("company_name", ticker)
    cur      = m.get("currency", "USD")
    sym      = get_sym(cur)
    cp_raw   = m.get("current_price")
    try:    cp = float(cp_raw) if cp_raw else 0.0
    except: cp = 0.0

    sm = a.get("scenario_math", {})
    base_scenario = sm.get("scenarios", {}).get("base", {})
    suggested_target = base_scenario.get("price_target", 0.0)
    try:
        if not suggested_target or float(suggested_target) == 0.0:
            suggested_target = round(cp * 1.15, 2)
        suggested_target = float(suggested_target)
    except:
        suggested_target = round(cp * 1.15, 2)

    rec_color = "#22c55e" if rec == "BUY" else "#f5c542"

    st.markdown(f'''<div class="track-box">
        <div class="track-box-title">Track this stock</div>
        <p style="color:rgba(255,255,255,0.45);font-size:0.9rem;line-height:1.65;margin:0 0 1rem;">
            Get an email when <strong style="color:#fff;">{strip_html(company)}</strong> hits your
            target price, with a live AI thesis check at that moment.
            Thesis target: <strong style="color:{rec_color};">{sym}{suggested_target:,.2f}</strong>
        </p>
    </div>''', unsafe_allow_html=True)

    with st.expander("Set up price alert", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            user_email = st.text_input(
                "Your email", placeholder="you@example.com",
                key=f"track_email_{ticker}"
            )
        with col2:
            target_price = st.number_input(
                f"Alert me when price reaches ({sym})",
                min_value=0.01, value=suggested_target, step=0.50,
                key=f"track_target_{ticker}"
            )

        thesis_snapshot  = strip_html(a.get("investment_thesis", ""))
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
                st.warning("Email not configured. Add GMAIL_SENDER and GMAIL_APP_PASS to secrets.")
            else:
                gh_ok, gh_err = _gh_put_file_tracked(ticker, company, rec,
                    target_price, cp, metrics_snapshot, thesis_snapshot, user_email)
                ok, err = email_confirmation(
                    user_email, ticker, company, rec,
                    f"{sym}{target_price:,.2f}", f"{sym}{cp:,.2f}"
                )
                if gh_ok and ok:
                    st.session_state.track_success = ("green", f"Tracking live! Confirmation sent to {user_email}")
                elif gh_ok and not ok:
                    st.session_state.track_success = ("green", f"Tracking live! (Email failed: {err})")
                elif not gh_ok and ok:
                    st.session_state.track_success = ("yellow", f"Email sent but GitHub save failed: {gh_err}")
                else:
                    st.session_state.track_success = ("red", f"Both GitHub save and email failed. GitHub: {gh_err} | Email: {err}")

        if st.session_state.track_success:
            colour, msg = st.session_state.track_success
            bg = {"green":"rgba(74,222,128,0.1)","yellow":"rgba(251,191,36,0.1)","red":"rgba(248,113,113,0.1)"}.get(colour,"rgba(74,222,128,0.1)")
            border = {"green":"rgba(74,222,128,0.3)","yellow":"rgba(251,191,36,0.3)","red":"rgba(248,113,113,0.3)"}.get(colour,"rgba(74,222,128,0.3)")
            text_c = {"green":"#4ade80","yellow":"#fbbf24","red":"#f87171"}.get(colour,"#4ade80")
            st.markdown(
                f'<div style="background:{bg};border:1px solid {border};border-radius:6px;'
                f'padding:0.8rem 1.2rem;font-size:0.88rem;color:{text_c};margin-top:0.8rem;'
                f'line-height:1.5;">{msg}</div>',
                unsafe_allow_html=True
            )
            st.session_state.track_success = None

        st.markdown(
            '<div class="track-note">Your email is only used for price alerts. Never shared.</div>',
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
cl, cm, cr = st.columns([1, 2.5, 1])
with cm:
    recent_list = st.session_state.recent[-6:]

    l1, l2 = st.columns([3, 2])
    with l1:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Search by company name</div>', unsafe_allow_html=True)
    with l2:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Popular stocks</div>', unsafe_allow_html=True)

    s_col1, s_col2 = st.columns([3, 2])

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

    tl1, tl2 = st.columns([3, 2])
    with tl1:
        st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Enter ticker directly</div>', unsafe_allow_html=True)
    with tl2:
        if recent_list:
            st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Recent searches</div>', unsafe_allow_html=True)

    t_col1, t_col2 = st.columns([3, 2])
    with t_col1:
        td = st.text_input("Enter ticker directly",
                           placeholder="e.g. AVGO, AAPL, RELIANCE.NS",
                           label_visibility="collapsed", key="s4")
        if td:
            st.session_state["resolved"] = td.strip().upper()
    with t_col2:
        if recent_list:
            sr = st.selectbox("Recent", ["-- recent --"] + list(reversed(recent_list)),
                              label_visibility="collapsed", key="s_recent")
            if sr and sr != "-- recent --":
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
    go = st.button("Generate Report", type="primary")

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
            <div class="hiw-desc">We fetch real-time data, compute 24 financial metrics in Python, and run two-pass AI analysis.</div>
        </div>
        <div class="hiw-card">
            <div class="hiw-step">Step 3</div>
            <div class="hiw-title2">Report</div>
            <div class="hiw-desc">Get a full research report with scores, charts, peer comparison, and downloadable analysis.</div>
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
    <div class="params-row"><span class="params-key">AI Analysis</span><span class="params-val">Two-pass architecture (assumptions then narrative)</span></div>
    <div class="params-row"><span class="params-key">Metrics Calculation</span><span class="params-val">Python (verified, not AI-generated)</span></div>
    <div class="params-row"><span class="params-key">Valuation Anchor</span><span class="params-val">Forward P/E (primary), Trailing P/E (fallback)</span></div>
    <div class="params-row"><span class="params-key">Risk-Free Rate</span><span class="params-val">6.0%</span></div>
    <div class="params-row"><span class="params-key">EPS Method</span><span class="params-val">Anchored to trailing EPS, grown by revenue + margin delta</span></div>
    <div class="params-row"><span class="params-key">Peer Selection</span><span class="params-val">FMP peers + sector fallback (top 4)</span></div>
    <div class="params-row"><span class="params-key">Price Tracking</span><span class="params-val">Daily email alerts when target price is reached</span></div>
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

            # ── Step 1: Fetch data ──
            st.write(f"Fetching data for **{ticker}**...")
            st.caption("Pulling real-time price, fundamentals, financials, and 5-year history")
            try:
                sd = fetch(ticker)
            except Exception as e:
                st.error(f"Failed to fetch data: {e}"); st.stop()
            info = sd.get("info", {})
            if isinstance(info, dict) and info.get("error"):
                st.error(f"Ticker '{ticker}' not found or unavailable."); st.stop()

            company_name = info.get("shortName", info.get("longName", ticker))
            data_source  = info.get('_source', 'yfinance')
            st.write(f"Loaded **{company_name}** (via {data_source})")

            # ── Step 2: Compute metrics ──
            st.write("Computing 24 verified financial metrics...")
            st.caption("Revenue CAGR, margins, ROE/ROA, FCF yield, valuation ratios, debt metrics")
            m = calc(sd)
            if "error" in m:
                st.error(m["error"]); st.stop()

            # ── Step 3: Pass 1 - Get assumptions ──
            st.write("Pass 1: Getting structured assumptions from AI...")
            st.caption("Macro drivers, scenario assumptions, headwinds, tailwinds, risks, catalysts")

            # ── Step 4: Python computes math ──
            # (happens inside run_ai_two_pass)

            # ── Step 5: Pass 2 - Get narrative ──
            st.write("Computing scenario math and getting narrative from AI...")
            st.caption("Price targets, probabilities, expected value, then writing report consistent with math")

            a = run_ai_two_pass(ticker, m)
            if isinstance(a, dict) and a.get("error"):
                status.update(label="Analysis failed", state="error")
                for d in a.get("details", []):
                    st.code(d)
                st.stop()

            rec = a.get("recommendation", "WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state.cached_report = {"ticker": ticker, "metrics": m, "analysis": a, "data": sd}


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
                f"# {c_m.get('company_name', c_ticker)} ({c_ticker})",
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
            for sn, sl in [("bull", "Bull"), ("base", "Base"), ("bear", "Bear")]:
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
                f"Risk-Adjusted Score: {sm.get('risk_adjusted_score',0):.2f}",
                f"Probability of Positive Return: {sm.get('prob_positive_return',0)*100:.0f}%", "",
                "## Conclusion", "", strip_html(c_a.get("conclusion", "")),
                "", f"*PickR / {datetime.now().strftime('%B %d, %Y')}*"
            ]
            st.download_button("Download (Markdown)", "\n".join(md_lines),
                f"PickR_{c_ticker}.md", "text/markdown")

        with dl2:
            sm = c_a.get("scenario_math", {})
            export_data = {
                "ticker": c_ticker,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "recommendation": c_a.get("recommendation"),
                "conviction": c_a.get("conviction"),
                "expected_value": sm.get("expected_value"),
                "expected_return": sm.get("expected_return"),
                "risk_adjusted_score": sm.get("risk_adjusted_score"),
                "prob_positive": sm.get("prob_positive_return"),
                "scenarios": sm.get("scenarios"),
                "risk_impacts": sm.get("risk_impacts"),
                "metrics": {k: v for k, v in c_m.items()
                           if k not in ["description", "news", "revenue_history", "net_income_history"]},
            }
            st.download_button("Download (JSON)", json.dumps(export_data, indent=2, default=str),
                f"PickR_{c_ticker}.json", "application/json")


# ── Footer ────────────────────────────────────────────────────
st.markdown(f'''<div class="foot-card">
    <div class="foot-name">Built by Mayukh Kondepudi</div>
    <div class="foot-email">mayukhkondepudi@gmail.com</div>
    <div class="foot-disclaimer">
        PickR is an AI-powered equity research tool for educational and informational purposes only.
        It does not constitute financial advice, investment recommendations, or an offer to buy or sell securities.
        All financial data is sourced from FMP API with Yahoo Finance fallback and may be delayed. AI-generated analysis
        is based on publicly available information and should not be relied upon as the sole basis for investment decisions.
        Past performance does not guarantee future results. Always consult a qualified financial advisor
        before making investment decisions.
    </div>
    <div class="foot-copy">2025 PickR. All rights reserved.</div>
</div>''', unsafe_allow_html=True)
