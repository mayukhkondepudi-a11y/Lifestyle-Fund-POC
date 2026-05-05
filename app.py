"""PickR - Streamlit UI and rendering."""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import os
from datetime import datetime
import json

st.set_page_config(page_title="PickR", page_icon="P", layout="wide", initial_sidebar_state="collapsed")

# ── Hide Streamlit toolbar/ellipsis via JS ──
# FIX: Removed 'header' and '[data-testid="stHeader"]' from hide list
#      so the sidebar toggle button remains accessible.
import streamlit.components.v1 as _sc
_sc.html("""
<script>
(function(){
    function hide(){
        var p = window.parent.document;
        var sel = [
            '[data-testid="stToolbar"]',
            '[data-testid="stDecoration"]',
            '[data-testid="stToolbarActions"]',
            '[data-testid="stAppDeployButton"]',
            '#MainMenu'
        ];
        sel.forEach(function(s){
            p.querySelectorAll(s).forEach(function(el){
                el.style.setProperty('display','none','important');
                el.style.setProperty('visibility','hidden','important');
                el.style.setProperty('height','0','important');
                el.style.setProperty('overflow','hidden','important');
            });
        });
        // FIX: Force sidebar toggle to always be visible
        var toggle = p.querySelectorAll(
            '[data-testid="stSidebarCollapsedControl"], ' +
            '[data-testid="collapsedControl"], ' +
            'button[aria-label="Open sidebar"], ' +
            'button[aria-label="Close sidebar"]'
        );
        toggle.forEach(function(el){
            el.style.setProperty('display','flex','important');
            el.style.setProperty('visibility','visible','important');
            el.style.setProperty('height','auto','important');
            el.style.setProperty('overflow','visible','important');
            el.style.setProperty('opacity','1','important');
            el.style.setProperty('z-index','99999','important');
        });
    }
    hide();
    setTimeout(hide, 300);
    setTimeout(hide, 800);
    setTimeout(hide, 1500);
    var obs = new MutationObserver(hide);
    obs.observe(window.parent.document.body, {childList:true, subtree:true});
})();
</script>
""", height=0, scrolling=False)


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
from logos import get_logo_html, get_logo_and_name_html

