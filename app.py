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

SYSTEM_PROMPT   = load_text_file("prompt_system.txt")
PASS1_PROMPT    = load_text_file("prompt_pass1.txt")
PASS2_PROMPT    = load_text_file("prompt_pass2.txt")

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
def load_screener_results():
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/screener_results.json"
            req = urllib.request.Request(url, headers=_gh_headers())
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                return json.loads(base64.b64decode(data["content"]).decode())
        except Exception:
            pass
    try:
        with open("screener_results.json") as f:
            return json.load(f)
    except Exception:
        return None

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
        "peg_ratio": None,
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

    # ── PEG: compute from multi-year earnings CAGR, never trust API ──
    m["peg_ratio"] = None

    try:
        # Use forward PE as numerator (preferred) or trailing PE
        pe = safe_float(m.get("forward_pe"))
        if pe <= 0:
            pe = safe_float(m.get("trailing_pe"))

        if pe > 0:
            growth = None

            # Priority 1: EPS CAGR (most direct measure)
            if m.get("eps_cagr") and float(m["eps_cagr"]) > 0:
                growth = float(m["eps_cagr"]) * 100

            # Priority 2: Net income CAGR
            if growth is None and m.get("net_income_cagr") and float(m["net_income_cagr"]) > 0:
                growth = float(m["net_income_cagr"]) * 100

            # Priority 3: Single-year earnings growth (least reliable)
            if growth is None and m.get("earnings_growth"):
                g_val = float(m["earnings_growth"])
                g_pct = g_val * 100 if abs(g_val) < 1 else g_val
                if g_pct > 0:
                    growth = g_pct

                if growth and growth > 0:
                # Cap growth at 50% to prevent supercycle distortion
                 capped_growth = min(growth, 50.0)
                peg = round(pe / capped_growth, 2)
                if 0 < peg <= 5.0:
                    m["peg_ratio"] = peg
                    print(f"  PEG computed: {pe:.1f}x PE / {growth:.1f}% growth = {peg:.2f}")
                else:
                    print(f"  PEG computed but out of range ({peg:.2f}), discarding")
            else:
                print(f"  PEG: no positive earnings growth available")
    except Exception as e:
        print(f"  PEG computation error: {e}")

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
    Segment-level scenario math engine.
    
    The LLM provides segment revenue builds, headwind/tailwind dollar
    impacts, margins, and PE multiples per scenario. Python computes
    every derived number and cross-validates the LLM's stated EPS.
    
    If the LLM's EPS and Python's EPS diverge by more than 10%,
    Python's number wins and a flag is raised.
    """

    # ── Step 1: Extract base metrics ──
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

    # Derive shares if missing
    if shares == 0 and current_price > 0 and market_cap > 0:
        shares = market_cap / current_price

    # FCF margin for FCF yield calculations
    fcf_margin = (free_cashflow / total_revenue) if total_revenue > 0 and free_cashflow > 0 else 0.0

    # PE anchor
    if forward_pe > 0:
        anchor_pe = forward_pe
    elif trailing_pe > 0:
        anchor_pe = trailing_pe
    else:
        anchor_pe = 0

    print(f"  Scenario math inputs: price={current_price}, trailing_eps={trailing_eps:.2f}, "
          f"forward_eps={forward_eps:.2f}, shares={shares:.0f}, "
          f"op_margin={operating_margin:.3f}, net_margin={profit_margin:.3f}, "
          f"fcf_margin={fcf_margin:.3f}, anchor_pe={anchor_pe:.1f}")

    # ── Step 2: Compute scenario probabilities from macro drivers ──
    prob_output = compute_scenario_probabilities(llm_output)
    scenario_probs = {
        "bull": prob_output["bull"],
        "base": prob_output["base"],
        "bear": prob_output["bear"],
    }

    # ── Step 3: Compute each scenario ──
    scenarios_input = llm_output.get("scenarios", {})
    results = {}

    for scenario_name in ["bull", "base", "bear"]:
        s = scenarios_input.get(scenario_name, {})
        if not s:
            continue

        try:
            prob = scenario_probs.get(scenario_name, 0.20)

            # ── Segment revenue build ──
            segment_builds = s.get("segment_builds", [])
            segment_revenue_total = sum(
                safe_float(seg.get("projected_revenue"))
                for seg in segment_builds
            )

            # ── Headwind and tailwind adjustments ──
            hw_revenue = safe_float(s.get("total_headwind_revenue"))
            hw_eps     = safe_float(s.get("total_headwind_eps"))
            tw_revenue = safe_float(s.get("total_tailwind_revenue"))
            tw_eps     = safe_float(s.get("total_tailwind_eps"))

            # ── Total revenue ──
            # Segment builds should already include organic growth.
            # Headwinds subtract, tailwinds add.
            llm_total_revenue = safe_float(s.get("total_revenue"))

            # Python-computed total
            python_total_revenue = segment_revenue_total + hw_revenue + tw_revenue
            # hw_revenue is negative, tw_revenue is positive

            # Use Python's total if available, fall back to LLM's
            if python_total_revenue > 0:
                total_rev = python_total_revenue
            elif llm_total_revenue > 0:
                total_rev = llm_total_revenue
            else:
                total_rev = total_revenue  # fall back to current

            # Log discrepancy
            if llm_total_revenue > 0 and python_total_revenue > 0:
                rev_diff = abs(python_total_revenue - llm_total_revenue) / llm_total_revenue
                if rev_diff > 0.05:
                    print(f"  {scenario_name}: Revenue discrepancy - "
                          f"Python={python_total_revenue:.0f}, "
                          f"LLM={llm_total_revenue:.0f} ({rev_diff*100:.1f}% diff)")

            # ── Revenue growth ──
            rev_growth = ((total_rev / total_revenue) - 1) if total_revenue > 0 else 0.0

            # ── Margins ──
            op_margin  = safe_float(s.get("operating_margin"), default=operating_margin)
            net_margin = safe_float(s.get("net_margin"), default=profit_margin)
            tax_rate   = safe_float(s.get("tax_rate"), default=0.21)
            margin_rationale = s.get("margin_rationale", "")

            # If net margin not provided, derive from operating margin and tax rate
            if net_margin == 0 and op_margin > 0:
                net_margin = op_margin * (1 - tax_rate)

            # ── EPS: Python computation ──
            if total_rev > 0 and net_margin > 0 and shares > 0:
                python_eps = (total_rev * net_margin) / shares
            elif total_rev > 0 and op_margin > 0 and shares > 0:
                python_eps = (total_rev * op_margin * (1 - tax_rate)) / shares
            else:
                python_eps = 0.0

            # Add headwind/tailwind EPS adjustments if not already in margin
            # Only add if Python built EPS from revenue * margin (pre-adjustment)
            # The LLM's segment builds should include headwind revenue impact,
            # but the EPS impact from headwinds might include non-revenue effects
            # (margin compression, one-time charges). We add the delta.
            llm_eps = safe_float(s.get("projected_eps"))

            # Cross-validate
            eps_flag = None
            if python_eps > 0 and llm_eps > 0:
                eps_diff = abs(python_eps - llm_eps) / llm_eps
                if eps_diff > 0.10:
                    eps_flag = (f"Python EPS ({python_eps:.2f}) differs from "
                                f"LLM EPS ({llm_eps:.2f}) by {eps_diff*100:.1f}%. "
                                f"Using Python's number.")
                    print(f"  {scenario_name}: {eps_flag}")
                    final_eps = python_eps
                else:
                    final_eps = python_eps  # Python always wins, but no flag
            elif python_eps > 0:
                final_eps = python_eps
            elif llm_eps > 0:
                final_eps = llm_eps
                eps_flag = "Python could not compute EPS. Using LLM's number."
            else:
                # Last resort: grow trailing EPS by revenue growth
                final_eps = trailing_eps * (1 + rev_growth) if trailing_eps > 0 else 0
                eps_flag = "Both computations failed. Using trailing EPS grown by revenue growth."

            # ── PE multiple ──
            pe_mult = safe_float(s.get("pe_multiple"), default=20.0)
            pe_mult = max(pe_mult, 3.0)  # absolute floor
            pe_rationale = s.get("pe_rationale", "")

            # ── Price target ──
            price_target = final_eps * pe_mult

            # ── Implied return ──
            implied_return = ((price_target - current_price) / current_price
                              if current_price > 0 else 0.0)

            # ── Breakeven PE ──
            breakeven_pe = (current_price / final_eps) if final_eps > 0 else None

            # ── FCF yield at target price ──
            if fcf_margin > 0 and total_rev > 0 and price_target > 0 and shares > 0:
                implied_market_cap = price_target * shares
                projected_fcf = total_rev * fcf_margin
                fcf_yield_at_target = projected_fcf / implied_market_cap
            else:
                fcf_yield_at_target = None

            results[scenario_name] = {
                "probability":          round(prob, 4),
                "segment_builds":       segment_builds,
                "segment_revenue_total": round(segment_revenue_total, 0),
                "total_headwind_revenue": round(hw_revenue, 0),
                "total_headwind_eps":   round(hw_eps, 2),
                "total_tailwind_revenue": round(tw_revenue, 0),
                "total_tailwind_eps":   round(tw_eps, 2),
                "total_revenue":        round(total_rev, 0),
                "revenue_growth":       round(rev_growth, 4),
                "operating_margin":     round(op_margin, 4),
                "net_margin":           round(net_margin, 4),
                "margin_rationale":     margin_rationale,
                "projected_eps":        round(final_eps, 2),
                "llm_eps":              round(llm_eps, 2) if llm_eps else None,
                "eps_flag":             eps_flag,
                "pe_multiple":          round(pe_mult, 1),
                "pe_rationale":         pe_rationale,
                "price_target":         round(price_target, 2),
                "implied_return":       round(implied_return, 4),
                "breakeven_pe":         round(breakeven_pe, 2) if breakeven_pe else None,
                "fcf_yield_at_target":  round(fcf_yield_at_target, 4) if fcf_yield_at_target else None,
                "narrative":            s.get("narrative", ""),
            }

        except Exception as e:
            print(f"  Scenario {scenario_name} math error: {e}")
            results[scenario_name] = {
                "probability": scenario_probs.get(scenario_name, 0.20),
                "segment_builds": [], "segment_revenue_total": 0,
                "total_headwind_revenue": 0, "total_headwind_eps": 0,
                "total_tailwind_revenue": 0, "total_tailwind_eps": 0,
                "total_revenue": 0, "revenue_growth": 0,
                "operating_margin": 0, "net_margin": 0,
                "margin_rationale": "", "projected_eps": 0,
                "llm_eps": None, "eps_flag": str(e),
                "pe_multiple": 0, "pe_rationale": "",
                "price_target": 0, "implied_return": 0,
                "breakeven_pe": None, "fcf_yield_at_target": None,
                "narrative": str(e),
            }

    # ── Step 4: Aggregate metrics ──
    expected_value = sum(
        r["price_target"] * r["probability"] for r in results.values()
    )
    expected_return = ((expected_value - current_price) / current_price
                       if current_price > 0 else 0)

    variance = sum(
        r["probability"] * (r["implied_return"] - expected_return) ** 2
        for r in results.values()
    )
    std_dev = variance ** 0.5

    risk_adj_score = ((expected_return - risk_free_rate) / std_dev
                      if std_dev > 0 else 0)

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
        r["probability"] for r in results.values()
        if r["price_target"] > current_price
    )

    bear = results.get("bear", {})

    # ── Step 5: Market expectations (pass through from LLM) ──
    market_expectations = llm_output.get("market_expectations", {})

    # ── Step 6: Sensitivity (pass through, LLM computed) ──
    sensitivity = llm_output.get("sensitivity", {})

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
        "fcf_margin_used":        round(fcf_margin, 4),
        "market_expectations":    market_expectations,
        "sensitivity":            sensitivity,
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
                model="claude-opus-4-6",
                system=system_msg,
                messages=user_msgs,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return r.content[0].text.strip(), "claude-opus-4.6", None
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
    """Build Pass 1 messages from external prompt files."""
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str
    )
    description_snippet = (m.get("description") or "N/A")[:800]

    replacements = {
        "{ticker}": ticker,
        "{company_name}": m.get("company_name", ticker),
        "{metrics_json}": ms,
        "{current_price}": str(m.get("current_price")),
        "{trailing_pe}": str(m.get("trailing_pe")),
        "{forward_pe}": str(m.get("forward_pe")),
        "{ev_to_ebitda}": str(m.get("ev_to_ebitda")),
        "{trailing_eps}": str(m.get("trailing_eps")),
        "{forward_eps}": str(m.get("forward_eps")),
        "{operating_margin}": str(m.get("operating_margin")),
        "{profit_margin}": str(m.get("profit_margin")),
        "{description}": description_snippet,
        "{today_date}": datetime.now().strftime("%B %d, %Y"),
        "{total_revenue}": fmt_c(m.get("total_revenue"), m.get("currency", "USD")),
    }

    user_prompt = PASS1_PROMPT
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, val)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

def ai_prompt_pass2(ticker, m, scenario_math, pass1_output):
    """Build Pass 2 messages from external prompt file with computed math."""
    ms = json.dumps(
        {k: v for k, v in m.items()
         if k not in ["description", "news", "revenue_history", "net_income_history"]},
        indent=2, default=str
    )
    description_snippet = (m.get("description") or "N/A")[:800]

    sm = scenario_math
    scenarios = sm.get("scenarios", {})

    math_summary = {
        "expected_value":       sm.get("expected_value"),
        "expected_return":      f"{sm.get('expected_return', 0) * 100:.1f}%",
        "prob_positive_return": f"{sm.get('prob_positive_return', 0) * 100:.0f}%",
        "risk_adjusted_score":  sm.get("risk_adjusted_score"),
        "upside_downside_ratio": sm.get("upside_downside_ratio"),
    }
    for sname in ["bull", "base", "bear"]:
        s = scenarios.get(sname, {})
        math_summary[f"{sname}_price_target"]      = s.get("price_target")
        math_summary[f"{sname}_implied_return"]     = f"{s.get('implied_return', 0) * 100:.1f}%"
        math_summary[f"{sname}_probability"]        = f"{s.get('probability', 0) * 100:.0f}%"
        math_summary[f"{sname}_eps"]                = s.get("projected_eps")
        math_summary[f"{sname}_pe"]                 = s.get("pe_multiple")
        math_summary[f"{sname}_revenue"]            = s.get("total_revenue")
        math_summary[f"{sname}_op_margin"]          = s.get("operating_margin")
        math_summary[f"{sname}_fcf_yield"]          = s.get("fcf_yield_at_target")
        math_summary[f"{sname}_breakeven_pe"]       = s.get("breakeven_pe")
        math_summary[f"{sname}_margin_rationale"]   = s.get("margin_rationale")

    mkt = sm.get("market_expectations", {})
    segments = pass1_output.get("segments", [])
    hw_tw = {
        "headwinds": pass1_output.get("headwinds", []),
        "tailwinds": pass1_output.get("tailwinds", []),
    }

    replacements = {
        "{ticker}": ticker,
        "{company_name}": m.get("company_name", ticker),
        "{metrics_json}": ms,
        "{description}": description_snippet,
        "{segments_json}": json.dumps(segments, indent=2, default=str),
        "{scenario_math_json}": json.dumps(math_summary, indent=2, default=str),
        "{market_expectations_json}": json.dumps(mkt, indent=2, default=str),
        "{headwinds_tailwinds_json}": json.dumps(hw_tw, indent=2, default=str),
        "{expected_return}": math_summary["expected_return"],
        "{prob_positive}": math_summary["prob_positive_return"],
        "{risk_adjusted_score}": str(sm.get("risk_adjusted_score")),
        "{upside_downside_ratio}": str(sm.get("upside_downside_ratio")),
        "{implied_vs_base}": mkt.get("vs_base_case", "N/A"),
    }

    user_prompt = PASS2_PROMPT
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, str(val))

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

# ══════════════════════════════════════════════════════════════
# AI — ORCHESTRATOR (TWO-PASS)
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass1(ticker, metrics_json_str):
    """Pass 1: Get structured assumptions from LLM."""
    m = json.loads(metrics_json_str)
    msgs = ai_prompt_pass1(ticker, m)
    raw, model, errors = run_ai(msgs, max_tokens=6000)
    if raw is None:
        return {"error": True, "details": errors}
    a, err = _parse_json_response(raw, model)
    if err:
        return {"error": True, "details": [err]}

    # Apply defaults for missing fields
    defaults = {
        "segments": [],
        "concentration": {},
        "headwinds": [],
        "tailwinds": [],
        "macro_drivers": [],
        "scenarios": {
            "bull": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 20,
                     "pe_rationale": "N/A", "narrative": "N/A"},
            "base": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 18,
                     "pe_rationale": "N/A", "narrative": "N/A"},
            "bear": {"segment_builds": [], "total_revenue": 0,
                     "operating_margin": 0, "net_margin": 0,
                     "projected_eps": 0, "pe_multiple": 14,
                     "pe_rationale": "N/A", "narrative": "N/A"},
        },
        "market_expectations": {},
        "sensitivity": {},
        "catalysts": [],
        "peer_tickers": [],
    }
    for k, v in defaults.items():
        if k not in a:
            a[k] = v

    # ── Validate segment revenue totals against actual data ──
    m = json.loads(metrics_json_str)
    actual_revenue = safe_float(m.get("total_revenue"))
    if actual_revenue > 0 and a.get("segments"):
        segment_total = sum(
            safe_float(seg.get("current_revenue"))
            for seg in a["segments"]
        )
        if segment_total > 0:
            rev_ratio = segment_total / actual_revenue
            if rev_ratio < 0.5 or rev_ratio > 2.0:
                print(f"  VALIDATION FAIL: Segment total ({segment_total:.0f}) vs "
                      f"actual revenue ({actual_revenue:.0f}) = {rev_ratio:.2f}x. "
                      f"LLM may have analyzed the wrong company.")
                return {
                    "error": True,
                    "details": [
                        f"LLM segment revenues ({fmt_n(segment_total)}) do not match "
                        f"actual company revenue ({fmt_n(actual_revenue)}). "
                        f"The model may have analyzed the wrong company. "
                        f"Please retry."
                    ]
                }

    return a

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str):
    """Pass 2: Get narrative from LLM seeing computed math."""
    m = json.loads(metrics_json_str)
    sm = json.loads(math_json_str)
    p1 = json.loads(pass1_json_str)
    msgs = ai_prompt_pass2(ticker, m, sm, p1)
    raw, model, errors = run_ai(msgs, max_tokens=6000)
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
        "margin_analysis": "Analysis not available.",
        "financial_health": "Analysis not available.",
        "competitive_position": "Analysis not available.",
        "headwind_narrative": "Analysis not available.",
        "tailwind_narrative": "Analysis not available.",
        "market_pricing_commentary": "Analysis not available.",
        "scenario_commentary": "Analysis not available.",
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
    1. Pass 1: Get structured assumptions (segments, drivers, scenarios)
    2. Python: Compute all scenario math from segment builds
    3. Pass 2: Get narrative consistent with computed math
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
    math_json_str  = json.dumps(scenario_math, sort_keys=True, default=str)
    pass1_json_str = json.dumps(pass1, sort_keys=True, default=str)

    pass2 = _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str)
    if isinstance(pass2, dict) and pass2.get("error"):
        return pass2

    # ── Merge ──
    final = {}

    # From pass2 (narrative)
    for key in ["recommendation", "conviction", "investment_thesis",
                "business_overview", "revenue_architecture", "growth_drivers",
                "margin_analysis", "financial_health", "competitive_position",
                "headwind_narrative", "tailwind_narrative",
                "market_pricing_commentary", "scenario_commentary",
                "conclusion", "model_used"]:
        final[key] = pass2.get(key, "")

    # From pass1 (structured data)
    for key in ["segments", "concentration", "headwinds", "tailwinds",
                "macro_drivers", "scenarios", "catalysts", "peer_tickers",
                "market_expectations", "sensitivity"]:
        final[key] = pass1.get(key, {} if key in ["concentration",
                     "market_expectations", "sensitivity"] else [])

    # Computed math
    final["scenario_math"] = scenario_math

    # ── Consistency check ──
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

    # ── Override warning ──
    if a.get("rec_override_reason"):
        st.markdown(
            f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);'
            f'border-radius:6px;padding:0.8rem 1.2rem;font-size:0.85rem;color:#fbbf24;'
            f'margin:0.8rem 0;line-height:1.5;">{strip_html(a["rec_override_reason"])}</div>',
            unsafe_allow_html=True
        )

    # ── Market Expectations (NEW) ──
    mkt = sm.get("market_expectations", {})
    if mkt:
        implied_growth = safe_float(mkt.get("implied_growth_rate")) * 100
        vs_base = mkt.get("vs_base_case", "")
        commentary = strip_html(mkt.get("commentary", ""))
        vs_color = "#4ade80" if vs_base == "undervalued" else (
                   "#f87171" if vs_base == "overvalued" else "#fbbf24")

        st.markdown(f'''<div class="sec">What The Market Is Pricing In</div>
        <div style="background:#141414;border:1px solid rgba(255,255,255,0.06);
            border-radius:8px;padding:1.2rem 1.5rem;margin:0.8rem 0;">
            <div style="display:flex;justify-content:center;gap:3rem;margin-bottom:1rem;">
                <div style="text-align:center;">
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.12em;color:rgba(255,255,255,0.3);margin-bottom:0.3rem;">
                        Implied Growth Rate</div>
                    <div style="font-size:1.6rem;font-weight:800;color:#fff;">
                        {implied_growth:.0f}%</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.12em;color:rgba(255,255,255,0.3);margin-bottom:0.3rem;">
                        vs Base Case</div>
                    <div style="font-size:1.6rem;font-weight:800;color:{vs_color};
                        text-transform:uppercase;">{vs_base}</div>
                </div>
            </div>
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.55);line-height:1.7;
                text-align:center;max-width:680px;margin:0 auto;">{commentary}</div>
        </div>''', unsafe_allow_html=True)

    # ── 52-Week Range ──
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

    # ── 5-Year Price History ──
    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy()
        cd.columns = ["Price"]
        st.line_chart(cd, height=250, color="#8b1a1a")

    # ── Key Metrics ──
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

    # ── Revenue & Earnings Trend ──
    rh = m.get("revenue_history", {})
    nh = m.get("net_income_history", {})
    if rh or nh:
        st.markdown(
            '<div class="sec">Revenue &amp; Earnings Trend (Billions)</div>',
            unsafe_allow_html=True
        )
        cc1, cc2 = st.columns(2)
        with cc1:
            if rh:
                st.bar_chart(pd.DataFrame({"Revenue": rh}), height=200, color="#8b1a1a")
        with cc2:
            if nh:
                st.bar_chart(pd.DataFrame({"Net Income": nh}), height=200, color="#d4443a")

    # ── Revenue Segmentation (NEW) ──
    segments = a.get("segments", [])
    if segments:
        st.markdown(
            '<div class="sec">Revenue Segmentation</div>',
            unsafe_allow_html=True
        )
        seg_header = ("<tr><th>Segment</th><th>Revenue</th><th>% of Total</th>"
                      "<th>Gross Margin</th><th>YoY Growth</th>"
                      "<th>Trajectory</th><th>Primary Driver</th></tr>")
        seg_rows = ""
        for seg in segments:
            traj = strip_html(seg.get("trajectory", ""))
            traj_color = ("#4ade80" if traj == "accelerating"
                          else ("#f87171" if traj == "decelerating" else "#fbbf24"))
            seg_rows += f'''<tr>
                <td><strong>{strip_html(seg.get("name",""))}</strong></td>
                <td>{fmt_c(seg.get("current_revenue"), cur)}</td>
                <td>{fmt_p(seg.get("pct_of_total"))}</td>
                <td>{fmt_p(seg.get("gross_margin"))}</td>
                <td>{fmt_p(seg.get("yoy_growth"))}</td>
                <td style="color:{traj_color};font-weight:600;
                    text-transform:uppercase;font-size:0.78rem;">{traj}</td>
                <td style="font-size:0.82rem;color:rgba(255,255,255,0.5);">
                    {strip_html(seg.get("primary_driver",""))}</td>
            </tr>'''
        st.markdown(
            f'<table class="pt"><thead>{seg_header}</thead>'
            f'<tbody>{seg_rows}</tbody></table>',
            unsafe_allow_html=True
        )

    # ── Concentration & Dependencies (NEW) ──
    conc = a.get("concentration", {})
    if conc:
        st.markdown(
            '<div class="sec">Concentration &amp; Dependencies</div>',
            unsafe_allow_html=True
        )
        conc_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">'

        # Geographic split
        geo = conc.get("geographic_split", {})
        if geo:
            geo_items = ""
            for region, pct in geo.items():
                geo_items += f'''<div class="params-row">
                    <span class="params-key">{region.replace("_"," ")}</span>
                    <span class="params-val">{fmt_p(pct)}</span>
                </div>'''
            conc_html += f'''<div class="params-card" style="margin-bottom:0;">
                <div class="thesis-title">Geographic Exposure</div>
                {geo_items}
            </div>'''

        # Customer and dependency info
        dep_items = ""
        top_cust = conc.get("top_customer_pct")
        top_5 = conc.get("top_5_customers_pct")
        if top_cust:
            dep_items += f'''<div class="params-row">
                <span class="params-key">Top Customer</span>
                <span class="params-val">{fmt_p(top_cust)}</span>
            </div>'''
        if top_5:
            dep_items += f'''<div class="params-row">
                <span class="params-key">Top 5 Customers</span>
                <span class="params-val">{fmt_p(top_5)}</span>
            </div>'''
        for dep in conc.get("critical_dependencies", []):
            dep_items += f'''<div class="params-row">
                <span class="params-key">Dependency</span>
                <span class="params-val" style="font-size:0.82rem;">{strip_html(dep)}</span>
            </div>'''
        if dep_items:
            conc_html += f'''<div class="params-card" style="margin-bottom:0;">
                <div class="thesis-title">Customer &amp; Supply Chain</div>
                {dep_items}
            </div>'''

        conc_html += '</div>'
        st.markdown(conc_html, unsafe_allow_html=True)

        # Relationships at risk
        at_risk = conc.get("relationships_at_risk", [])
        if at_risk:
            risk_items = ""
            for r in at_risk:
                risk_items += f'''<div style="padding:0.4rem 0;border-bottom:1px solid
                    rgba(255,255,255,0.04);font-size:0.88rem;color:rgba(255,255,255,0.55);">
                    {strip_html(r)}</div>'''
            st.markdown(f'''<div style="background:rgba(248,113,113,0.06);
                border:1px solid rgba(248,113,113,0.15);border-radius:6px;
                padding:0.8rem 1.2rem;margin-top:0.8rem;">
                <div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;
                    letter-spacing:0.1em;color:#f87171;margin-bottom:0.4rem;">
                    Relationships At Risk</div>
                {risk_items}
            </div>''', unsafe_allow_html=True)

    # ── Business Overview ──
    st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("business_overview", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Revenue Architecture ──
    st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("revenue_architecture", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Growth Drivers ──
    st.markdown(
        '<div class="sec">Growth Drivers &amp; Competitive Moats</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        f'<div class="prose">{strip_html(a.get("growth_drivers", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Margin Analysis (NEW) ──
    st.markdown('<div class="sec">Margin Analysis</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("margin_analysis", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Financial Health (NEW) ──
    st.markdown('<div class="sec">Financial Health</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("financial_health", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Competitive Position (NEW) ──
    st.markdown('<div class="sec">Competitive Position</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="prose">{strip_html(a.get("competitive_position", "Not available."))}</div>',
        unsafe_allow_html=True
    )

    # ── Peer Comparison ──
    sector = m.get("sector", "")
    llm_peers = a.get("peer_tickers", [])
    if sector in SECTOR_PEERS or llm_peers:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
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

    # ── Headwinds & Tailwinds (NEW - with dollar impacts) ──
    headwinds = a.get("headwinds", [])
    tailwinds = a.get("tailwinds", [])

    if headwinds or tailwinds:
        st.markdown(
            '<div class="sec">Headwinds &amp; Tailwinds '
            '<span class="vtag">Quantified</span></div>',
            unsafe_allow_html=True
        )

        # Headwind narrative from Pass 2
        if a.get("headwind_narrative"):
            st.markdown(
                f'<div class="prose">{strip_html(a["headwind_narrative"])}</div>',
                unsafe_allow_html=True
            )

        # Headwind impact table
        if headwinds:
            hw_header = ("<tr><th>Headwind</th><th>Prob.</th><th>Revenue at Risk</th>"
                         "<th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>")
            hw_rows = ""
            for hw in headwinds:
                bull_imp = hw.get("bull_impact", {})
                base_imp = hw.get("base_impact", {})
                bear_imp = hw.get("bear_impact", {})
                hw_rows += f'''<tr>
                    <td><strong>{strip_html(hw.get("name",""))}</strong><br>
                    <span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">
                        {strip_html(hw.get("description",""))[:120]}</span></td>
                    <td>{safe_float(hw.get("probability"))*100:.0f}%</td>
                    <td style="color:#f87171;">{fmt_c(hw.get("revenue_at_risk"), cur)}</td>
                    <td style="font-size:0.82rem;">{fmt_c(bull_imp.get("revenue"), cur)}
                        <br><span style="color:rgba(255,255,255,0.4);">
                        {sym}{safe_float(bull_imp.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(base_imp.get("revenue"), cur)}
                        <br><span style="color:rgba(255,255,255,0.4);">
                        {sym}{safe_float(base_imp.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;color:#f87171;">
                        {fmt_c(bear_imp.get("revenue"), cur)}
                        <br><span>{sym}{safe_float(bear_imp.get("eps")):+.2f} EPS</span></td>
                </tr>'''
            st.markdown(
                f'<table class="pt"><thead>{hw_header}</thead>'
                f'<tbody>{hw_rows}</tbody></table>',
                unsafe_allow_html=True
            )

        # Tailwind narrative from Pass 2
        if a.get("tailwind_narrative"):
            st.markdown(
                f'<div class="prose" style="margin-top:1rem;">'
                f'{strip_html(a["tailwind_narrative"])}</div>',
                unsafe_allow_html=True
            )

        # Tailwind impact table
        if tailwinds:
            tw_header = ("<tr><th>Tailwind</th><th>Prob.</th><th>Revenue Opportunity</th>"
                         "<th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>")
            tw_rows = ""
            for tw in tailwinds:
                bull_imp = tw.get("bull_impact", {})
                base_imp = tw.get("base_impact", {})
                bear_imp = tw.get("bear_impact", {})
                tw_rows += f'''<tr>
                    <td><strong>{strip_html(tw.get("name",""))}</strong><br>
                    <span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">
                        {strip_html(tw.get("description",""))[:120]}</span></td>
                    <td>{safe_float(tw.get("probability"))*100:.0f}%</td>
                    <td style="color:#4ade80;">{fmt_c(tw.get("revenue_opportunity"), cur)}</td>
                    <td style="font-size:0.82rem;color:#4ade80;">
                        {fmt_c(bull_imp.get("revenue"), cur)}
                        <br><span>{sym}{safe_float(bull_imp.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(base_imp.get("revenue"), cur)}
                        <br><span style="color:rgba(255,255,255,0.4);">
                        {sym}{safe_float(base_imp.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(bear_imp.get("revenue"), cur)}
                        <br><span style="color:rgba(255,255,255,0.4);">
                        {sym}{safe_float(bear_imp.get("eps")):+.2f} EPS</span></td>
                </tr>'''
            st.markdown(
                f'<table class="pt"><thead>{tw_header}</thead>'
                f'<tbody>{tw_rows}</tbody></table>',
                unsafe_allow_html=True
            )

    # ── Macro Drivers ──
    macro_drivers = a.get("macro_drivers", [])
    if macro_drivers:
        st.markdown(
            '<div class="sec">What Drives the Outcome '
            '<span class="vtag">Bottom-Up Probability</span></div>',
            unsafe_allow_html=True
        )

        st.markdown('''<div class="plain-callout">
            <div class="plain-callout-label">How this works</div>
            Instead of guessing scenario probabilities, we identify the specific
            events that determine this company's outcome. Each event gets an
            independent probability. The math computes final scenario
            probabilities from these inputs.
        </div>''', unsafe_allow_html=True)

        for d in macro_drivers:
            dname = strip_html(d.get("name", ""))
            dmeasures = strip_html(d.get("measures", ""))

            bull_p = safe_float(d.get("bull_outcome", {}).get("probability"))
            base_p = safe_float(d.get("base_outcome", {}).get("probability"))
            bear_p = safe_float(d.get("bear_outcome", {}).get("probability"))
            bull_n = strip_html(d.get("bull_outcome", {}).get("description", ""))[:120]
            base_n = strip_html(d.get("base_outcome", {}).get("description", ""))[:120]
            bear_n = strip_html(d.get("bear_outcome", {}).get("description", ""))[:120]

            bull_w = max(2, min(100, round(bull_p * 100)))
            base_w = max(2, min(100, round(base_p * 100)))
            bear_w = max(2, min(100, round(bear_p * 100)))

            st.markdown(f'''<div class="driver-card">
                <div class="driver-card-name">{dname}</div>
                <div class="driver-card-desc">{dmeasures}</div>
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
                Geometric mean of each driver's bull/bear probabilities, with
                clustering adjustment: <strong>{bull_mult:.1f}x</strong> bull tail,
                <strong>{bear_mult:.1f}x</strong> bear tail (downside scenarios
                correlate more tightly in practice).
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

    # ── Market Pricing Commentary (NEW) ──
    if a.get("market_pricing_commentary"):
        st.markdown('<div class="sec">Valuation vs Expectations</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="prose">{strip_html(a["market_pricing_commentary"])}</div>',
            unsafe_allow_html=True
        )

    # ── Scenario Analysis (NEW - segment-level builds) ──
    st.markdown(
        '<div class="sec">Scenario Analysis '
        '<span class="vtag">Segment-Level Builds</span></div>',
        unsafe_allow_html=True
    )

    # Scenario commentary from Pass 2
    if a.get("scenario_commentary"):
        st.markdown(
            f'<div class="prose">{strip_html(a["scenario_commentary"])}</div>',
            unsafe_allow_html=True
        )

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
        op_margin   = s.get("operating_margin", 0)
        rev_growth  = s.get("revenue_growth", 0)
        total_rev   = s.get("total_revenue", 0)
        fcf_y       = s.get("fcf_yield_at_target")
        margin_rat  = strip_html(s.get("margin_rationale", ""))
        narrative   = strip_html(s.get("narrative", ""))
        pe_rat      = strip_html(s.get("pe_rationale", ""))
        eps_flag    = s.get("eps_flag")
        hw_rev      = s.get("total_headwind_revenue", 0)
        hw_eps      = s.get("total_headwind_eps", 0)
        tw_rev      = s.get("total_tailwind_revenue", 0)
        tw_eps      = s.get("total_tailwind_eps", 0)

        bpe_text = f"Breakeven P/E: {bpe:.1f}x" if bpe else ""
        fcf_text = f"FCF Yield at Target: {fcf_y*100:.1f}%" if fcf_y else ""

        # Header card
        st.markdown(f'''<div class="scenario-card" style="border-left:3px solid {scolor};">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.8rem;">
                <div>
                    <span style="font-weight:800;font-size:0.9rem;text-transform:uppercase;
                        letter-spacing:0.1em;color:{scolor};">{slabel}</span>
                    <span style="color:rgba(255,255,255,0.35);font-size:0.8rem;
                        font-weight:600;margin-left:0.6rem;">{prob:.0f}% probability</span>
                    <div style="font-size:0.72rem;color:rgba(255,255,255,0.3);
                        margin-top:0.2rem;font-style:italic;">{stag}</div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:1.4rem;font-weight:900;color:#fff;">{sym}{pt:,.2f}</div>
                    <div style="font-size:0.88rem;font-weight:700;color:{scolor};
                        margin-top:0.1rem;">{ret:+.1f}%</div>
                </div>
            </div>
        </div>''', unsafe_allow_html=True)

        # Stats row
        stats_parts = [
            f"Revenue: <strong>{fmt_c(total_rev, cur)}</strong> ({rev_growth*100:+.1f}%)",
            f"EPS: <strong>{sym}{eps:.2f}</strong>",
            f"P/E: <strong>{pe:.1f}x</strong>",
            f"Op. Margin: <strong>{op_margin*100:.1f}%</strong>",
        ]
        if bpe_text:
            stats_parts.append(f"<strong>{bpe_text}</strong>")
        if fcf_text:
            stats_parts.append(f"<strong>{fcf_text}</strong>")
        stats_html = " &nbsp;/&nbsp; ".join(
            f'<span style="font-size:0.8rem;color:rgba(255,255,255,0.4);">{p}</span>'
            for p in stats_parts
        )
        st.markdown(
            f'<div style="padding:0.4rem 0 0.6rem;">{stats_html}</div>',
            unsafe_allow_html=True
        )

        # Segment builds
        seg_builds = s.get("segment_builds", [])
        if seg_builds:
            seg_lines = []
            for seg in seg_builds:
                seg_rev = safe_float(seg.get("projected_revenue"))
                seg_gr  = safe_float(seg.get("growth_rate"))
                seg_lines.append(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:0.2rem 0;font-size:0.82rem;">'
                    f'<span style="color:rgba(255,255,255,0.55);">'
                    f'{strip_html(seg.get("name",""))}</span>'
                    f'<span style="color:#fff;font-weight:600;">'
                    f'{fmt_c(seg_rev, cur)}'
                    f'<span style="color:{scolor};font-size:0.75rem;margin-left:0.4rem;">'
                    f'{seg_gr*100:+.0f}%</span></span></div>'
                )
            st.markdown(
                f'<div style="border-top:1px solid rgba(255,255,255,0.06);'
                f'padding:0.6rem 0;margin:0.3rem 0;">'
                f'<div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:0.1em;color:rgba(255,255,255,0.3);margin-bottom:0.4rem;">'
                f'Segment Revenue Builds</div>'
                f'{"".join(seg_lines)}</div>',
                unsafe_allow_html=True
            )

        # Headwind/tailwind summary
        if hw_rev != 0 or tw_rev != 0:
            hw_tw_parts = []
            if hw_rev != 0:
                hw_tw_parts.append(
                    f'Headwinds: <span style="color:#f87171;">'
                    f'{fmt_c(hw_rev, cur)} / {sym}{hw_eps:+.2f} EPS</span>'
                )
            if tw_rev != 0:
                hw_tw_parts.append(
                    f'Tailwinds: <span style="color:#4ade80;">'
                    f'{fmt_c(tw_rev, cur)} / {sym}{tw_eps:+.2f} EPS</span>'
                )
            st.markdown(
                f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.4);'
                f'margin:0.3rem 0;">{" &nbsp;|&nbsp; ".join(hw_tw_parts)}</div>',
                unsafe_allow_html=True
            )

        # Narrative and rationale
        st.markdown(
            f'<div style="font-size:0.9rem;color:rgba(255,255,255,0.6);line-height:1.7;'
            f'font-style:italic;margin:0.4rem 0;">{narrative}</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div style="font-size:0.76rem;color:rgba(255,255,255,0.3);margin-top:0.3rem;">'
            f'Margin: {margin_rat}</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div style="font-size:0.76rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">'
            f'Valuation: {pe_rat}</div>',
            unsafe_allow_html=True
        )

        # EPS flag
        if eps_flag:
            st.markdown(
                f'<div style="font-size:0.75rem;color:#fbbf24;margin-top:0.4rem;'
                f'font-style:italic;">{strip_html(eps_flag)}</div>',
                unsafe_allow_html=True
            )

        # Spacer between scenarios
        st.markdown(
            '<div style="height:0.8rem;"></div>',
            unsafe_allow_html=True
        )

    # ── Expected Value Bar ──
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

    # ── Sensitivity Analysis (NEW) ──
    sensitivity = sm.get("sensitivity", {})
    if sensitivity and sensitivity.get("dominant_driver"):
        driver_name = strip_html(sensitivity.get("dominant_driver", ""))
        current_p   = safe_float(sensitivity.get("current_bull_probability")) * 100
        ev_plus     = safe_float(sensitivity.get("ev_if_bull_plus_10"))
        ev_minus    = safe_float(sensitivity.get("ev_if_bull_minus_10"))
        interp      = strip_html(sensitivity.get("interpretation", ""))

        st.markdown(
            '<div class="sec">Sensitivity Analysis '
            '<span class="vtag">Dominant Driver</span></div>',
            unsafe_allow_html=True
        )
        st.markdown(f'''<div style="background:#141414;border:1px solid rgba(255,255,255,0.06);
            border-radius:8px;padding:1.2rem 1.5rem;margin:0.8rem 0;">
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.55);margin-bottom:1rem;">
                What happens to the expected value if we change the bull probability
                on <strong style="color:#fff;">{driver_name}</strong>?</div>
            <div style="display:flex;justify-content:center;gap:2.5rem;">
                <div style="text-align:center;">
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.1em;color:#f87171;margin-bottom:0.3rem;">
                        Bull Prob -10pp ({current_p - 10:.0f}%)</div>
                    <div style="font-size:1.3rem;font-weight:800;color:#f87171;">
                        {sym}{ev_minus:,.2f}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.1em;color:rgba(255,255,255,0.3);margin-bottom:0.3rem;">
                        Current ({current_p:.0f}%)</div>
                    <div style="font-size:1.3rem;font-weight:800;color:#fff;">
                        {sym}{ev:,.2f}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.1em;color:#4ade80;margin-bottom:0.3rem;">
                        Bull Prob +10pp ({current_p + 10:.0f}%)</div>
                    <div style="font-size:1.3rem;font-weight:800;color:#4ade80;">
                        {sym}{ev_plus:,.2f}</div>
                </div>
            </div>
            <div style="font-size:0.85rem;color:rgba(255,255,255,0.45);text-align:center;
                margin-top:1rem;line-height:1.6;font-style:italic;">{interp}</div>
        </div>''', unsafe_allow_html=True)

    # ── Catalyst Calendar ──
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
                <td style="color:#4ade80;">{strip_html(c.get("positive_signal", c.get("bull_signal","")))}</td>
                <td style="color:#f87171;">{strip_html(c.get("negative_signal", c.get("bear_signal","")))}</td>
            </tr>'''
        st.markdown(
            f'<table class="pt"><thead>{cat_header}</thead>'
            f'<tbody>{cat_rows}</tbody></table>',
            unsafe_allow_html=True
        )

    # ── Conclusion ──
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
        &nbsp;/&nbsp; Math computed in Python (segment-level)
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
    <div class="tag">AI Assisted Equity Research</div>
    <div class="desc">Equity analysis powered by the QGLP framework. Bottoms up EPS projections with quantified headwinds, probability assigned scenarios, and AI-assised insights.</div>
</div>''', unsafe_allow_html=True)

# ── QGLP Top Picks ──
screener_data = load_screener_results()
if screener_data:
    last_updated = screener_data.get("last_updated", "")

    st.markdown(f'''<div style="padding:1.5rem 0 0.5rem;">
        <div style="display:flex;justify-content:space-between;align-items:baseline;">
            <div style="font-size:0.9rem;font-weight:900;text-transform:uppercase;
                letter-spacing:0.18em;color:rgba(255,255,255,0.18);">
                QGLP Top Picks</div>
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.15);">
                Updated {last_updated}</div>
        </div>
    </div>''', unsafe_allow_html=True)

    us_picks    = screener_data.get("us_picks", [])[:5]
    india_picks = screener_data.get("india_picks", [])[:5]

    st.markdown(
        '<div style="font-size:0.85rem;color:rgba(255,255,255,0.35);'
        'text-align:center;margin-bottom:1.2rem;">Select any ticker from '
        'the tables below to generate a full report, or search for a stock below the tables.</div>',
        unsafe_allow_html=True
    )

    def render_picks_table(picks, market_label, select_key):
        if not picks:
            return
        st.markdown(
            f'<div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.12em;color:rgba(255,255,255,0.25);margin:0.8rem 0 0.4rem;">'
            f'{market_label}</div>',
            unsafe_allow_html=True
        )

        header = ("<tr><th>Ticker</th><th>Company</th><th>Score</th>"
                  "<th>PEG</th><th>ROE</th><th>Earnings CAGR</th>"
                  "<th>FCF Yield</th><th>D/E</th></tr>")
        rows = ""
        for pick in picks:
            score = pick.get("qglp_score", 0)
            if score >= 85:
                sc = "#4ade80"
            elif score >= 70:
                sc = "#fbbf24"
            else:
                sc = "#f87171"

            roe  = pick.get("roe", 0)
            cagr = pick.get("earnings_cagr", 0)
            fcf  = pick.get("fcf_yield")
            de   = pick.get("debt_equity", 0)
            peg  = pick.get("peg_ratio", "-")
            ticker = pick.get("ticker", "")
            name   = pick.get("name", ticker)

            rows += f'''<tr>
                <td style="font-weight:700;color:#fff;">{ticker.replace(".NS","")}</td>
                <td style="color:rgba(255,255,255,0.55);font-size:0.82rem;">{name[:25]}</td>
                <td style="color:{sc};font-weight:800;">{score}</td>
                <td style="font-weight:600;">{peg}</td>
                <td>{roe*100:.1f}%</td>
                <td>{cagr*100:.1f}%</td>
                <td>{f"{fcf*100:.1f}%" if fcf else "-"}</td>
                <td>{de:.2f}</td>
            </tr>'''

        st.markdown(
            f'<table class="pt"><thead>{header}</thead>'
            f'<tbody>{rows}</tbody></table>',
            unsafe_allow_html=True
        )

        # Selectbox to pick a ticker
        ticker_options = [""] + [p.get("ticker", "") for p in picks]
        display_options = ["Select a ticker to analyze..."] + [
            f"{p.get('ticker','').replace('.NS','')} - {p.get('name','')[:25]}"
            for p in picks
        ]
        sel = st.selectbox(
            "Analyze", display_options,
            label_visibility="collapsed", key=select_key
        )
        if sel and sel != "Select a ticker to analyze...":
            idx = display_options.index(sel)
            chosen = ticker_options[idx]
            if chosen:
                st.session_state["resolved"] = chosen
                st.session_state["auto_generate"] = True

    render_picks_table(us_picks, "United States", "us_pick_select")
    render_picks_table(india_picks, "India", "india_pick_select")

st.markdown(f'''<div class="stats-row">
    <div class="sr-item"><span class="sr-num">24</span><span class="sr-lbl">Verified Metrics</span></div>
    <div class="sr-item"><span class="sr-num">5</span><span class="sr-lbl">Revenue Segments</span></div>
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

with st.expander("About the QGLP Framework", expanded=False):
    st.markdown('''<div class="thesis-section" style="margin:0;">
        <div class="thesis-title">Quality-Growth-Longevity-Price</div>
        <div class="thesis-grid">
            <div class="thesis-card">
                <div class="thesis-card-letter">Q</div>
                <div class="thesis-card-name">Quality</div>
                <div class="thesis-card-desc">Durable moats, ROE/ROCE above 15%, strong FCF, clean management. Debt/Equity below 1.0.</div>
            </div>
            <div class="thesis-card">
                <div class="thesis-card-letter">G</div>
                <div class="thesis-card-name">Growth</div>
                <div class="thesis-card-desc">Earnings CAGR above 12%. Revenue and EPS trajectory assessed by segment. TAM expanding at 2x+ GDP.</div>
            </div>
            <div class="thesis-card">
                <div class="thesis-card-letter">L</div>
                <div class="thesis-card-name">Longevity</div>
                <div class="thesis-card-desc">Competitive advantages persist 5+ years. Market share stability, succession depth, regulatory durability.</div>
            </div>
            <div class="thesis-card">
                <div class="thesis-card-letter">P</div>
                <div class="thesis-card-name">Price</div>
                <div class="thesis-card-desc">PEG below 1.2x is target. Below 1.0x is exceptional. Above 1.4x requires documented rationale.</div>
            </div>
        </div>
    </div>''', unsafe_allow_html=True)

report_area = st.container()

# ══════════════════════════════════════════════════════════════
# GENERATION LOGIC
# ══════════════════════════════════════════════════════════════

should_generate = False
ticker          = None

resolved = st.session_state.get("resolved", None)

auto_gen = st.session_state.pop("auto_generate", False)

if (go or auto_gen) and resolved:
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
    <div class="foot-name">Mayukh Kondepudi</div>
    <div class="foot-email">mayukhkondepudi@gmail.com</div>
    <div class="foot-disclaimer">
        PickR is an AI-assisted equity research tool for educational and informational purposes only.
        It does not constitute financial advice, investment recommendations, or an offer to buy or sell securities.
        All financial data is sourced from Yahoo Finance or FMP as fallback and may be delayed. AI-assisted analysis
        is based on publicly available information and should not be relied upon as the sole basis for investment decisions.
        Past performance does not guarantee future results. Always consult a qualified financial advisor
        before making investment decisions.
    </div>
    <div class="foot-copy">2025 PickR. All rights reserved.</div>
</div>''', unsafe_allow_html=True)
