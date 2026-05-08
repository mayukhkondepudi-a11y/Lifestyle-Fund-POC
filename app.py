"""PickR - Streamlit UI and rendering."""

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from compute import clean_latex

st.set_page_config(page_title="PickR", page_icon="P", layout="wide", initial_sidebar_state="collapsed")

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
    }
    hide();
    setTimeout(hide, 300);
    setTimeout(hide, 800);
    var obs = new MutationObserver(hide);
    obs.observe(window.parent.document.body, {childList:true, subtree:true});
})();
</script>
""", height=0, scrolling=False)


from config import (POPULAR, SECTOR_PEERS, GMAIL_SENDER, GMAIL_APP_PASS,
                    RESEND_API_KEY, DOMAIN_MAP)
from formatting import (safe_float, get_sym, fmt_n, fmt_p, fmt_r, fmt_c,
                         strip_html, clean_ticker)

# FIX: fmt_eps_impact now correctly accepts sym as a required parameter
#      and uses it consistently. The original had it missing from tailwind calls.
def fmt_eps_impact(val, sym, is_headwind=False):
    """Format EPS impact with correct sign and color."""
    v = safe_float(val)
    if v == 0:
        return f'<span style="color:#888">{sym}0.00</span>'
    if is_headwind:
        return f'<span style="color:#ef4444">-{sym}{abs(v):.2f}</span>'
    else:
        return f'<span style="color:#22c55e">+{sym}{abs(v):.2f}</span>'


def pt_table(header_html, rows_html):
    """Render a styled .pt table given pre-built <tr>...</tr> header and rows HTML."""
    return (f'<div class="pt-wrap"><table class="pt">'
            f'<thead>{header_html}</thead>'
            f'<tbody>{rows_html}</tbody></table></div>')

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

from styles import APP_CSS
st.markdown(APP_CSS, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════

from auth import render_auth_modal

for _k in ["authenticated", "username", "user_name", "user_email", "is_guest", "show_auth"]:
    if _k not in st.session_state:
        st.session_state[_k] = False if _k in ("authenticated","is_guest","show_auth") else ""
if "initialized" not in st.session_state:
    st.session_state["show_auth"] = False
    st.session_state["initialized"] = True

if st.session_state.get("show_auth"):
    render_auth_modal()
    if st.session_state.pop("_just_authed", False):
        st.rerun()

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
# TOP BAR
# ══════════════════════════════════════════════════════════════

if authenticated:
    _display_name = "Guest" if is_guest else name
    _report_count = st.session_state.get('report_count', 0)
    _is_admin     = not is_guest and username.lower() in {"mayukhk"}
    _limit        = 1 if is_guest else (None if _is_admin else 3)
    _limit_str    = "∞" if _is_admin else str(_limit)
    _count_color  = "#c084fc" if _is_admin else ("#4ade80" if _report_count < (_limit or 999) else "#f87171")
    _initial      = (name[0].upper() if name else "G")

    _has_report = bool(st.session_state.get("cached_report"))
    if _has_report:
        _topbar_col, _back_col, _signout_col = st.columns([4.6, 1.4, 0.85])
    else:
        _topbar_col, _back_col, _signout_col = st.columns([6, 0.001, 0.85])

    with _topbar_col:
        st.markdown(f'''
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;
            gap:0.5rem;padding:0.45rem 1rem;margin:-0.5rem 0 0.5rem;
            position:sticky;top:0;z-index:100;
            backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
            background:linear-gradient(90deg,rgba(12,12,18,0.96) 0%,rgba(14,14,20,0.96) 100%);
            border:1px solid rgba(255,255,255,0.07);border-radius:8px;
            box-shadow:0 1px 6px rgba(0,0,0,0.25);min-height:44px;">
            <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
                <div style="width:26px;height:26px;border-radius:50%;flex-shrink:0;
                    background:linear-gradient(135deg,#8b1a1a,#c03030);
                    display:flex;align-items:center;justify-content:center;
                    font-size:0.6rem;font-weight:800;color:#fff;
                    box-shadow:0 0 0 2px rgba(192,48,48,0.25);">{_initial}</div>
                <span style="font-size:0.82rem;color:rgba(255,255,255,0.7);font-weight:600;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;"
                    title="{_display_name}">{_display_name}</span>
                <span style="font-size:0.7rem;color:rgba(255,255,255,0.2);flex-shrink:0;">·</span>
                <span style="font-size:0.72rem;font-weight:700;color:{_count_color};
                    background:rgba(255,255,255,0.04);padding:0.1rem 0.45rem;
                    border-radius:3px;border:1px solid rgba(255,255,255,0.06);
                    white-space:nowrap;">{_report_count}/{_limit_str} reports</span>
            </div>
            <div style="font-size:0.62rem;color:rgba(255,255,255,0.2);font-weight:700;
                text-transform:uppercase;letter-spacing:0.12em;flex-shrink:0;">
                Pick<span style="color:rgba(192,48,48,0.6);">R</span></div>
        </div>
        ''', unsafe_allow_html=True)

    with _back_col:
        if _has_report:
            st.markdown('<div style="padding-top:0.05rem;">', unsafe_allow_html=True)
            if st.button("← New Search", key="topbar_clear_btn", use_container_width=True):
                st.session_state.cached_report = None
                st.session_state.pop("resolved", None)
                st.session_state.pop("resolved_source", None)
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with _signout_col:
        st.markdown('<div class="pickr-signout-col" style="padding-top:0.05rem;">', unsafe_allow_html=True)
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Past reports history dropdown ──
    try:
        from report_store import load_user_index, load_report as load_saved_report
        past_reports = load_user_index(username)
        if past_reports and len(past_reports) > 0:
            display_reports = list(reversed(past_reports[-10:]))

            _opts = ["History"]
            _rids = [None]
            for r in display_reports:
                tk      = clean_ticker(r["ticker"])
                rec     = r.get("recommendation", "")
                ret     = r.get("expected_return")
                ret_str = f"  {ret*100:+.0f}%" if ret is not None else ""
                date_str = r.get("date", "")
                if date_str and len(date_str) >= 7:
                    date_str = date_str[5:]  # MM-DD
                _opts.append(f"{tk}  ·  {rec}{ret_str}  ·  {date_str}")
                _rids.append(r.get("report_id", f"{r['ticker']}_{r.get('date','')}"))

            sel_label = st.selectbox(
                "History", _opts,
                key="history_select",
                label_visibility="collapsed",
            )
            if sel_label and sel_label != _opts[0]:
                sel_idx = _opts.index(sel_label)
                rid = _rids[sel_idx]
                report_data = load_saved_report(username, rid)
                if report_data:
                    st.session_state.cached_report = {
                        "ticker": report_data["ticker"],
                        "metrics": report_data["metrics"],
                        "analysis": report_data["analysis"],
                        "data": {"hist": None, "info": {}, "inc": None, "qinc": None,
                                 "bs": None, "cf": None, "news": []},
                    }
                    try:
                        st.query_params["ticker"] = report_data["ticker"]
                    except Exception:
                        pass
                    st.session_state["history_select"] = _opts[0]
                    st.rerun()
                else:
                    st.toast("Could not load that report.", icon="⚠️")
                    st.session_state["history_select"] = _opts[0]
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
    _tk_clean = clean_ticker(ticker)
    _website  = data.get("info", {}).get("website", "") if data else ""
    if _website and _tk_clean not in DOMAIN_MAP:
        _domain = _website.split("//")[-1].split("/")[0].replace("www.", "").strip() or f"{_tk_clean.lower()}.com"
    else:
        _domain = DOMAIN_MAP.get(_tk_clean, f"{_tk_clean.lower()}.com")
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
    base_ret = sm.get("scenarios", {}).get("base", {}).get("implied_return", exp_ret)
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
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;overflow:hidden;">'
        f'<div style="display:flex;align-items:center;gap:0.75rem;min-width:0;overflow:hidden;">'
        f'<span style="font-weight:800;font-size:0.95rem;color:#fff;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis;max-width:200px;">{strip_html(company)}</span>'
        f'<span style="font-size:0.78rem;color:rgba(255,255,255,0.35);background:rgba(255,255,255,0.06);'
        f'padding:0.1rem 0.45rem;border-radius:4px;font-weight:600;flex-shrink:0;">{ticker}</span>'
        f'<span style="font-size:0.92rem;color:#fff;font-weight:700;flex-shrink:0;">{_price_str}</span>'
        f'{_spark}</div>'
        f'<div style="display:flex;align-items:center;gap:1.5rem;flex-shrink:0;">'
        f'<div style="text-align:right;"><div style="font-size:0.64rem;font-weight:700;text-transform:uppercase;letter-spacing:0.10em;color:rgba(255,255,255,0.55);margin-bottom:0.1rem;">Verdict</div>'
        f'<div style="font-size:0.97rem;font-weight:800;color:{_rec_color};">{rec}</div></div>'
        f'<div style="text-align:right;"><div style="font-size:0.64rem;font-weight:700;text-transform:uppercase;letter-spacing:0.10em;color:rgba(255,255,255,0.55);margin-bottom:0.1rem;">Base Case</div>'
        f'<div style="font-size:0.97rem;font-weight:800;color:{_rec_color};">{base_ret*100:+.1f}%</div></div>'
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
        <div class="rb-item"><div class="rb-label">Base Case Return</div><div class="rb-val {rc}">{base_ret*100:+.1f}%</div></div>
        <div class="rb-item" title="Probability mass of scenarios whose price target exceeds today's price. With 3 discrete scenarios this only takes values in &#123;0, P(bull), P(bull)+P(base), 1&#125; — it is NOT a continuous probability of a positive 12-month return."><div class="rb-label">P(Target &gt; Today)</div><div class="rb-val {rc}">{prob_pos*100:.0f}%</div></div>
    </div>''', unsafe_allow_html=True)

    if a.get("investment_thesis"):
        st.markdown(f'<div class="exec-summary">{clean_latex(strip_html(a["investment_thesis"]))}</div>', unsafe_allow_html=True)
    if a.get("rec_override_reason"):
        st.markdown(f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);border-radius:8px;padding:1rem 1.2rem;margin:0.8rem 0;font-size:0.88rem;color:#fbbf24;line-height:1.6;">{clean_latex(strip_html(a["rec_override_reason"]))}</div>', unsafe_allow_html=True)
    if a.get("business_overview"):
        st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["business_overview"]))}</div>', unsafe_allow_html=True)

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
        seg_header = "<tr><th>Segment</th><th>Revenue</th><th>% of Total</th><th>Gross Margin</th><th>YoY Growth</th><th>Trajectory</th></tr>"
        seg_rows = ""
        _driver_style = 'font-size:0.78rem;color:rgba(255,255,255,0.4);font-weight:400;margin-top:0.25rem;line-height:1.5;'
        for seg in segments:
            traj = strip_html(seg.get("trajectory", ""))
            tcolor = "#4ade80" if "accel" in traj.lower() else ("#f87171" if "decel" in traj.lower() else "#fbbf24")
            _driver = strip_html(seg.get("primary_driver", ""))
            _driver_html = f'<div style="{_driver_style}">{_driver}</div>' if _driver else ""
            seg_rows += (
                f'<tr>'
                f'<td style="font-weight:600;min-width:160px;">'
                f'{strip_html(seg.get("name",""))}{_driver_html}'
                f'</td>'
                f'<td class="nowrap">{fmt_c(seg.get("current_revenue"), cur)}</td>'
                f'<td class="nowrap">{fmt_p(seg.get("pct_of_total"))}</td>'
                f'<td class="nowrap">{fmt_p(seg.get("gross_margin"))}</td>'
                f'<td class="nowrap">{fmt_p(seg.get("yoy_growth"))}</td>'
                f'<td class="nowrap" style="color:{tcolor};">{traj}</td>'
                f'</tr>'
            )
        st.markdown(pt_table(seg_header, seg_rows), unsafe_allow_html=True)

    if a.get("revenue_architecture"):
        st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["revenue_architecture"]))}</div>', unsafe_allow_html=True)

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
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["growth_drivers"]))}</div>', unsafe_allow_html=True)
    if a.get("margin_analysis"):
        st.markdown('<div class="sec">Margin Analysis</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["margin_analysis"]))}</div>', unsafe_allow_html=True)
    if a.get("financial_health"):
        st.markdown('<div class="sec">Financial Health</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["financial_health"]))}</div>', unsafe_allow_html=True)

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
            tr_c = "<tr class='hl'>" + "".join(f"<td class='nowrap'>{cur_row[hd]}</td>" for hd in hds) + "</tr>"
            tr_p = "".join(
                "<tr>" + "".join(f"<td class='nowrap'>{pr.get(hd, '-')}</td>" for hd in hds) + "</tr>"
                for pr in peers
            )
            st.markdown(pt_table(f"<tr>{th}</tr>", tr_c + tr_p), unsafe_allow_html=True)

    if a.get("competitive_position"):
        st.markdown('<div class="sec">Competitive Position</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["competitive_position"]))}</div>', unsafe_allow_html=True)

    # ── Headwinds & Tailwinds ──
    # FIX: This block was dedented out of render() in the original, making a, cur, sym
    #      undefined at module level. It is now correctly inside render().
    headwinds = a.get("headwinds", [])
    tailwinds = a.get("tailwinds", [])
    if headwinds or tailwinds:
        st.markdown('<div class="sec">What Could Go Wrong &amp; What Could Go Right <span class="vtag">Quantified</span></div>', unsafe_allow_html=True)
        if a.get("headwind_narrative"):
            st.markdown(f'<div class="prose">{clean_latex(strip_html(a["headwind_narrative"]))}</div>', unsafe_allow_html=True)
        if headwinds:
            hw_header = "<tr><th>Headwind</th><th>Prob.</th><th>Rev. at Risk</th><th>Bull EPS</th><th>Base EPS</th><th>Bear EPS</th></tr>"
            # FIX: was using `tw` variable inside headwind loop — corrected to `hw`
            # FIX: fmt_eps_impact now receives `sym` and correct is_headwind=True for headwinds
            hw_rows = "".join(
                f'<tr>'
                f'<td style="font-weight:600;">{strip_html(hw.get("name",""))}</td>'
                f'<td class="nowrap">{fmt_p(hw.get("probability"))}</td>'
                f'<td class="nowrap">{fmt_c(hw.get("revenue_at_risk"), cur)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(hw.get("bull_eps_impact", 0), sym, is_headwind=True)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(hw.get("base_eps_impact", 0), sym, is_headwind=True)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(hw.get("bear_eps_impact", 0), sym, is_headwind=True)}</td>'
                f'</tr>'
                for hw in headwinds
            )
            st.markdown(pt_table(hw_header, hw_rows), unsafe_allow_html=True)
        if a.get("tailwind_narrative"):
            st.markdown(f'<div class="prose" style="margin-top:1rem;">{clean_latex(strip_html(a["tailwind_narrative"]))}</div>', unsafe_allow_html=True)
        if tailwinds:
            tw_header = "<tr><th>Tailwind</th><th>Prob.</th><th>Rev. Opportunity</th><th>Bull EPS</th><th>Base EPS</th><th>Bear EPS</th></tr>"
            # FIX: fmt_eps_impact now receives `sym` — was missing in original tailwind call
            tw_rows = "".join(
                f'<tr>'
                f'<td style="font-weight:600;">{strip_html(tw.get("name",""))}</td>'
                f'<td class="nowrap">{fmt_p(tw.get("probability"))}</td>'
                f'<td class="nowrap">{fmt_c(tw.get("revenue_opportunity"), cur)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("bull_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("base_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("bear_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'</tr>'
                for tw in tailwinds
            )
            st.markdown(pt_table(tw_header, tw_rows), unsafe_allow_html=True)

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
            dname     = strip_html(d.get("name", ""))
            dmeasures = strip_html(d.get("measures", ""))
            bull_p    = safe_float(d.get("bull_outcome", {}).get("probability"))
            base_p    = safe_float(d.get("base_outcome", {}).get("probability"))
            bear_p    = safe_float(d.get("bear_outcome", {}).get("probability"))
            bull_n    = strip_html(d.get("bull_outcome", {}).get("description", ""))[:120]
            base_n    = strip_html(d.get("base_outcome", {}).get("description", ""))[:120]
            bear_n    = strip_html(d.get("bear_outcome", {}).get("description", ""))[:120]
            bw   = max(2, min(100, round(bull_p*100)))
            basew = max(2, min(100, round(base_p*100)))
            bearw = max(2, min(100, round(bear_p*100)))
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
        bull_score = prob_out.get("bull_score")
        signal_detail = prob_out.get("signal_detail", []) or []
        active_signals = [s for s in signal_detail
                          if isinstance(s, dict) and s.get("delta") not in (0, 0.0, None)]
        score_str = f"{bull_score:.1f}/100" if bull_score is not None else "N/A"
        st.markdown(f'''<div class="plain-callout">
            <div class="plain-callout-label">Weights derived from fundamentals scoring</div>
            Scenario weights come from an 8-signal scoring engine on the company's fundamentals
            (EPS revision momentum, revenue and earnings CAGR, operating margin, PEG, debt-to-equity,
            beta, and price vs 200-day MA). Bull score: <strong>{score_str}</strong>
            ({len(active_signals)} of {len(signal_detail)} signals materially active).
            The qualitative factor distributions shown above are narrative context; they do not
            mathematically drive the weights below.
        </div>''', unsafe_allow_html=True)
        if active_signals:
            with st.expander("Show signal breakdown"):
                for sig in active_signals:
                    name  = strip_html(str(sig.get("signal", "")))
                    delta = sig.get("delta", 0) or 0
                    note  = strip_html(str(sig.get("note", "")))
                    color = "#4ade80" if delta > 0 else "#f87171"
                    sign  = "+" if delta > 0 else ""
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:0.82rem;padding:0.25rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">'
                        f'<span style="color:rgba(255,255,255,0.7);">{name}</span>'
                        f'<span style="color:rgba(255,255,255,0.45);font-size:0.78rem;">{note}</span>'
                        f'<span style="color:{color};font-weight:700;min-width:3rem;text-align:right;">{sign}{delta:.1f}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
        bull_pct = f"{fb*100:.0f}"; base_pct = f"{fba*100:.0f}"; bear_pct = f"{fbe*100:.0f}"
        _bw  = max(2, min(96, round(fb*100)))
        _baw = max(2, min(96, round(fba*100)))
        _bew = max(2, min(96, round(fbe*100)))
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
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["scenario_commentary"]))}</div>', unsafe_allow_html=True)

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
            prob      = s.get("probability", 0) * 100
            pt        = s.get("price_target", 0)
            ret       = s.get("implied_return", 0) * 100
            eps       = s.get("projected_eps", 0)
            pe        = s.get("pe_multiple", 0)
            bpe       = s.get("breakeven_pe")
            op_m      = s.get("operating_margin", 0)
            total_rev = s.get("total_revenue", 0)
            fcf_y     = s.get("fcf_yield_at_target")
            # FIX: narrative and pe_rat were on a broken split line — now correct single assignments
            narrative  = clean_latex(strip_html(s.get("narrative", "")))
            pe_rat     = strip_html(s.get("pe_rationale", ""))
            margin_rat = strip_html(s.get("margin_rationale", ""))
            eps_flag   = s.get("eps_flag")

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
                # FIX: was `{clean_latex(strip_html(eps_flag)}</div>` — mismatched brackets, now fixed
                if eps_flag:   st.markdown(f'<div style="font-size:0.82rem;color:#fbbf24;margin-top:0.5rem;font-style:italic;">{clean_latex(strip_html(eps_flag))}</div>', unsafe_allow_html=True)

    # ── EV reconciliation: show the actual probability-weighted math ──
    # Resolves the apparent mismatch where displayed integer probabilities
    # (e.g. 40%/50%/10%) don't quite reproduce the displayed EV when the
    # underlying probabilities carry 3-decimal precision.
    if bull_s and base_s and bear_s:
        bu_p = bull_s.get("probability", 0); bu_t = bull_s.get("price_target", 0)
        ba_p = base_s.get("probability", 0); ba_t = base_s.get("price_target", 0)
        be_p = bear_s.get("probability", 0); be_t = bear_s.get("price_target", 0)
        ev_check = bu_p * bu_t + ba_p * ba_t + be_p * be_t
        st.markdown(
            f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.55);'
            f'margin:0.6rem 0 1rem;padding:0.6rem 0.9rem;'
            f'background:rgba(255,255,255,0.02);border-left:2px solid rgba(255,255,255,0.15);'
            f'border-radius:4px;font-family:ui-monospace,monospace;">'
            f'Probability-weighted EV = '
            f'{bu_p:.3f}×{sym}{bu_t:,.2f} + '
            f'{ba_p:.3f}×{sym}{ba_t:,.2f} + '
            f'{be_p:.3f}×{sym}{be_t:,.2f} = '
            f'<strong style="color:rgba(255,255,255,0.85);">{sym}{ev_check:,.2f}</strong>'
            f'</div>',
            unsafe_allow_html=True
        )

    if a.get("market_pricing_commentary"):
        st.markdown('<div class="sec">Valuation vs Expectations</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["market_pricing_commentary"]))}</div>', unsafe_allow_html=True)

    ras      = sm.get("risk_adjusted_score", 0)
    ud_ratio = sm.get("upside_downside_ratio", 0)
    mdd      = abs(sm.get("max_drawdown_magnitude", 0)) * 100
    mdd_prob = sm.get("max_drawdown_prob", 0) * 100
    rfr      = sm.get("risk_free_rate", 0.06) * 100
    std_dev  = sm.get("std_dev", 0) * 100
    ras_color  = "#4ade80" if ras > 1.0 else ("#fbbf24" if ras > 0.3 else "#f87171")
    ret_color  = "positive" if exp_ret > 0.05 else ("neutral" if exp_ret > 0 else "negative")
    ud_display = "inf" if ud_ratio == float("inf") else f"{ud_ratio:.2f}x"
    ud_color   = "#4ade80" if ud_ratio > 1.5 or ud_ratio == float("inf") else ("#fbbf24" if ud_ratio > 1.0 else "#f87171")
    st.markdown('<div class="sec">The Bottom Line</div>', unsafe_allow_html=True)
    st.markdown(f'''<div class="ev-bar">
        <div class="ev-item"><div class="ev-label">Expected Value</div><div class="ev-val">{sym}{ev:,.2f}</div></div>
        <div class="ev-item"><div class="ev-label">Base Case</div><div class="ev-val {ret_color}">{base_ret*100:+.1f}%</div></div>
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
        current_p   = safe_float(sensitivity.get("current_bull_probability")) * 100
        ev_plus     = safe_float(sensitivity.get("ev_if_bull_plus_10"))
        ev_minus    = safe_float(sensitivity.get("ev_if_bull_minus_10"))
        interp      = strip_html(sensitivity.get("interpretation", ""))
        st.markdown('<div class="sec">What If? <span class="vtag">Sensitivity Check</span></div>', unsafe_allow_html=True)
        st.markdown(f'''<div style="background:#0e0e14;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:1.2rem 1.5rem;margin:0.8rem 0;">
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.55);margin-bottom:1rem;">
                What happens to the expected value if we change the bull probability on <strong style="color:#fff;">{driver_name}</strong>?
            </div>
            <div style="display:flex;justify-content:center;gap:2.5rem;flex-wrap:wrap;">
                <div style="text-align:center;"><div style="font-size:0.82rem;color:#f87171;font-weight:600;">Bull Prob -10pp ({current_p-10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#f87171;">{sym}{ev_minus:,.2f}</div></div>
                <div style="text-align:center;"><div style="font-size:0.82rem;color:rgba(255,255,255,0.5);font-weight:600;">Current ({current_p:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#fff;">{sym}{ev:,.2f}</div></div>
                <div style="text-align:center;"><div style="font-size:0.82rem;color:#4ade80;font-weight:600;">Bull Prob +10pp ({current_p+10:.0f}%)</div><div style="font-size:1.3rem;font-weight:800;color:#4ade80;">{sym}{ev_plus:,.2f}</div></div>
            </div>
            <div style="text-align:center;font-size:0.85rem;font-style:italic;color:rgba(255,255,255,0.4);margin-top:1rem;">{interp}</div>
        </div>''', unsafe_allow_html=True)

    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">What to Watch</div>', unsafe_allow_html=True)
        cat_header = "<tr><th>Date</th><th>Event</th><th>Positive Signal</th><th>Negative Signal</th></tr>"
        cat_rows = "".join(
            f'<tr>'
            f'<td class="nowrap" style="font-weight:600;">{strip_html(c.get("date",""))}</td>'
            f'<td>{strip_html(c.get("event",""))}</td>'
            f'<td style="color:#4ade80;">{strip_html(c.get("positive_signal", c.get("bull_signal", "")))}</td>'
            f'<td style="color:#f87171;">{strip_html(c.get("negative_signal", c.get("bear_signal", "")))}</td>'
            f'</tr>'
            for c in catalysts
        )
        st.markdown(pt_table(cat_header, cat_rows), unsafe_allow_html=True)

    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["conclusion"]))}</div>', unsafe_allow_html=True)

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
        <p style="color:rgba(255,255,255,0.5);font-size:0.9rem;line-height:1.65;margin:0 0 1rem;">
        Get an email when <strong style="color:#fff;">{strip_html(company)}</strong> hits your target price.
        Thesis target: <strong style="color:{rec_color};">{sym}{suggested_target:,.2f}</strong></p></div>''', unsafe_allow_html=True)

    col1, col2 = st.columns([1.4, 1])
    with col1:
        user_email = st.text_input(
            "Email address", placeholder="you@example.com",
            key=f"track_email_{ticker}",
            help="Used only for price alerts — never shared."
        )
    with col2:
        target_price = st.number_input(
            f"Alert price ({sym})", min_value=0.01,
            value=suggested_target, step=0.50,
            key=f"track_target_{ticker}", format="%.2f"
        )

    thesis_snapshot  = strip_html(a.get("investment_thesis", ""))
    metrics_snapshot = {k: m.get(k) for k in ["trailing_pe","forward_pe","peg_ratio","operating_margin","roe","revenue_growth","revenue_cagr","fcf_yield","debt_to_equity","ev_to_ebitda"]}

    if st.button("Set Alert", key=f"track_btn_{ticker}", type="primary"):
        if not user_email or "@" not in user_email:
            st.toast("Enter a valid email address.", icon="⚠️")
        elif not GMAIL_SENDER or not GMAIL_APP_PASS:
            st.toast("Email alerts are not configured yet.", icon="ℹ️")
        else:
            gh_ok, gh_err = add_tracked_stock(ticker, company, rec, target_price, cp, metrics_snapshot, thesis_snapshot, user_email)
            ok, err = email_confirmation(user_email, ticker, company, rec, f"{sym}{target_price:,.2f}", f"{sym}{cp:,.2f}")
            if gh_ok and ok:
                st.toast(f"Alert set! Confirmation sent to {user_email}", icon="✅")
                st.session_state.track_success = ("green", f"Alert set! Confirmation sent to {user_email}")
            elif gh_ok and not ok:
                st.toast(f"Alert saved. Email delivery failed: {err}", icon="⚠️")
                st.session_state.track_success = ("green", f"Alert saved. (Email failed: {err})")
            elif not gh_ok and ok:
                st.toast("Confirmation sent but save failed.", icon="⚠️")
                st.session_state.track_success = ("yellow", f"Email sent but save failed: {gh_err}")
            else:
                st.toast("Something went wrong. Please try again.", icon="❌")
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
        tk      = clean_ticker(p.get("ticker", ""))
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

    rows_html = ""
    for i, pick in enumerate(picks):
        score    = pick.get("qglp_score", 0)
        sc       = "#4ade80" if score >= 85 else ("#fbbf24" if score >= 70 else "#f87171")
        roe      = pick.get("roe", 0)
        cagr     = pick.get("earnings_cagr", 0)
        peg      = float(pick.get("peg_ratio") or 0)
        tk       = pick.get("ticker", "")
        name     = pick.get("name", tk)
        tk_clean = clean_ticker(tk)
        _ini     = tk_clean[:1].upper()
        _domain  = DOMAIN_MAP.get(tk_clean, f"{tk_clean.lower()}.com")

        logo_html = (
            f'<img src="https://www.google.com/s2/favicons?domain={_domain}&sz=64" '
            f'width="18" height="18" loading="lazy" '
            f'style="border-radius:4px;object-fit:contain;background:#111118;'
            f'border:1px solid rgba(255,255,255,0.08);vertical-align:middle;margin-right:0.45rem;" '
            f'onerror="this.style.display=\'none\';">'
        )
        rows_html += (
            f'<tr>'
            f'<td style="padding:0.7rem 0.7rem;white-space:nowrap;">'
            f'<span style="display:inline-flex;align-items:center;">'
            f'{logo_html}'
            f'<strong style="color:#fff;font-weight:800;margin-right:0.4rem;">{tk_clean}</strong>'
            f'</span>'
            f'<span class="co-name" title="{name}">{name}</span>'
            f'</td>'
            f'<td class="right" style="padding:0.7rem 0.7rem;font-weight:800;color:{sc};white-space:nowrap;">{score:.0f}</td>'
            f'<td class="right" style="padding:0.7rem 0.7rem;color:rgba(255,255,255,0.7);white-space:nowrap;">{peg:.2f}</td>'
            f'<td class="right" style="padding:0.7rem 0.7rem;color:rgba(255,255,255,0.7);white-space:nowrap;">{roe*100:.0f}%</td>'
            f'<td class="right" style="padding:0.7rem 0.7rem;color:#4ade80;font-weight:600;white-space:nowrap;">+{cagr*100:.0f}%</td>'
            f'</tr>'
        )

    st.markdown(
        f'<table class="picks-table">'
        f'<thead><tr>'
        f'<th>Company</th>'
        f'<th class="right">Score</th>'
        f'<th class="right">PEG</th>'
        f'<th class="right">ROE</th>'
        f'<th class="right">EPS CAGR</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>',
        unsafe_allow_html=True
    )

    btn_cols = st.columns(len(picks))
    for i, (pick, col) in enumerate(zip(picks, btn_cols)):
        tk       = pick.get("ticker", "")
        tk_clean = clean_ticker(tk)
        with col:
            if st.button(f"{tk_clean} →", key=f"{select_key}_btn_{i}",
                         type="secondary", use_container_width=True,
                         help=f"Generate full report for {tk_clean}"):
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
        '<h1 style="font-size:2rem;font-weight:800;color:#fff;margin:0 0 0.5rem;'
        'line-height:1.25;letter-spacing:-0.02em;">'
        'Institutional-grade equity research. <span style="color:#c03030">In 120 seconds.</span></h1>'
        '<p style="font-size:1.02rem;color:rgba(255,255,255,0.55);line-height:1.8;'
        'max-width:620px;margin:0 0 1rem;">'
        'QGLP scoring across 24 verified metrics, three probability-weighted scenarios, '
        'and a full analyst narrative — for any listed company.</p>'
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;">'
        '<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.78rem;'
        'font-weight:600;color:rgba(255,255,255,0.75);background:rgba(74,222,128,0.08);'
        'border:1px solid rgba(74,222,128,0.22);border-radius:20px;padding:0.2rem 0.7rem;">'
        '&#10003; No credit card</span>'
        '<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.78rem;'
        'font-weight:600;color:rgba(255,255,255,0.75);background:rgba(74,222,128,0.08);'
        'border:1px solid rgba(74,222,128,0.22);border-radius:20px;padding:0.2rem 0.7rem;">'
        '&#10003; 3 free reports</span>'
        '<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.78rem;'
        'font-weight:600;color:rgba(255,255,255,0.75);background:rgba(74,222,128,0.08);'
        'border:1px solid rgba(74,222,128,0.22);border-radius:20px;padding:0.2rem 0.7rem;">'
        '&#10003; US &amp; India stocks</span>'
        '</div>'
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

    _qt = st.query_params.get("_qt", "")
    if _qt:
        try: st.query_params.clear()
        except Exception: pass
        st.session_state["resolved"] = _qt.strip().upper()
        st.session_state["resolved_source"] = "quickticker"
        if st.session_state.get("authenticated"):
            st.session_state["auto_generate"] = True
        st.rerun()

    _ticker_qp = st.query_params.get("ticker", "")
    if _ticker_qp and not st.session_state.get("cached_report"):
        try: st.query_params.clear()
        except Exception: pass
        st.session_state["resolved"] = _ticker_qp.strip().upper()
        st.session_state["resolved_source"] = "quickticker"
        if st.session_state.get("authenticated"):
            st.session_state["auto_generate"] = True
        st.rerun()

    if sq and len(sq) >= 2:
        with st.spinner(""):
            res = search_ticker(sq)
        if res:
            cards = ""
            for r in res[:6]:
                name = r.get("name", r["symbol"])
                sym  = r["symbol"]
                exch = r.get("exchange", "")
                tk   = clean_ticker(sym)
                dom  = DOMAIN_MAP.get(tk, f"{tk.lower()}.com")
                exch_badge = f'<span class="sr-exch">{exch}</span>' if exch else ""
                cards += (
                    f'<a href="?_qt={sym}" target="_self" class="sr-row">'
                    f'<img src="https://www.google.com/s2/favicons?domain={dom}&sz=32"'
                    f' width="20" height="20" class="sr-ico"'
                    f' onerror="this.style.display=\'none\'">'
                    f'<span class="sr-name">{name}</span>'
                    f'<span class="sr-sym">{sym}</span>'
                    f'{exch_badge}</a>'
                )
            st.markdown(f"""