# ── Session State ─────────────────────────────────────────────
for key, default in [
    ("report_count", 0), ("recent", []), ("cached_report", None),
    ("cached_html", None), ("trigger_ticker", None),
    ("generate_html", False), ("html_just_generated", False),
    ("track_success", None), ("_generating", False),
    ("_scroll_to_report", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ══════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

    /* ── BASE ── */
    html, body, .stApp {
        background: linear-gradient(180deg, #0f0f13 0%, #14141a 100%) !important;
        color: rgba(255,255,255,0.92) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 17px !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .block-container {
        padding-top: 0 !important;
        max-width: 1400px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        background: transparent !important;
    }
    .stApp > div,
    [data-testid="stAppViewContainer"] {
        background: transparent !important;
    }

    /* FIX: Only hide specific toolbar elements, NOT the entire header.
       This preserves the sidebar toggle button. */
    [data-testid="stToolbar"],
    [data-testid="stToolbarActions"],
    [data-testid="stToolbarActionButtonContainer"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    [data-testid="stAppDeployButton"],
    button[data-testid="baseButton-header"],
    button[data-testid="baseButton-minimal"],
    #MainMenu, #MainMenu > ul, footer,
    .reportview-container .main footer {
        display:    none       !important;
        visibility: hidden     !important;
        height:     0px        !important;
        max-height: 0px        !important;
        overflow:   hidden     !important;
        padding:    0          !important;
        margin:     0          !important;
    }

    /* FIX: Make header transparent but keep it in layout for sidebar toggle */
    header, .stAppHeader, [data-testid="stHeader"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }

    /* FIX: Sidebar toggle — always visible and clickable */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"],
    button[aria-label="Open sidebar"],
    button[aria-label="Close sidebar"] {
        display:    flex       !important;
        visibility: visible    !important;
        height:     auto       !important;
        overflow:   visible    !important;
        opacity:    1          !important;
        z-index:    99999      !important;
        position:   relative   !important;
    }

    /* ── STICKY LOGO ── */
    .pickr-logo-sticky {
        top: 1.1rem;
        left: 1.6rem;
        transform: scale(1.25);
        opacity: 0.95;
    }
    .pickr-logo-sticky .wordmark {
        font-size: 1.4rem;
        font-weight: 900;
        letter-spacing: -0.015em;
    }

    /* ── HERO ── */
    .hero {
        padding: 4rem 2rem 1.5rem;
        text-align: center;
        position: relative;
        animation: fadeInUp 0.6s ease-out;
        background: radial-gradient(ellipse 80% 40% at 50% 0%, rgba(139,26,26,0.07) 0%, transparent 70%);
    }
    .hero::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 50%;
        transform: translateX(-50%);
        width: 60px;
        height: 2px;
        background: linear-gradient(90deg, transparent, #8b1a1a, transparent);
    }
    .hero h1 { font-size: 4.2rem; font-weight: 900; letter-spacing: -0.03em; margin: 0; }
    .hero h1 .pick {
        background: linear-gradient(180deg, #ffffff 0%, #ffffff 35%, #e0e0e0 55%, #c8c8c8 75%, #e8e8e8 100%);
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
    .hero .tag  { color: rgba(255,255,255,0.7); }
    .hero .desc { color: rgba(255,255,255,0.65); }

    /* ── STATS ROW ── */
    .stats-row {
        display: flex;
        justify-content: center;
        gap: 3rem;
        padding: 1.3rem 0;
        margin-top: 1.5rem;
        border-top: 1px solid rgba(255,255,255,0.05);
        border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .sr-item { text-align: center; }
    .sr-num  { font-size: 1.6rem; font-weight: 800; color: #fff; display: block; }
    .sr-lbl  { font-size: 0.65rem; color: rgba(255,255,255,0.6); text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; }

    /* ── HOW IT WORKS ── */
    .hiw { padding: 2rem 0 1rem; }
    .hiw-title { text-align: center; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.18em; color: rgba(255,255,255,0.5); margin-bottom: 1.2rem; }
    .hiw-grid { display: flex; justify-content: center; gap: 1.5rem; }
    .hiw-card { background: #1a1a22; border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; padding: 1.3rem; text-align: center; flex: 1; max-width: 260px; }
    .hiw-step { font-size: 0.6rem; font-weight: 800; color: #8b1a1a; text-transform: uppercase; letter-spacing: 0.16em; margin-bottom: 0.4rem; }
    .hiw-title2 { font-size: 1.1rem; font-weight: 700; color: #fff; margin-bottom: 0.3rem; }
    .hiw-desc { font-size: 0.97rem; color: rgba(255,255,255,0.55); line-height: 1.7; }

    /* ── QGLP THESIS ── */
    .thesis-section {
        background: linear-gradient(135deg, rgba(25,20,35,0.85) 0%, rgba(18,16,28,0.95) 100%);
        border: 1px solid rgba(139,80,50,0.2);
        border-radius: 8px;
        padding: 2rem;
        margin: 1.5rem 0;
    }
    .thesis-title { font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.16em; color: rgba(255,255,255,0.6); margin-bottom: 1rem; }
    .thesis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
    .thesis-card { background: rgba(20,18,30,0.7); border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; padding: 1rem 1.2rem; transition: all 0.2s ease; }
    .thesis-card:hover { border-color: rgba(255,255,255,0.12); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
    .thesis-card-letter { font-size: 1.4rem; font-weight: 800; color: #8b1a1a; margin-bottom: 0.2rem; }
    .thesis-card-name   { font-size: 0.95rem; font-weight: 700; color: #ffffff; margin-bottom: 0.3rem; }
    .thesis-card-desc   { font-size: 0.92rem; color: rgba(255,255,255,0.6); line-height: 1.7; }
    .thesis-scoring { margin-top: 1.2rem; padding-top: 1rem; border-top: 1px solid rgba(255,255,255,0.05); }
    .thesis-scoring-title { font-size: 0.72rem; font-weight: 700; color: rgba(255,255,255,0.35); margin-bottom: 0.6rem; }
    .scoring-row { display: flex; gap: 1.5rem; }
    .scoring-item { text-align: center; flex: 1; }
    .scoring-range { font-size: 1.15rem; font-weight: 700; }
    .scoring-range.buy   { color: #22c55e; }
    .scoring-range.watch { color: #f5c542; }
    .scoring-range.pass  { color: #ff4d4d; }
    .scoring-label { font-size: 0.62rem; color: rgba(255,255,255,0.35); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }

    /* ── PARAMS CARD ── */
    .params-card { background: #111118; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.5rem; }
    .params-row { display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 0.9rem; }
    .params-row:last-child { border-bottom: none; }
    .params-key { color: rgba(255,255,255,0.6); font-weight: 500; }
    .params-val { color: rgba(255,255,255,0.95); font-weight: 600; }

    /* ── REPORT CARD ── */
    .rpt-card {
        background: #16161e;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        border-top: 1px solid rgba(74,222,128,0.12);
        padding: 2rem 2.5rem;
        margin-top: 1rem;
        animation: fadeInUp 0.4s ease-out;
    }
    .rpt-head h2 { font-size: 2.4rem; font-weight: 800; color: #ffffff; margin: 0; letter-spacing: -0.02em; }
    .rpt-head .meta { color: rgba(255,255,255,0.55); font-size: 0.97rem; letter-spacing: 0.04em; margin-top: 0.4rem; font-weight: 500; }

    /* ── RECOMMENDATION BAR ── */
    .rec-bar {
        display: flex;
        justify-content: center;
        gap: 3.5rem;
        padding: 1.5rem 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 0.5rem;
        background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%);
        border-radius: 8px;
        animation: fadeInUp 0.5s ease-out;
    }
    .rb-item { text-align: center; }
    .rb-label { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: rgba(255,255,255,0.72); margin-bottom: 0.3rem; }
    .rb-val { font-size: 1.8rem; font-weight: 800; }
    .rb-val.buy   { color: #4ade80; }
    .rb-val.watch { color: #fbbf24; }
    .rb-val.pass  { color: #f87171; }

    /* ── EXECUTIVE SUMMARY ── */
    .exec-summary {
        background: linear-gradient(135deg, rgba(35,50,45,0.3) 0%, rgba(25,28,37,1) 100%);
        border-left: 3px solid rgba(74,222,128,0.4);
        border-radius: 0 8px 8px 0;
        padding: 1.4rem 1.8rem;
        margin: 1.2rem 0;
        font-size: 1.05rem;
        line-height: 2;
        color: rgba(255,255,255,0.82);
        font-style: italic;
    }

    /* ── SECTION HEADERS ── */
    .sec {
        font-size: 0.86rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: rgba(255,255,255,0.85);
        margin: 3rem 0 1.2rem;
        padding-bottom: 0.6rem;
        border-bottom: 2px solid rgba(255,255,255,0.12);
        display: block;
    }

    /* ── METRICS ── */
    [data-testid="stMetricLabel"] {
        color: rgba(255,255,255,0.75) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
        font-weight: 700 !important;
        color: rgba(255,255,255,0.95) !important;
        font-feature-settings: "tnum","ss01" !important;
        letter-spacing: 0.01em !important;
    }
    [data-testid="stMetricDelta"] { display: none !important; }

    /* ── 52-WEEK RANGE BAR ── */
    .range-bar-container { margin: 0.8rem 0 1.5rem; }
    .range-bar-labels { display: flex; justify-content: space-between; font-size: 0.82rem; color: rgba(255,255,255,0.7); margin-bottom: 0.4rem; font-weight: 600; }
    .range-bar { height: 7px; background: rgba(255,255,255,0.1); border-radius: 4px; position: relative; }
    .range-bar-fill { height: 100%; background: linear-gradient(90deg,#8b1a1a,#e03030); border-radius: 4px; }
    .range-bar-dot { width: 12px; height: 12px; background: #fff; border-radius: 50%; position: absolute; top: -2.5px; transform: translateX(-50%); box-shadow: 0 0 8px rgba(224,48,48,0.8); }

    /* ── PROSE / BODY TEXT ── */
    .prose { color: rgba(255,255,255,0.90); line-height: 1.85; }

    /* ── RISK ROWS ── */
    .risk-row { padding: 0.75rem 0; border-bottom: 1px solid rgba(255,255,255,0.07); font-size: 0.95rem; line-height: 1.85; color: rgba(255,255,255,0.82); }
    .risk-row:last-child { border-bottom: none; }

    /* ── BULL / BEAR BOXES ── */
    .cb { padding: 1.2rem 1.5rem; border-radius: 8px; font-size: 0.95rem; line-height: 1.85; color: rgba(255,255,255,0.82); }
    .cb-bull { background: rgba(74,222,128,0.08); border: 1px solid rgba(74,222,128,0.28); }
    .cb-bear { background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.25); }
    .cb-title { font-size: 0.65rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.14em; margin-bottom: 0.5rem; }
    .cb-bull .cb-title { color: #4ade80; }
    .cb-bear .cb-title { color: #f87171; }

    /* ── TABLES ── */
    .pt { width: 100%; border-collapse: collapse; font-size: 0.97rem; }
    .pt th {
        text-align: left;
        font-size: 0.67rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 0.7rem 0.85rem;
        border-bottom: 2px solid rgba(74,222,128,0.25);
        background: linear-gradient(135deg, rgba(100,20,20,0.4) 0%, rgba(25,20,35,0.95) 100%);
        color: rgba(255,255,255,0.85) !important;
    }
    .pt td { color: rgba(255,255,255,0.85); padding: 0.6rem 0.85rem; }
    .pt tr.hl td { font-weight: 700; color: #ffffff; background: rgba(224,48,48,0.12); }
    .pt tbody tr:nth-child(even) td { background: rgba(255,255,255,0.025); }
    .pt tbody tr:nth-child(odd)  td { background: transparent; }
    .pt tbody tr:hover td { background: rgba(255,255,255,0.05); }

    /* ── VTAG ── */
    .vtag { display: inline-block; font-size: 0.52rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #e03030; border: 1px solid rgba(224,48,48,0.4); padding: 0.06rem 0.3rem; border-radius: 2px; margin-left: 0.4rem; vertical-align: middle; }

    /* ── DIVIDER ── */
    .div { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 1rem 0; }

    /* ── TRACK BOX ── */
    .track-box { background: #16161e; border: 1px solid rgba(224,48,48,0.3); border-radius: 8px; padding: 1.5rem 2rem; margin-top: 1.5rem; }
    .track-box-title { font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.16em; color: #e03030; margin-bottom: 0.6rem; }
    .track-success { background: rgba(74,222,128,0.1); border: 1px solid rgba(74,222,128,0.3); border-radius: 6px; padding: 0.8rem 1.2rem; font-size: 0.9rem; color: #4ade80; margin-top: 0.8rem; }
    .track-note { font-size: 0.85rem; color: rgba(255,255,255,0.55); margin-top: 0.6rem; line-height: 1.6; }

    /* ── STICKY LOGO (fixed) ── */
    .pickr-logo-sticky {
        position: fixed;
        top: 0.85rem;
        left: 1.2rem;
        z-index: 9999;
        display: flex;
        align-items: center;
        gap: 0.45rem;
        pointer-events: none;
    }
    .pickr-logo-sticky .wm-pick {
        background: linear-gradient(180deg,#fff 0%,#e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 1.05rem;
        font-weight: 900;
        letter-spacing: -0.02em;
    }
    .pickr-logo-sticky .wm-accent {
        background: linear-gradient(135deg,#a52525,#e04040 40%,#ff8a8a 60%,#a52525);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 1.05rem;
        font-weight: 900;
        letter-spacing: -0.02em;
    }

    /* ── FOOTER ── */
    .foot-card { background: #16161e; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 1.5rem 2rem; margin-top: 2rem; text-align: center; }
    .foot-name { font-size: 1rem; font-weight: 600; color: rgba(255,255,255,0.8); }
    .foot-email { font-size: 0.85rem; color: rgba(255,255,255,0.5); margin-top: 0.2rem; }
    .foot-disclaimer { font-size: 0.8rem; color: rgba(255,255,255,0.55); margin-top: 1rem; line-height: 1.75; max-width: 700px; margin-left: auto; margin-right: auto; }
    .foot-copy { font-size: 0.7rem; color: rgba(255,255,255,0.38); margin-top: 0.8rem; }
    .foot-email a { color: #e08070 !important; text-decoration: none; border-bottom: 1px solid rgba(224,128,112,0.35); }
    .foot-email a:hover { color: #ffb8a8 !important; border-bottom-color: rgba(255,184,168,0.6); }

    /* ── DRIVER CARDS ── */
    .driver-card { background: #111118; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 1rem 1.2rem; margin: 0.5rem 0; transition: all 0.2s ease; }
    .driver-card:hover { border-color: rgba(255,255,255,0.12); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
    .driver-card-name { font-weight: 700; color: #fff; font-size: 0.98rem; margin-bottom: 0.3rem; }
    .driver-card-desc { font-size: 0.92rem; color: rgba(255,255,255,0.70); margin-bottom: 0.8rem; line-height: 1.7; }

    /* ── HEADWIND / TAILWIND CARDS ── */
    .hw-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin: 0.8rem 0 1.2rem; }
    .hw-card { background: #111118; border: 1px solid rgba(248,113,113,0.2); border-radius: 8px; padding: 1rem 1.2rem; }
    .tw-card { background: #111118; border: 1px solid rgba(74,222,128,0.2);  border-radius: 8px; padding: 1rem 1.2rem; }
    .hw-card-title { font-size: 0.78rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.1em; color: #f87171; margin-bottom: 0.3rem; }
    .tw-card-title { font-size: 0.78rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.1em; color: #4ade80; margin-bottom: 0.3rem; }
    .hw-card-desc  { font-size: 0.95rem; color: rgba(255,255,255,0.72); line-height: 1.65; margin-bottom: 0.6rem; }
    .hw-prob-badge { display: inline-block; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; padding: 0.15rem 0.4rem; border-radius: 3px; background: rgba(248,113,113,0.15); color: #f87171; border: 1px solid rgba(248,113,113,0.3); margin-bottom: 0.4rem; }
    .tw-prob-badge { display: inline-block; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; padding: 0.15rem 0.4rem; border-radius: 3px; background: rgba(74,222,128,0.1);  color: #4ade80; border: 1px solid rgba(74,222,128,0.25);  margin-bottom: 0.4rem; }

    /* ── SCENARIO CARDS ── */
    .scenario-card { background: #16161e; border-radius: 8px; padding: 1.2rem 1.5rem; margin: 0.8rem 0; transition: all 0.2s ease; }
    .scenario-card:hover { border-color: rgba(255,255,255,0.12); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }

    /* ── EXPECTED VALUE BAR ── */
    .ev-bar {
        display: flex;
        justify-content: center;
        gap: 2.5rem;
        background: linear-gradient(180deg, rgba(14,14,20,1) 0%, rgba(18,18,26,1) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 1.2rem 1.5rem;
        margin: 1rem 0;
        flex-wrap: wrap;
        animation: fadeInUp 0.5s ease-out;
    }
    .ev-item { text-align: center; }
    .ev-label { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: rgba(255,255,255,0.62); margin-bottom: 0.3rem; }
    .ev-val { font-size: 1.3rem; font-weight: 800; color: #fff; }
    .ev-val.positive { color: #4ade80; }
    .ev-val.negative { color: #f87171; }
    .ev-val.neutral  { color: #fbbf24; }

    /* ── CALLOUTS ── */
    .plain-callout { background: rgba(139,26,26,0.14); border-left: 3px solid #8b1a1a; border-radius: 0 6px 6px 0; padding: 1rem 1.4rem; margin: 0.8rem 0; font-size: 0.92rem; color: rgba(255,255,255,0.7); line-height: 1.8; }
    .plain-callout-label { font-size: 0.64rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.14em; color: #d44040; margin-bottom: 0.4rem; }

    /* ── PROBABILITY EXPLAINER ── */
    .prob-explainer { background: #111118; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 1.4rem 1.6rem; margin: 1rem 0; font-size: 0.9rem; color: rgba(255,255,255,0.6); line-height: 1.8; }
    .prob-explainer strong { color: rgba(255,255,255,0.95); }
    .prob-math-row   { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin: 0.6rem 0; font-size: 0.85rem; }
    .prob-math-chip  { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; padding: 0.25rem 0.6rem; color: #e0e0e0; font-weight: 600; }
    .prob-math-chip.bull { border-color: rgba(74,222,128,0.4);  color: #4ade80; background: rgba(74,222,128,0.06); }
    .prob-math-chip.bear { border-color: rgba(248,113,113,0.4); color: #f87171; background: rgba(248,113,113,0.06); }
    .prob-math-chip.base { border-color: rgba(251,191,36,0.4);  color: #fbbf24; background: rgba(251,191,36,0.06); }
    .prob-math-arrow { color: rgba(255,255,255,0.35); font-size: 0.9rem; }

    /* ── FORM INPUTS ── */
    .stTextInput > div > div > input {
        background: #0e0e14 !important;
        border: 1px solid rgba(255,255,255,0.18) !important;
        border-radius: 6px !important;
        color: #fff !important;
        font-size: 1rem !important;
        padding: 0.6rem 1rem !important;
        caret-color: #fff !important;
    }
    .stTextInput > div > div > input:focus { border-color: #8b1a1a !important; box-shadow: 0 0 0 2px rgba(139,26,26,0.2) !important; }
    .stTextInput > div > div > input::placeholder { color: rgba(255,255,255,0.4) !important; }
    .stSelectbox > div > div { background: #0e0e14 !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 6px !important; color: #fff !important; }
    .stSelectbox > div > div > div { color: #fff !important; }
    .stSelectbox svg { fill: rgba(255,255,255,0.5) !important; }
    .stNumberInput > div > div > input { background: #0e0e14 !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 6px !important; color: #fff !important; }

    /* ── STATUS / ALERTS ── */
    [data-testid="stStatusWidget"], .stAlert, .stStatus { background: #12121a !important; border: 1px solid rgba(255,255,255,0.08) !important; color: #e8e8e8 !important; border-radius: 6px !important; }
    [data-testid="stStatusWidget"] p, [data-testid="stStatusWidget"] span, [data-testid="stStatusWidget"] div { color: #e8e8e8 !important; }
    .stWarning, .stError, .stInfo { background: #0e0e14 !important; color: #e8e8e8 !important; }

    /* ══════════════════════════════════════════════════════
       BUTTON SYSTEM
    ══════════════════════════════════════════════════════ */

    /* ── Base reset for ALL buttons ── */
    .stButton > button,
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stDownloadButton"] > button {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.04em !important;
        border-radius: 8px !important;
        padding: 0.58rem 1.4rem !important;
        min-height: 38px !important;
        cursor: pointer !important;
        transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1) !important;
        position: relative !important;
        overflow: hidden !important;
        white-space: nowrap !important;
    }

    /* ── Shimmer layer ── */
    .stButton > button::before,
    [data-testid="stDownloadButton"] > button::before {
        content: '' !important;
        position: absolute !important;
        top: 0 !important; left: -100% !important;
        width: 60% !important; height: 100% !important;
        background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.07) 50%, transparent 100%) !important;
        transition: left 0.55s ease !important;
        pointer-events: none !important;
    }
    .stButton > button:hover::before,
    [data-testid="stDownloadButton"] > button:hover::before {
        left: 160% !important;
    }

    /* ── PRIMARY — red gradient CTA ── */
    .stButton > button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(145deg, #7a1515 0%, #b02828 55%, #c93535 100%) !important;
        border: 1px solid rgba(180,40,40,0.55) !important;
        color: #fff !important;
        text-shadow: 0 1px 3px rgba(0,0,0,0.35) !important;
        box-shadow: 0 2px 8px rgba(139,26,26,0.45), 0 1px 2px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.10) !important;
    }
    .stButton > button[kind="primary"]:hover,
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(145deg, #921a1a 0%, #cc2e2e 55%, #e03a3a 100%) !important;
        border-color: rgba(210,55,55,0.65) !important;
        box-shadow: 0 4px 18px rgba(160,30,30,0.55), 0 2px 4px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.12) !important;
        transform: translateY(-1px) !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"]:active,
    [data-testid="stBaseButton-primary"]:active {
        transform: translateY(0) scale(0.98) !important;
        box-shadow: 0 1px 4px rgba(139,26,26,0.4), inset 0 1px 3px rgba(0,0,0,0.2) !important;
    }

    /* ── PRIMARY DISABLED ── */
    .stButton > button[kind="primary"]:disabled,
    [data-testid="stBaseButton-primary"]:disabled {
        background: rgba(120,20,20,0.35) !important;
        border-color: rgba(140,30,30,0.25) !important;
        color: rgba(255,255,255,0.4) !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
        transform: none !important;
        text-shadow: none !important;
    }

    /* ── SECONDARY — refined ghost ── */
    .stButton > button[kind="secondary"],
    [data-testid="stBaseButton-secondary"],
    .stButton > button:not([kind]) {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        color: rgba(255,255,255,0.78) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    }
    .stButton > button[kind="secondary"]:hover,
    [data-testid="stBaseButton-secondary"]:hover,
    .stButton > button:not([kind]):hover {
        background: rgba(255,255,255,0.09) !important;
        border-color: rgba(255,255,255,0.26) !important;
        color: #fff !important;
        box-shadow: 0 3px 10px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"]:active,
    [data-testid="stBaseButton-secondary"]:active {
        transform: translateY(0) scale(0.98) !important;
        background: rgba(255,255,255,0.07) !important;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.2) !important;
    }

    /* ── DOWNLOAD BUTTON ── */
    [data-testid="stDownloadButton"] > button {
        background: rgba(45,55,72,0.55) !important;
        border: 1px solid rgba(100,130,160,0.28) !important;
        color: rgba(180,210,240,0.88) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: rgba(55,70,95,0.70) !important;
        border-color: rgba(120,160,200,0.40) !important;
        color: rgba(210,230,255,0.95) !important;
        box-shadow: 0 3px 12px rgba(30,60,100,0.35), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        transform: translateY(-1px) !important;
    }

    /* ── SIDEBAR BUTTONS ── */
    [data-testid="stSidebar"] .stButton > button {
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.09) !important;
        color: rgba(255,255,255,0.55) !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        padding: 0.4rem 0.8rem !important;
        box-shadow: none !important;
        transform: none !important;
        letter-spacing: normal !important;
        text-shadow: none !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        border-color: rgba(192,48,48,0.45) !important;
        color: #fff !important;
        background: rgba(139,26,26,0.12) !important;
        transform: none !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] .stButton > button::before { display: none !important; }
    [data-testid="stVegaLiteChart"] { background: rgba(255,255,255,0.02) !important; border: 1px solid rgba(255,255,255,0.04) !important; border-radius: 6px !important; }

    /* ── SIDEBAR ── */
    [data-testid="stSidebar"] > div { background: #0a0a0f !important; border-right: 1px solid rgba(255,255,255,0.05) !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: rgba(255,255,255,0.7) !important; }

    /* ── TABS ── */
    .stTabs [data-baseweb="tab-list"] { background: transparent !important; gap: 0 !important; border-bottom: 1px solid rgba(255,255,255,0.06) !important; }
    .stTabs [data-baseweb="tab"] { color: rgba(255,255,255,0.45) !important; font-size: 0.82rem !important; font-weight: 600 !important; padding: 0.6rem 1.2rem !important; border-bottom: 2px solid transparent !important; transition: all 0.2s ease !important; }
    .stTabs [data-baseweb="tab"]:hover { color: rgba(255,255,255,0.7) !important; }
    .stTabs [aria-selected="true"] { color: #fff !important; border-bottom-color: #e03030 !important; }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 1rem !important; }

    /* ── ANIMATIONS ── */
    @keyframes fadeInUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

    /* ── SCROLLBAR ── */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #080810; }
    ::-webkit-scrollbar-thumb { background: #2a2a35; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #44445a; }

    /* ── MOBILE RESPONSIVE ── */
    @media (max-width: 768px) {
        .hero h1 { font-size: 2.8rem !important; }
        .hero .desc { font-size: 0.88rem; padding: 0 1rem; }
        .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
        .rpt-card { padding: 1.2rem 1rem !important; }
        .rec-bar { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem 0.5rem !important; }
        .rb-val  { font-size: 1.2rem !important; }
        .rb-label { font-size: 0.58rem !important; }
        .ev-bar  { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem !important; }
        .ev-val  { font-size: 1rem !important; }
        .stats-row { gap: 1.5rem !important; flex-wrap: wrap !important; }
        .sr-num  { font-size: 1.2rem !important; }
        .pt { font-size: 0.75rem !important; }
        .pt th { font-size: 0.55rem !important; padding: 0.4rem !important; }
        .pt td { padding: 0.4rem !important; }
        .prose { font-size: 0.9rem !important; }
        .exec-summary { padding: 1rem !important; font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.6rem !important; }
        .rpt-head .meta { font-size: 0.72rem !important; }
        .thesis-grid { grid-template-columns: 1fr !important; }
        .hiw-grid { flex-direction: column !important; align-items: center !important; }
        .hw-grid { grid-template-columns: 1fr !important; }
        div[style*="grid-template-columns:1fr 1fr"] { grid-template-columns: 1fr !important; }
    }
    @media (max-width: 480px) {
        .hero h1 { font-size: 2.2rem !important; }
        .rb-val  { font-size: 1rem !important; }
        .ev-val  { font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.3rem !important; }
        .pt { display: block !important; overflow-x: auto !important; }
    }
            /* ── Kill sidebar entirely ── */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"],
    button[aria-label="Open sidebar"],
    button[aria-label="Close sidebar"] {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
    }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════

from auth import render_auth_modal

# ── Session-state defaults for auth ──
for _k in ["authenticated", "username", "user_name", "user_email", "is_guest", "show_auth"]:
    if _k not in st.session_state:
        st.session_state[_k] = False if _k in ("authenticated","is_guest","show_auth") else ""
if "initialized" not in st.session_state:
    st.session_state["show_auth"] = False
    st.session_state["initialized"] = True

if st.session_state.get("show_auth"):
    render_auth_modal()
    st.stop()

if st.query_params.get("_si") == "1":
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.session_state["show_auth"] = True
    st.rerun()

authenticated = st.session_state.get("authenticated", False)
name     = st.session_state.get("user_name", "")
username = st.session_state.get("username", "")
is_guest = st.session_state.get("is_guest", False)

# ══════════════════════════════════════════════════════════════
# TOP BAR (replaces sidebar)
# ══════════════════════════════════════════════════════════════

if authenticated:
    _display_name = f"Guest" if is_guest else name
    _report_count = st.session_state.get('report_count', 0)
    _limit = 1 if is_guest else 3
    _count_color = "#4ade80" if _report_count < _limit else "#f87171"

    # ── Visual bar: one clean HTML strip ──
    st.markdown(f'''
    <div style="display:flex;align-items:center;justify-content:space-between;
        padding:0.5rem 1rem;margin:-0.5rem 0 0.8rem;
        background:rgba(255,255,255,0.025);
        border:1px solid rgba(255,255,255,0.06);border-radius:8px;">
        <div style="display:flex;align-items:center;gap:0.8rem;">
            <div style="width:26px;height:26px;border-radius:50%;
                background:linear-gradient(135deg,#8b1a1a,#c03030);
                display:flex;align-items:center;justify-content:center;
                font-size:0.6rem;font-weight:800;color:#fff;">
                {name[0].upper() if name else "G"}</div>
            <span style="font-size:0.82rem;color:rgba(255,255,255,0.6);font-weight:500;">
                {_display_name}</span>
            <span style="font-size:0.7rem;color:rgba(255,255,255,0.3);">·</span>
            <span style="font-size:0.72rem;color:{_count_color};font-weight:600;">
                {_report_count}/{_limit} reports</span>
        </div>
        <div style="font-size:0.65rem;color:rgba(255,255,255,0.25);font-weight:600;
            text-transform:uppercase;letter-spacing:0.1em;">
            Pick<span style="color:#c03030;">R</span></div>
    </div>
    ''', unsafe_allow_html=True)

    # ── Sign out: tiny right-aligned button ──
    _, _, _, _, signout_col = st.columns([1, 1, 1, 1, 0.4])
    with signout_col:
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ── Past reports: horizontal chip row ──
    try:
        from report_store import load_user_index, load_report as load_saved_report
        past_reports = load_user_index(username)
        if past_reports and len(past_reports) > 0:
            # Build visual row in HTML
            chips_html = ""
            display_reports = list(reversed(past_reports[-6:]))
            for r in display_reports:
                rec = r.get("recommendation", "")
                tk  = r["ticker"].replace(".NS","").replace(".BO","")
                rc  = {"BUY": "#4ade80", "PASS": "#f87171"}.get(rec, "#fbbf24")
                ret = r.get("expected_return")
                ret_str = f"{ret*100:+.0f}%" if ret else ""
                chips_html += (
                    f'<div style="display:flex;flex-direction:column;align-items:center;'
                    f'gap:0.15rem;min-width:52px;">'
                    f'<span style="font-size:0.78rem;font-weight:800;color:#fff;">{tk}</span>'
                    f'<span style="font-size:0.6rem;font-weight:700;color:{rc};">'
                    f'{rec} {ret_str}</span>'
                    f'</div>'
                )

            st.markdown(f'''
            <div style="display:flex;align-items:center;gap:1.2rem;
                padding:0.5rem 0.8rem;margin:0.2rem 0 0.5rem;
                border-top:1px solid rgba(255,255,255,0.04);overflow-x:auto;">
                <span style="font-size:0.58rem;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.12em;color:rgba(255,255,255,0.2);white-space:nowrap;
                    flex-shrink:0;">History</span>
                {chips_html}
            </div>
            ''', unsafe_allow_html=True)

            # Interactive buttons below (small, subtle)
            chip_cols = st.columns(len(display_reports))
            for idx, r in enumerate(display_reports):
                tk  = r["ticker"].replace(".NS","").replace(".BO","")
                rid = r.get("report_id", f"{r['ticker']}_{r['date']}")
                with chip_cols[idx]:
                    if st.button(f"Load", key=f"load_{rid}", use_container_width=True):
                        report_data = load_saved_report(username, rid)
                        if report_data:
                            st.session_state.cached_report = {
                                "ticker": report_data["ticker"],
                                "metrics": report_data["metrics"],
                                "analysis": report_data["analysis"],
                                "data": {"hist": None, "info": {}, "inc": None, "qinc": None, "bs": None, "cf": None, "news": []},
                            }
                            st.rerun()
                        else:
                            st.toast("Could not load report")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
# CACHED DATA FETCHING
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_screener_results():
    from config import GITHUB_TOKEN, GITHUB_REPO, SCREENER_FILE
    import urllib.request, json, base64
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SCREENER_FILE}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return json.loads(base64.b64decode(data["content"]).decode())
        except Exception:
            pass
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
        except Exception:
            continue
    return out

# ══════════════════════════════════════════════════════════════
# CACHED AI PASSES
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass1(ticker, metrics_json_str, reverse_dcf_json):
    m = json.loads(metrics_json_str)
    return ai.run_pass1(ticker, m, reverse_dcf_json)

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str, reverse_dcf_json):
    m  = json.loads(metrics_json_str)
    sm = json.loads(math_json_str)
    p1 = json.loads(pass1_json_str)
    return ai.run_pass2(ticker, m, sm, p1, reverse_dcf_json)

def run_analysis(ticker, m):
    metrics_json_str = json.dumps(
        {k: v for k, v in m.items() if k not in ["description", "news"]},
        sort_keys=True, default=str)
    reverse_dcf_json = json.dumps(m.get("reverse_dcf", {"available": False, "reason": "Not computed"}), indent=2)
    pass1 = _cached_pass1(ticker, metrics_json_str, reverse_dcf_json)
    if isinstance(pass1, dict) and pass1.get("error"):
        return pass1
    scenario_math = compute_scenario_math(m, pass1)
    math_json_str  = json.dumps(scenario_math, sort_keys=True, default=str)
    pass1_json_str = json.dumps(pass1, sort_keys=True, default=str)
    pass2 = _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str, reverse_dcf_json)
    if isinstance(pass2, dict) and pass2.get("error"):
        return pass2
    final = {}
    for key in ["recommendation","conviction","investment_thesis","business_overview",
                "revenue_architecture","growth_drivers","margin_analysis","financial_health",
                "competitive_position","headwind_narrative","tailwind_narrative",
                "market_pricing_commentary","scenario_commentary","conclusion","model_used"]:
        final[key] = pass2.get(key, "")
    for key in ["segments","concentration","headwinds","tailwinds","macro_drivers",
                "scenarios","catalysts","peer_tickers","market_expectations","sensitivity"]:
        final[key] = pass1.get(key, {} if key in ["concentration","market_expectations","sensitivity"] else [])
    final["scenario_math"] = scenario_math
    exp_ret  = scenario_math.get("expected_return", 0)
    prob_pos = scenario_math.get("prob_positive_return", 0)
    rec      = final["recommendation"].upper()
    if rec == "BUY" and exp_ret < -0.20 and prob_pos < 0.25:
        final["recommendation"] = "PASS"; final["conviction"] = "High"
        final["rec_override_reason"] = f"Override: LLM recommended BUY despite expected return of {exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."
    elif rec == "PASS" and exp_ret > 0.20 and prob_pos > 0.70:
        final["recommendation"] = "BUY"; final["conviction"] = "Medium"
        final["rec_override_reason"] = f"Override: LLM recommended PASS despite expected return of {exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."
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

    # ── Masthead ──
    _DOMAIN_MAP = {
        "NVDA":"nvidia.com","AAPL":"apple.com","MSFT":"microsoft.com","AMZN":"amazon.com",
        "GOOGL":"google.com","META":"meta.com","TSLA":"tesla.com","NFLX":"netflix.com",
        "ADBE":"adobe.com","INTU":"intuit.com","NOW":"servicenow.com","PYPL":"paypal.com",
        "AVGO":"broadcom.com","PH":"parker.com","BHARTIARTL":"airtel.in","DRREDDY":"drreddys.com",
        "RELIANCE":"ril.com","TCS":"tcs.com","INFY":"infosys.com",
    }
    _tk_clean = ticker.replace(".NS","").replace(".BO","").replace(".L","")
    _domain   = _DOMAIN_MAP.get(_tk_clean, f"{_tk_clean.lower()}.com")
    _ini      = (company[:1] if company else ticker[:1]).upper()
    _logo     = (
        f'<img src="https://www.google.com/s2/favicons?domain={_domain}&sz=64" '
        f'width="44" height="44" loading="lazy" '
        f'style="border-radius:10px;object-fit:contain;background:#1a1a22;padding:3px;'
        f'border:1px solid rgba(255,255,255,0.1);flex-shrink:0;" '
        f'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\';">'
        f'<div style="display:none;width:44px;height:44px;border-radius:10px;'
        f'background:linear-gradient(135deg,#8b1a1a,#c03030);'
        f'align-items:center;justify-content:center;'
        f'font-size:1.1rem;font-weight:800;color:#fff;flex-shrink:0;">{_ini}</div>'
    )
    st.markdown(
        f'<div class="rpt-head">'
        f'<div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.4rem;">'
        f'{_logo}<h2 style="margin:0;">{strip_html(company)}</h2></div>'
        f'<div class="meta">{ticker} &nbsp;/&nbsp; {m.get("sector","")} &nbsp;/&nbsp; '
        f'{m.get("industry","")} &nbsp;/&nbsp; {cur} &nbsp;/&nbsp; {date}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    # ── Sticky nav bar ──
    rec      = a.get("recommendation", "WATCH").upper()
    conv     = a.get("conviction", "Medium")
    rc       = "buy" if rec == "BUY" else ("pass" if rec == "PASS" else "watch")
    ev       = sm.get("expected_value", 0)
    exp_ret  = sm.get("expected_return", 0)
    prob_pos = sm.get("prob_positive_return", 0)
    try:
        _price = float(m.get("current_price") or 0)
    except (ValueError, TypeError):
        _price = 0.0
    _price_str = f"{sym}{_price:,.2f}" if _price else "—"

    _spark = ""
    try:
        _hist = data.get("hist") if data else None
        if _hist is not None and not _hist.empty:
            _closes = _hist["Close"].dropna().tolist()
            if len(_closes) >= 5:
                _sample = _closes[::max(1, len(_closes) // 40)]
                _mn, _mx = min(_sample), max(_sample)
                _rng = (_mx - _mn) if _mx != _mn else 1
                _pts = " ".join(
                    f"{int(i / (len(_sample) - 1) * 118)},{int(26 - (_p - _mn) / _rng * 22)}"
                    for i, _p in enumerate(_sample)
                )
                _sc = "#4ade80" if _sample[-1] >= _sample[0] else "#f87171"
                _spark = (
                    f'<svg width="120" height="30" viewBox="0 0 120 30" style="opacity:0.6;flex-shrink:0;">'
                    f'<polyline points="{_pts}" fill="none" stroke="{_sc}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
                    f'</svg>'
                )
    except Exception:
        _spark = ""

    _rec_color = {"buy": "#4ade80", "pass": "#f87171", "watch": "#fbbf24"}.get(rc, "#fff")
    st.markdown(
        f'<div style="position:sticky;top:0;z-index:100;'
        f'background:rgba(10,10,16,0.97);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);'
        f'border-bottom:1px solid rgba(255,255,255,0.07);padding:0.55rem 1.5rem;margin:0 -2.5rem 1rem;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<div style="display:flex;align-items:center;gap:0.75rem;">'
        f'<span style="font-weight:800;font-size:0.95rem;color:#fff;">{strip_html(company)}</span>'
        f'<span style="font-size:0.78rem;color:rgba(255,255,255,0.35);background:rgba(255,255,255,0.06);padding:0.1rem 0.45rem;border-radius:4px;font-weight:600;">{ticker}</span>'
        f'<span style="font-size:0.92rem;color:#fff;font-weight:700;">{_price_str}</span>'
        f'{_spark}</div>'
        f'<div style="display:flex;align-items:center;gap:1.5rem;">'
        f'<div style="text-align:right;"><div style="font-size:0.64rem;font-weight:700;text-transform:uppercase;letter-spacing:0.10em;color:rgba(255,255,255,0.55);margin-bottom:0.1rem;">Verdict</div>'
        f'<div style="font-size:0.97rem;font-weight:800;color:{_rec_color};">{rec}</div></div>'
        f'<div style="text-align:right;"><div style="font-size:0.64rem;font-weight:700;text-transform:uppercase;letter-spacing:0.10em;color:rgba(255,255,255,0.55);margin-bottom:0.1rem;">Exp. Return</div>'
        f'<div style="font-size:0.97rem;font-weight:800;color:{_rec_color};">{exp_ret*100:+.1f}%</div></div>'
        f'<div style="text-align:right;"><div style="font-size:0.64rem;font-weight:700;text-transform:uppercase;letter-spacing:0.10em;color:rgba(255,255,255,0.55);margin-bottom:0.1rem;">EV</div>'
        f'<div style="font-size:0.97rem;font-weight:700;color:rgba(255,255,255,0.9);">{sym}{ev:,.2f}</div></div>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

    # ── Recommendation bar ──
    st.markdown(f'''<div class="rec-bar">
        <div class="rb-item"><div class="rb-label">Recommendation</div><div class="rb-val {rc}">{rec}</div></div>
        <div class="rb-item"><div class="rb-label">Conviction</div><div class="rb-val {rc}">{conv}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Value</div><div class="rb-val {rc}">{sym}{ev:,.2f}</div></div>
        <div class="rb-item"><div class="rb-label">Expected Return</div><div class="rb-val {rc}">{exp_ret*100:+.1f}%</div></div>
        <div class="rb-item"><div class="rb-label">Chance of Gain</div><div class="rb-val {rc}">{prob_pos*100:.0f}%</div></div>
    </div>''', unsafe_allow_html=True)

    if a.get("investment_thesis"):
        st.markdown(f'<div class="exec-summary">{strip_html(a["investment_thesis"])}</div>', unsafe_allow_html=True)
    if a.get("rec_override_reason"):
        st.markdown(f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);border-radius:8px;padding:1rem 1.2rem;margin:0.8rem 0;font-size:0.88rem;color:#fbbf24;line-height:1.6;">{strip_html(a["rec_override_reason"])}</div>', unsafe_allow_html=True)
    if a.get("business_overview"):
        st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["business_overview"])}</div>', unsafe_allow_html=True)

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

    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy(); cd.columns = ["Price"]
        st.line_chart(cd, height=250, color="#4ade80")

    rh = m.get("revenue_history", {}); nh = m.get("net_income_history", {})
    if rh or nh:
        st.markdown('<div class="sec">Revenue &amp; Earnings Trend (Billions)</div>', unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1:
            if rh: st.bar_chart(pd.DataFrame({"Revenue": rh}), height=200, color="#4ade80")
        with cc2:
            if nh: st.bar_chart(pd.DataFrame({"Net Income": nh}), height=200, color="#81c784")

    segments = a.get("segments", [])
    if segments:
        st.markdown('<div class="sec">Revenue Segmentation</div>', unsafe_allow_html=True)
        seg_header = "<tr><th>Segment</th><th>Revenue</th><th>% of Total</th><th>Gross Margin</th><th>YoY Growth</th><th>Trajectory</th><th>Primary Driver</th></tr>"
        seg_rows = ""
        for seg in segments:
            traj = strip_html(seg.get("trajectory", ""))
            tcolor = "#4ade80" if "accel" in traj.lower() else ("#f87171" if "decel" in traj.lower() else "#fbbf24")
            seg_rows += f'<tr><td style="font-weight:600;">{strip_html(seg.get("name",""))}</td><td>{fmt_c(seg.get("current_revenue"), cur)}</td><td>{fmt_p(seg.get("pct_of_total"))}</td><td>{fmt_p(seg.get("gross_margin"))}</td><td>{fmt_p(seg.get("yoy_growth"))}</td><td style="color:{tcolor};">{traj}</td><td style="color:rgba(255,255,255,0.5);font-size:0.85rem;">{strip_html(seg.get("primary_driver",""))}</td></tr>'
        st.markdown(f'<table class="pt"><thead>{seg_header}</thead><tbody>{seg_rows}</tbody></table>', unsafe_allow_html=True)

    if a.get("revenue_architecture"):
        st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["revenue_architecture"])}</div>', unsafe_allow_html=True)

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

    if a.get("growth_drivers"):
        st.markdown('<div class="sec">Growth Drivers &amp; Competitive Moats</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["growth_drivers"])}</div>', unsafe_allow_html=True)
    if a.get("margin_analysis"):
        st.markdown('<div class="sec">Margin Analysis</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["margin_analysis"])}</div>', unsafe_allow_html=True)
    if a.get("financial_health"):
        st.markdown('<div class="sec">Financial Health</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["financial_health"])}</div>', unsafe_allow_html=True)

    sector    = m.get("sector", "")
    llm_peers = a.get("peer_tickers", [])
    if sector in SECTOR_PEERS or llm_peers:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        with st.spinner("Loading peers..."):
            peers = fetch_peers(ticker, sector, llm_peers=llm_peers)
        if peers:
            cur_row = {"Ticker": ticker, "Company": m.get("company_name", ticker),
                       "Mkt Cap": fmt_c(m.get("market_cap"), cur), "P/E": fmt_r(m.get("trailing_pe")),
                       "Fwd P/E": fmt_r(m.get("forward_pe")), "PEG": fmt_r(m.get("peg_ratio")),
                       "Margin": fmt_p(m.get("operating_margin")), "ROE": fmt_p(m.get("roe")),
                       "Rev Gr.": fmt_p(m.get("revenue_growth"))}
            hds  = list(cur_row.keys())
            th   = "".join(f"<th>{hd}</th>" for hd in hds)
            tr_c = "<tr class='hl'>" + "".join(f"<td>{cur_row[hd]}</td>" for hd in hds) + "</tr>"
            tr_p = "".join("<tr>" + "".join(f"<td>{pr.get(hd, '-')}</td>" for hd in hds) + "</tr>" for pr in peers)
            st.markdown(f'<table class="pt"><thead><tr>{th}</tr></thead><tbody>{tr_c}{tr_p}</tbody></table>', unsafe_allow_html=True)

    if a.get("competitive_position"):
        st.markdown('<div class="sec">Competitive Position</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["competitive_position"])}</div>', unsafe_allow_html=True)

    headwinds = a.get("headwinds", [])
    tailwinds = a.get("tailwinds", [])
    if headwinds or tailwinds:
        st.markdown('<div class="sec">What Could Go Wrong &amp; What Could Go Right <span class="vtag">Quantified</span></div>', unsafe_allow_html=True)
        if a.get("headwind_narrative"):
            st.markdown(f'<div class="prose">{strip_html(a["headwind_narrative"])}</div>', unsafe_allow_html=True)
        if headwinds:
            hw_header = "<tr><th>Headwind</th><th>Prob.</th><th>Revenue at Risk</th><th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>"
            hw_rows = "".join(f'<tr><td style="font-weight:600;">{strip_html(hw.get("name",""))}</td><td>{fmt_p(hw.get("probability"))}</td><td>{fmt_c(hw.get("revenue_at_risk"), cur)}</td><td>{sym}{safe_float(hw.get("bull_eps_impact",0)):+.2f}</td><td>{sym}{safe_float(hw.get("base_eps_impact",0)):+.2f}</td><td>{sym}{safe_float(hw.get("bear_eps_impact",0)):+.2f}</td></tr>' for hw in headwinds)
            st.markdown(f'<table class="pt"><thead>{hw_header}</thead><tbody>{hw_rows}</tbody></table>', unsafe_allow_html=True)
        if a.get("tailwind_narrative"):
            st.markdown(f'<div class="prose" style="margin-top:1rem;">{strip_html(a["tailwind_narrative"])}</div>', unsafe_allow_html=True)
        if tailwinds:
            tw_header = "<tr><th>Tailwind</th><th>Prob.</th><th>Revenue Opportunity</th><th>Bull Impact</th><th>Base Impact</th><th>Bear Impact</th></tr>"
            tw_rows = "".join(f'<tr><td style="font-weight:600;">{strip_html(tw.get("name",""))}</td><td>{fmt_p(tw.get("probability"))}</td><td>{fmt_c(tw.get("revenue_opportunity"), cur)}</td><td>{sym}{safe_float(tw.get("bull_eps_impact",0)):+.2f}</td><td>{sym}{safe_float(tw.get("base_eps_impact",0)):+.2f}</td><td>{sym}{safe_float(tw.get("bear_eps_impact",0)):+.2f}</td></tr>' for tw in tailwinds)
            st.markdown(f'<table class="pt"><thead>{tw_header}</thead><tbody>{tw_rows}</tbody></table>', unsafe_allow_html=True)

    macro_drivers = a.get("macro_drivers", [])
    if macro_drivers:
        st.markdown('<div class="sec">Key Factors That Drive This Stock <span class="vtag">Factor-by-Factor Analysis</span></div>', unsafe_allow_html=True)
        st.markdown('''<div class="plain-callout">
            <div class="plain-callout-label">How this works</div>
            We identified the most important factors that will determine where this stock goes.
            For each factor, we assessed three possible outcomes: optimistic (green), neutral (yellow), and pessimistic (red).
            The percentages show how likely each outcome is.
        </div>''', unsafe_allow_html=True)
        for d in macro_drivers:
            dname    = strip_html(d.get("name", ""))
            dmeasures = strip_html(d.get("measures", ""))
            bull_p   = safe_float(d.get("bull_outcome", {}).get("probability"))
            base_p   = safe_float(d.get("base_outcome", {}).get("probability"))
            bear_p   = safe_float(d.get("bear_outcome", {}).get("probability"))
            bull_n   = strip_html(d.get("bull_outcome", {}).get("description", ""))[:120]
            base_n   = strip_html(d.get("base_outcome", {}).get("description", ""))[:120]
            bear_n   = strip_html(d.get("bear_outcome", {}).get("description", ""))[:120]
            bw = max(2, min(100, round(bull_p*100))); basew = max(2, min(100, round(base_p*100))); bearw = max(2, min(100, round(bear_p*100)))
            st.markdown(f'''<div class="driver-card">
                <div class="driver-card-name">{dname}</div>
                <div class="driver-card-desc">{dmeasures}</div>
                <div style="margin:0.3rem 0;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.25rem 0;">
                        <div style="width:{bw}%;height:6px;background:#22703a;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#4ade80;min-width:2.5rem;">{bull_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);">{bull_n}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.25rem 0;">
                        <div style="width:{basew}%;height:6px;background:#92681a;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#fbbf24;min-width:2.5rem;">{base_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);">{base_n}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.25rem 0;">
                        <div style="width:{bearw}%;height:6px;background:#8b2020;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#f87171;min-width:2.5rem;">{bear_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);">{bear_n}</span>
                    </div>
                </div>
            </div>''', unsafe_allow_html=True)

    fb  = prob_out.get("bull", 0)
    fba = prob_out.get("base", 0)
    fbe = prob_out.get("bear", 0)
    if fb or fba or fbe:
        st.markdown('<div class="sec">How We Weighted the Scenarios</div>', unsafe_allow_html=True)
        n_drivers = len(macro_drivers)
        st.markdown(f'''<div class="plain-callout">
            <div class="plain-callout-label">From factors to scenario weights</div>
            We analyzed <strong>{n_drivers} key factor{"s" if n_drivers != 1 else ""}</strong> above and combined their probabilities to arrive at these scenario weights:
        </div>''', unsafe_allow_html=True)
        bull_pct = f"{fb*100:.0f}"; base_pct = f"{fba*100:.0f}"; bear_pct = f"{fbe*100:.0f}"
        _bw = max(2, min(96, round(fb*100))); _baw = max(2, min(96, round(fba*100))); _bew = max(2, min(96, round(fbe*100)))
        st.markdown(
            f'<div style="margin:1.2rem 0 1.4rem;">'
            f'<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.55rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;text-align:right;flex-shrink:0;">Bull</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_bw}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#22703a,#4ade80);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#4ade80;text-align:right;flex-shrink:0;">{bull_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Better than expected</div></div>'
            f'<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.55rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#fbbf24;text-align:right;flex-shrink:0;">Base</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_baw}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#92681a,#fbbf24);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#fbbf24;text-align:right;flex-shrink:0;">{base_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Consensus plays out</div></div>'
            f'<div style="display:flex;align-items:center;gap:0.75rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;text-align:right;flex-shrink:0;">Bear</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_bew}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#8b2020,#f87171);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#f87171;text-align:right;flex-shrink:0;">{bear_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Worse than expected</div></div>'
            f'<div style="margin-top:0.9rem;font-size:0.88rem;color:rgba(255,255,255,0.55);line-height:1.7;">'
            f'There is a <strong style="color:#4ade80;">{bull_pct}% chance</strong> things go better than expected, '
            f'a <strong style="color:#fbbf24;">{base_pct}% chance</strong> they play out as expected, and a '
            f'<strong style="color:#f87171;">{bear_pct}% chance</strong> of a worse-than-expected outcome.'
            f'</div></div>',
            unsafe_allow_html=True
        )

    # ── Scenario tabs ──
    st.markdown('<div class="sec">Scenario Analysis <span class="vtag">Segment-Level Builds</span></div>', unsafe_allow_html=True)
    if a.get("scenario_commentary"):
        st.markdown(f'<div class="prose">{strip_html(a["scenario_commentary"])}</div>', unsafe_allow_html=True)

    scenarios = sm.get("scenarios", {})
    bull_s = scenarios.get("bull", {}); base_s = scenarios.get("base", {}); bear_s = scenarios.get("bear", {})
    bull_label = f"Bull ({bull_s.get('probability',0)*100:.0f}%) / {sym}{bull_s.get('price_target',0):,.0f}" if bull_s else "Bull"
    base_label = f"Base ({base_s.get('probability',0)*100:.0f}%) / {sym}{base_s.get('price_target',0):,.0f}" if base_s else "Base"
    bear_label = f"Bear ({bear_s.get('probability',0)*100:.0f}%) / {sym}{bear_s.get('price_target',0):,.0f}" if bear_s else "Bear"

    bull_tab, base_tab, bear_tab = st.tabs([f":green[{bull_label}]", f":orange[{base_label}]", f":red[{bear_label}]"])
    for tab, sname, slabel, scolor in [(bull_tab,"bull","Bull Case","#4ade80"),(base_tab,"base","Base Case","#fbbf24"),(bear_tab,"bear","Bear Case","#f87171")]:
        s = scenarios.get(sname, {})
        if not s: continue
        with tab:
            prob = s.get("probability",0)*100; pt = s.get("price_target",0)
            ret  = s.get("implied_return",0)*100; eps = s.get("projected_eps",0)
            pe   = s.get("pe_multiple",0); bpe = s.get("breakeven_pe")
            op_m = s.get("operating_margin",0); rev_g = s.get("revenue_growth",0)
            total_rev = s.get("total_revenue",0); fcf_y = s.get("fcf_yield_at_target")
            narrative  = strip_html(s.get("narrative","")); pe_rat = strip_html(s.get("pe_rationale",""))
            margin_rat = strip_html(s.get("margin_rationale","")); eps_flag = s.get("eps_flag")
            hw_rev = s.get("total_headwind_revenue",0); hw_eps = s.get("total_headwind_eps",0)
            tw_rev = s.get("total_tailwind_revenue",0); tw_eps = s.get("total_tailwind_eps",0)
            st.markdown(f'''<div style="text-align:center;padding:1.5rem 0 1rem;">
                <div style="font-size:2.2rem;font-weight:900;color:#fff;">{sym}{pt:,.2f}</div>
                <div style="font-size:1.1rem;font-weight:700;color:{scolor};margin-top:0.3rem;">{ret:+.1f}% return</div>
                <div style="font-size:0.75rem;color:rgba(255,255,255,0.6);margin-top:0.2rem;">{prob:.0f}% probability</div>
            </div>''', unsafe_allow_html=True)
            m1,m2,m3,m4 = st.columns(4)
            with m1: st.metric("Revenue", fmt_c(total_rev, cur))
            with m2: st.metric("EPS", f"{sym}{eps:.2f}")
            with m3: st.metric("P/E Multiple", f"{pe:.1f}x")
            with m4: st.metric("Op. Margin", f"{op_m*100:.1f}%")
            seg_builds = s.get("segment_builds", [])
            if seg_builds:
                st.markdown('<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.65);margin:1rem 0 0.5rem;">Segment Revenue Builds</div>', unsafe_allow_html=True)
                for seg in seg_builds:
                    sr = safe_float(seg.get("projected_revenue")); sg = safe_float(seg.get("growth_rate"))
                    pct_of_total = (sr / total_rev * 100) if total_rev > 0 else 0
                    bar_width = max(2, min(100, pct_of_total))
                    st.markdown(f'''<div style="margin:0.3rem 0;">
                        <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:0.2rem;">
                            <span style="color:rgba(255,255,255,0.6);">{strip_html(seg.get("name",""))}</span>
                            <span style="color:#fff;font-weight:600;">{fmt_c(sr, cur)} <span style="color:{scolor};font-size:0.75rem;">{sg*100:+.0f}%</span></span>
                        </div>
                        <div style="height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                            <div style="width:{bar_width}%;height:100%;background:{scolor};opacity:0.4;border-radius:2px;"></div>
                        </div>
                    </div>''', unsafe_allow_html=True)
            if narrative:
                st.markdown(f'<div style="font-size:0.95rem;color:rgba(255,255,255,0.78);line-height:1.8;font-style:italic;margin:0.8rem 0;padding:1rem;background:rgba(255,255,255,0.02);border-radius:6px;">{narrative}</div>', unsafe_allow_html=True)
            with st.expander("Valuation & margin rationale"):
                if margin_rat: st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);line-height:1.7;margin-bottom:0.5rem;"><strong style="color:rgba(255,255,255,0.7);">Margin:</strong> {margin_rat}</div>', unsafe_allow_html=True)
                if pe_rat:     st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);line-height:1.7;"><strong style="color:rgba(255,255,255,0.7);">Valuation:</strong> {pe_rat}</div>', unsafe_allow_html=True)
                if bpe:        st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);margin-top:0.5rem;">Breakeven P/E: <strong style="color:#fff;">{bpe:.1f}x</strong></div>', unsafe_allow_html=True)
                if fcf_y:      st.markdown(f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.5);">FCF Yield at target: <strong style="color:#fff;">{fcf_y*100:.1f}%</strong></div>', unsafe_allow_html=True)
                if eps_flag:   st.markdown(f'<div style="font-size:0.82rem;color:#fbbf24;margin-top:0.5rem;font-style:italic;">{strip_html(eps_flag)}</div>', unsafe_allow_html=True)

    if a.get("market_pricing_commentary"):
        st.markdown('<div class="sec">Valuation vs Expectations</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["market_pricing_commentary"])}</div>', unsafe_allow_html=True)

    ras      = sm.get("risk_adjusted_score", 0)
    ud_ratio = sm.get("upside_downside_ratio", 0)
    mdd      = sm.get("max_drawdown_magnitude", 0)*100
    mdd_prob = sm.get("max_drawdown_prob", 0)*100
    rfr      = sm.get("risk_free_rate", 0.06)*100
    std_dev  = sm.get("std_dev", 0)*100
    ras_color  = "#4ade80" if ras > 1.0 else ("#fbbf24" if ras > 0.3 else "#f87171")
    ret_color  = "positive" if exp_ret > 0.05 else ("neutral" if exp_ret > 0 else "negative")
    ud_display = "inf" if ud_ratio == float("inf") else f"{ud_ratio:.2f}x"
    ud_color   = "#4ade80" if ud_ratio > 1.5 or ud_ratio == float("inf") else ("#fbbf24" if ud_ratio > 1.0 else "#f87171")
    st.markdown('<div class="sec">The Bottom Line</div>', unsafe_allow_html=True)
    st.markdown(f'''<div class="ev-bar">
        <div class="ev-item"><div class="ev-label">Expected Value</div><div class="ev-val">{sym}{ev:,.2f}</div></div>
        <div class="ev-item"><div class="ev-label">Expected Return</div><div class="ev-val {ret_color}">{exp_ret*100:+.1f}%</div></div>
        <div class="ev-item"><div class="ev-label">Volatility</div><div class="ev-val">{std_dev:.1f}%</div></div>
        <div class="ev-item"><div class="ev-label">Risk-Adjusted Return</div><div class="ev-val" style="color:{ras_color};">{ras:.2f}</div>
            <div style="font-size:0.65rem;color:rgba(255,255,255,0.6);">above a safe {rfr:.0f}% return</div></div>
        <div class="ev-item"><div class="ev-label">Upside vs Downside</div><div class="ev-val" style="color:{ud_color};">{ud_display}</div></div>
        <div class="ev-item"><div class="ev-label">Worst Case Drop</div><div class="ev-val" style="color:#f87171;">{mdd:.1f}%</div>
            <div style="font-size:0.65rem;color:rgba(255,255,255,0.6);">{mdd_prob:.0f}% chance of this</div></div>
    </div>''', unsafe_allow_html=True)

    sensitivity = sm.get("sensitivity", {})
    if sensitivity and sensitivity.get("dominant_driver"):
        driver_name = strip_html(sensitivity.get("dominant_driver", ""))
        current_p   = safe_float(sensitivity.get("current_bull_probability"))*100
        ev_plus     = safe_float(sensitivity.get("ev_if_bull_plus_10"))
        ev_minus    = safe_float(sensitivity.get("ev_if_bull_minus_10"))
        interp      = strip_html(sensitivity.get("interpretation", ""))
        st.markdown('<div class="sec">What If? <span class="vtag">Sensitivity Check</span></div>', unsafe_allow_html=True)
        st.markdown(f'''<div style="background:#0e0e14;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:1.2rem 1.5rem;margin:0.8rem 0;">
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.55);margin-bottom:1rem;">
                What happens to the expected value if we change the bull probability on <strong style="color:#fff;">{driver_name}</strong>?
            </div>
            <div style="display:flex;justify-content:center;gap:2.5rem;">
                <div style="text-align:center;"><div style="font-size:0.82rem;color:#f87171;font-weight:600;">Bull Prob -10pp ({current_p-10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#f87171;">{sym}{ev_minus:,.2f}</div></div>
                <div style="text-align:center;"><div style="font-size:0.82rem;color:rgba(255,255,255,0.5);font-weight:600;">Current ({current_p:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#fff;">{sym}{ev:,.2f}</div></div>
                <div style="text-align:center;"><div style="font-size:0.82rem;color:#4ade80;font-weight:600;">Bull Prob +10pp ({current_p+10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#4ade80;">{sym}{ev_plus:,.2f}</div></div>
            </div>
            <div style="text-align:center;font-size:0.85rem;font-style:italic;color:rgba(255,255,255,0.4);margin-top:1rem;">{interp}</div>
        </div>''', unsafe_allow_html=True)

    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">What to Watch</div>', unsafe_allow_html=True)
        cat_header = "<tr><th>Date</th><th>Event</th><th style='color:#4ade80;'>Positive Signal</th><th style='color:#f87171;'>Negative Signal</th></tr>"
        cat_rows = "".join(f'<tr><td style="font-weight:600;">{strip_html(c.get("date",""))}</td><td>{strip_html(c.get("event",""))}</td><td style="color:#4ade80;">{strip_html(c.get("positive_signal",c.get("bull_signal","")))}</td><td style="color:#f87171;">{strip_html(c.get("negative_signal",c.get("bear_signal","")))}</td></tr>' for c in catalysts)
        st.markdown(f'<table class="pt"><thead>{cat_header}</thead><tbody>{cat_rows}</tbody></table>', unsafe_allow_html=True)

    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{strip_html(a["conclusion"])}</div>', unsafe_allow_html=True)

    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")} &nbsp;/&nbsp;
        Math computed in Python (segment-level) &nbsp;/&nbsp; Report #{st.session_state.report_count}</div>''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# RENDER — TRACK BOX
# UX: Removed the expander — fields are shown directly.
#     One less click to set up a price alert.
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
        <p style="color:rgba(255,255,255,0.5);font-size:0.9rem;line-height:1.65;margin:0 0 1rem;">
        Get an email when <strong style="color:#fff;">{strip_html(company)}</strong> hits your target price.
        Thesis target: <strong style="color:{rec_color};">{sym}{suggested_target:,.2f}</strong></p></div>''', unsafe_allow_html=True)

    # UX: Fields shown directly — no expander needed (saves one click)
    col1, col2 = st.columns(2)
    with col1:
        user_email = st.text_input("Your email", placeholder="you@example.com", key=f"track_email_{ticker}")
    with col2:
        target_price = st.number_input(f"Alert price ({sym})", min_value=0.01, value=suggested_target, step=0.50, key=f"track_target_{ticker}")

    thesis_snapshot  = strip_html(a.get("investment_thesis", ""))
    metrics_snapshot = {k: m.get(k) for k in ["trailing_pe","forward_pe","peg_ratio","operating_margin","roe","revenue_growth","revenue_cagr","fcf_yield","debt_to_equity","ev_to_ebitda"]}

    if st.button("Start Tracking", key=f"track_btn_{ticker}", type="primary"):
        if not user_email or "@" not in user_email:
            st.error("Please enter a valid email address.")
        elif not GMAIL_SENDER or not GMAIL_APP_PASS:
            st.warning("Email not configured.")
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
        bg     = {"green":"rgba(74,222,128,0.1)","yellow":"rgba(251,191,36,0.1)","red":"rgba(248,113,113,0.1)"}.get(colour,"rgba(74,222,128,0.1)")
        border = {"green":"rgba(74,222,128,0.3)","yellow":"rgba(251,191,36,0.3)","red":"rgba(248,113,113,0.3)"}.get(colour)
        text_c = {"green":"#4ade80","yellow":"#fbbf24","red":"#f87171"}.get(colour)
        st.markdown(f'<div style="background:{bg};border:1px solid {border};border-radius:6px;padding:0.8rem 1.2rem;font-size:0.88rem;color:{text_c};margin-top:0.8rem;line-height:1.5;">{msg}</div>', unsafe_allow_html=True)
        st.session_state.track_success = None

    st.markdown('<div class="track-note">Your email is only used for price alerts. Never shared.</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# MAIN UI
# ══════════════════════════════════════════════════════════════

header_left, header_right = st.columns([2.5, 1.5])
with header_left:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:0.7rem;">'
        '<span style="font-size:2.3rem;font-weight:900;letter-spacing:-0.025em;color:#fff;">'
        'Pick<span style="color:#e74c3c;">R</span></span>'
        '<span style="font-size:0.9rem;color:rgba(255,255,255,0.55);font-weight:500;">'
        'QGLP equity research</span>'
        '</div>',
        unsafe_allow_html=True
    )

with header_right:
    metrics = "24 Metrics · 3 Scenarios · 5yr Data"
    if not st.session_state.get("authenticated"):
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:1.2rem;height:2.4rem">'
            f'<span style="font-size:0.78rem;font-weight:600;text-transform:uppercase;letter-spacing:0.14em;color:rgba(255,255,255,0.7)">{metrics}</span>'
            f'</div>',
            unsafe_allow_html=True)
        if st.button("Sign in", key="elegantsignin"):
            st.session_state.show_auth = True
            st.rerun()
    else:
        st.markdown(
            f'<div style="text-align:right;height:2.4rem;display:flex;align-items:center;justify-content:flex-end">'
            f'<span style="font-size:0.78rem;font-weight:600;text-transform:uppercase;letter-spacing:0.14em;color:rgba(255,255,255,0.7)">{metrics}</span>'
            f'</div>',
            unsafe_allow_html=True)

# ── PEG tape ──────────────────────────────────────────────────
def render_peg_tape(screener_data):
    if not screener_data:
        return
    all_picks = screener_data.get("us_picks", []) + screener_data.get("india_picks", [])
    peg_picks = []
    for p in all_picks:
        try:
            peg_val = float(p.get("peg_ratio") or 0)
            if 0 < peg_val < 1.0:
                peg_picks.append(p)
        except (TypeError, ValueError):
            continue
    if not peg_picks:
        return

    tape_items = []
    for p in peg_picks:
        tk      = p.get("ticker", "").replace(".NS","").replace(".BO","")
        peg     = p.get("peg_ratio", 0)
        score   = p.get("qglp_score", 0)
        roe     = p.get("roe", 0)
        epscagr = p.get("earnings_cagr", 0)
        sc      = "#4ade80" if score >= 85 else "#fbbf24" if score >= 70 else "#e0e0e0"
        tape_items.append((tk, peg, score, roe, sc, epscagr))

    tape_items = tape_items * 4
    items_html = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:0.5rem;'
        f'padding:0 1.2rem;border-right:1px solid rgba(255,255,255,0.06);white-space:nowrap">'
        f'<span style="font-size:0.75rem;font-weight:800;color:#fff;letter-spacing:0.03em">{tk}</span>'
        f'<span style="font-size:0.65rem;font-weight:700;color:{sc};background:rgba(255,255,255,0.05);padding:0.1rem 0.35rem;border-radius:3px">PEG {peg:.2f}</span>'
        f'<span style="font-size:0.65rem;color:rgba(255,255,255,0.5)">EPS {epscagr*100:.0f}%</span>'
        f'</span>'
        for tk, peg, score, roe, sc, epscagr in tape_items
    )
    st.markdown(f'''
    <div style="width:100%;overflow:hidden;background:rgba(12,12,18,0.95);
        border-top:1px solid rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.06);
        padding:0.5rem 0;margin:0 0 1rem;display:flex;align-items:center;">
        <div style="font-size:0.75rem;font-weight:800;color:rgba(255,255,255,0.4);
            padding:0 1rem;white-space:nowrap;flex-shrink:0;text-transform:uppercase;letter-spacing:0.08em;">PEG &lt;1</div>
        <div style="overflow:hidden;flex:1;">
            <div class="tape-scroll" style="display:flex;align-items:center;
                animation:tape-scroll-main 40s linear infinite;width:max-content;">
                {items_html}
            </div>
        </div>
    </div>
    <style>
    @keyframes tape-scroll-main {{ 0% {{ transform:translateX(0); }} 100% {{ transform:translateX(-50%); }} }}
    .tape-scroll:hover {{ animation-play-state:paused !important; }}
    </style>
    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.14em;
        color:rgba(255,255,255,0.2);text-align:center;margin:-1rem 0 1rem;">
        ↑ QGLP-screened stocks with PEG &lt; 1.0 · hover to pause</div>
    ''', unsafe_allow_html=True)

# ── Screener picks table ──────────────────────────────────────
# UX: Clicking a ticker in the table now IMMEDIATELY sets it and
#     triggers generation (if authenticated). One click = report.
#     No intermediate "selected" state requiring a second click.
def render_picks_table(picks, market_label, select_key):
    if not picks:
        return
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.14em;color:rgba(255,255,255,0.6);'
        f'margin:1.2rem 0 0.5rem;padding-bottom:0.4rem;'
        f'border-bottom:1px solid rgba(255,255,255,0.05);">{market_label}</div>',
        unsafe_allow_html=True
    )

    header_html = (
        '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);">'
        '<th style="padding:0.6rem 0.5rem;text-align:left;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);">Company</th>'
        '<th style="padding:0.6rem 0.5rem;text-align:center;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);">Sc.</th>'
        '<th style="padding:0.6rem 0.5rem;text-align:center;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);">PEG</th>'
        '<th style="padding:0.6rem 0.5rem;text-align:center;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);">ROE</th>'
        '<th style="padding:0.6rem 0.5rem;text-align:center;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);">CAGR</th>'
        '</tr>'
    )

    _DOMAIN_MAP = {
        "NVDA":"nvidia.com","AAPL":"apple.com","MSFT":"microsoft.com","AMZN":"amazon.com",
        "GOOGL":"google.com","META":"meta.com","TSLA":"tesla.com","NFLX":"netflix.com",
        "ADBE":"adobe.com","INTU":"intuit.com","NOW":"servicenow.com","PYPL":"paypal.com",
        "AVGO":"broadcom.com","BHARTIARTL":"airtel.in","DRREDDY":"drreddys.com",
        "RELIANCE":"ril.com","TCS":"tcs.com","INFY":"infosys.com",
        "HDFCBANK":"hdfcbank.com","ICICIBANK":"icicibank.com","WIPRO":"wipro.com","HINDUNILVR":"hul.co.in",
    }

    rows_html = ""
    for i, pick in enumerate(picks):
        score    = pick.get("qglp_score", 0)
        sc       = "#4ade80" if score >= 85 else ("#fbbf24" if score >= 70 else "#f87171")
        roe      = pick.get("roe", 0)
        cagr     = pick.get("earnings_cagr", 0)
        peg      = float(pick.get("peg_ratio") or 0)
        tk       = pick.get("ticker", "")
        name     = pick.get("name", tk)
        tk_clean = tk.replace(".NS","").replace(".BO","")
        _ini     = tk_clean[:1].upper()
        _domain  = _DOMAIN_MAP.get(tk_clean, f"{tk_clean.lower()}.com")

        logo_html = (
            f'<img src="https://www.google.com/s2/favicons?domain={_domain}&sz=64" '
            f'width="22" height="22" loading="lazy" '
            f'style="border-radius:5px;object-fit:contain;background:#111118;padding:1px;'
            f'border:1px solid rgba(255,255,255,0.08);vertical-align:middle;margin-right:0.5rem;" '
            f'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'inline-flex\';">'
            f'<span style="display:none;width:22px;height:22px;border-radius:5px;background:#16161e;'
            f'border:1px solid rgba(255,255,255,0.1);align-items:center;justify-content:center;'
            f'font-size:0.55rem;font-weight:800;color:rgba(255,255,255,0.5);'
            f'vertical-align:middle;margin-right:0.5rem;">{_ini}</span>'
        )
        rows_html += (
            f'<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'<td style="padding:0.7rem 0.5rem;font-size:0.95rem;">'
            f'{logo_html}'
            f'<strong style="color:#fff;font-weight:800;">{tk_clean}</strong>'
            f'<span style="color:rgba(255,255,255,0.4);margin-left:0.5rem;">{name[:20]}</span>'
            f'</td>'
            f'<td style="padding:0.7rem 0.5rem;text-align:center;font-weight:800;color:{sc};font-size:0.95rem;">{score:.0f}</td>'
            f'<td style="padding:0.7rem 0.5rem;text-align:center;font-size:0.95rem;color:rgba(255,255,255,0.7);">{peg:.2f}</td>'
            f'<td style="padding:0.7rem 0.5rem;text-align:center;font-size:0.95rem;color:rgba(255,255,255,0.7);">{roe*100:.0f}%</td>'
            f'<td style="padding:0.7rem 0.5rem;text-align:center;font-size:0.95rem;color:#4ade80;font-weight:600;">+{cagr*100:.0f}%</td>'
            f'</tr>'
        )

    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead>{header_html}</thead><tbody>{rows_html}</tbody></table>',
        unsafe_allow_html=True
    )

    # UX: Subtle ghost buttons — not red primary. Less visual noise.
    btn_cols = st.columns(len(picks))
    for i, (pick, col) in enumerate(zip(picks, btn_cols)):
        tk       = pick.get("ticker", "")
        tk_clean = tk.replace(".NS","").replace(".BO","")
        with col:
            if st.button(f"{tk_clean}", key=f"{select_key}_btn_{i}",
                         type="secondary", use_container_width=True):
                st.session_state["resolved"] = tk
                st.session_state["resolved_source"] = "picks_table"
                if st.session_state.get("authenticated"):
                    st.session_state["auto_generate"] = True
                    st.rerun()
                else:
                    st.session_state["show_auth"] = True
                    st.rerun()

# ── Load screener data ──
screener_data = None
try:
    screener_data = load_screener_results()
except Exception:
    pass

render_peg_tape(screener_data)

# ── Two-column landing layout ──────────────────────────────────
left_col, right_col = st.columns([2.2, 1], gap="large")

with left_col:
    st.markdown(
        '<div style="padding:1.5rem 1.4rem;background:rgba(255,255,255,0.03);'
        'border:1px solid rgba(255,255,255,0.07);border-radius:10px;margin-top:0.5rem">'
        '<h1 style="font-size:2rem;font-weight:800;color:#fff;margin:0 0 0.6rem;'
        'line-height:1.25;letter-spacing:-0.02em;">'
        'Generate a <span style="color:#c03030">report</span> on any listed company.</h1>'
        '<p style="font-size:1.05rem;color:rgba(255,255,255,0.55);line-height:1.8;'
        'max-width:620px;margin:0;">'
        'Scores it on 24 metrics across Quality, Growth, Longevity and Price. '
        'Three probability-weighted scenarios. Instant.</p>'
        '</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
        'letter-spacing:0.14em;color:rgba(255,255,255,0.6);margin:1rem 0 0.5rem;">'
        'Search by company name or enter ticker directly</div>',
        unsafe_allow_html=True
    )
    sq = st.text_input(
        "Search", placeholder="e.g. Apple, AVGO, AAPL, RELIANCE.NS",
        label_visibility="collapsed", key="s1"
    )

    # UX: Quick-pick pills. Clicking goes straight to generation
    #     (no intermediate state). Uses query param for instant action.
    st.markdown("""
    <div style="font-size:0.85rem;color:rgba(255,255,255,0.35);margin-top:0.5rem;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
        <span>Try:</span>
        <a href="?_qt=NVDA" target="_self" style="color:rgba(255,255,255,0.7);font-weight:700;
           background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
           border-radius:4px;padding:0.1rem 0.5rem;text-decoration:none;font-size:0.82rem;">NVDA</a>
        <a href="?_qt=AAPL" target="_self" style="color:rgba(255,255,255,0.7);font-weight:700;
           background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
           border-radius:4px;padding:0.1rem 0.5rem;text-decoration:none;font-size:0.82rem;">AAPL</a>
        <a href="?_qt=RELIANCE.NS" target="_self" style="color:rgba(255,255,255,0.7);font-weight:700;
           background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
           border-radius:4px;padding:0.1rem 0.5rem;text-decoration:none;font-size:0.82rem;">RELIANCE.NS</a>
        <a href="?_qt=AVGO" target="_self" style="color:rgba(255,255,255,0.7);font-weight:700;
           background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
           border-radius:4px;padding:0.1rem 0.5rem;text-decoration:none;font-size:0.82rem;">AVGO</a>
    </div>
    """, unsafe_allow_html=True)

    # Handle ?_qt= quick-ticker param
    _qt = st.query_params.get("_qt", "")
    if _qt:
        try: st.query_params.clear()
        except Exception: pass
        st.session_state["resolved"] = _qt.strip().upper()
        st.session_state["resolved_source"] = "quickticker"
        if st.session_state.get("authenticated"):
            # UX: Auto-generate immediately — zero extra clicks
            st.session_state["auto_generate"] = True
        st.rerun()

    if sq and len(sq) >= 2:
        if len(sq) <= 12 and " " not in sq:
            st.session_state["resolved"] = sq.strip().upper()
            st.session_state.pop("resolved_source", None)
            st.markdown(
                f'<div style="font-size:0.82rem;color:rgba(255,255,255,0.4);padding:0.3rem 0 0.1rem;">'
                f'Using ticker: <strong style="color:#fff;">{sq.strip().upper()}</strong></div>',
                unsafe_allow_html=True
            )
        else:
            res = search_ticker(sq)
            if res:
                opts = {f"{r['name']} ({r['symbol']})": r['symbol'] for r in res}
                sel2 = st.selectbox("Pick result", opts.keys(), label_visibility="collapsed", key="s2")
                if sel2:
                    st.session_state["resolved"] = opts[sel2]
                    st.session_state["resolved_source"] = "search"
            else:
                st.caption("No results found. Try entering the ticker directly.")
    else:
        # UX: Popular / Recent selectors — shown when search box is empty.
        pop_keys   = list(POPULAR.keys())
        recent_rev = list(reversed(st.session_state.recent[-6:]))

        if pop_keys and recent_rev:
            qc1, qc2 = st.columns([1, 1])
            with qc1:
                sp = st.selectbox("Popular", ["— popular —"] + pop_keys,
                                  label_visibility="collapsed", key="s3")
                if sp and sp != "— popular —" and POPULAR.get(sp):
                    st.session_state["resolved"] = POPULAR[sp]
                    st.session_state["resolved_source"] = "popular"
            with qc2:
                sr = st.selectbox("Recent", ["— recent —"] + recent_rev,
                                  label_visibility="collapsed", key="s_recent")
                if sr and sr != "— recent —":
                    st.session_state["resolved"] = sr
                    st.session_state["resolved_source"] = "recent"
        elif pop_keys:
            sp = st.selectbox("Popular stocks", ["— popular —"] + pop_keys,
                              label_visibility="collapsed", key="s3")
            if sp and sp != "— popular —" and POPULAR.get(sp):
                st.session_state["resolved"] = POPULAR[sp]
                st.session_state["resolved_source"] = "popular"
        elif recent_rev:
            sr = st.selectbox("Recent searches", ["— recent —"] + recent_rev,
                              label_visibility="collapsed", key="s_recent")
            if sr and sr != "— recent —":
                st.session_state["resolved"] = sr
                st.session_state["resolved_source"] = "recent"

    resolved_now = st.session_state.get("resolved")
    if resolved_now:
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:0.5rem;'
            f'background:rgba(139,26,26,0.15);border:1px solid rgba(192,48,48,0.35);'
            f'border-radius:6px;padding:0.4rem 0.8rem;margin:0.5rem 0;">'
            f'<span style="font-size:0.72rem;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.08em;">Selected</span>'
            f'<span style="font-size:0.95rem;font-weight:800;color:#fff;">'
            f'{resolved_now.replace(".NS","").replace(".BO","")}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    _generating = st.session_state.get("_generating", False)
    go = st.button(
        "Generating..." if _generating else "Generate Report",
        type="primary",
        disabled=_generating or not resolved_now,
        key="generate_btn"
    )
    if go:
        st.session_state["_generating"] = True

# ── Right column — How It Scores ──────────────────────────────
with right_col:
    _dim  = "color:rgba(255,255,255,0.45);font-size:0.88rem;margin-top:0.2rem;"
    _head = "font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.45);"

    st.markdown(f'<div style="{_head}">How It Scores</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    for letter, name_str, detail in [
        ("Q", "Quality",   "ROE &gt;15%, FCF positive, D/E &lt;1"),
        ("G", "Growth",    "EPS CAGR &gt;12%, TAM 2&times; GDP"),
        ("L", "Longevity", "Moat durability 5+ years"),
        ("P", "Price",     "PEG &lt;1.2&times; is the target"),
    ]:
        st.markdown(
            f'<div style="margin-bottom:1.1rem;">'
            f'<div style="font-size:1rem;font-weight:800;color:#fff;">'
            f'{letter} &middot; {name_str}</div>'
            f'<div style="{_dim}">{detail}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.07);margin:0.6rem 0 1rem;'>",
                unsafe_allow_html=True)

    st.markdown(f'<div style="{_head}margin-bottom:0.7rem;">Score Bands</div>',
                unsafe_allow_html=True)
    for score_range, color, label in [
        ("85 - 100", "#4ade80", "Strong buy"),
        ("70 - 84",  "#fbbf24", "Watch"),
        ("&lt; 70",  "#f87171", "Pass"),
    ]:
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;margin-bottom:0.35rem;">'
            f'<span style="font-size:0.95rem;font-weight:700;color:{color};">{score_range}</span>'
            f'<span style="font-size:0.88rem;color:rgba(255,255,255,0.65);">{label}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.07);margin:0.8rem 0 1rem;'>",
                unsafe_allow_html=True)

    st.markdown(f'<div style="{_head}margin-bottom:0.6rem;">Account</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.9rem;color:rgba(255,255,255,0.65);line-height:1.7;">'
        '3 full reports free. Screener browsing always free, no login needed.'
        '</div>',
        unsafe_allow_html=True
    )

# ── QGLP Top Picks table ──────────────────────────────────────
report_already_run = bool(st.session_state.get("cached_report"))
if screener_data and not report_already_run:
    last_updated = screener_data.get("last_updated", "")
    st.markdown(f'''<div style="padding:2rem 0 0.8rem;">
        <div style="display:flex;justify-content:space-between;align-items:baseline;">
            <div style="font-size:0.9rem;font-weight:900;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.7);">QGLP Top Picks</div>
            <div style="font-size:0.82rem;color:rgba(255,255,255,0.35);font-weight:500;">Updated {last_updated}</div>
        </div>
        <div style="height:2px;background:linear-gradient(90deg,#8b1a1a,transparent);margin-top:0.6rem;border-radius:1px;"></div>
    </div>''', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.95rem;color:rgba(255,255,255,0.45);text-align:center;margin-bottom:1.5rem;line-height:1.7;">'
        'Click any ticker below to generate a full report instantly.</div>',
        unsafe_allow_html=True
    )
    render_picks_table(screener_data.get("us_picks", [])[:5], "United States", "us_pick_select")
    render_picks_table(screener_data.get("india_picks", [])[:5], "India", "india_pick_select")

# ── Auth redirect on Generate ──
if go and not st.session_state.get("authenticated"):
    st.session_state["show_auth"] = True
    st.rerun()

report_count = st.session_state.get("report_count", 0)
if authenticated:
    if is_guest:
        st.markdown(f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
        background:rgba(14,14,20,0.9);border:1px solid rgba(255,255,255,0.07);
        border-radius:7px;padding:0.6rem 1rem;margin-bottom:0.6rem;">
            <span style="font-size:0.8rem;color:rgba(255,255,255,0.45);">
                Guest report: <strong style="color:#fff">{report_count}/1</strong> used</span>
            <span style="font-size:0.75rem;color:#e03030;font-weight:700;">Create account for 3 reports</span>
        </div>
        """, unsafe_allow_html=True)
    elif report_count > 0:
        bar_pct   = min(report_count / 3 * 100, 100)
        bar_color = "#4ade80" if report_count < 2 else "#fbbf24" if report_count < 3 else "#f87171"
        limit_msg = " &nbsp;·&nbsp; <span style='color:#f87171;'>Limit reached</span>" if report_count >= 3 else ""
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:0.8rem;
        background:rgba(14,14,20,0.9);border:1px solid rgba(255,255,255,0.07);
        border-radius:7px;padding:0.6rem 1rem;margin-bottom:0.6rem;">
            <span style="font-size:0.8rem;color:rgba(255,255,255,0.45);">
                Reports: <strong style="color:#fff">{report_count}/3</strong>{limit_msg}</span>
            <div style="flex:1;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;">
                <div style="width:{bar_pct:.0f}%;height:100%;background:{bar_color};border-radius:2px;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

status_area = st.container()
report_area = st.container()

# ══════════════════════════════════════════════════════════════
# GENERATION LOGIC
# ══════════════════════════════════════════════════════════════

should_generate = False
ticker          = None
resolved        = st.session_state.get("resolved", None)
auto_gen        = st.session_state.pop("auto_generate", False)

if (go or auto_gen) and resolved and st.session_state.get("authenticated"):
    ticker          = resolved.strip().upper()
    should_generate = True
    st.session_state.pop("resolved", None)
    st.session_state.pop("resolved_source", None)
elif go and not resolved and st.session_state.get("authenticated"):
    with status_area:
        st.warning("Select or enter a company first.")

if should_generate and ticker:
    GUEST_LIMIT = 1
    USER_LIMIT  = 3

    if not is_guest:
        try:
            from auth import load_users_github, save_users_github
            _u, _ = load_users_github()
            if username in _u:
                st.session_state.report_count = _u[username].get("report_count", 0)
                report_count = st.session_state.report_count
        except Exception:
            pass

    if is_guest and report_count >= GUEST_LIMIT:
        st.markdown("""
        <div style="background:rgba(139,26,26,0.12);border:1px solid rgba(224,48,48,0.3);
        border-radius:10px;padding:1.8rem 2rem;margin:1rem 0;text-align:center;">
            <div style="font-size:1.1rem;font-weight:800;color:#fff;margin-bottom:0.4rem">
                You've used your free guest report</div>
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.5);line-height:1.7;
            margin-bottom:1rem;max-width:400px;margin-left:auto;margin-right:auto">
                Create a free account to unlock <strong style="color:#fff">3 reports</strong>,
                save your history, and track stocks with price alerts.</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Create a Free Account", type="primary", key="upgrade_cta"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.stop()

    elif not is_guest and report_count >= USER_LIMIT:
        st.warning(f"You've used all {USER_LIMIT} free reports. Paid tiers are coming soon.")
        st.stop()

    # Guest fingerprint check
    if is_guest:
        from auth import load_guest_counts, increment_guest_count
        fp     = st.session_state.get("guest_fingerprint", "unknown")
        counts = load_guest_counts()
        if counts.get(fp, 0) >= GUEST_LIMIT:
            st.error("This device has already used its free guest report. Please create an account.")
            st.stop()
        increment_guest_count(fp)

    if ticker not in st.session_state.recent:
        st.session_state.recent.append(ticker)
    st.session_state.report_count += 1

    if not is_guest:
        try:
            from auth import load_users_github, save_users_github
            _u, _sha = load_users_github()
            if username in _u:
                _u[username]["report_count"] = st.session_state.report_count
                save_users_github(_u, _sha)
        except Exception as e:
            print(f"Could not persist report count: {e}")

    st.session_state.cached_html          = None
    st.session_state.generate_html        = False
    st.session_state.html_just_generated  = False

    with status_area:
        with st.status(f"Analyzing {ticker}...", expanded=True) as status:
            st.markdown(
                "This analysis may take up to 2 minutes. "
                "We're computing 24 financial metrics and running "
                "AI-driven scenario analysis across bull, base, and bear cases."
            )

            st.write("Step 1 of 6 - Fetching financial data...")
            try:
                sd = fetch(ticker)
            except Exception as e:
                st.error(f"Failed to fetch data: {e}"); st.stop()
            info = sd.get("info", {})
            if isinstance(info, dict) and info.get("error"):
                st.error(f"Ticker '{ticker}' not found or unavailable."); st.stop()
            company_name = info.get("shortName", info.get("longName", ticker))
            data_source  = info.get("_source", "yfinance")
            st.write(f"Loaded **{company_name}** (via {data_source})")

            status.update(label=f"Analyzing {ticker}... (Step 2 of 6)")
            st.write("Step 2 of 6 - Computing 24 verified financial metrics...")
            m = calc(sd)
            if "error" in m:
                st.error(m["error"]); st.stop()
            reverse_dcf_json = json.dumps(m.get("reverse_dcf", {"available": False, "reason": "Not computed"}), indent=2)
            st.write("Metrics computed")

            status.update(label=f"Analyzing {ticker}... (Step 3 of 6)")
            st.write("Step 3 of 6 - AI is building scenario assumptions...")
            metrics_json_str = json.dumps(
                {k: v for k, v in m.items() if k not in ["description","news"]},
                sort_keys=True, default=str)
            pass1 = _cached_pass1(ticker, metrics_json_str, reverse_dcf_json)
            if isinstance(pass1, dict) and pass1.get("error"):
                status.update(label="Analysis failed (Pass 1)", state="error")
                for d in pass1.get("details", []): st.code(d)
                st.stop()
            st.write("Assumptions locked in")

            status.update(label=f"Analyzing {ticker}... (Step 4 of 6)")
            st.write("Step 4 of 6 - Running probability math...")
            scenario_math = compute_scenario_math(m, pass1)
            st.write("Scenarios computed")

            status.update(label=f"Analyzing {ticker}... (Step 5 of 6)")
            st.write("Step 5 of 6 - AI is writing the final analysis...")
            math_json_str  = json.dumps(scenario_math, sort_keys=True, default=str)
            pass1_json_str = json.dumps(pass1, sort_keys=True, default=str)
            pass2 = _cached_pass2(ticker, metrics_json_str, math_json_str, pass1_json_str, reverse_dcf_json)
            if isinstance(pass2, dict) and pass2.get("error"):
                status.update(label="Analysis failed (Pass 2)", state="error")
                for d in pass2.get("details", []): st.code(d)
                st.stop()
            st.write("Narrative complete")

            status.update(label=f"Analyzing {ticker}... (Step 6 of 6)")
            st.write("Step 6 of 6 - Finalizing report...")

            final = {}
            for key in ["recommendation","conviction","investment_thesis","business_overview",
                        "revenue_architecture","growth_drivers","margin_analysis","financial_health",
                        "competitive_position","headwind_narrative","tailwind_narrative",
                        "market_pricing_commentary","scenario_commentary","conclusion","model_used"]:
                final[key] = pass2.get(key, "")
            for key in ["segments","concentration","headwinds","tailwinds","macro_drivers",
                        "scenarios","catalysts","peer_tickers","market_expectations","sensitivity"]:
                final[key] = pass1.get(key, {} if key in ["concentration","market_expectations","sensitivity"] else [])
            final["scenario_math"] = scenario_math

            exp_ret  = scenario_math.get("expected_return", 0)
            prob_pos = scenario_math.get("prob_positive_return", 0)
            rec      = final["recommendation"].upper()
            if rec == "BUY" and exp_ret < -0.20 and prob_pos < 0.25:
                final["recommendation"] = "PASS"; final["conviction"] = "High"
                final["rec_override_reason"] = f"Override: LLM recommended BUY despite expected return of {exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."
            elif rec == "PASS" and exp_ret > 0.20 and prob_pos > 0.70:
                final["recommendation"] = "BUY"; final["conviction"] = "Medium"
                final["rec_override_reason"] = f"Override: LLM recommended PASS despite expected return of {exp_ret*100:.1f}% and {prob_pos*100:.0f}% probability of positive return."

            a   = final
            rec = a.get("recommendation", "WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state["_generating"] = False

    st.session_state.cached_report = {"ticker": ticker, "metrics": m, "analysis": a, "data": sd}
    st.session_state["_scroll_to_report"] = True

# ══════════════════════════════════════════════════════════════
# RENDER FROM CACHE
# ══════════════════════════════════════════════════════════════

if st.session_state.cached_report:
    cached   = st.session_state.cached_report
    c_ticker = cached["ticker"]
    c_m      = cached["metrics"]
    c_a      = cached["analysis"]
    c_data   = cached["data"]

    save_key = f"saved_{c_ticker}_{c_a.get('recommendation','')}"
    if save_key not in st.session_state and not is_guest:
        try:
            from report_store import save_report
            save_report(username, c_ticker, c_m, c_a)
            st.session_state[save_key] = True
        except Exception as e:
            print(f"Report save failed: {e}")

    with report_area:
        # ── Scroll anchor + auto-scroll JS ──
        st.markdown('<div id="pickr-report-top"></div>', unsafe_allow_html=True)
        if st.session_state.pop("_scroll_to_report", False):
            _sc.html("""
            <script>
            (function(){
                function scroll(){
                    var el = window.parent.document.getElementById('pickr-report-top');
                    if(el){ el.scrollIntoView({behavior:'smooth', block:'start'}); }
                    else { window.parent.scrollTo({top: window.parent.document.body.scrollHeight, behavior:'smooth'}); }
                }
                setTimeout(scroll, 400);
            })();
            </script>
            """, height=0, scrolling=False)

        # UX: Clear bar at top with ticker + recommendation visible.
        #     "Clear" button is prominent so user knows how to analyze another stock.
        _rec_now = c_a.get("recommendation","WATCH").upper()
        _rc_col  = {"BUY":"#4ade80","PASS":"#f87171"}.get(_rec_now,"#fbbf24")
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'background:rgba(14,14,20,0.9);border:1px solid rgba(255,255,255,0.08);'
            f'border-radius:8px;padding:0.7rem 1.2rem;margin-bottom:1rem;">'
            f'<span style="font-size:0.82rem;color:rgba(255,255,255,0.5);">'
            f'Viewing: <strong style="color:#fff;">{c_ticker}</strong>'
            f'&nbsp;&nbsp;<span style="color:{_rc_col};font-weight:700;">{_rec_now}</span>'
            f'</span>'
            f'<span style="font-size:0.75rem;color:rgba(255,255,255,0.3);">Scroll up to search another</span>'
            f'</div>',
            unsafe_allow_html=True
        )
        if st.button("Clear and analyze a different stock", key="clear_report_btn"):
            st.session_state.cached_report = None
            st.session_state.pop("resolved", None)
            st.session_state.pop("resolved_source", None)
            st.rerun()

        render(c_ticker, c_m, c_a, c_data)
        render_track_box(c_ticker, c_m, c_a)

        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;padding:1rem 0 0.5rem;"><div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div></div>', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)
        sm = c_a.get("scenario_math", {}); scenarios = sm.get("scenarios", {})
        with dl1:
            md_lines = [
                f"# {c_m.get('company_name', c_ticker)} ({c_ticker})",
                f"PickR Research / {datetime.now().strftime('%B %d, %Y')}",
                f"{c_m.get('sector','')} / {c_m.get('industry','')} / {c_m.get('currency','USD')}", "",
                f"## {c_a.get('recommendation','N/A')} | {c_a.get('conviction','N/A')}", "",
                strip_html(c_a.get("investment_thesis", "")), "", "---", "",
                "## Business Overview", "", strip_html(c_a.get("business_overview", "")), "",
                "## Conclusion", "", strip_html(c_a.get("conclusion", "")),
                "", f"*PickR / {datetime.now().strftime('%B %d, %Y')}*"
            ]
            st.download_button("Download (Markdown)", "\n".join(md_lines), f"PickR_{c_ticker}.md", "text/markdown")
        with dl2:
            export_data = {
                "ticker": c_ticker, "date": datetime.now().strftime("%Y-%m-%d"),
                "recommendation": c_a.get("recommendation"), "conviction": c_a.get("conviction"),
                "expected_value": sm.get("expected_value"), "expected_return": sm.get("expected_return"),
                "risk_adjusted_score": sm.get("risk_adjusted_score"), "prob_positive": sm.get("prob_positive_return"),
                "scenarios": sm.get("scenarios"),
                "metrics": {k: v for k, v in c_m.items() if k not in ["description","news","revenue_history","net_income_history"]},
            }
            st.download_button("Download (JSON)", json.dumps(export_data, indent=2, default=str), f"PickR_{c_ticker}.json", "application/json")

# ── Footer ────────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:2.5rem;padding:1.5rem 2rem;border-top:1px solid rgba(255,255,255,0.06);
  border-radius:0 0 8px 8px;background:rgba(255,255,255,0.015);text-align:center">
  <div style="display:flex;align-items:center;justify-content:center;gap:0.5rem;margin-bottom:0.6rem">
    <svg width="16" height="16" viewBox="0 0 28 28" fill="none" style="flex-shrink:0">
      <rect width="28" height="28" rx="7" fill="#8b1a1a"/>
      <rect x="7" y="6" width="3.5" height="16" rx="1.75" fill="white" opacity="0.9"/>
      <rect x="12" y="10" width="3.5" height="12" rx="1.75" fill="white" opacity="0.7"/>
      <rect x="17" y="7" width="3.5" height="15" rx="1.75" fill="white" opacity="0.85"/>
      <circle cx="18.75" cy="6.5" r="2.2" fill="#f87171"/>
    </svg>
    <span style="font-size:0.82rem;font-weight:700;color:rgba(255,255,255,0.62);letter-spacing:0.06em">
      Built by <span style="color:#e08070">Mayukh Kondepudi</span>
      &nbsp;&middot;&nbsp;
      <a href="mailto:mayukhkondepudi@gmail.com"
         style="color:#e08070;text-decoration:none;border-bottom:1px solid rgba(224,128,112,0.35)">
        mayukhkondepudi@gmail.com</a>
    </span>
  </div>
  <div style="font-size:0.75rem;color:rgba(255,255,255,0.45);line-height:1.75;max-width:680px;margin:0 auto">
    PickR is an independent research tool for <strong style="color:rgba(255,255,255,0.65)">educational purposes only</strong>.
    Nothing on this platform constitutes financial advice, a solicitation, or a recommendation to buy or sell any security.
    Always do your own due diligence before investing.
  </div>
  <div style="margin-top:0.6rem;font-size:0.68rem;color:rgba(255,255,255,0.28);letter-spacing:0.06em">
    &copy; 2026 PickR &nbsp;&middot;&nbsp; All rights reserved
  </div>
</div>
""", unsafe_allow_html=True)
