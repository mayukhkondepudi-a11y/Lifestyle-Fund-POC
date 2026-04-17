"""PickR — Streamlit UI and rendering."""
import streamlit as st
# ── DEBUG: Remove after fixing ──
from config import GITHUB_TOKEN, GITHUB_REPO
st.sidebar.write(f"TOKEN: {'SET' if GITHUB_TOKEN else 'EMPTY'}")
st.sidebar.write(f"REPO: {GITHUB_REPO or 'EMPTY'}")
import streamlit.components.v1 as components
import pandas as pd
import json
import os
from datetime import datetime

from config import (POPULAR, SECTOR_PEERS, GMAIL_SENDER, GMAIL_APP_PASS,
                    RESEND_API_KEY)
from formatting import (safe_float, get_sym, fmt_n, fmt_p, fmt_r, fmt_c,
                         strip_html)
from github_store import (add_tracked_stock, load_screener_results_raw,
                          load_tracker)
from email_service import send_email, email_confirmation
from compute import calc, compute_scenario_math
import ai
import fmp_api

st.set_page_config(page_title="PickR", page_icon="P", layout="wide")

# ── Session State ─────────────────────────────────────────────
for key, default in [
    ("report_count", 147), ("recent", []), ("cached_report", None),
    ("cached_html", None), ("trigger_ticker", None),
    ("generate_html", False), ("html_just_generated", False),
    ("track_success", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ══════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    html, body, .stApp { background:#0c0c0c !important; color:#e8e8e8 !important; font-family:'Inter',sans-serif !important; font-size:16px !important; }
    .block-container { padding-top:0 !important; max-width:1200px !important; }
    .stApp > div, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] { background:#0c0c0c !important; }
    #MainMenu, footer, header { visibility:hidden !important; }
    .hero { padding:4rem 2rem 1.5rem; text-align:center; }
    .hero h1 { font-size:4.2rem; font-weight:900; letter-spacing:-0.03em; margin:0; }
    .hero h1 .pick { background: linear-gradient(180deg, #ffffff 0%, #ffffff 35%, #e0e0e0 55%, #c8c8c8 75%, #e8e8e8 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6)) drop-shadow(0 0 12px rgba(255,255,255,0.08)); }
    .hero h1 .accent { background: linear-gradient(135deg, #a52525 0%, #e04040 30%, #ff8a8a 50%, #e04040 70%, #a52525 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; filter: drop-shadow(0 0 8px rgba(200,50,50,0.3)); }
    .hero .tag { font-size:1.1rem; color:rgba(255,255,255,0.4); margin-top:0.3rem; }
    .hero .desc { font-size:1rem; color:rgba(255,255,255,0.35); max-width:620px; margin:1rem auto 0; line-height:1.7; }
    .stats-row { display:flex; justify-content:center; gap:3rem; padding:1.3rem 0; margin-top:1.5rem; border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); }
    .sr-item { text-align:center; }
    .sr-num { font-size:1.6rem; font-weight:800; color:#fff; display:block; }
    .sr-lbl { font-size:0.65rem; color:rgba(255,255,255,0.22); text-transform:uppercase; letter-spacing:0.14em; font-weight:600; }
    .hiw { padding:2rem 0 1rem; }
    .hiw-title { text-align:center; font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.18em; color:rgba(255,255,255,0.18); margin-bottom:1.2rem; }
    .hiw-grid { display:flex; justify-content:center; gap:1.5rem; }
    .hiw-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:1.3rem; text-align:center; flex:1; max-width:260px; }
    .hiw-step { font-size:0.6rem; font-weight:800; color:#8b1a1a; text-transform:uppercase; letter-spacing:0.16em; margin-bottom:0.4rem; }
    .hiw-title2 { font-size:1.1rem; font-weight:700; color:#fff; margin-bottom:0.3rem; }
    .hiw-desc { font-size:0.9rem; color:rgba(255,255,255,0.55); line-height:1.65; }
    .thesis-section { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:2rem; margin:1.5rem 0; }
    .thesis-title { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.16em; color:rgba(255,255,255,0.2); margin-bottom:1rem; }
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
    .scoring-range.buy { color:#22c55e; } .scoring-range.watch { color:#f5c542; } .scoring-range.pass { color:#ff4d4d; }
    .scoring-label { font-size:0.62rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.1em; font-weight:600; }
    .params-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:1.2rem 1.5rem; margin-bottom:1.5rem; }
    .params-row { display:flex; justify-content:space-between; padding:0.5rem 0; border-bottom:1px solid rgba(255,255,255,0.03); font-size:0.9rem; }
    .params-row:last-child { border-bottom:none; }
    .params-key { color:rgba(255,255,255,0.55); font-weight:500; }
    .params-val { color:#ffffff; font-weight:600; }
    .rpt-card { background:#1a1a1a; border:1px solid #333; border-radius:12px; padding:2rem 2.5rem; margin-top:1rem; }
    .rpt-head h2 { font-size:2.4rem; font-weight:800; color:#ffffff; margin:0; letter-spacing:-0.02em; }
    .rpt-head .meta { color:rgba(255,255,255,0.6); font-size:0.88rem; letter-spacing:0.04em; margin-top:0.4rem; font-weight:500; }
    .rec-bar { display:flex; justify-content:center; gap:3.5rem; padding:1.5rem 0; border-bottom:1px solid rgba(255,255,255,0.1); margin-bottom:0.5rem; }
    .rb-item { text-align:center; }
    .rb-label { font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em; color:rgba(255,255,255,0.55); margin-bottom:0.3rem; }
    .rb-val { font-size:1.6rem; font-weight:800; }
    .rb-val.buy { color:#4ade80; } .rb-val.watch { color:#fbbf24; } .rb-val.pass { color:#f87171; }
    .exec-summary { background:#222; border-left:4px solid #e03030; border-radius:0 8px 8px 0; padding:1.2rem 1.6rem; margin:1.2rem 0; font-size:1rem; line-height:1.85; color:#eeeeee; font-style:italic; }
    .rationale-text { text-align:center; font-size:0.97rem; color:rgba(255,255,255,0.65); font-style:italic; max-width:680px; margin:0 auto; padding-bottom:1.5rem; line-height:1.8; }
    .sec { font-size:0.75rem; font-weight:800; text-transform:uppercase; letter-spacing:0.18em; color:#ffffff; margin:2.2rem 0 0.9rem; padding-bottom:0.5rem; border-bottom:2px solid #e03030; display:block; }
    [data-testid="stMetricLabel"] { font-size:0.68rem !important; color:rgba(255,255,255,0.6) !important; text-transform:uppercase !important; letter-spacing:0.06em !important; font-weight:700 !important; }
    [data-testid="stMetricValue"] { font-size:1.3rem !important; font-weight:700 !important; color:#ffffff !important; }
    [data-testid="stMetricDelta"] { display:none !important; }
    .range-bar-container { margin:0.8rem 0 1.5rem; }
    .range-bar-labels { display:flex; justify-content:space-between; font-size:0.8rem; color:rgba(255,255,255,0.65); margin-bottom:0.4rem; font-weight:600; }
    .range-bar { height:7px; background:rgba(255,255,255,0.1); border-radius:4px; position:relative; }
    .range-bar-fill { height:100%; background:linear-gradient(90deg,#8b1a1a,#e03030); border-radius:4px; }
    .range-bar-dot { width:12px; height:12px; background:#fff; border-radius:50%; position:absolute; top:-2.5px; transform:translateX(-50%); box-shadow:0 0 8px rgba(224,48,48,0.8); }
    .prose { font-size:1rem; line-height:1.95; color:#dedede; padding:0.3rem 0 0.8rem; }
    .risk-row { padding:0.75rem 0; border-bottom:1px solid rgba(255,255,255,0.07); font-size:0.95rem; line-height:1.75; color:#dedede; }
    .risk-row:last-child { border-bottom:none; }
    .cb { padding:1.2rem 1.5rem; border-radius:8px; font-size:0.95rem; line-height:1.8; color:#dedede; }
    .cb-bull { background:rgba(74,222,128,0.08); border:1px solid rgba(74,222,128,0.28); }
    .cb-bear { background:rgba(248,113,113,0.08); border:1px solid rgba(248,113,113,0.25); }
    .cb-title { font-size:0.65rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em; margin-bottom:0.5rem; }
    .cb-bull .cb-title { color:#4ade80; } .cb-bear .cb-title { color:#f87171; }
    .pt { width:100%; border-collapse:collapse; font-size:0.88rem; }
    .pt th { text-align:left; font-size:0.65rem; font-weight:800; text-transform:uppercase; letter-spacing:0.08em; color:rgba(255,255,255,0.6); padding:0.6rem 0.75rem; border-bottom:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.03); }
    .pt td { padding:0.55rem 0.75rem; border-bottom:1px solid rgba(255,255,255,0.06); color:#dedede; }
    .pt tr.hl td { font-weight:700; color:#ffffff; background:rgba(224,48,48,0.1); }
    .vtag { display:inline-block; font-size:0.52rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#e03030; border:1px solid rgba(224,48,48,0.4); padding:0.06rem 0.3rem; border-radius:2px; margin-left:0.4rem; vertical-align:middle; }
    .div { border:none; border-top:1px solid rgba(255,255,255,0.08); margin:1rem 0; }
    .track-box { background:#1e1e1e; border:1px solid rgba(224,48,48,0.35); border-radius:8px; padding:1.5rem 2rem; margin-top:1.5rem; }
    .track-box-title { font-size:0.7rem; font-weight:800; text-transform:uppercase; letter-spacing:0.16em; color:#e03030; margin-bottom:0.6rem; }
    .track-success { background:rgba(74,222,128,0.1); border:1px solid rgba(74,222,128,0.3); border-radius:6px; padding:0.8rem 1.2rem; font-size:0.9rem; color:#4ade80; margin-top:0.8rem; }
    .track-note { font-size:0.75rem; color:rgba(255,255,255,0.4); margin-top:0.6rem; line-height:1.5; }
    .foot-card { background:#1a1a1a; border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:1.5rem 2rem; margin-top:2rem; text-align:center; }
    .foot-name { font-size:1rem; font-weight:600; color:rgba(255,255,255,0.75); }
    .foot-email { font-size:0.85rem; color:rgba(255,255,255,0.45); margin-top:0.2rem; }
    .foot-disclaimer { font-size:0.78rem; color:rgba(255,255,255,0.35); margin-top:1rem; line-height:1.65; max-width:700px; margin-left:auto; margin-right:auto; }
    .foot-copy { font-size:0.68rem; color:rgba(255,255,255,0.2); margin-top:0.8rem; }
    .driver-card { background:#141414; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:1rem 1.2rem; margin:0.5rem 0; }
    .driver-card-name { font-weight:700; color:#fff; font-size:0.95rem; margin-bottom:0.2rem; }
    .driver-card-desc { font-size:0.82rem; color:rgba(255,255,255,0.45); margin-bottom:0.8rem; }
    .hw-grid { display:grid; grid-template-columns:1fr 1fr; gap:0.8rem; margin:0.8rem 0 1.2rem; }
    .hw-card { background:#141414; border:1px solid rgba(248,113,113,0.2); border-radius:8px; padding:1rem 1.2rem; }
    .tw-card { background:#141414; border:1px solid rgba(74,222,128,0.2); border-radius:8px; padding:1rem 1.2rem; }
    .hw-card-title { font-size:0.78rem; font-weight:800; text-transform:uppercase; letter-spacing:0.1em; color:#f87171; margin-bottom:0.3rem; }
    .tw-card-title { font-size:0.78rem; font-weight:800; text-transform:uppercase; letter-spacing:0.1em; color:#4ade80; margin-bottom:0.3rem; }
    .hw-card-desc { font-size:0.85rem; color:rgba(255,255,255,0.5); line-height:1.55; margin-bottom:0.6rem; }
    .hw-prob-badge { display:inline-block; font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; padding:0.15rem 0.4rem; border-radius:3px; background:rgba(248,113,113,0.15); color:#f87171; border:1px solid rgba(248,113,113,0.3); margin-bottom:0.4rem; }
    .tw-prob-badge { display:inline-block; font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; padding:0.15rem 0.4rem; border-radius:3px; background:rgba(74,222,128,0.1); color:#4ade80; border:1px solid rgba(74,222,128,0.25); margin-bottom:0.4rem; }
    .scenario-card { background:#1a1a1a; border-radius:8px; padding:1.2rem 1.5rem; margin:0.8rem 0; }
    .ev-bar { display:flex; justify-content:center; gap:2.5rem; background:#141414; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:1.2rem 1.5rem; margin:1rem 0; flex-wrap:wrap; }
    .ev-item { text-align:center; }
    .ev-label { font-size:0.62rem; font-weight:700; text-transform:uppercase; letter-spacing:0.12em; color:rgba(255,255,255,0.3); margin-bottom:0.3rem; }
    .ev-val { font-size:1.3rem; font-weight:800; color:#fff; }
    .ev-val.positive { color:#4ade80; } .ev-val.negative { color:#f87171; } .ev-val.neutral { color:#fbbf24; }
    .plain-callout { background:rgba(139,26,26,0.12); border-left:3px solid #8b1a1a; border-radius:0 6px 6px 0; padding:0.9rem 1.2rem; margin:0.8rem 0; font-size:0.9rem; color:rgba(255,255,255,0.65); line-height:1.7; }
    .plain-callout-label { font-size:0.62rem; font-weight:800; text-transform:uppercase; letter-spacing:0.14em; color:#c03030; margin-bottom:0.3rem; }
    .prob-explainer { background:#141414; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:1.2rem 1.5rem; margin:1rem 0; font-size:0.88rem; color:rgba(255,255,255,0.55); line-height:1.7; }
    .prob-explainer strong { color:#fff; }
    .prob-math-row { display:flex; gap:1rem; align-items:center; flex-wrap:wrap; margin:0.6rem 0; font-size:0.85rem; }
    .prob-math-chip { background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:4px; padding:0.25rem 0.6rem; color:#e0e0e0; font-weight:600; }
    .prob-math-chip.bull { border-color:rgba(74,222,128,0.4); color:#4ade80; background:rgba(74,222,128,0.06); }
    .prob-math-chip.bear { border-color:rgba(248,113,113,0.4); color:#f87171; background:rgba(248,113,113,0.06); }
    .prob-math-chip.base { border-color:rgba(251,191,36,0.4); color:#fbbf24; background:rgba(251,191,36,0.06); }
    .prob-math-arrow { color:rgba(255,255,255,0.3); font-size:0.9rem; }
    .stTextInput > div > div > input { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important; border-radius:6px !important; color:#fff !important; font-size:1rem !important; padding:0.6rem 1rem !important; caret-color:#fff !important; }
    .stTextInput > div > div > input:focus { border-color:#8b1a1a !important; box-shadow:0 0 0 2px rgba(139,26,26,0.15) !important; }
    .stTextInput > div > div > input::placeholder { color:rgba(255,255,255,0.25) !important; }
    .stSelectbox > div > div { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important; border-radius:6px !important; color:#fff !important; }
    .stSelectbox > div > div > div { color:#fff !important; }
    .stSelectbox svg { fill:rgba(255,255,255,0.4) !important; }
    [data-testid="stStatusWidget"], .stAlert, .stStatus { background:#141414 !important; border:1px solid rgba(255,255,255,0.06) !important; color:#e8e8e8 !important; border-radius:6px !important; }
    [data-testid="stStatusWidget"] p, [data-testid="stStatusWidget"] span, [data-testid="stStatusWidget"] div { color:#e8e8e8 !important; }
    .stButton > button { background:linear-gradient(160deg,#7a1818,#a52525 30%,#c03030 50%,#a52525 70%,#7a1818) !important; color:#fff !important; border:none !important; border-radius:6px !important; font-size:0.9rem !important; font-weight:700 !important; letter-spacing:0.08em !important; text-transform:uppercase !important; padding:0.7rem 2rem !important; transition:all 0.2s ease !important; box-shadow:0 2px 8px rgba(139,26,26,0.2), inset 0 1px 0 rgba(255,255,255,0.1) !important; }
    .stButton > button:hover { background:linear-gradient(160deg,#8b1a1a,#c03030 30%,#d44040 50%,#c03030 70%,#8b1a1a) !important; transform:translateY(-1px) !important; box-shadow:0 6px 20px rgba(139,26,26,0.4), inset 0 1px 0 rgba(255,255,255,0.15) !important; }
    .stDownloadButton > button { background:transparent !important; color:rgba(255,255,255,0.5) !important; border:1px solid rgba(139,26,26,0.35) !important; border-radius:6px !important; font-size:0.78rem !important; font-weight:600 !important; letter-spacing:0.08em !important; text-transform:uppercase !important; box-shadow:none !important; }
    .stDownloadButton > button:hover { border-color:#8b1a1a !important; color:#fff !important; box-shadow:none !important; }
    [data-testid="stVegaLiteChart"] { background:rgba(255,255,255,0.02) !important; border:1px solid rgba(255,255,255,0.04) !important; border-radius:6px !important; }
    .stWarning, .stError, .stInfo { background:#1a1a1a !important; color:#e8e8e8 !important; }
    .stNumberInput > div > div > input { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important; border-radius:6px !important; color:#fff !important; }
            
                /* ── POLISH LAYER ── */
    .stApp { transition: all 0.2s ease; }
    .sec { margin: 3rem 0 1.2rem; padding-bottom:0.6rem; }
    
    .driver-card, .scenario-card, .params-card, .thesis-card {
        transition: all 0.2s ease;
    }
    .driver-card:hover, .scenario-card:hover, .params-card:hover, .thesis-card:hover {
        border-color: rgba(255,255,255,0.12);
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .pt tbody tr { transition: background 0.15s ease; }
    .pt tbody tr:hover { background: rgba(255,255,255,0.03); }
    
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .hero { animation: fadeInUp 0.6s ease-out; }
    .rpt-card { animation: fadeInUp 0.4s ease-out; }
    .rec-bar { animation: fadeInUp 0.5s ease-out; }
    .ev-bar { animation: fadeInUp 0.5s ease-out; }
    
    .hero::after {
        content: ''; position: absolute; bottom: 0; left: 50%;
        transform: translateX(-50%); width: 60px; height: 2px;
        background: linear-gradient(90deg, transparent, #8b1a1a, transparent);
    }
    .hero { position: relative; }
    
    .rec-bar {
        background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%);
        border-radius: 8px;
    }
    
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0c0c0c; }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #555; }
    
    .exec-summary {
        border-left-width: 3px;
        background: linear-gradient(135deg, rgba(224,48,48,0.06) 0%, rgba(34,34,34,1) 100%);
    }
    
    .ev-bar {
        background: linear-gradient(180deg, rgba(20,20,20,1) 0%, rgba(26,26,26,1) 100%);
        border: 1px solid rgba(255,255,255,0.08);
    }
    
    .stButton > button { transition: all 0.25s ease !important; }
    .stButton > button:active { transform: scale(0.97) !important; }
            
        /* ── MOBILE RESPONSIVE ── */
    @media (max-width: 768px) {
        .hero h1 { font-size: 2.8rem !important; }
        .hero .desc { font-size: 0.88rem; padding: 0 1rem; }
        .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
        .rpt-card { padding: 1.2rem 1rem !important; }
        .rec-bar { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem 0.5rem !important; }
        .rb-val { font-size: 1.2rem !important; }
        .rb-label { font-size: 0.58rem !important; }
        .ev-bar { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem !important; }
        .ev-val { font-size: 1rem !important; }
        .stats-row { gap: 1.5rem !important; flex-wrap: wrap !important; }
        .sr-num { font-size: 1.2rem !important; }
        .pt { font-size: 0.75rem !important; }
        .pt th { font-size: 0.55rem !important; padding: 0.4rem !important; }
        .pt td { padding: 0.4rem !important; }
        .prose { font-size: 0.9rem !important; }
        .sec { font-size: 0.68rem !important; margin: 2rem 0 0.8rem !important; }
        .exec-summary { padding: 1rem !important; font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.6rem !important; }
        .rpt-head .meta { font-size: 0.72rem !important; }
        .range-bar-labels { font-size: 0.7rem !important; }
        .thesis-grid { grid-template-columns: 1fr !important; }
        .hiw-grid { flex-direction: column !important; align-items: center !important; }
        .params-row { font-size: 0.8rem !important; }
        .driver-card { padding: 0.8rem !important; }
        .scenario-card { padding: 0.8rem 1rem !important; }
        .plain-callout { padding: 0.7rem 0.9rem !important; font-size: 0.82rem !important; }
        .prob-math-row { font-size: 0.75rem !important; }
        .prob-math-chip { padding: 0.2rem 0.4rem !important; font-size: 0.72rem !important; }
        .track-box { padding: 1rem 1.2rem !important; }
        .foot-card { padding: 1rem !important; }
        .foot-disclaimer { font-size: 0.7rem !important; }
        
        /* Concentration grid single column on mobile */
        div[style*="grid-template-columns:1fr 1fr"] {
            grid-template-columns: 1fr !important;
        }
        
        /* Sticky header compact on mobile */
        div[style*="position:sticky"] {
            padding: 0.4rem 0.8rem !important;
            font-size: 0.8rem !important;
        }
    }
    
    @media (max-width: 480px) {
        .hero h1 { font-size: 2.2rem !important; }
        .rec-bar { gap: 0.8rem !important; }
        .rb-val { font-size: 1rem !important; }
        .ev-bar { gap: 0.8rem !important; }
        .ev-val { font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.3rem !important; }
        .pt { display: block !important; overflow-x: auto !important; }
    }

</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════

from auth import render_auth, render_sidebar

name, username, authenticated = render_auth()

if not authenticated:
    st.stop()

render_sidebar(username, name)

# DEBUG: Remove after fixing
st.sidebar.write(f"DEBUG: username={username}")
try:
    from report_store import load_user_index
    idx = load_user_index(username)
    st.sidebar.write(f"DEBUG: index={idx}")
except Exception as e:
    st.sidebar.write(f"DEBUG: error={e}")


# Report history in sidebar
with st.sidebar:
    st.markdown('<div style="font-size:0.6rem;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.14em;color:rgba(255,255,255,0.18);'
                'margin:1.5rem 0 0.6rem;">Report History</div>',
                unsafe_allow_html=True)
    try:
        from report_store import load_user_index, load_report as load_saved_report
        past_reports = load_user_index(username)
        if past_reports:
            for r in reversed(past_reports[-15:]):
                rec = r.get("recommendation", "")
                ret = r.get("expected_return")
                rec_color = ("#4ade80" if rec == "BUY"
                             else ("#f87171" if rec == "PASS" else "#fbbf24"))
                ret_str = f"{ret*100:+.0f}%" if ret else ""
                company = r.get("company_name", r["ticker"])[:20]
                rid = r.get("report_id", f"{r['ticker']}_{r['date']}")

                st.markdown(f'''<div style="display:flex;justify-content:space-between;
                    align-items:center;padding:0.35rem 0;
                    border-bottom:1px solid rgba(255,255,255,0.03);">
                    <div>
                        <div style="font-size:0.82rem;color:#fff;font-weight:600;">
                            {r["ticker"]}</div>
                        <div style="font-size:0.65rem;color:rgba(255,255,255,0.25);">
                            {company} / {r["date"]}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="color:{rec_color};font-size:0.7rem;
                            font-weight:700;">{rec}</div>
                        <div style="font-size:0.62rem;
                            color:rgba(255,255,255,0.25);">{ret_str}</div>
                    </div>
                </div>''', unsafe_allow_html=True)

                if st.button(f"Load", key=f"load_{rid}",
                             use_container_width=True):
                    report_data = load_saved_report(username, rid)
                    if report_data:
                        st.session_state.cached_report = {
                            "ticker": report_data["ticker"],
                            "metrics": report_data["metrics"],
                            "analysis": report_data["analysis"],
                            "data": {"hist": None, "info": {},
                                     "inc": None, "qinc": None,
                                     "bs": None, "cf": None,
                                     "news": []},
                        }
                        st.rerun()
                    else:
                        st.toast("Could not load report")
        else:
            st.markdown('<div style="font-size:0.8rem;color:rgba(255,255,255,0.2);'
                        'font-style:italic;">No reports yet.</div>',
                        unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<div style="font-size:0.72rem;color:rgba(255,255,255,0.15);">'
                    f'History unavailable</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# CACHED DATA FETCHING
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_screener_results():
    from config import GITHUB_TOKEN, GITHUB_REPO, SCREENER_FILE
    import urllib.request, json, base64
    
    st.sidebar.write(f"DEBUG load_screener: FILE={SCREENER_FILE}")
    
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SCREENER_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                content = json.loads(base64.b64decode(data["content"]).decode())
                st.sidebar.write(f"DEBUG load_screener: GOT {type(content)}, keys={list(content.keys()) if isinstance(content, dict) else 'not dict'}")
                return content
        except Exception as e:
            st.sidebar.write(f"DEBUG load_screener ERROR: {str(e)[:200]}")
    
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def search_ticker(query):
    return fmp_api.search_ticker(query)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch(ticker):
    result = fmp_api.fetch_full(ticker)
    if result is None:
        return {"info": {"error": f"Could not fetch data for {ticker}"},
                "inc": None, "qinc": None, "bs": None, "cf": None,
                "hist": None, "news": []}
    return result

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_peers(ticker, sector, llm_peers=None):
    if llm_peers and len(llm_peers) > 0:
        peer_tickers = [p.upper() for p in llm_peers
                        if p.upper() != ticker.upper()][:5]
    else:
        peer_tickers = [p for p in SECTOR_PEERS.get(sector, [])
                        if p.upper() != ticker.upper()][:4]
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
        except Exception:
            continue
    return out


# ══════════════════════════════════════════════════════════════
# CACHED AI PASSES (wraps ai.py with @st.cache_data)
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass1(ticker, metrics_json_str):
    m = json.loads(metrics_json_str)
    return ai.run_pass1(ticker, m)

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str):
    m  = json.loads(metrics_json_str)
    sm = json.loads(math_json_str)
    p1 = json.loads(pass1_json_str)
    return ai.run_pass2(ticker, m, sm, p1)


def run_analysis(ticker, m):
    """Orchestrate two-pass analysis with Streamlit caching."""
    metrics_json_str = json.dumps(
        {k: v for k, v in m.items() if k not in ["description", "news"]},
        sort_keys=True, default=str)

    # Pass 1
    pass1 = _cached_pass1(ticker, metrics_json_str)
    if isinstance(pass1, dict) and pass1.get("error"):
        return pass1

    # Python math
    scenario_math = compute_scenario_math(m, pass1)

    # Pass 2
    math_json_str  = json.dumps(scenario_math, sort_keys=True, default=str)
    pass1_json_str = json.dumps(pass1, sort_keys=True, default=str)
    pass2 = _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str)
    if isinstance(pass2, dict) and pass2.get("error"):
        return pass2

    # Merge
    final = {}
    for key in ["recommendation", "conviction", "investment_thesis",
                "business_overview", "revenue_architecture", "growth_drivers",
                "margin_analysis", "financial_health", "competitive_position",
                "headwind_narrative", "tailwind_narrative",
                "market_pricing_commentary", "scenario_commentary",
                "conclusion", "model_used"]:
        final[key] = pass2.get(key, "")

    for key in ["segments", "concentration", "headwinds", "tailwinds",
                "macro_drivers", "scenarios", "catalysts", "peer_tickers",
                "market_expectations", "sensitivity"]:
        final[key] = pass1.get(key, {} if key in ["concentration",
                     "market_expectations", "sensitivity"] else [])

    final["scenario_math"] = scenario_math

    # Consistency override
    exp_ret  = scenario_math.get("expected_return", 0)
    prob_pos = scenario_math.get("prob_positive_return", 0)
    rec      = final["recommendation"].upper()
    if rec == "BUY" and exp_ret < -0.20 and prob_pos < 0.25:
        final["recommendation"] = "PASS"
        final["conviction"] = "High"
        final["rec_override_reason"] = (
            f"Override: LLM recommended BUY despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return.")
    elif rec == "PASS" and exp_ret > 0.20 and prob_pos > 0.70:
        final["recommendation"] = "BUY"
        final["conviction"] = "Medium"
        final["rec_override_reason"] = (
            f"Override: LLM recommended PASS despite expected return of "
            f"{exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return.")

    return final


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

    # Masthead
    st.markdown(f'''<div class="rpt-head">
        <h2>{strip_html(company)}</h2>
        <div class="meta">{ticker} &nbsp;/&nbsp; {m.get("sector","")} &nbsp;/&nbsp;
        {m.get("industry","")} &nbsp;/&nbsp; {cur} &nbsp;/&nbsp; {date}</div>
    </div>''', unsafe_allow_html=True)

    # Recommendation Bar
    rec  = a.get("recommendation", "WATCH").upper()
    conv = a.get("conviction", "Medium")
    rc   = "buy" if rec == "BUY" else ("pass" if rec == "PASS" else "watch")
    ev       = sm.get("expected_value", 0)
    exp_ret  = sm.get("expected_return", 0)
    prob_pos = sm.get("prob_positive_return", 0)

        # Sticky nav
    st.markdown(f'''<div style="position:sticky;top:0;z-index:100;
        background:rgba(26,26,26,0.92);backdrop-filter:blur(12px);
        border-bottom:1px solid rgba(255,255,255,0.06);
        padding:0.6rem 1.5rem;margin:0 -2.5rem 1rem;
        display:flex;justify-content:space-between;align-items:center;">
        <div style="display:flex;align-items:center;gap:1rem;">
            <span style="font-weight:900;color:#fff;font-size:0.95rem;">
                Pick<span style="color:#c03030;">R</span></span>
            <span style="color:rgba(255,255,255,0.5);font-size:0.85rem;font-weight:600;">
                {strip_html(company)}</span>
            <span style="color:rgba(255,255,255,0.25);font-size:0.8rem;">{ticker}</span>
        </div>
        <div style="display:flex;align-items:center;gap:2rem;">
            <span style="font-size:0.85rem;color:rgba(255,255,255,0.5);font-weight:600;">
                {sym}{safe_float(m.get("current_price")):,.2f}</span>
            <span style="font-size:0.85rem;font-weight:800;
                color:{'#4ade80' if rec=='BUY' else ('#f87171' if rec=='PASS' else '#fbbf24')};">
                {rec}</span>
            <span style="font-size:0.85rem;font-weight:700;
                color:{'#4ade80' if exp_ret > 0 else '#f87171'};">
                {exp_ret*100:+.1f}% EV</span>
        </div>
    </div>''', unsafe_allow_html=True)

    st.markdown(f'''<div class="rec-bar">
        <div class="rb-item"><div class="rb-label">Recommendation</div><div class="rb-val {rc}">{rec}</div></div>
        <div class="rb-item"><div class="rb-label">Conviction</div><div class="rb-val {rc}">{conv}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Value</div><div class="rb-val {rc}">{sym}{ev:,.2f}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Return</div><div class="rb-val {rc}">{exp_ret*100:+.1f}%</div></div>
        <div class="rb-item"><div class="rb-label">P(Positive)</div><div class="rb-val {rc}">{prob_pos*100:.0f}%</div></div>
    </div>''', unsafe_allow_html=True)

    # Investment Thesis
    if a.get("investment_thesis"):
        st.markdown(f'<div class="exec-summary">{strip_html(a["investment_thesis"])}</div>',
                    unsafe_allow_html=True)

    # Override warning
    if a.get("rec_override_reason"):
        st.markdown(
            f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);'
            f'border-radius:6px;padding:0.8rem 1.2rem;font-size:0.85rem;color:#fbbf24;'
            f'margin:0.8rem 0;line-height:1.5;">{strip_html(a["rec_override_reason"])}</div>',
            unsafe_allow_html=True)

    # 52-Week Range
    w52h = m.get("week_52_high"); w52l = m.get("week_52_low"); cp = m.get("current_price")
    if w52h and w52l and cp:
        try:
            w52h = float(w52h); w52l = float(w52l); cpf = float(cp)
            if w52h > w52l:
                pct = max(0, min(100, ((cpf - w52l) / (w52h - w52l)) * 100))
                st.markdown(f'''<div class="sec">52-Week Range</div>
                <div class="range-bar-container"><div class="range-bar-labels">
                    <span>{sym}{w52l:,.2f}</span>
                    <span style="color:rgba(255,255,255,0.6);font-weight:600;">Current: {sym}{cpf:,.2f}</span>
                    <span>{sym}{w52h:,.2f}</span></div>
                <div class="range-bar"><div class="range-bar-fill" style="width:{pct}%"></div>
                    <div class="range-bar-dot" style="left:{pct}%"></div></div></div>''',
                    unsafe_allow_html=True)
        except Exception:
            pass

    # 5-Year Price History
    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy(); cd.columns = ["Price"]
        st.line_chart(cd, height=250, color="#8b1a1a")

    # Key Metrics
    st.markdown('<div class="sec">Key Metrics <span class="vtag">Python-Verified</span></div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Market Cap", fmt_c(m.get("market_cap"), cur))
    with c2: st.metric("Price", fmt_c(m.get("current_price"), cur))
    with c3: st.metric("Trailing P/E", fmt_r(m.get("trailing_pe")))
    with c4: st.metric("Forward P/E", fmt_r(m.get("forward_pe")))
    with c5: st.metric("PEG", fmt_r(m.get("peg_ratio")))
    with c6: st.metric("EV/EBITDA", fmt_r(m.get("ev_to_ebitda")))
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Revenue", fmt_c(m.get("total_revenue"), cur))
    with c2: st.metric("Gross Margin", fmt_p(m.get("gross_margin")))
    with c3: st.metric("Op. Margin", fmt_p(m.get("operating_margin")))
    with c4: st.metric("Net Margin", fmt_p(m.get("profit_margin")))
    with c5: st.metric("ROE", fmt_p(m.get("roe")))
    with c6: st.metric("FCF Yield", fmt_p(m.get("fcf_yield")))
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Rev Growth", fmt_p(m.get("revenue_growth")))
    rev_cagr_yrs = m.get("revenue_cagr_years", 0)
    with c2: st.metric(f"Rev CAGR ({rev_cagr_yrs}Y)" if rev_cagr_yrs else "Rev CAGR", fmt_p(m.get("revenue_cagr")))
    with c3: st.metric("Debt/Equity", fmt_r(m.get("debt_to_equity")))
    with c4: st.metric("Current Ratio", fmt_r(m.get("current_ratio")))
    with c5: st.metric("Beta", fmt_r(m.get("beta")))
    with c6:
        r5 = m.get("price_5y_return")
        st.metric("5Y Return", f"{r5}%" if r5 else "-")

    # Revenue & Earnings Trend
    rh = m.get("revenue_history", {}); nh = m.get("net_income_history", {})
    if rh or nh:
        st.markdown('<div class="sec">Revenue &amp; Earnings Trend (Billions)</div>', unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            if rh: st.bar_chart(pd.DataFrame({"Revenue": rh}), height=200, color="#8b1a1a")
        with cc2:
            if nh: st.bar_chart(pd.DataFrame({"Net Income": nh}), height=200, color="#d4443a")

    # Revenue Segmentation
    segments = a.get("segments", [])
    if segments:
        st.markdown('<div class="sec">Revenue Segmentation</div>', unsafe_allow_html=True)
        seg_header = "<tr><th>Segment</th><th>Revenue</th><th>% of Total</th><th>Gross Margin</th><th>YoY Growth</th><th>Trajectory</th><th>Primary Driver</th></tr>"
        seg_rows = ""
        for seg in segments:
            traj = strip_html(seg.get("trajectory", ""))
            tc = "#4ade80" if traj == "accelerating" else ("#f87171" if traj == "decelerating" else "#fbbf24")
            seg_rows += f'''<tr><td><strong>{strip_html(seg.get("name",""))}</strong></td>
                <td>{fmt_c(seg.get("current_revenue"), cur)}</td><td>{fmt_p(seg.get("pct_of_total"))}</td>
                <td>{fmt_p(seg.get("gross_margin"))}</td><td>{fmt_p(seg.get("yoy_growth"))}</td>
                <td style="color:{tc};font-weight:600;text-transform:uppercase;font-size:0.78rem;">{traj}</td>
                <td style="font-size:0.82rem;color:rgba(255,255,255,0.5);">{strip_html(seg.get("primary_driver",""))}</td></tr>'''
        st.markdown(f'<table class="pt"><thead>{seg_header}</thead><tbody>{seg_rows}</tbody></table>', unsafe_allow_html=True)

    # Concentration & Dependencies
    conc = a.get("concentration", {})
    if conc:
        st.markdown('<div class="sec">Concentration &amp; Dependencies</div>', unsafe_allow_html=True)
        conc_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">'
        geo = conc.get("geographic_split", {})
        if geo:
            geo_items = "".join(f'<div class="params-row"><span class="params-key">{r.replace("_"," ")}</span><span class="params-val">{fmt_p(p)}</span></div>' for r, p in geo.items())
            conc_html += f'<div class="params-card" style="margin-bottom:0;"><div class="thesis-title">Geographic Exposure</div>{geo_items}</div>'
        dep_items = ""
        if conc.get("top_customer_pct"):
            dep_items += f'<div class="params-row"><span class="params-key">Top Customer</span><span class="params-val">{fmt_p(conc["top_customer_pct"])}</span></div>'
        if conc.get("top_5_customers_pct"):
            dep_items += f'<div class="params-row"><span class="params-key">Top 5 Customers</span><span class="params-val">{fmt_p(conc["top_5_customers_pct"])}</span></div>'
        for dep in conc.get("critical_dependencies", []):
            dep_items += f'<div class="params-row"><span class="params-key">Dependency</span><span class="params-val" style="font-size:0.82rem;">{strip_html(dep)}</span></div>'
        if dep_items:
            conc_html += f'<div class="params-card" style="margin-bottom:0;"><div class="thesis-title">Customer &amp; Supply Chain</div>{dep_items}</div>'
        conc_html += '</div>'
        st.markdown(conc_html, unsafe_allow_html=True)
        at_risk = conc.get("relationships_at_risk", [])
        if at_risk:
            risk_items = "".join(f'<div style="padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.88rem;color:rgba(255,255,255,0.55);">{strip_html(r)}</div>' for r in at_risk)
            st.markdown(f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.15);border-radius:6px;padding:0.8rem 1.2rem;margin-top:0.8rem;"><div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;margin-bottom:0.4rem;">Relationships At Risk</div>{risk_items}</div>', unsafe_allow_html=True)

    # Narrative sections
    for section_id, section_title in [
        ("business_overview", "Business Overview"),
        ("revenue_architecture", "Revenue Architecture"),
        ("growth_drivers", "Growth Drivers &amp; Competitive Moats"),
        ("margin_analysis", "Margin Analysis"),
        ("financial_health", "Financial Health"),
        ("competitive_position", "Competitive Position"),
    ]:
        if a.get(section_id):
            st.markdown(f'<div class="sec">{section_title}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="prose">{strip_html(a[section_id])}</div>', unsafe_allow_html=True)

    # Peer Comparison
    sector = m.get("sector", "")
    llm_peers = a.get("peer_tickers", [])
    if sector in SECTOR_PEERS or llm_peers:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        with st.spinner("Loading peers..."):
            peers = fetch_peers(ticker, sector, llm_peers=llm_peers)
        if peers:
            cur_row = {
                "Ticker": ticker, "Company": m.get("company_name", ticker),
                "Mkt Cap": fmt_c(m.get("market_cap"), cur), "P/E": fmt_r(m.get("trailing_pe")),
                "Fwd P/E": fmt_r(m.get("forward_pe")), "PEG": fmt_r(m.get("peg_ratio")),
                "Margin": fmt_p(m.get("operating_margin")), "ROE": fmt_p(m.get("roe")),
                "Rev Gr.": fmt_p(m.get("revenue_growth")),
            }
            hds  = list(cur_row.keys())
            th   = "".join(f"<th>{hd}</th>" for hd in hds)
            tr_c = "<tr class='hl'>" + "".join(f"<td>{cur_row[hd]}</td>" for hd in hds) + "</tr>"
            tr_p = "".join("<tr>" + "".join(f"<td>{pr.get(hd, '-')}</td>" for hd in hds) + "</tr>" for pr in peers)
            st.markdown(f'<table class="pt"><thead><tr>{th}</tr></thead><tbody>{tr_c}{tr_p}</tbody></table>', unsafe_allow_html=True)

    # Headwinds & Tailwinds
    headwinds = a.get("headwinds", [])
    tailwinds = a.get("tailwinds", [])
    if headwinds or tailwinds:
        st.markdown('<div class="sec">Headwinds &amp; Tailwinds <span class="vtag">Quantified</span></div>', unsafe_allow_html=True)
        if a.get("headwind_narrative"):
            st.markdown(f'<div class="prose">{strip_html(a["headwind_narrative"])}</div>', unsafe_allow_html=True)
        if headwinds:
            hw_header = "<tr><th>Headwind</th><th>Prob.</th><th>Revenue at Risk</th><th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>"
            hw_rows = ""
            for hw in headwinds:
                bi = hw.get("bull_impact", {}); bai = hw.get("base_impact", {}); bei = hw.get("bear_impact", {})
                hw_rows += f'''<tr><td><strong>{strip_html(hw.get("name",""))}</strong><br><span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">{strip_html(hw.get("description",""))[:120]}</span></td>
                    <td>{safe_float(hw.get("probability"))*100:.0f}%</td>
                    <td style="color:#f87171;">{fmt_c(hw.get("revenue_at_risk"), cur)}</td>
                    <td style="font-size:0.82rem;">{fmt_c(bi.get("revenue"), cur)}<br><span style="color:rgba(255,255,255,0.4);">{sym}{safe_float(bi.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(bai.get("revenue"), cur)}<br><span style="color:rgba(255,255,255,0.4);">{sym}{safe_float(bai.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;color:#f87171;">{fmt_c(bei.get("revenue"), cur)}<br><span>{sym}{safe_float(bei.get("eps")):+.2f} EPS</span></td></tr>'''
            st.markdown(f'<table class="pt"><thead>{hw_header}</thead><tbody>{hw_rows}</tbody></table>', unsafe_allow_html=True)
        if a.get("tailwind_narrative"):
            st.markdown(f'<div class="prose" style="margin-top:1rem;">{strip_html(a["tailwind_narrative"])}</div>', unsafe_allow_html=True)
        if tailwinds:
            tw_header = "<tr><th>Tailwind</th><th>Prob.</th><th>Revenue Opportunity</th><th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>"
            tw_rows = ""
            for tw in tailwinds:
                bi = tw.get("bull_impact", {}); bai = tw.get("base_impact", {}); bei = tw.get("bear_impact", {})
                tw_rows += f'''<tr><td><strong>{strip_html(tw.get("name",""))}</strong><br><span style="color:rgba(255,255,255,0.4);font-size:0.78rem;">{strip_html(tw.get("description",""))[:120]}</span></td>
                    <td>{safe_float(tw.get("probability"))*100:.0f}%</td>
                    <td style="color:#4ade80;">{fmt_c(tw.get("revenue_opportunity"), cur)}</td>
                    <td style="font-size:0.82rem;color:#4ade80;">{fmt_c(bi.get("revenue"), cur)}<br><span>{sym}{safe_float(bi.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(bai.get("revenue"), cur)}<br><span style="color:rgba(255,255,255,0.4);">{sym}{safe_float(bai.get("eps")):+.2f} EPS</span></td>
                    <td style="font-size:0.82rem;">{fmt_c(bei.get("revenue"), cur)}<br><span style="color:rgba(255,255,255,0.4);">{sym}{safe_float(bei.get("eps")):+.2f} EPS</span></td></tr>'''
            st.markdown(f'<table class="pt"><thead>{tw_header}</thead><tbody>{tw_rows}</tbody></table>', unsafe_allow_html=True)

    # Macro Drivers
    macro_drivers = a.get("macro_drivers", [])
    if macro_drivers:
        st.markdown('<div class="sec">What Drives the Outcome <span class="vtag">Bottom-Up Probability</span></div>', unsafe_allow_html=True)
        st.markdown('''<div class="plain-callout"><div class="plain-callout-label">How this works</div>
            Instead of guessing scenario probabilities, we identify the specific events that determine this company's outcome.
            Each event gets an independent probability. The math computes final scenario probabilities from these inputs.</div>''', unsafe_allow_html=True)
        for d in macro_drivers:
            dname = strip_html(d.get("name", ""))
            dmeasures = strip_html(d.get("measures", ""))
            bull_p = safe_float(d.get("bull_outcome", {}).get("probability"))
            base_p = safe_float(d.get("base_outcome", {}).get("probability"))
            bear_p = safe_float(d.get("bear_outcome", {}).get("probability"))
            bull_n = strip_html(d.get("bull_outcome", {}).get("description", ""))[:120]
            base_n = strip_html(d.get("base_outcome", {}).get("description", ""))[:120]
            bear_n = strip_html(d.get("bear_outcome", {}).get("description", ""))[:120]
            bw = max(2, min(100, round(bull_p*100))); basew = max(2, min(100, round(base_p*100))); bearw = max(2, min(100, round(bear_p*100)))
            st.markdown(f'''<div class="driver-card"><div class="driver-card-name">{dname}</div><div class="driver-card-desc">{dmeasures}</div>
                <div style="margin:0.3rem 0;">
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;"><div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;"><div style="width:{bw}%;height:100%;background:#4ade80;border-radius:3px;"></div></div><span style="font-size:0.75rem;color:#4ade80;font-weight:700;min-width:35px;">{bull_p*100:.0f}%</span><span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{bull_n}</span></div>
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;"><div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;"><div style="width:{basew}%;height:100%;background:#fbbf24;border-radius:3px;"></div></div><span style="font-size:0.75rem;color:#fbbf24;font-weight:700;min-width:35px;">{base_p*100:.0f}%</span><span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{base_n}</span></div>
                <div style="display:flex;align-items:center;gap:0.5rem;"><div style="width:100px;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;"><div style="width:{bearw}%;height:100%;background:#f87171;border-radius:3px;"></div></div><span style="font-size:0.75rem;color:#f87171;font-weight:700;min-width:35px;">{bear_p*100:.0f}%</span><span style="font-size:0.75rem;color:rgba(255,255,255,0.4);">{bear_n}</span></div>
                </div></div>''', unsafe_allow_html=True)

        # Probability math explainer
        if prob_out.get("method") == "geometric_mean_probability":
            raw_bull  = prob_out.get("raw_geometric", {}).get("bull", 0)
            raw_bear  = prob_out.get("raw_geometric", {}).get("bear", 0)
            bull_mult = prob_out.get("correlation_multipliers", {}).get("bull", 1.2)
            bear_mult = prob_out.get("correlation_multipliers", {}).get("bear", 1.4)
            fb = prob_out.get("bull", 0); fba = prob_out.get("base", 0); fbe = prob_out.get("bear", 0)
            st.markdown(f'''<div class="prob-explainer"><strong>How the final probabilities were computed:</strong><br><br>
                Geometric mean of each driver's bull/bear probabilities, with clustering adjustment:
                <strong>{bull_mult:.1f}x</strong> bull tail, <strong>{bear_mult:.1f}x</strong> bear tail
                (downside scenarios correlate more tightly in practice).
                <div class="prob-math-row" style="margin-top:0.8rem;">
                <span style="color:rgba(255,255,255,0.4);font-size:0.82rem;">Geometric mean:</span>
                <span class="prob-math-chip bull">Bull {raw_bull*100:.1f}%</span>
                <span class="prob-math-chip bear">Bear {raw_bear*100:.1f}%</span>
                <span class="prob-math-arrow">after clustering</span>
                <span class="prob-math-chip bull">Bull {fb*100:.1f}%</span>
                <span class="prob-math-chip base">Base {fba*100:.1f}%</span>
                <span class="prob-math-chip bear">Bear {fbe*100:.1f}%</span></div></div>''', unsafe_allow_html=True)

    # Market Pricing Commentary
    if a.get("market_pricing_commentary"):
        st.markdown('<div class="sec">Valuation vs Expectations</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["market_pricing_commentary"])}</div>', unsafe_allow_html=True)

    # Scenario Analysis
    st.markdown('<div class="sec">Scenario Analysis <span class="vtag">Segment-Level Builds</span></div>', unsafe_allow_html=True)
    if a.get("scenario_commentary"):
        st.markdown(f'<div class="prose">{strip_html(a["scenario_commentary"])}</div>', unsafe_allow_html=True)

    scenarios = sm.get("scenarios", {})
    
    bull_s = scenarios.get("bull", {})
    base_s = scenarios.get("base", {})
    bear_s = scenarios.get("bear", {})
    
    bull_label = f"Bull ({bull_s.get('probability',0)*100:.0f}%) / {sym}{bull_s.get('price_target',0):,.0f}" if bull_s else "Bull"
    base_label = f"Base ({base_s.get('probability',0)*100:.0f}%) / {sym}{base_s.get('price_target',0):,.0f}" if base_s else "Base"
    bear_label = f"Bear ({bear_s.get('probability',0)*100:.0f}%) / {sym}{bear_s.get('price_target',0):,.0f}" if bear_s else "Bear"
    
    bull_tab, base_tab, bear_tab = st.tabs([
        f":green[{bull_label}]",
        f":orange[{base_label}]",
        f":red[{bear_label}]",
    ])
    
    tab_configs = [
        (bull_tab, "bull", "Bull Case", "#4ade80", "What goes right"),
        (base_tab, "base", "Base Case", "#fbbf24", "Most likely path"),
        (bear_tab, "bear", "Bear Case", "#f87171", "What goes wrong"),
    ]
    
    for tab, sname, slabel, scolor, stag in tab_configs:
        s = scenarios.get(sname, {})
        if not s:
            continue
        with tab:
            prob = s.get("probability", 0)*100; pt = s.get("price_target", 0)
            ret = s.get("implied_return", 0)*100; eps = s.get("projected_eps", 0)
            pe = s.get("pe_multiple", 0); bpe = s.get("breakeven_pe")
            op_m = s.get("operating_margin", 0); rev_g = s.get("revenue_growth", 0)
            total_rev = s.get("total_revenue", 0); fcf_y = s.get("fcf_yield_at_target")
            narrative = strip_html(s.get("narrative", "")); pe_rat = strip_html(s.get("pe_rationale", ""))
            margin_rat = strip_html(s.get("margin_rationale", "")); eps_flag = s.get("eps_flag")
            hw_rev = s.get("total_headwind_revenue", 0); hw_eps = s.get("total_headwind_eps", 0)
            tw_rev = s.get("total_tailwind_revenue", 0); tw_eps = s.get("total_tailwind_eps", 0)

            # Price target hero
            st.markdown(f'''<div style="text-align:center;padding:1.5rem 0 1rem;">
                <div style="font-size:2.2rem;font-weight:900;color:#fff;">{sym}{pt:,.2f}</div>
                <div style="font-size:1.1rem;font-weight:700;color:{scolor};margin-top:0.3rem;">{ret:+.1f}% return</div>
                <div style="font-size:0.75rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">{prob:.0f}% probability</div>
            </div>''', unsafe_allow_html=True)

            # Key metrics row
            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("Revenue", fmt_c(total_rev, cur))
            with m2: st.metric("EPS", f"{sym}{eps:.2f}")
            with m3: st.metric("P/E Multiple", f"{pe:.1f}x")
            with m4: st.metric("Op. Margin", f"{op_m*100:.1f}%")

            # Segment builds
            seg_builds = s.get("segment_builds", [])
            if seg_builds:
                st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.3);margin:1rem 0 0.5rem;">Segment Revenue Builds</div>', unsafe_allow_html=True)
                for seg in seg_builds:
                    sr = safe_float(seg.get("projected_revenue")); sg = safe_float(seg.get("growth_rate"))
                    pct_of_total = (sr / total_rev * 100) if total_rev > 0 else 0
                    bar_width = max(2, min(100, pct_of_total))
                    st.markdown(f'''<div style="margin:0.3rem 0;">
                        <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:0.2rem;">
                            <span style="color:rgba(255,255,255,0.6);">{strip_html(seg.get("name",""))}</span>
                            <span style="color:#fff;font-weight:600;">{fmt_c(sr, cur)}
                                <span style="color:{scolor};font-size:0.75rem;margin-left:0.3rem;">{sg*100:+.0f}%</span></span>
                        </div>
                        <div style="height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                            <div style="width:{bar_width}%;height:100%;background:{scolor};opacity:0.4;border-radius:2px;"></div>
                        </div>
                    </div>''', unsafe_allow_html=True)

            # Headwind/tailwind summary
            if hw_rev != 0 or tw_rev != 0:
                parts = []
                if hw_rev != 0: parts.append(f'<span style="color:#f87171;">Headwinds: {fmt_c(hw_rev, cur)} / {sym}{hw_eps:+.2f} EPS</span>')
                if tw_rev != 0: parts.append(f'<span style="color:#4ade80;">Tailwinds: {fmt_c(tw_rev, cur)} / {sym}{tw_eps:+.2f} EPS</span>')
                st.markdown(f'<div style="font-size:0.82rem;color:rgba(255,255,255,0.4);margin:1rem 0 0.5rem;padding:0.6rem 0;border-top:1px solid rgba(255,255,255,0.06);">{" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(parts)}</div>', unsafe_allow_html=True)

            # Narrative
            if narrative:
                st.markdown(f'<div style="font-size:0.92rem;color:rgba(255,255,255,0.6);line-height:1.8;font-style:italic;margin:0.8rem 0;padding:1rem;background:rgba(255,255,255,0.02);border-radius:6px;">{narrative}</div>', unsafe_allow_html=True)

            # Rationale details
            with st.expander("Valuation & margin rationale"):
                if margin_rat:
                    st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);line-height:1.7;margin-bottom:0.5rem;"><strong style="color:rgba(255,255,255,0.7);">Margin:</strong> {margin_rat}</div>', unsafe_allow_html=True)
                if pe_rat:
                    st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);line-height:1.7;"><strong style="color:rgba(255,255,255,0.7);">Valuation:</strong> {pe_rat}</div>', unsafe_allow_html=True)
                if bpe:
                    st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);margin-top:0.5rem;">Breakeven P/E: <strong style="color:#fff;">{bpe:.1f}x</strong></div>', unsafe_allow_html=True)
                if fcf_y:
                    st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);">FCF Yield at target: <strong style="color:#fff;">{fcf_y*100:.1f}%</strong></div>', unsafe_allow_html=True)
                if eps_flag:
                    st.markdown(f'<div style="font-size:0.82rem;color:#fbbf24;margin-top:0.5rem;font-style:italic;">{strip_html(eps_flag)}</div>', unsafe_allow_html=True)
        # Stats
        stats_parts = [
            f"Revenue: <strong>{fmt_c(total_rev, cur)}</strong> ({rev_g*100:+.1f}%)",
            f"EPS: <strong>{sym}{eps:.2f}</strong>", f"P/E: <strong>{pe:.1f}x</strong>",
            f"Op. Margin: <strong>{op_m*100:.1f}%</strong>",
        ]
        if bpe: stats_parts.append(f"<strong>Breakeven P/E: {bpe:.1f}x</strong>")
        if fcf_y: stats_parts.append(f"<strong>FCF Yield at Target: {fcf_y*100:.1f}%</strong>")
        stats_html = " &nbsp;/&nbsp; ".join(f'<span style="font-size:0.8rem;color:rgba(255,255,255,0.4);">{p}</span>' for p in stats_parts)
        st.markdown(f'<div style="padding:0.4rem 0 0.6rem;">{stats_html}</div>', unsafe_allow_html=True)

        # Segment builds
        seg_builds = s.get("segment_builds", [])
        if seg_builds:
            seg_lines = []
            for seg in seg_builds:
                sr = safe_float(seg.get("projected_revenue")); sg = safe_float(seg.get("growth_rate"))
                seg_lines.append(f'<div style="display:flex;justify-content:space-between;padding:0.2rem 0;font-size:0.82rem;"><span style="color:rgba(255,255,255,0.55);">{strip_html(seg.get("name",""))}</span><span style="color:#fff;font-weight:600;">{fmt_c(sr, cur)}<span style="color:{scolor};font-size:0.75rem;margin-left:0.4rem;">{sg*100:+.0f}%</span></span></div>')
            st.markdown(f'<div style="border-top:1px solid rgba(255,255,255,0.06);padding:0.6rem 0;margin:0.3rem 0;"><div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.3);margin-bottom:0.4rem;">Segment Revenue Builds</div>{"".join(seg_lines)}</div>', unsafe_allow_html=True)

        if hw_rev != 0 or tw_rev != 0:
            parts = []
            if hw_rev != 0: parts.append(f'Headwinds: <span style="color:#f87171;">{fmt_c(hw_rev, cur)} / {sym}{hw_eps:+.2f} EPS</span>')
            if tw_rev != 0: parts.append(f'Tailwinds: <span style="color:#4ade80;">{fmt_c(tw_rev, cur)} / {sym}{tw_eps:+.2f} EPS</span>')
            st.markdown(f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.4);margin:0.3rem 0;">{" &nbsp;|&nbsp; ".join(parts)}</div>', unsafe_allow_html=True)

        st.markdown(f'<div style="font-size:0.9rem;color:rgba(255,255,255,0.6);line-height:1.7;font-style:italic;margin:0.4rem 0;">{narrative}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:0.76rem;color:rgba(255,255,255,0.3);margin-top:0.3rem;">Margin: {margin_rat}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:0.76rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">Valuation: {pe_rat}</div>', unsafe_allow_html=True)
        if eps_flag:
            st.markdown(f'<div style="font-size:0.75rem;color:#fbbf24;margin-top:0.4rem;font-style:italic;">{strip_html(eps_flag)}</div>', unsafe_allow_html=True)
        st.markdown('<div style="height:0.8rem;"></div>', unsafe_allow_html=True)

    # Expected Value Bar
    ras = sm.get("risk_adjusted_score", 0); ud_ratio = sm.get("upside_downside_ratio", 0)
    mdd = sm.get("max_drawdown_magnitude", 0)*100; mdd_prob = sm.get("max_drawdown_prob", 0)*100
    rfr = sm.get("risk_free_rate", 0.06)*100; std_dev = sm.get("std_dev", 0)*100
    ras_color = "#4ade80" if ras > 1.0 else ("#fbbf24" if ras > 0.3 else "#f87171")
    ret_color = "positive" if exp_ret > 0.05 else ("neutral" if exp_ret > 0 else "negative")
    ud_display = "inf" if ud_ratio == float("inf") else f"{ud_ratio:.2f}x"
    ud_color = "#4ade80" if ud_ratio > 1.5 or ud_ratio == float("inf") else ("#fbbf24" if ud_ratio > 1.0 else "#f87171")

    st.markdown(f'''<div class="ev-bar">
        <div class="ev-item"><div class="ev-label">Expected Value</div><div class="ev-val">{sym}{ev:,.2f}</div></div>
        <div class="ev-item"><div class="ev-label">Expected Return</div><div class="ev-val {ret_color}">{exp_ret*100:+.1f}%</div></div>
        <div class="ev-item"><div class="ev-label">Std. Deviation</div><div class="ev-val">{std_dev:.1f}%</div></div>
        <div class="ev-item"><div class="ev-label">Risk-Adjusted Score</div><div class="ev-val" style="color:{ras_color};">{ras:.2f}</div><div style="font-size:0.65rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">vs {rfr:.0f}% risk-free</div></div>
        <div class="ev-item"><div class="ev-label">Up/Down Capture</div><div class="ev-val" style="color:{ud_color};">{ud_display}</div></div>
        <div class="ev-item"><div class="ev-label">Max Drawdown</div><div class="ev-val" style="color:#f87171;">{mdd:.1f}%</div><div style="font-size:0.65rem;color:rgba(255,255,255,0.3);margin-top:0.2rem;">{mdd_prob:.0f}% probability</div></div>
    </div>''', unsafe_allow_html=True)

    # Sensitivity Analysis
    sensitivity = sm.get("sensitivity", {})
    if sensitivity and sensitivity.get("dominant_driver"):
        driver_name = strip_html(sensitivity.get("dominant_driver", ""))
        current_p = safe_float(sensitivity.get("current_bull_probability"))*100
        ev_plus = safe_float(sensitivity.get("ev_if_bull_plus_10"))
        ev_minus = safe_float(sensitivity.get("ev_if_bull_minus_10"))
        interp = strip_html(sensitivity.get("interpretation", ""))
        st.markdown('<div class="sec">Sensitivity Analysis <span class="vtag">Dominant Driver</span></div>', unsafe_allow_html=True)
        st.markdown(f'''<div style="background:#141414;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:1.2rem 1.5rem;margin:0.8rem 0;">
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.55);margin-bottom:1rem;">What happens to the expected value if we change the bull probability on <strong style="color:#fff;">{driver_name}</strong>?</div>
            <div style="display:flex;justify-content:center;gap:2.5rem;">
            <div style="text-align:center;"><div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;margin-bottom:0.3rem;">Bull Prob -10pp ({current_p - 10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#f87171;">{sym}{ev_minus:,.2f}</div></div>
            <div style="text-align:center;"><div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.3);margin-bottom:0.3rem;">Current ({current_p:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#fff;">{sym}{ev:,.2f}</div></div>
            <div style="text-align:center;"><div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;margin-bottom:0.3rem;">Bull Prob +10pp ({current_p + 10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#4ade80;">{sym}{ev_plus:,.2f}</div></div></div>
            <div style="font-size:0.85rem;color:rgba(255,255,255,0.45);text-align:center;margin-top:1rem;line-height:1.6;font-style:italic;">{interp}</div></div>''', unsafe_allow_html=True)

    # Catalyst Calendar
    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">Catalyst Calendar</div>', unsafe_allow_html=True)
        cat_header = "<tr><th>Date</th><th>Event</th><th style='color:#4ade80;'>Positive Signal</th><th style='color:#f87171;'>Negative Signal</th></tr>"
        cat_rows = "".join(f'<tr><td style="font-weight:600;">{strip_html(c.get("date",""))}</td><td>{strip_html(c.get("event",""))}</td><td style="color:#4ade80;">{strip_html(c.get("positive_signal", c.get("bull_signal","")))}</td><td style="color:#f87171;">{strip_html(c.get("negative_signal", c.get("bear_signal","")))}</td></tr>' for c in catalysts)
        st.markdown(f'<table class="pt"><thead>{cat_header}</thead><tbody>{cat_rows}</tbody></table>', unsafe_allow_html=True)

    # Conclusion
    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["conclusion"])}</div>', unsafe_allow_html=True)

    # Report footer
    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")} &nbsp;/&nbsp;
        Math computed in Python (segment-level) &nbsp;/&nbsp; Report #{st.session_state.report_count}</div>''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# RENDER — TRACK BOX
# ══════════════════════════════════════════════════════════════

def render_track_box(ticker, m, a):
    rec = a.get("recommendation", "WATCH").upper()
    if rec not in ("BUY", "WATCH"):
        return
    company = m.get("company_name", ticker)
    cur = m.get("currency", "USD"); sym = get_sym(cur)
    try: cp = float(m.get("current_price")) if m.get("current_price") else 0.0
    except: cp = 0.0

    sm = a.get("scenario_math", {})
    base_scenario = sm.get("scenarios", {}).get("base", {})
    suggested_target = base_scenario.get("price_target", 0.0)
    try:
        if not suggested_target or float(suggested_target) == 0.0:
            suggested_target = round(cp * 1.15, 2)
        suggested_target = float(suggested_target)
    except: suggested_target = round(cp * 1.15, 2)

    rec_color = "#22c55e" if rec == "BUY" else "#f5c542"
    st.markdown(f'''<div class="track-box"><div class="track-box-title">Track this stock</div>
        <p style="color:rgba(255,255,255,0.45);font-size:0.9rem;line-height:1.65;margin:0 0 1rem;">
        Get an email when <strong style="color:#fff;">{strip_html(company)}</strong> hits your
        target price, with a live AI thesis check at that moment.
        Thesis target: <strong style="color:{rec_color};">{sym}{suggested_target:,.2f}</strong></p></div>''', unsafe_allow_html=True)

    with st.expander("Set up price alert", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            user_email = st.text_input("Your email", placeholder="you@example.com", key=f"track_email_{ticker}")
        with col2:
            target_price = st.number_input(f"Alert me when price reaches ({sym})", min_value=0.01, value=suggested_target, step=0.50, key=f"track_target_{ticker}")

        thesis_snapshot = strip_html(a.get("investment_thesis", ""))
        metrics_snapshot = {k: m.get(k) for k in ["trailing_pe", "forward_pe", "peg_ratio", "operating_margin", "roe", "revenue_growth", "revenue_cagr", "fcf_yield", "debt_to_equity", "ev_to_ebitda"]}

        if st.button("Start Tracking", key=f"track_btn_{ticker}", type="primary"):
            if not user_email or "@" not in user_email:
                st.error("Please enter a valid email address.")
            elif not GMAIL_SENDER or not GMAIL_APP_PASS:
                st.warning("Email not configured. Add GMAIL_SENDER and GMAIL_APP_PASS to secrets.")
            else:
                gh_ok, gh_err = add_tracked_stock(ticker, company, rec, target_price, cp, metrics_snapshot, thesis_snapshot, user_email)
                ok, err = email_confirmation(user_email, ticker, company, rec, f"{sym}{target_price:,.2f}", f"{sym}{cp:,.2f}")
                if gh_ok and ok:
                    st.session_state.track_success = ("green", f"Tracking live! Confirmation sent to {user_email}")
                elif gh_ok and not ok:
                    st.session_state.track_success = ("green", f"Tracking live! (Email failed: {err})")
                elif not gh_ok and ok:
                    st.session_state.track_success = ("yellow", f"Email sent but GitHub save failed: {gh_err}")
                else:
                    st.session_state.track_success = ("red", f"Both failed. GitHub: {gh_err} | Email: {err}")

        if st.session_state.track_success:
            colour, msg = st.session_state.track_success
            bg = {"green": "rgba(74,222,128,0.1)", "yellow": "rgba(251,191,36,0.1)", "red": "rgba(248,113,113,0.1)"}.get(colour, "rgba(74,222,128,0.1)")
            border = {"green": "rgba(74,222,128,0.3)", "yellow": "rgba(251,191,36,0.3)", "red": "rgba(248,113,113,0.3)"}.get(colour)
            text_c = {"green": "#4ade80", "yellow": "#fbbf24", "red": "#f87171"}.get(colour)
            st.markdown(f'<div style="background:{bg};border:1px solid {border};border-radius:6px;padding:0.8rem 1.2rem;font-size:0.88rem;color:{text_c};margin-top:0.8rem;line-height:1.5;">{msg}</div>', unsafe_allow_html=True)
            st.session_state.track_success = None

        st.markdown('<div class="track-note">Your email is only used for price alerts. Never shared.</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# MAIN UI
# ══════════════════════════════════════════════════════════════

st.markdown('''<div class="hero">
    <h1><span class="pick">Pick</span><span class="accent">R</span></h1>
    <div class="tag">AI Assisted Equity Research</div>
    <div class="desc">Equity analysis powered by the Quality Growth Longevity Price (QGLP) framework. Bottoms up EPS projections with quantified headwinds, probability assigned scenarios, and AI-assised insights.</div>
</div>''', unsafe_allow_html=True)

# QGLP Top Picks
@st.cache_data(ttl=3600, show_spinner=False)
def load_screener_results():
    from config import GITHUB_TOKEN, GITHUB_REPO
    import urllib.request, json, base64
    
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/screener_results.json"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return json.loads(base64.b64decode(data["content"]).decode())
        except Exception:
            pass
    return None

def render_picks_table(picks, market_label, select_key):
    if not picks: return
    st.markdown(f'<div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.25);margin:0.8rem 0 0.4rem;">{market_label}</div>', unsafe_allow_html=True)
    header = "<tr><th>Ticker</th><th>Company</th><th>Score</th><th>PEG</th><th>ROE</th><th>Earnings CAGR</th><th>FCF Yield</th><th>D/E</th></tr>"
    rows = ""
    for pick in picks:
        score = pick.get("qglp_score", 0)
        sc = "#4ade80" if score >= 85 else ("#fbbf24" if score >= 70 else "#f87171")
        roe = pick.get("roe", 0); cagr = pick.get("earnings_cagr", 0)
        cagr_yrs = pick.get("earnings_cagr_years", 0); fcf = pick.get("fcf_yield")
        de = pick.get("debt_equity", 0); peg = pick.get("peg_ratio", "-")
        tk = pick.get("ticker", ""); name = pick.get("name", tk)
        rows += f'<tr><td style="font-weight:700;color:#fff;">{tk.replace(".NS","")}</td><td style="color:rgba(255,255,255,0.55);font-size:0.82rem;">{name[:25]}</td><td style="color:{sc};font-weight:800;">{score}</td><td style="font-weight:600;">{peg}</td><td>{roe*100:.1f}%</td><td>{cagr*100:.1f}% <span style="font-size:0.6rem;color:rgba(255,255,255,0.2);">({cagr_yrs}Y)</span></td><td>{f"{fcf*100:.1f}%" if fcf else "-"}</td><td>{de:.2f}</td></tr>'
    st.markdown(f'<table class="pt"><thead>{header}</thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
    ticker_options = [""] + [p.get("ticker", "") for p in picks]
    display_options = ["Select a ticker to analyze..."] + [f"{p.get('ticker','').replace('.NS','')} - {p.get('name','')[:25]}" for p in picks]
    sel = st.selectbox("Analyze", display_options, label_visibility="collapsed", key=select_key)
    if sel and sel != "Select a ticker to analyze...":
        idx = display_options.index(sel)
        chosen = ticker_options[idx]
        if chosen:
            st.session_state["resolved"] = chosen
            st.session_state["auto_generate"] = True

screener_data = None
try:
    screener_data = load_screener_results()
except Exception as e:
    st.error(f"Screener load error: {e}")

if screener_data:
    last_updated = screener_data.get("last_updated", "")
    st.markdown(f'''<div style="padding:1.5rem 0 0.5rem;"><div style="display:flex;justify-content:space-between;align-items:baseline;">
        <div style="font-size:0.9rem;font-weight:900;text-transform:uppercase;letter-spacing:0.18em;color:rgba(255,255,255,0.18);">QGLP Top Picks</div>
        <div style="font-size:0.9rem;color:rgba(255,255,255,0.15);">Updated {last_updated}</div></div></div>''', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;color:rgba(255,255,255,0.35);text-align:center;margin-bottom:1.2rem;">Select any ticker from the tables below to generate a full report, or search for a stock below the tables.</div>', unsafe_allow_html=True)
    render_picks_table(screener_data.get("us_picks", [])[:5], "United States", "us_pick_select")
    render_picks_table(screener_data.get("india_picks", [])[:5], "India", "india_pick_select")

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
    with l1: st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Search by company name</div>', unsafe_allow_html=True)
    with l2: st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Popular stocks</div>', unsafe_allow_html=True)

    s_col1, s_col2 = st.columns([3, 2])
    with s_col1:
        sq = st.text_input("Search by name", placeholder="e.g. Apple, Reliance, Broadcom", label_visibility="collapsed", key="s1")
        if sq and len(sq) >= 2:
            res = search_ticker(sq)
            if res:
                opts = {f"{r['name']} ({r['symbol']})": r['symbol'] for r in res}
                sel = st.selectbox("Pick result", opts.keys(), label_visibility="collapsed", key="s2")
                if sel: st.session_state["resolved"] = opts[sel]
            else: st.caption("No results. Try the ticker box below.")
    with s_col2:
        sp = st.selectbox("Popular", POPULAR.keys(), label_visibility="collapsed", key="s3")
        if sp and POPULAR[sp]: st.session_state["resolved"] = POPULAR[sp]

    tl1, tl2 = st.columns([3, 2])
    with tl1: st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Enter ticker directly</div>', unsafe_allow_html=True)
    with tl2:
        if recent_list: st.markdown('<div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Recent searches</div>', unsafe_allow_html=True)

    t_col1, t_col2 = st.columns([3, 2])
    with t_col1:
        td = st.text_input("Enter ticker directly", placeholder="e.g. AVGO, AAPL, RELIANCE.NS", label_visibility="collapsed", key="s4")
        if td: st.session_state["resolved"] = td.strip().upper()
    with t_col2:
        if recent_list:
            sr = st.selectbox("Recent", ["-- recent --"] + list(reversed(recent_list)), label_visibility="collapsed", key="s_recent")
            if sr and sr != "-- recent --": st.session_state["resolved"] = sr
        else: st.markdown("<div style='height:2.3rem'></div>", unsafe_allow_html=True)

    resolved_now = st.session_state.get("resolved")
    if resolved_now:
        st.markdown(f'<div style="text-align:center;font-size:0.78rem;color:rgba(255,255,255,0.45);padding:0.4rem 0 0.1rem;font-weight:600;letter-spacing:0.04em;">Selected: <span style="color:#ffffff;">{resolved_now}</span></div>', unsafe_allow_html=True)

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    go = st.button("Generate Report", type="primary")

status_area = st.container()

with st.expander("About the QGLP Framework", expanded=False):
    st.markdown('''<div class="thesis-section" style="margin:0;"><div class="thesis-title">Quality-Growth-Longevity-Price</div><div class="thesis-grid">
        <div class="thesis-card"><div class="thesis-card-letter">Q</div><div class="thesis-card-name">Quality</div><div class="thesis-card-desc">Durable moats, ROE/ROCE above 15%, strong FCF, clean management. Debt/Equity below 1.0.</div></div>
        <div class="thesis-card"><div class="thesis-card-letter">G</div><div class="thesis-card-name">Growth</div><div class="thesis-card-desc">Earnings CAGR above 12%. Revenue and EPS trajectory assessed by segment. TAM expanding at 2x+ GDP.</div></div>
        <div class="thesis-card"><div class="thesis-card-letter">L</div><div class="thesis-card-name">Longevity</div><div class="thesis-card-desc">Competitive advantages persist 5+ years. Market share stability, succession depth, regulatory durability.</div></div>
        <div class="thesis-card"><div class="thesis-card-letter">P</div><div class="thesis-card-name">Price</div><div class="thesis-card-desc">PEG below 1.2x is target. Below 1.0x is exceptional. Above 1.4x requires documented rationale.</div></div>
    </div></div>''', unsafe_allow_html=True)

report_area = st.container()

# ══════════════════════════════════════════════════════════════
# GENERATION LOGIC
# ══════════════════════════════════════════════════════════════

should_generate = False
ticker = None
resolved = st.session_state.get("resolved", None)
auto_gen = st.session_state.pop("auto_generate", False)

if (go or auto_gen) and resolved:
    ticker = resolved.strip().upper()
    should_generate = True
elif go and not resolved:
    with status_area: st.warning("Select or enter a company first.")

if should_generate and ticker:
    if ticker not in st.session_state.recent:
        st.session_state.recent.append(ticker)
    st.session_state.report_count += 1
    st.session_state.cached_html = None
    st.session_state.generate_html = False
    st.session_state.html_just_generated = False

    with status_area:
        with st.status(f"Analyzing {ticker}...", expanded=True) as status:
            st.write(f"Fetching data for **{ticker}**...")
            st.caption("Pulling real-time price, fundamentals, financials, and 5-year history")
            try: sd = fetch(ticker)
            except Exception as e: st.error(f"Failed to fetch data: {e}"); st.stop()
            info = sd.get("info", {})
            if isinstance(info, dict) and info.get("error"):
                st.error(f"Ticker '{ticker}' not found or unavailable."); st.stop()
            company_name = info.get("shortName", info.get("longName", ticker))
            data_source = info.get('_source', 'yfinance')
            st.write(f"Loaded **{company_name}** (via {data_source})")

            st.write("Computing 24 verified financial metrics...")
            st.caption("Revenue CAGR, margins, ROE/ROA, FCF yield, valuation ratios, debt metrics")
            m = calc(sd)
            if "error" in m: st.error(m["error"]); st.stop()

            st.write("Pass 1: Getting structured assumptions from AI...")
            st.caption("Macro drivers, scenario assumptions, headwinds, tailwinds, risks, catalysts")

            st.write("Computing scenario math and getting narrative from AI...")
            st.caption("Price targets, probabilities, expected value, then writing report consistent with math")

            a = run_analysis(ticker, m)
            if isinstance(a, dict) and a.get("error"):
                status.update(label="Analysis failed", state="error")
                for d in a.get("details", []): st.code(d)
                st.stop()

            rec = a.get("recommendation", "WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state.cached_report = {"ticker": ticker, "metrics": m, "analysis": a, "data": sd}
        # Save report to user history
    try:
        from report_store import save_report
        save_report(username, ticker, m, a)
    except Exception as e:
        print(f"Report save failed (non-blocking): {e}")

# ══════════════════════════════════════════════════════════════
# RENDER FROM CACHE
# ══════════════════════════════════════════════════════════════

if st.session_state.cached_report:
    cached = st.session_state.cached_report
    c_ticker = cached["ticker"]; c_m = cached["metrics"]; c_a = cached["analysis"]; c_data = cached["data"]

    with report_area:
        render(c_ticker, c_m, c_a, c_data)
        render_track_box(c_ticker, c_m, c_a)

        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('''<div style="text-align:center;padding:1rem 0 0.5rem;"><div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div></div>''', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)
        with dl1:
            sm = c_a.get("scenario_math", {}); scenarios = sm.get("scenarios", {})
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
                    f"EPS: ${s.get('projected_eps',0):.2f} | P/E: {s.get('pe_multiple',0):.1f}x",
                    strip_html(s.get("narrative", "")), "",
                ]
            md_lines += ["---", "", f"Expected Value: ${sm.get('expected_value',0):,.2f}",
                f"Risk-Adjusted Score: {sm.get('risk_adjusted_score',0):.2f}",
                f"Probability of Positive Return: {sm.get('prob_positive_return',0)*100:.0f}%", "",
                "## Conclusion", "", strip_html(c_a.get("conclusion", "")),
                "", f"*PickR / {datetime.now().strftime('%B %d, %Y')}*"]
            st.download_button("Download (Markdown)", "\n".join(md_lines), f"PickR_{c_ticker}.md", "text/markdown")

        with dl2:
            export_data = {
                "ticker": c_ticker, "date": datetime.now().strftime("%Y-%m-%d"),
                "recommendation": c_a.get("recommendation"), "conviction": c_a.get("conviction"),
                "expected_value": sm.get("expected_value"), "expected_return": sm.get("expected_return"),
                "risk_adjusted_score": sm.get("risk_adjusted_score"), "prob_positive": sm.get("prob_positive_return"),
                "scenarios": sm.get("scenarios"),
                "metrics": {k: v for k, v in c_m.items() if k not in ["description", "news", "revenue_history", "net_income_history"]},
            }
            st.download_button("Download (JSON)", json.dumps(export_data, indent=2, default=str), f"PickR_{c_ticker}.json", "application/json")

# Footer
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