<style>
.sr-wrap{{border:1px solid rgba(255,255,255,0.07);border-radius:10px;
    overflow:hidden;margin:0.4rem 0;background:#0d0d16;}}
.sr-row{{display:flex;align-items:center;gap:0.7rem;
    padding:0.6rem 0.9rem;text-decoration:none;color:inherit;
    border-bottom:1px solid rgba(255,255,255,0.04);transition:background 0.12s;}}
.sr-row:last-child{{border-bottom:none;}}
.sr-row:hover{{background:rgba(255,255,255,0.04);}}
.sr-ico{{border-radius:4px;flex-shrink:0;}}
.sr-name{{flex:1;font-size:0.88rem;color:rgba(255,255,255,0.75);
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.sr-sym{{font-size:0.76rem;font-weight:700;color:rgba(255,255,255,0.5);
    background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);
    padding:0.1rem 0.4rem;border-radius:4px;flex-shrink:0;}}
.sr-exch{{font-size:0.72rem;color:rgba(255,255,255,0.2);flex-shrink:0;}}
</style>
<div class="sr-wrap">{cards}</div>""", unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="font-size:0.84rem;color:rgba(255,255,255,0.35);'
                f'padding:0.5rem 0;">No companies found for <em>"{sq}"</em></div>',
                unsafe_allow_html=True
            )
            if len(sq) <= 8 and sq.replace(".", "").replace("-", "").isalnum():
                if st.button(f"Try '{sq.upper()}' as a ticker anyway",
                             key=f"try_{sq}"):
                    st.session_state["resolved"] = sq.strip().upper()
                    st.session_state.pop("resolved_source", None)
                    st.rerun()
    else:
        pop_keys   = [k for k in POPULAR if k]
        recent_rev = list(reversed(st.session_state.recent[-6:]))

        if pop_keys and recent_rev:
            qc1, qc2 = st.columns([1, 1])
            with qc1:
                sp = st.selectbox("Popular", ["Popular stocks"] + pop_keys,
                                  label_visibility="collapsed", key="s3")
                if sp and sp != "Popular stocks" and POPULAR.get(sp):
                    st.session_state["resolved"] = POPULAR[sp]
                    st.session_state["resolved_source"] = "popular"
            with qc2:
                sr = st.selectbox("Recent", ["Recent searches"] + recent_rev,
                                  label_visibility="collapsed", key="s_recent")
                if sr and sr != "Recent searches":
                    st.session_state["resolved"] = sr
                    st.session_state["resolved_source"] = "recent"
        elif pop_keys:
            sp = st.selectbox("Popular stocks", ["Popular stocks"] + pop_keys,
                              label_visibility="collapsed", key="s3")
            if sp and sp != "Popular stocks" and POPULAR.get(sp):
                st.session_state["resolved"] = POPULAR[sp]
                st.session_state["resolved_source"] = "popular"
        elif recent_rev:
            sr = st.selectbox("Recent searches", ["Recent searches"] + recent_rev,
                              label_visibility="collapsed", key="s_recent")
            if sr and sr != "Recent searches":
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
            f'{clean_ticker(resolved_now)}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)

    if not authenticated:
        _cta_c1, _cta_c2 = st.columns(2)
        with _cta_c1:
            if st.button("Continue as Guest", key="cta_guest_btn", use_container_width=True):
                st.session_state["show_auth"] = True
                st.rerun()
        with _cta_c2:
            if st.button("Create free account", key="cta_signup_btn", type="primary", use_container_width=True):
                st.session_state["show_auth"] = True
                st.rerun()
        st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)

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

    st.markdown(f'<div style="{_head}margin-bottom:0.7rem;">Account</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div style="background:#111118;border:1px solid rgba(255,255,255,0.07);'
        'border-radius:8px;padding:0.85rem 1rem;margin-bottom:0.5rem;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.35rem;">'
        '<span style="font-size:0.82rem;font-weight:700;color:rgba(255,255,255,0.6);">Guest</span>'
        '<span style="font-size:0.72rem;color:rgba(255,255,255,0.35);">No signup</span>'
        '</div>'
        '<div style="font-size:0.8rem;color:rgba(255,255,255,0.45);line-height:1.6;">'
        '1 report &middot; No history saved</div>'
        '</div>'
        '<div style="background:#111118;border:1px solid rgba(192,48,48,0.3);'
        'border-radius:8px;padding:0.85rem 1rem;margin-bottom:0.6rem;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.35rem;">'
        '<span style="font-size:0.82rem;font-weight:700;color:#fff;">Free account</span>'
        '<span style="font-size:0.72rem;color:#c03030;font-weight:600;">3 reports</span>'
        '</div>'
        '<div style="font-size:0.8rem;color:rgba(255,255,255,0.55);line-height:1.6;">'
        'History saved &middot; Price alerts &middot; Always free</div>'
        '</div>',
        unsafe_allow_html=True
    )
    if not authenticated:
        if st.button("Sign up free →", key="rc_signup_btn", use_container_width=True):
            st.session_state["show_auth"] = True
            st.rerun()

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
_bar_is_admin = not is_guest and username.lower() in {"mayukhk"}
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
    elif _bar_is_admin:
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:0.8rem;
        background:rgba(14,14,20,0.9);border:1px solid rgba(255,255,255,0.07);
        border-radius:7px;padding:0.6rem 1rem;margin-bottom:0.6rem;">
            <span style="font-size:0.8rem;color:rgba(255,255,255,0.45);">
                Reports: <strong style="color:#fff">{report_count}/∞</strong></span>
            <span style="font-size:0.72rem;color:#c084fc;font-weight:700;">Admin · Unlimited</span>
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
    st.toast("Select or enter a company first.", icon="👆")

if should_generate and ticker:
    GUEST_LIMIT = 1
    USER_LIMIT  = 3
    _is_admin   = not is_guest and username.lower() in {"mayukhk"}

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

    elif not is_guest and not _is_admin and report_count >= USER_LIMIT:
        st.warning(f"You've used all {USER_LIMIT} free reports. Paid tiers are coming soon.")
        st.stop()

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
    try:
        st.query_params["ticker"] = ticker
    except Exception:
        pass

    _rec_emoji = {"BUY": "✅", "PASS": "🔴", "WATCH": "🟡"}.get(rec.upper(), "📊")
    st.toast(f"{_rec_emoji} {ticker}: {rec} — scroll down to view", icon=None)

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
            st.toast(f"{c_ticker} saved to history.", icon="💾")
        except Exception as e:
            print(f"Report save failed: {e}")

    with report_area:
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

        _rec_now = c_a.get("recommendation","WATCH").upper()
        _rc_col  = {"BUY":"#4ade80","PASS":"#f87171"}.get(_rec_now,"#fbbf24")

        _report_bar_col, _new_search_col = st.columns([5, 1])
        with _report_bar_col:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:0.75rem;'
                f'background:rgba(14,14,20,0.9);border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:8px;padding:0.55rem 1.2rem;margin-bottom:0.4rem;">'
                f'<span style="font-size:0.82rem;color:rgba(255,255,255,0.5);">Report:</span>'
                f'<strong style="color:#fff;font-size:0.9rem;">{c_ticker}</strong>'
                f'<span style="color:{_rc_col};font-weight:700;font-size:0.88rem;">{_rec_now}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        with _new_search_col:
            st.markdown('<div style="padding-top:0.05rem;">', unsafe_allow_html=True)
            if st.button("← New Search", key="clear_report_btn", use_container_width=True):
                st.session_state.cached_report = None
                st.session_state.pop("resolved", None)
                st.session_state.pop("resolved_source", None)
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        render(c_ticker, c_m, c_a, c_data)
        render_track_box(c_ticker, c_m, c_a)

        st.markdown('<hr class="div" style="margin-top:2rem;">', unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;padding:0.8rem 0 0.5rem;"><div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div></div>', unsafe_allow_html=True)

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