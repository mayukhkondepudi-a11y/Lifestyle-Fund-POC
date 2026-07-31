"""PickR - Streamlit UI and rendering."""

import streamlit as st
import pandas as pd
import json
from datetime import datetime
from compute import clean_latex

st.set_page_config(page_title="PickR", page_icon="P", layout="wide", initial_sidebar_state="collapsed")

import streamlit.components.v1 as _sc
assert hasattr(_sc, "html"), (
    "_sc must be the streamlit.components.v1 module (has .html); "
    "if you're seeing this, a local variable has shadowed _sc somewhere."
)
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
                    DOMAIN_MAP, METHODOLOGY_VERSION, ADMIN_USERS)
from formatting import (safe_float, get_sym, fmt_p, fmt_r, fmt_c,
                         strip_html, clean_ticker)

# Test seam. None in production; a module only when PICKR_OFFLINE=1, which lets
# tests_app_flows.py drive the real app without FMP/Anthropic/GitHub.
try:
    import offline_mode as _offline_mode
    if not _offline_mode.enabled():
        _offline_mode = None
except Exception:
    _offline_mode = None

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

from github_store import add_tracked_stock
from email_service import email_confirmation
from compute import calc, calc_baseline
import ai
import fmp_api

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

# Persisted-session cookie: instantiate the CookieManager exactly once per run
# (top-level code runs once per rerun) so auth survives the full page reload that
# stock-selection anchor links trigger. auth.py reuses this same instance.
import extra_streamlit_components as stx
from session_cookie import restore_session_from_cookie
st.session_state["_cookie_mgr"] = stx.CookieManager(key="pickr_cookies")

for _k in ["authenticated", "username", "user_name", "user_email", "is_guest", "show_auth"]:
    if _k not in st.session_state:
        st.session_state[_k] = False if _k in ("authenticated","is_guest","show_auth") else ""
if "initialized" not in st.session_state:
    st.session_state["show_auth"] = False
    st.session_state["initialized"] = True

# Restore identity from the cookie before any auth-gated logic reads it.
_restored = restore_session_from_cookie()

# A guest's report lives only in session_state, which a full page reload wipes —
# and every ?_qt= ticker chip IS a full reload. Without this, a guest could pay
# (in tokens) for a report and lose it to a single click, with no way to get it
# back because their one-report allowance was already spent.
if (_restored and st.session_state.get("is_guest")
        and not st.session_state.get("cached_report")
        and st.session_state.get("_guest_report_ticker")):
    try:
        from report_store import load_guest_report
        _gr = load_guest_report(st.session_state.get("guest_fingerprint", ""))
        if _gr and _gr.get("analysis"):
            st.session_state["cached_report"] = {
                "ticker":   _gr["ticker"],
                "metrics":  _gr.get("metrics", {}),
                "analysis": _gr["analysis"],
                "data":     {"hist": None, "info": {}, "inc": None, "qinc": None,
                             "bs": None, "cf": None, "news": []},
            }
    except Exception as _e:
        print(f"  guest report restore failed: {type(_e).__name__}: {_e}")

# Cookie-hydration gate.
#
# extra_streamlit_components' CookieManager reads document.cookie in a browser
# round-trip and reports {} until that lands. Every ?_qt= ticker chip is an
# <a href> — a FULL page reload — so session_state is wiped and identity has to
# come back from the cookie on each stock pick.
#
# This used to wait a fixed 0.4s (2 x 0.2s) and then assume "no cookie" — so any
# slower round-trip, which is routine on Streamlit Cloud, signed the user out
# just for clicking a stock. That is the same mistake as the rest of this
# codebase made with GitHub: treating "no answer yet" as "the answer is no".
#
# cookies_hydrated() is a real signal (the component has reported or it hasn't),
# so we now wait on the CONDITION and exit the instant it is met. The counter is
# only a backstop against a component that never arrives. Net effect: faster in
# the common case (no fixed sleep once hydrated) and far more tolerant on slow
# connections. session_state is wiped per reload, so this re-arms each time.
_COOKIE_MAX_WAITS = 8       # x 0.15s => up to ~1.2s, vs 0.4s before
if not st.session_state.get("authenticated"):
    from session_cookie import cookies_hydrated
    _cw = st.session_state.get("_cookie_waits", 0)
    if not cookies_hydrated() and _cw < _COOKIE_MAX_WAITS:
        st.session_state["_cookie_waits"] = _cw + 1
        import time as _t
        _t.sleep(0.15)
        st.rerun()
    elif _restored is False and _cw > 0 and cookies_hydrated():
        # Component answered and there was no valid session cookie — genuinely
        # logged out. Recorded so the reason is visible in logs if a user
        # reports being signed out unexpectedly.
        print(f"  cookie gate: hydrated after {_cw} wait(s), no valid session — logged out")

if st.session_state.get("show_auth"):
    render_auth_modal()
    if st.session_state.pop("_just_authed", False):
        st.session_state["_generating"] = False  # clear any stuck state from pre-auth button press
        st.rerun()
    st.stop()  # halt the rest of the page so it doesn't paint behind the auth UI

if st.query_params.get("_si") == "1":
    try:
        st.query_params.clear()
    except Exception:
        pass  # URL cosmetics only — deliberately silent (sweep-reviewed)
    st.session_state["show_auth"] = True
    st.rerun()

authenticated = st.session_state.get("authenticated", False)
name     = st.session_state.get("user_name", "")
username = st.session_state.get("username", "")
is_guest = st.session_state.get("is_guest", False)

# Diagnostic: log when auth state is observed (helps detect session loss across reruns)
if authenticated and not st.session_state.get("_auth_logged"):
    print(f"  auth: user '{username}' authenticated, session active")
    st.session_state["_auth_logged"] = True


def _render_generation_failure(ticker, reason, details=None, is_admin=False):
    """Explain a failed report honestly, and say the allowance was not spent.

    Reaching here means no report was produced. The count is only incremented
    after cached_report is set, so the user genuinely still has their quota —
    saying so is what keeps a failure from feeling like theft.
    """
    st.markdown(
        f'<div style="background:rgba(139,26,26,0.12);border:1px solid rgba(224,48,48,0.3);'
        f'border-radius:10px;padding:1.5rem 1.8rem;margin:1rem 0;">'
        f'<div style="font-size:1.05rem;font-weight:800;color:#fff;margin-bottom:0.5rem;">'
        f'Couldn\'t finish the {ticker} report</div>'
        f'<div style="font-size:0.9rem;color:rgba(255,255,255,0.55);line-height:1.7;">'
        f'Something failed part-way through the analysis. '
        f'<strong style="color:#fff;">This did not use up one of your reports</strong> — '
        f'you can try again right away.</div></div>',
        unsafe_allow_html=True
    )
    if st.button("Try again", type="primary", key=f"retry_{ticker}"):
        st.session_state["resolved"] = ticker
        st.session_state["auto_generate"] = True
        st.rerun()
    if is_admin:
        with st.expander("Diagnostics (admin only)"):
            st.code(str(reason))
            for d in (details or []):
                st.code(str(d))


def _screener_age_days(last_updated):
    """Age in days of a 'YYYY-MM-DD HH:MM UTC' stamp, or None if unparseable."""
    from datetime import timezone
    try:
        ts = datetime.strptime(str(last_updated)[:16], "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).days
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# HEALTH BANNER
# ══════════════════════════════════════════════════════════════
# A dependency outage must be visible. Previously an expired GitHub token
# degraded four features at once with no signal anywhere in the UI, so the
# app looked randomly broken rather than misconfigured.

_health = None
try:
    import preflight
    _health = preflight.cached()
except Exception as _e:
    print(f"  preflight unavailable: {type(_e).__name__}: {_e}")

if _health is not None and _health.degraded:
    _is_admin_viewer = bool(authenticated and not is_guest
                            and username.lower() in ADMIN_USERS)
    _fails = _health.failures
    if _is_admin_viewer:
        # Operator view: name the fault and the remedy.
        _rows = "".join(
            f'<div style="margin-top:0.35rem;"><strong style="color:#f87171;">{c.name}</strong>'
            f'<span style="color:rgba(255,255,255,0.55);"> — {c.detail}</span>'
            + (f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.4);'
               f'margin-left:0.4rem;">↳ {c.remedy}</div>' if c.remedy else "")
            + '</div>'
            for c in (_fails + _health.warnings)
        )
        st.markdown(
            f'<div style="background:rgba(139,26,26,0.14);border:1px solid rgba(224,48,48,0.35);'
            f'border-radius:8px;padding:0.9rem 1.2rem;margin-bottom:0.8rem;font-size:0.85rem;">'
            f'<div style="font-weight:800;color:#fff;letter-spacing:0.04em;">SYSTEM HEALTH '
            f'({len(_fails)} failing)</div>{_rows}</div>',
            unsafe_allow_html=True
        )
    elif _fails:
        # Everyone else: honest, non-alarming, no internal detail.
        st.markdown(
            '<div style="background:rgba(180,140,20,0.10);border:1px solid rgba(220,180,40,0.28);'
            'border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.8rem;font-size:0.84rem;'
            'color:rgba(255,255,255,0.65);">Some features are temporarily unavailable while we '
            'sort out a service issue. Report generation is unaffected.</div>',
            unsafe_allow_html=True
        )

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
                    pass  # URL cosmetics only — deliberately silent (sweep-reviewed)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with _signout_col:
        st.markdown('<div class="pickr-signout-col" style="padding-top:0.05rem;">', unsafe_allow_html=True)
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            from auth import sign_out
            sign_out()  # clears the cookie first, then all session state
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Past reports history dropdown ──
    try:
        from report_store import load_user_index_result, load_report as load_saved_report
        _idx_res = load_user_index_result(username)
        if _idx_res.broken:
            # "You have no reports" is a lie when the store is simply down.
            print(f"  history unavailable for {username}: {_idx_res.describe()}")
            st.caption("History unavailable")
            past_reports = []
        else:
            past_reports = _idx_res.content if isinstance(_idx_res.content, list) else []
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
                        pass  # URL cosmetics only — deliberately silent (sweep-reviewed)
                    st.session_state["history_select"] = _opts[0]
                    st.rerun()
                else:
                    st.toast("Could not load that report.", icon="⚠️")
                    st.session_state["history_select"] = _opts[0]
    except Exception as _e:
        # Silent-failure sweep: this wraps the whole history dropdown, so a
        # bug anywhere inside used to make history vanish with no trace. The
        # dropdown is non-critical (never block the page on it) but the cause
        # must be recoverable from the logs.
        print(f"  history dropdown failed: {type(_e).__name__}: {_e}")

# ══════════════════════════════════════════════════════════════
# CACHED DATA FETCHING
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_screener_results():
    """Screener picks, via the canonical helper in github_store.

    This used to be a hand-rolled copy of the GitHub fetch that — unlike the
    original — had NO local-file fallback and swallowed every exception. When
    the PAT expired it returned None, and the QGLP Top Picks section silently
    rendered nothing. github_store.load_screener_results_raw() already falls
    back to the on-disk screener_results.json, so use it.
    """
    from github_store import load_screener_results_raw
    return load_screener_results_raw()

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
    warnings = []
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
        except Exception as e:
            warnings.append(f"peer_fetch_failed:{pt}:{type(e).__name__}")
            continue
    return out, warnings

# ══════════════════════════════════════════════════════════════
# CACHED AI PASSES
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_analysis(ticker, analysis_input_str):
    data = json.loads(analysis_input_str)
    return ai.run_pipeline(ticker, data)



# ══════════════════════════════════════════════════════════════
# RENDER — FINANCIAL STATEMENTS TAB
# ══════════════════════════════════════════════════════════════

def _render_stmt(df, sym, scale=1e9, scale_label="$B"):
    if df is None or df.empty:
        st.markdown('<div style="color:rgba(255,255,255,0.35);padding:1rem 0;">No data available.</div>', unsafe_allow_html=True)
        return
    cols = sorted(df.columns)
    headers = "<tr><th>Metric</th>" + "".join(
        f"<th>{str(c.year) if hasattr(c, 'year') else str(c)}</th>" for c in cols
    ) + "</tr>"
    rows = ""
    for label in df.index:
        cells = f"<td style='font-weight:600;white-space:nowrap;'>{label}</td>"
        for c in cols:
            v = df.loc[label, c]
            try:
                n = float(v)
                if abs(n) >= scale:
                    formatted = f"{sym}{n/scale:.2f}{scale_label[1:]}"
                elif abs(n) >= 1e6:
                    formatted = f"{sym}{n/1e6:.2f}M"
                elif n == 0:
                    formatted = "—"
                else:
                    formatted = f"{sym}{n:,.0f}"
                color = "color:#f87171;" if n < 0 else ""
                cells += f"<td class='nowrap' style='{color}'>{formatted}</td>"
            except (TypeError, ValueError):
                cells += "<td>—</td>"
        rows += f"<tr>{cells}</tr>"
    st.markdown(f'<div style="font-size:0.72rem;color:rgba(255,255,255,0.35);margin-bottom:0.4rem;">Values in {scale_label} where applicable</div>', unsafe_allow_html=True)
    st.markdown(pt_table(headers, rows), unsafe_allow_html=True)


def _render_financials(data, cur="USD"):
    sym = get_sym(cur)
    inc = data.get("inc")
    bs  = data.get("bs")
    cf  = data.get("cf")
    if inc is None and bs is None and cf is None:
        st.markdown(
            '<div style="color:rgba(255,255,255,0.35);padding:2rem 0;text-align:center;">'
            'Financial statement data is not available for saved reports. '
            'Generate a fresh report to view statements.</div>',
            unsafe_allow_html=True
        )
        return
    itab, btab, ctab = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])
    with itab: _render_stmt(inc, sym)
    with btab: _render_stmt(bs,  sym)
    with ctab: _render_stmt(cf,  sym)


# ══════════════════════════════════════════════════════════════
# RENDER — MAIN REPORT
# ══════════════════════════════════════════════════════════════

def _render_v2(ticker, m, a, data):
    raise NotImplementedError(
        "v2 renderer not yet built. Phase H delivers this. "
        "Set METHODOLOGY_VERSION back to 'v1' in config.py to use the existing renderer."
    )


def render(ticker, m, a, data):
    version = a.get("methodology_version", "v1") if isinstance(a, dict) else "v1"
    if version == "v2":
        return _render_v2(ticker, m, a, data)
    # ── v1 render below ──
    company  = m.get("company_name", ticker)
    date     = datetime.now().strftime("%B %d, %Y")
    cur      = m.get("currency", "USD")
    sym      = get_sym(cur)
    sm               = a.get("scenario_math", {})
    final_probs      = sm.get("final_probabilities", {})
    pt_dict          = sm.get("price_target", {})
    eps_dict         = sm.get("eps", {})
    rev_dict         = sm.get("scenario_revenue", {})
    scenario_inputs  = a.get("scenario_inputs", {})

    # ── Driver-label lookup (Stage 1a: name bare A/B/C in tables) ──
    # Authoritative id→label map from the normalized macro_drivers dict.
    # Returns "A — Hyperscaler AI Capex Cycle" or None when no label is available
    # (callers fall back to the pre-existing display string so nothing is lost).
    _macro_drivers = a.get("macro_drivers") if isinstance(a.get("macro_drivers"), dict) else {}

    def _driver_label(driver_id):
        if not driver_id:
            return None
        ent = _macro_drivers.get(driver_id)
        lbl = ent.get("label") if isinstance(ent, dict) else None
        lbl = strip_html(lbl).strip() if lbl else ""
        return f"{driver_id} — {lbl}" if lbl else None

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
    base_ret = sm.get("base_implied_return", exp_ret)
    prob_pos = sm.get("prob_positive", 0)
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
                _spark_color = "#4ade80" if _sample[-1] >= _sample[0] else "#f87171"
                _spark = (
                    f'<svg width="120" height="30" viewBox="0 0 120 30" style="opacity:0.6;flex-shrink:0;">'
                    f'<polyline points="{_pts}" fill="none" stroke="{_spark_color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
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

    # ── Top-of-report bull_below_current advisory — visible without expanding math notes ──
    _persistent_caveats = []
    if sm.get("bull_below_current"):
        _persistent_caveats.append(
            "Bull-case scenario could not be calibrated against current price after retry — "
            "recent management guidance or analyst-consensus updates may not be fully reflected."
        )
    _deg = sm.get("degraded_sections", []) or []
    if "pass1_validation_partial" in _deg:
        _persistent_caveats.append(
            "Pass-1 inputs failed validation; some sections (drivers, scenarios, KPIs, catalysts) may be incomplete."
        )
    if _persistent_caveats:
        _bullets = "<br>".join(f"&bull; {c}" for c in _persistent_caveats)
        st.markdown(
            f'<div style="background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.35);'
            f'border-radius:8px;padding:0.9rem 1.1rem;margin:0.8rem 0;font-size:0.86rem;'
            f'color:#fbbf24;line-height:1.65;">'
            f'<strong>&#9888; Analysis caveat</strong><br>{_bullets}'
            f'</div>',
            unsafe_allow_html=True
        )

    if a.get("investment_thesis"):
        st.markdown(f'<div class="exec-summary">{clean_latex(strip_html(a["investment_thesis"]))}</div>', unsafe_allow_html=True)
    if a.get("rec_override_reason"):
        st.markdown(f'<div style="background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);border-radius:8px;padding:1rem 1.2rem;margin:0.8rem 0;font-size:0.88rem;color:#fbbf24;line-height:1.6;">{clean_latex(strip_html(a["rec_override_reason"]))}</div>', unsafe_allow_html=True)
    if a.get("business_overview"):
        st.markdown('<div class="sec">Business Overview</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["business_overview"]))}</div>', unsafe_allow_html=True)

    if a.get("revenue_architecture"):
        st.markdown('<div class="sec">Revenue Architecture</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["revenue_architecture"]))}</div>', unsafe_allow_html=True)
        ssr = a.get("scenario_segment_revenue")
        if isinstance(ssr, dict) and ssr.get("segments"):
            seg_header = "<tr><th>Segment</th><th>FY Rev</th><th>Bull FY+2</th><th>Base FY+2</th><th>Bear FY+2</th></tr>"
            seg_rows = "".join(
                f"<tr>"
                f"<td style='font-weight:600;'>{strip_html(s.get('name', ''))}</td>"
                f"<td class='nowrap'>{fmt_c(s.get('fy_revenue'), cur)}</td>"
                f"<td class='nowrap' style='color:#4ade80;'>{fmt_c(s.get('bull'), cur)}</td>"
                f"<td class='nowrap' style='color:#fbbf24;'>{fmt_c(s.get('base'), cur)}</td>"
                f"<td class='nowrap' style='color:#f87171;'>{fmt_c(s.get('bear'), cur)}</td>"
                f"</tr>"
                for s in ssr["segments"]
            )
            st.markdown(pt_table(seg_header, seg_rows), unsafe_allow_html=True)
            if ssr.get("any_derived"):
                st.markdown('<div style="font-size:0.75rem;color:rgba(255,255,255,0.4);margin-top:0.3rem;">Segment scenario growth derived from trailing YoY rates.</div>', unsafe_allow_html=True)

    _cnd = a.get("concentration_and_dependencies")
    if _cnd:
        st.markdown('<div class="sec">Concentration &amp; Dependencies</div>', unsafe_allow_html=True)
        _geo = _cnd.get("geographic_exposure", "") if isinstance(_cnd, dict) else ""
        _tcc = _cnd.get("top_customer_concentration", "") if isinstance(_cnd, dict) else ""
        _scd = _cnd.get("supply_chain_dependencies", "") if isinstance(_cnd, dict) else ""
        _rar = _cnd.get("relationships_at_risk", "") if isinstance(_cnd, dict) else ""
        if _geo or _tcc:
            _col_l, _col_r = st.columns(2)
            if _geo:
                with _col_l:
                    st.markdown('<div style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.45);margin-bottom:0.4rem;">Geographic Exposure</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="prose" style="font-size:0.86rem;">{clean_latex(strip_html(_geo))}</div>', unsafe_allow_html=True)
            if _tcc:
                with _col_r:
                    st.markdown('<div style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.45);margin-bottom:0.4rem;">Customer Concentration</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="prose" style="font-size:0.86rem;">{clean_latex(strip_html(_tcc))}</div>', unsafe_allow_html=True)
        if _scd:
            _scd_items = [x.strip() for x in _scd.split(";") if x.strip()]
            if _scd_items:
                _scd_html = "".join(f'<li style="margin-bottom:0.2rem;">{strip_html(x)}</li>' for x in _scd_items)
                st.markdown(f'<div style="font-size:0.7rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.45);margin:0.8rem 0 0.3rem;">Supply Chain Dependencies</div><ul style="margin:0;padding-left:1.2rem;font-size:0.86rem;color:rgba(255,255,255,0.7);line-height:1.6;">{_scd_html}</ul>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="prose" style="font-size:0.86rem;">{clean_latex(strip_html(_scd))}</div>', unsafe_allow_html=True)
        if _rar:
            _rar_items = [x.strip() for x in _rar.split(";") if x.strip()]
            if _rar_items:
                _rar_html = "".join(f'<div style="padding:0.3rem 0;border-bottom:1px solid rgba(248,113,113,0.15);font-size:0.86rem;">{strip_html(x)}</div>' for x in _rar_items)
                st.markdown(f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.2);border-radius:6px;padding:0.7rem 1rem;margin-top:0.6rem;"><div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;margin-bottom:0.4rem;">Relationships at Risk</div>{_rar_html}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="background:rgba(248,113,113,0.06);border:1px solid rgba(248,113,113,0.2);border-radius:6px;padding:0.7rem 1rem;margin-top:0.6rem;"><div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;margin-bottom:0.3rem;">Relationships at Risk</div><div style="font-size:0.86rem;color:rgba(255,255,255,0.7);">{strip_html(_rar)}</div></div>', unsafe_allow_html=True)

    if a.get("growth_drivers_and_moats"):
        st.markdown('<div class="sec">Growth Drivers &amp; Moats</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["growth_drivers_and_moats"]))}</div>', unsafe_allow_html=True)

    if a.get("margin_analysis"):
        st.markdown('<div class="sec">Margin Analysis</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["margin_analysis"]))}</div>', unsafe_allow_html=True)
        _sc_inp = a.get("scenario_inputs", {})
        _bull_om = safe_float(_sc_inp.get("bull", {}).get("op_margin", 0))
        _base_om = safe_float(_sc_inp.get("base", {}).get("op_margin", 0))
        _bear_om = safe_float(_sc_inp.get("bear", {}).get("op_margin", 0))
        if _bull_om or _base_om or _bear_om:
            _mc1, _mc2, _mc3 = st.columns(3)
            with _mc1: st.metric("Bull Op Margin", f"{_bull_om*100:.1f}%" if _bull_om else "—")
            with _mc2: st.metric("Base Op Margin", f"{_base_om*100:.1f}%" if _base_om else "—")
            with _mc3: st.metric("Bear Op Margin", f"{_bear_om*100:.1f}%" if _bear_om else "—")
        # Surface the effective base operating margin the scenario EPS is actually
        # built on (event-weighted scenario_margin.base, FY-basis) so the reader can
        # tell it apart from the TTM figure in Key Metrics. Display-only; pulled from
        # the computed math, never hardcoded.
        _eff_margins = sm.get("scenario_margin") if isinstance(sm, dict) else None
        if isinstance(_eff_margins, dict) and _eff_margins.get("base") is not None:
            _eff_base = safe_float(_eff_margins.get("base"))
            st.markdown(
                f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.6);margin:0.4rem 0 0.2rem;">'
                f'Effective base op margin (scenario model): '
                f'<span style="font-weight:700;color:rgba(255,255,255,0.85);">{_eff_base*100:.1f}%</span>'
                f' &nbsp;·&nbsp; FY-basis operating margin the scenario EPS is built on — '
                f'distinct from the TTM figure shown in Key Metrics.</div>',
                unsafe_allow_html=True,
            )

    if a.get("financial_health"):
        st.markdown('<div class="sec">Financial Health</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["financial_health"]))}</div>', unsafe_allow_html=True)

    if a.get("competitive_position"):
        st.markdown('<div class="sec">Competitive Position</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["competitive_position"]))}</div>', unsafe_allow_html=True)

    _fa = a.get("factor_analysis")
    if _fa:
        st.markdown('<div class="sec">Factor Analysis</div>', unsafe_allow_html=True)
        _fa_items = list(_fa.values()) if isinstance(_fa, dict) else (_fa if isinstance(_fa, list) else [])
        for _drv in _fa_items:
            if not isinstance(_drv, dict):
                continue
            _drv_did  = strip_html(_drv.get("driver_id", ""))
            _drv_nm   = strip_html(_drv.get("name", ""))
            # Prefix the driver id so factor rows tie back to the A/B/C scenario drivers.
            _drv_name = f"{_drv_did} — {_drv_nm}" if _drv_did and _drv_nm else (_drv_nm or _drv_did)
            st.markdown(f'<div style="font-size:0.85rem;font-weight:700;color:rgba(255,255,255,0.85);margin:0.8rem 0 0.4rem;">{_drv_name}</div>', unsafe_allow_html=True)
            for _oc in (_drv.get("outcomes") or []):
                if not isinstance(_oc, dict):
                    continue
                _lbl   = _oc.get("label", "")
                _prob  = safe_float(_oc.get("probability", 0))
                _desc  = strip_html(_oc.get("description", ""))
                _bar_color = "#4ade80" if _lbl == "optimistic" else ("#f87171" if _lbl == "pessimistic" else "#fbbf24")
                _pct_str = f"{_prob*100:.0f}%"
                _col_a, _col_b = st.columns([3, 7])
                with _col_a:
                    st.markdown(f'<div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0;"><span style="font-size:0.75rem;color:rgba(255,255,255,0.5);width:5rem;text-transform:capitalize;">{_lbl}</span><span style="font-size:0.8rem;font-weight:700;color:{_bar_color};">{_pct_str}</span></div>', unsafe_allow_html=True)
                    st.progress(min(1.0, max(0.0, _prob)))
                with _col_b:
                    st.markdown(f'<div style="font-size:0.82rem;color:rgba(255,255,255,0.6);padding:0.3rem 0;line-height:1.5;">{_desc}</div>', unsafe_allow_html=True)

    _sae = a.get("scenario_analysis_extended")
    if isinstance(_sae, dict) and _sae:
        st.markdown('<div class="sec">Scenario Analysis — Extended</div>', unsafe_allow_html=True)
        _ssr2 = a.get("scenario_segment_revenue")
        for _sc_name, _sc_color, _sc_label in (
            ("bull", "#4ade80", "Bull"), ("base", "#fbbf24", "Base"), ("bear", "#f87171", "Bear")
        ):
            _sc_data = _sae.get(_sc_name)
            if not isinstance(_sc_data, dict):
                continue
            st.markdown(f'<div style="font-size:0.78rem;font-weight:800;text-transform:uppercase;letter-spacing:0.08em;color:{_sc_color};margin:0.8rem 0 0.3rem;">{_sc_label} Case</div>', unsafe_allow_html=True)
            if isinstance(_ssr2, dict) and _ssr2.get("segments"):
                _sr_header = "<tr><th>Segment</th><th>FY Rev</th><th>Projected FY+2</th></tr>"
                _sr_rows = "".join(
                    f"<tr><td>{strip_html(s.get('name',''))}</td><td class='nowrap'>{fmt_c(s.get('fy_revenue'), cur)}</td><td class='nowrap' style='color:{_sc_color};'>{fmt_c(s.get(_sc_name), cur)}</td></tr>"
                    for s in _ssr2["segments"]
                )
                st.markdown(pt_table(_sr_header, _sr_rows), unsafe_allow_html=True)
            _ht_summary = _sc_data.get("headwind_tailwind_summary", "")
            _val_rat    = _sc_data.get("valuation_rationale", "")
            if _ht_summary:
                st.markdown(f'<div class="prose" style="font-size:0.86rem;margin-top:0.3rem;">{clean_latex(strip_html(_ht_summary))}</div>', unsafe_allow_html=True)
            if _val_rat:
                st.markdown(f'<div class="prose" style="font-size:0.86rem;color:rgba(255,255,255,0.55);">{clean_latex(strip_html(_val_rat))}</div>', unsafe_allow_html=True)

    if a.get("valuation_vs_expectations"):
        st.markdown('<div class="sec">Valuation vs. Expectations</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["valuation_vs_expectations"]))}</div>', unsafe_allow_html=True)

    _st = sm.get("sensitivity_table") if isinstance(sm, dict) else None
    if _st or a.get("sensitivity_check"):
        st.markdown('<div class="sec">Sensitivity Check <span class="vtag">±10pp</span></div>', unsafe_allow_html=True)
        if isinstance(_st, dict):
            _sc1, _sc2, _sc3 = st.columns(3)
            _minus = _st.get("minus_10pp", {})
            _curr  = _st.get("current", {})
            _plus  = _st.get("plus_10pp", {})
            _drv_id = _st.get("driver", "A")
            # Name the perturbed driver once (width-safe); metric labels stay short below.
            _drv_full = _driver_label(_drv_id) or f"Driver {_drv_id}"
            st.markdown(
                f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.6);margin:0.2rem 0 0.5rem;">'
                f'Perturbing <span style="font-weight:700;color:rgba(255,255,255,0.85);">{_drv_full}</span> bull probability</div>',
                unsafe_allow_html=True,
            )
            with _sc1:
                st.metric(
                    f"Bull prob −10pp ({safe_float(_minus.get('bull_prob',0))*100:.0f}%)",
                    f"{sym}{safe_float(_minus.get('expected_value',0)):,.0f}",
                )
            with _sc2:
                st.metric(
                    f"Bull prob current ({safe_float(_curr.get('bull_prob',0))*100:.0f}%)",
                    f"{sym}{safe_float(_curr.get('expected_value',0)):,.0f}",
                )
            with _sc3:
                st.metric(
                    f"Bull prob +10pp ({safe_float(_plus.get('bull_prob',0))*100:.0f}%)",
                    f"{sym}{safe_float(_plus.get('expected_value',0)):,.0f}",
                )
        if a.get("sensitivity_check"):
            st.markdown(f'<div class="prose" style="margin-top:0.6rem;">{clean_latex(strip_html(a["sensitivity_check"]))}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Key Metrics</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Market Cap", fmt_c(m.get("market_cap"), cur))
    with c2: st.metric("Price", fmt_c(m.get("current_price"), cur))
    with c3: st.metric("Trailing P/E", fmt_r(m.get("trailing_pe")))
    with c4: st.metric("Forward P/E", fmt_r(m.get("forward_pe")))
    _peg = m.get("peg_ratio")
    with c5: st.metric("PEG", fmt_r(_peg) if _peg is not None else "N/A")
    with c6: st.metric("EV/EBITDA", fmt_r(m.get("ev_to_ebitda")))
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Revenue", fmt_c(m.get("total_revenue"), cur))
    with c2: st.metric("Gross Margin", fmt_p(m.get("gross_margin")))
    with c3: st.metric("Op. Margin (TTM)", fmt_p(m.get("operating_margin")))
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
        except Exception as _e:
            # Silent-failure sweep: genuinely cosmetic (one decorative bar), so
            # it stays non-fatal — but log it rather than vanishing silently.
            print(f"  52-week range bar skipped: {type(_e).__name__}: {_e}")

    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        try:
            import altair as alt
            _ph = h[["Close"]].reset_index(); _ph.columns = ["Date", "Price"]
            _ph = _ph.dropna(subset=["Price"])     # drop NaN rows that auto-expand the y-axis
            _ph = _ph[_ph["Price"] > 0]            # drop zero/negative outliers (split artifacts)
            if _ph.empty:
                raise ValueError("no valid price data")
            _color = "#4ade80" if _ph["Price"].iloc[-1] >= _ph["Price"].iloc[0] else "#f87171"
            _pc = (alt.Chart(_ph)
                .mark_line(color=_color, strokeWidth=1.8)
                .encode(
                    x=alt.X("Date:T", axis=alt.Axis(format="%Y", labelColor="#666", grid=False)),
                    y=alt.Y("Price:Q", scale=alt.Scale(zero=False, nice=True),
                            axis=alt.Axis(labelColor="#666", gridColor="rgba(255,255,255,0.04)")),
                    tooltip=[alt.Tooltip("Date:T", format="%b %d, %Y"),
                             alt.Tooltip("Price:Q", format=",.2f", title=f"Price ({sym})")]
                ).properties(height=250, background="transparent"))
            st.altair_chart(_pc, use_container_width=True)
        except Exception:
            cd = h[["Close"]].dropna().copy(); cd.columns = ["Price"]
            st.line_chart(cd, height=250, color="#4ade80")

    rh = m.get("revenue_history", {}); nh = m.get("net_income_history", {})
    if rh or nh:
        st.markdown('<div class="sec">Revenue &amp; Earnings Trend (Billions)</div>', unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        try:
            import altair as alt
            with cc1:
                if rh:
                    _rd = pd.DataFrame([{"Year": str(k), "Revenue": v} for k, v in rh.items()])
                    st.altair_chart(
                        alt.Chart(_rd).mark_bar(size=44, color="#4ade80",
                                                cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                        .encode(x=alt.X("Year:O", axis=alt.Axis(labelColor="#aaa", grid=False, labelAngle=0)),
                                y=alt.Y("Revenue:Q",
                                        scale=alt.Scale(zero=True, nice=True),
                                        axis=alt.Axis(labelColor="#aaa", title="$B",
                                                      gridColor="rgba(255,255,255,0.04)")),
                                tooltip=["Year:O", alt.Tooltip("Revenue:Q", format=".2f", title="Revenue ($B)")])
                        .properties(height=200, background="transparent"),
                        use_container_width=True)
            with cc2:
                if nh:
                    _nd = pd.DataFrame([{"Year": str(k), "Net Income": v} for k, v in nh.items()])
                    st.altair_chart(
                        alt.Chart(_nd).mark_bar(size=44, color="#81c784",
                                                cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                        .encode(x=alt.X("Year:O", axis=alt.Axis(labelColor="#aaa", grid=False, labelAngle=0)),
                                y=alt.Y("Net Income:Q",
                                        scale=alt.Scale(zero=True, nice=True),
                                        axis=alt.Axis(labelColor="#aaa", title="$B",
                                                      gridColor="rgba(255,255,255,0.04)")),
                                tooltip=["Year:O", alt.Tooltip("Net Income:Q", format=".2f", title="Net Income ($B)")])
                        .properties(height=200, background="transparent"),
                        use_container_width=True)
        except Exception:
            with cc1:
                if rh: st.bar_chart(pd.DataFrame({"Revenue": rh}), height=200, color="#4ade80")
            with cc2:
                if nh: st.bar_chart(pd.DataFrame({"Net Income": nh}), height=200, color="#81c784")

    segments = a.get("segments", [])
    if segments:
        st.markdown('<div class="sec">Revenue Segmentation</div>', unsafe_allow_html=True)
        seg_header = "<tr><th>Segment</th><th>Revenue</th><th>% of Total</th><th>Gross Margin</th><th>YoY Growth</th><th>Trajectory</th></tr>"
        _seg_fields = ("current_revenue", "pct_of_total", "gross_margin", "yoy_growth")
        _has_financials = any(seg.get(k) is not None for seg in segments for k in _seg_fields)
        if not _has_financials:
            # Segment names known (e.g. CCS/ATS) but FMP free tier returns no per-segment financials.
            # Show one clear note row rather than a table full of dashes that looks like a render failure.
            seg_rows = ('<tr><td colspan="6" style="text-align:center;color:rgba(255,255,255,0.5);'
                        'padding:1rem;">Segment data unavailable — requires FMP paid tier.</td></tr>')
        else:
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

    conc = a.get("concentration", {})
    if conc:
        st.markdown('<div class="sec">Concentration &amp; Dependencies</div>', unsafe_allow_html=True)
        with st.expander("Show detail", expanded=False):
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

    sector    = m.get("sector", "")
    llm_peers = a.get("peer_tickers", [])
    if sector in SECTOR_PEERS or llm_peers:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        with st.spinner("Loading peers..."):
            peers, peer_warnings = fetch_peers(ticker, sector, llm_peers=llm_peers)
            m.setdefault("data_quality_warnings", []).extend(peer_warnings)
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
                f'<td style="font-weight:600;">{_driver_label(hw.get("driver")) or strip_html(hw.get("name",""))}</td>'
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
                f'<td style="font-weight:600;">{_driver_label(tw.get("driver")) or strip_html(tw.get("name",""))}</td>'
                f'<td class="nowrap">{fmt_p(tw.get("probability"))}</td>'
                f'<td class="nowrap">{fmt_c(tw.get("revenue_opportunity"), cur)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("bull_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("base_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'<td class="nowrap">{fmt_eps_impact(tw.get("bear_eps_impact", 0), sym, is_headwind=False)}</td>'
                f'</tr>'
                for tw in tailwinds
            )
            st.markdown(pt_table(tw_header, tw_rows), unsafe_allow_html=True)

    # ── Driver cards (new schema: a["drivers"] from pass1) ──
    drivers_list = a.get("drivers", [])
    driver_narratives = a.get("driver_narratives", {})
    if drivers_list:
        st.markdown('<div class="sec">Key Drivers <span class="vtag">Bottom-Up Scenario Inputs</span></div>', unsafe_allow_html=True)
        st.markdown('''<div class="plain-callout">
            <div class="plain-callout-label">How this works</div>
            Each driver is a forward variable that resolves into one of three outcomes.
            Importance-weighted averages of driver outcome probabilities produce the final scenario weights below.
            The probabilities shown in the scenario bars are the only numbers used in the expected-value formula.
        </div>''', unsafe_allow_html=True)
        # Compact summary table — restores the OLD report's "Headwinds & Tailwinds" density
        ei_fmt = lambda v: (f'<span style="color:#4ade80;">+{sym}{v:.2f}</span>' if v > 0
                            else f'<span style="color:#f87171;">{sym}{v:.2f}</span>' if v < 0
                            else '<span style="color:rgba(255,255,255,0.35);">—</span>')
        sorted_drivers = sorted(
            [d for d in drivers_list if not d.get("_redundant")],
            key=lambda d: abs(
                safe_float(d.get("outcomes", {}).get("bull", {}).get("eps_impact", 0)) -
                safe_float(d.get("outcomes", {}).get("bear", {}).get("eps_impact", 0))
            ),
            reverse=True,
        )
        if sorted_drivers and any(
            d.get("outcomes", {}).get("bull", {}).get("eps_impact") is not None
            for d in sorted_drivers
        ):
            sum_header = "<tr><th>Driver</th><th>Importance</th><th>Bull EPS</th><th>Base EPS</th><th>Bear EPS</th></tr>"
            sum_rows = "".join(
                f'<tr>'
                f'<td style="font-weight:600;">{strip_html(d.get("name", ""))}</td>'
                f'<td class="nowrap">{safe_float(d.get("importance", 0))*100:.0f}%</td>'
                f'<td class="nowrap">{ei_fmt(safe_float(d.get("outcomes", {}).get("bull", {}).get("eps_impact", 0)))}</td>'
                f'<td class="nowrap">{ei_fmt(safe_float(d.get("outcomes", {}).get("base", {}).get("eps_impact", 0)))}</td>'
                f'<td class="nowrap">{ei_fmt(safe_float(d.get("outcomes", {}).get("bear", {}).get("eps_impact", 0)))}</td>'
                f'</tr>'
                for d in sorted_drivers
            )
            st.markdown('<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.55);margin:1rem 0 0.5rem;">Drivers — EPS Impact Summary</div>', unsafe_allow_html=True)
            st.markdown(pt_table(sum_header, sum_rows), unsafe_allow_html=True)

        for d in drivers_list:
            dname  = strip_html(d.get("name", ""))
            ddesc  = strip_html(d.get("description", ""))
            imp    = safe_float(d.get("importance", 0))
            outs   = d.get("outcomes", {})
            bull_p = safe_float(outs.get("bull", {}).get("probability", 0))
            base_p = safe_float(outs.get("base", {}).get("probability", 0))
            bear_p = safe_float(outs.get("bear", {}).get("probability", 0))
            bull_ri = safe_float(outs.get("bull", {}).get("revenue_impact", 0))
            base_ri = safe_float(outs.get("base", {}).get("revenue_impact", 0))
            bear_ri = safe_float(outs.get("bear", {}).get("revenue_impact", 0))
            bull_ei = safe_float(outs.get("bull", {}).get("eps_impact", 0))
            base_ei = safe_float(outs.get("base", {}).get("eps_impact", 0))
            bear_ei = safe_float(outs.get("bear", {}).get("eps_impact", 0))
            bull_n  = strip_html(outs.get("bull", {}).get("description", ""))[:130]
            base_n  = strip_html(outs.get("base", {}).get("description", ""))[:130]
            bear_n  = strip_html(outs.get("bear", {}).get("description", ""))[:130]
            bw   = max(2, min(100, round(bull_p * 100)))
            basew = max(2, min(100, round(base_p * 100)))
            bearw = max(2, min(100, round(bear_p * 100)))
            ri_fmt = lambda v: (f'+{fmt_c(v, cur)}' if v > 0 else fmt_c(v, cur)) if v else ''
            ei_inline = lambda v: (f' · EPS {sym}{v:+.2f}' if v else '')
            dnarr = strip_html(driver_narratives.get(dname, ""))
            redundant = d.get("_redundant", False)
            redundant_badge = '<span style="font-size:0.68rem;color:#fbbf24;margin-left:0.5rem;">[correlated — impact zeroed]</span>' if redundant else ''
            st.markdown(f'''<div class="driver-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;">
                    <div>
                        <div class="driver-card-name">{dname}{redundant_badge}</div>
                        <div class="driver-card-desc">{ddesc}</div>
                    </div>
                    <div style="text-align:right;flex-shrink:0;">
                        <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:rgba(255,255,255,0.4);">Importance</div>
                        <div style="font-size:1.1rem;font-weight:800;color:#fff;">{imp*100:.0f}%</div>
                    </div>
                </div>
                <div style="margin:0.5rem 0;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0;">
                        <div style="width:{bw}%;height:6px;background:#22703a;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#4ade80;min-width:2.5rem;flex-shrink:0;">{bull_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);flex:1;">{bull_n}</span>
                        <span style="font-size:0.72rem;color:#4ade80;flex-shrink:0;">{ri_fmt(bull_ri)}{ei_inline(bull_ei)}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0;">
                        <div style="width:{basew}%;height:6px;background:#92681a;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#fbbf24;min-width:2.5rem;flex-shrink:0;">{base_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);flex:1;">{base_n}</span>
                        <span style="font-size:0.72rem;color:#fbbf24;flex-shrink:0;">{ri_fmt(base_ri)}{ei_inline(base_ei)}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0;">
                        <div style="width:{bearw}%;height:6px;background:#8b2020;border-radius:3px;min-width:4px;"></div>
                        <span style="font-size:0.78rem;color:#f87171;min-width:2.5rem;flex-shrink:0;">{bear_p*100:.0f}%</span>
                        <span style="font-size:0.78rem;color:rgba(255,255,255,0.5);flex:1;">{bear_n}</span>
                        <span style="font-size:0.72rem;color:#f87171;flex-shrink:0;">{ri_fmt(bear_ri)}{ei_inline(bear_ei)}</span>
                    </div>
                </div>
                {f'<div style="font-size:0.85rem;color:rgba(255,255,255,0.55);line-height:1.7;margin-top:0.5rem;padding-top:0.5rem;border-top:1px solid rgba(255,255,255,0.06);">{dnarr}</div>' if dnarr else ''}
            </div>''', unsafe_allow_html=True)

    # ── Scenario probability bars (derived from drivers) ──
    fb  = final_probs.get("bull", 0)
    fba = final_probs.get("base", 0)
    fbe = final_probs.get("bear", 0)
    if fb or fba or fbe:
        st.markdown('<div class="sec">Scenario Probabilities <span class="vtag">Driver-Derived</span></div>', unsafe_allow_html=True)
        bull_pct = f"{fb*100:.0f}"; base_pct = f"{fba*100:.0f}"; bear_pct = f"{fbe*100:.0f}"
        _bw  = max(2, min(96, round(fb * 100)))
        _baw = max(2, min(96, round(fba * 100)))
        _bew = max(2, min(96, round(fbe * 100)))
        st.markdown(
            f'<div style="margin:1.2rem 0 1.4rem;">'
            f'<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.55rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#4ade80;text-align:right;flex-shrink:0;">Bull</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_bw}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#22703a,#4ade80);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#4ade80;text-align:right;flex-shrink:0;">{bull_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Driver-weighted average</div></div>'
            f'<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.55rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#fbbf24;text-align:right;flex-shrink:0;">Base</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_baw}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#92681a,#fbbf24);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#fbbf24;text-align:right;flex-shrink:0;">{base_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Driver-weighted average</div></div>'
            f'<div style="display:flex;align-items:center;gap:0.75rem;">'
            f'<div style="width:3.5rem;font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#f87171;text-align:right;flex-shrink:0;">Bear</div>'
            f'<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:4px;height:10px;"><div style="width:{_bew}%;height:100%;border-radius:4px;background:linear-gradient(90deg,#8b2020,#f87171);"></div></div>'
            f'<div style="width:2.8rem;font-size:0.88rem;font-weight:800;color:#f87171;text-align:right;flex-shrink:0;">{bear_pct}%</div>'
            f'<div style="width:9rem;font-size:0.72rem;color:rgba(255,255,255,0.4);flex-shrink:0;line-height:1.4;">Driver-weighted average</div></div>'
            f'<div style="margin-top:0.9rem;font-size:0.88rem;color:rgba(255,255,255,0.55);line-height:1.7;">'
            f'Probabilities are importance-weighted averages of the driver outcome probabilities above, '
            f'rounded to integer percent. These exact weights drive the expected-value calculation.'
            f'</div></div>',
            unsafe_allow_html=True
        )
        # Diagnostics panel: fundamentals signals vs driver-derived
        diagnostic = sm.get("diagnostic") or a.get("python_outputs", {}).get("diagnostic", {})
        if diagnostic:
            sig_probs = diagnostic.get("signal_implied_probabilities", {})
            diverge   = diagnostic.get("divergence_flag", False)
            div_color = "#fbbf24" if diverge else "rgba(255,255,255,0.35)"
            with st.expander("Fundamentals signal check" + (" — divergence detected" if diverge else ""), expanded=False):
                st.markdown(f'<div style="font-size:0.8rem;color:rgba(255,255,255,0.5);margin-bottom:0.5rem;">'
                            f'Comparison of driver-derived probabilities vs an independent 8-signal fundamentals engine. '
                            f'This is a cross-check only — it does not alter any numbers in the report.</div>',
                            unsafe_allow_html=True)
                for sname, scolor in [("bull","#4ade80"),("base","#fbbf24"),("bear","#f87171")]:
                    drv_p = final_probs.get(sname, 0) * 100
                    sig_p = sig_probs.get(sname, 0) * 100
                    diff  = drv_p - sig_p
                    diff_str = f'{diff:+.0f}pp' if abs(diff) >= 1 else 'matches'
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;font-size:0.82rem;'
                        f'padding:0.2rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">'
                        f'<span style="color:{scolor};font-weight:700;width:3rem;">{sname.capitalize()}</span>'
                        f'<span style="color:rgba(255,255,255,0.6);">Driver: <strong style="color:#fff;">{drv_p:.0f}%</strong></span>'
                        f'<span style="color:rgba(255,255,255,0.6);">Signals: <strong style="color:#fff;">{sig_p:.0f}%</strong></span>'
                        f'<span style="color:{div_color};">{diff_str}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

    # ── Scenario tabs ──
    st.markdown('<div class="sec">Scenario Analysis</div>', unsafe_allow_html=True)
    sc_commentary = a.get("scenario_commentary", {})
    # scenario_commentary is now a dict {bull, base, bear}; string form kept for compat
    if isinstance(sc_commentary, str) and sc_commentary:
        st.markdown(f'<div class="prose">{clean_latex(strip_html(sc_commentary))}</div>', unsafe_allow_html=True)

    # Reconstruct per-scenario data from new flat schema
    _cp = safe_float(m.get("current_price", 0))
    _scenarios_built = {}
    for _sn in ("bull", "base", "bear"):
        _si  = scenario_inputs.get(_sn, {})
        _pt  = safe_float(pt_dict.get(_sn, 0))
        _eps_v = safe_float(eps_dict.get(_sn, 0))
        _rev = rev_dict.get(_sn)  # keep None when absent (v2 doesn't aggregate scenario revenue) → render "N/A"
        _op_m = safe_float(_si.get("op_margin", 0))
        _pe   = safe_float(_si.get("pe_multiple_pick", 0))
        _prob = safe_float(final_probs.get(_sn, 0))
        _ret  = (_pt / _cp - 1) if _cp > 0 and _pt > 0 else 0
        _narr = sc_commentary.get(_sn, "") if isinstance(sc_commentary, dict) else ""
        _scenarios_built[_sn] = {
            "probability": _prob, "price_target": _pt, "eps": _eps_v,
            "revenue": _rev, "op_margin": _op_m, "pe": _pe,
            "implied_return": _ret, "narrative": _narr,
        }

    bull_s = _scenarios_built.get("bull", {}); base_s = _scenarios_built.get("base", {}); bear_s = _scenarios_built.get("bear", {})
    bull_label = f"Bull ({bull_s.get('probability',0)*100:.0f}%) / {sym}{bull_s.get('price_target',0):,.0f}" if bull_s.get("price_target") else "Bull"
    base_label = f"Base ({base_s.get('probability',0)*100:.0f}%) / {sym}{base_s.get('price_target',0):,.0f}" if base_s.get("price_target") else "Base"
    bear_label = f"Bear ({bear_s.get('probability',0)*100:.0f}%) / {sym}{bear_s.get('price_target',0):,.0f}" if bear_s.get("price_target") else "Bear"

    bull_tab, base_tab, bear_tab = st.tabs([f":green[{bull_label}]", f":orange[{base_label}]", f":red[{bear_label}]"])
    for tab, sname, slabel, scolor in [(bull_tab,"bull","Bull Case","#4ade80"),(base_tab,"base","Base Case","#fbbf24"),(bear_tab,"bear","Bear Case","#f87171")]:
        s = _scenarios_built.get(sname, {})
        with tab:
            prob      = s.get("probability", 0) * 100
            pt        = s.get("price_target", 0)
            ret       = s.get("implied_return", 0) * 100
            eps_val   = s.get("eps", 0)
            pe        = s.get("pe", 0)
            op_m      = s.get("op_margin", 0)
            total_rev = s.get("revenue")
            narrative  = clean_latex(strip_html(s.get("narrative", "")))

            st.markdown(f'''<div style="text-align:center;padding:1.5rem 0 1rem;">
                <div style="font-size:2.2rem;font-weight:900;color:#fff;">{sym}{pt:,.2f}</div>
                <div style="font-size:1.1rem;font-weight:700;color:{scolor};margin-top:0.3rem;">{ret:+.1f}% return</div>
                <div style="font-size:0.75rem;color:rgba(255,255,255,0.6);margin-top:0.2rem;">{prob:.0f}% probability</div>
            </div>''', unsafe_allow_html=True)
            m1,m2,m3,m4 = st.columns(4)
            with m1: st.metric("Revenue", fmt_c(total_rev, cur) if total_rev is not None else "N/A")
            with m2: st.metric("EPS", f"{sym}{eps_val:.2f}")
            with m3: st.metric("P/E Multiple", f"{pe:.1f}x")
            with m4: st.metric("Op. Margin", f"{op_m*100:.1f}%")
            # Driver revenue impacts for this scenario
            driver_impacts = [
                (strip_html(d.get("name", "")),
                 safe_float(d.get("outcomes", {}).get(sname, {}).get("revenue_impact", 0)))
                for d in drivers_list
                if not d.get("_redundant") and d.get("outcomes", {}).get(sname, {}).get("revenue_impact")
            ]
            if driver_impacts and total_rev:
                st.markdown('<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.65);margin:1rem 0 0.5rem;">Driver Revenue Impacts</div>', unsafe_allow_html=True)
                for dname_i, ri in sorted(driver_impacts, key=lambda x: abs(x[1]), reverse=True):
                    ri_color = scolor if ri >= 0 else "#f87171"
                    st.markdown(f'<div style="display:flex;justify-content:space-between;font-size:0.82rem;padding:0.15rem 0;">'
                                f'<span style="color:rgba(255,255,255,0.6);">{dname_i}</span>'
                                f'<span style="color:{ri_color};font-weight:600;">{fmt_c(ri, cur)}</span>'
                                f'</div>', unsafe_allow_html=True)
            if narrative:
                st.markdown(f'<div style="font-size:0.95rem;color:rgba(255,255,255,0.78);line-height:1.8;margin:0.8rem 0;padding:1rem;background:rgba(255,255,255,0.02);border-radius:6px;">{narrative}</div>', unsafe_allow_html=True)

    # ── EV reconciliation (single source of truth) ──
    # Render the math layer's own ev_formula_string verbatim. The app NEVER
    # recomputes EV — the previous app-side recomputation used a different bear
    # price (bear_low) and different weight rounding than the headline EV, so it
    # contradicted the headline. Display exactly what the math computed.
    ev_formula = sm.get("ev_formula_string", "")
    if ev_formula:
        st.markdown(
            f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.55);'
            f'margin:0.6rem 0 1rem;padding:0.6rem 0.9rem;'
            f'background:rgba(255,255,255,0.02);border-left:2px solid rgba(255,255,255,0.15);'
            f'border-radius:4px;font-family:ui-monospace,monospace;">'
            f'EV = {clean_latex(ev_formula)}'
            f'&nbsp;— probability-weighted scenario mids, single source of truth'
            f'</div>',
            unsafe_allow_html=True
        )

    ud_ratio   = sm.get("upside_downside_ratio") or 0
    ret_color  = "positive" if exp_ret > 0.05 else ("neutral" if exp_ret > 0 else "negative")
    ud_display = "∞" if (ud_ratio == float("inf") or ud_ratio is None) else f"{ud_ratio:.2f}x"
    ud_color   = "#4ade80" if (ud_ratio and ud_ratio > 1.5) else ("#fbbf24" if (ud_ratio and ud_ratio > 1.0) else "#f87171")
    st.markdown('<div class="sec">The Bottom Line</div>', unsafe_allow_html=True)
    st.markdown(f'''<div class="ev-bar">
        <div class="ev-item"><div class="ev-label">Expected Value</div><div class="ev-val">{sym}{ev:,.2f}</div></div>
        <div class="ev-item"><div class="ev-label">Base Case</div><div class="ev-val {ret_color}">{base_ret*100:+.1f}%</div></div>
        <div class="ev-item"><div class="ev-label">P(Positive)</div><div class="ev-val">{prob_pos*100:.0f}%</div></div>
        <div class="ev-item"><div class="ev-label">Upside vs Downside</div><div class="ev-val" style="color:{ud_color};">{ud_display}</div></div>
    </div>''', unsafe_allow_html=True)

    # ── Analyst Reference Range (yfinance forward consensus) ──
    ac = m.get("analyst_consensus") or {}
    if ac.get("revenue_fy_avg") or ac.get("price_target_mean"):
        n_an = ac.get("revenue_fy_n_analysts", 0)
        rev_low  = ac.get("revenue_fy_low", 0)  / 1e9
        rev_avg  = ac.get("revenue_fy_avg", 0)  / 1e9
        rev_high = ac.get("revenue_fy_high", 0) / 1e9
        eps_low, eps_avg, eps_high = ac.get("eps_fy_low", 0), ac.get("eps_fy_avg", 0), ac.get("eps_fy_high", 0)
        pt_low, pt_med, pt_high   = ac.get("price_target_low", 0), ac.get("price_target_median", 0), ac.get("price_target_high", 0)
        st.markdown(f'<div class="sec">Analyst Reference Range <span class="vtag">FY Consensus · {n_an} analysts</span></div>', unsafe_allow_html=True)
        st.markdown(f'''<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:1rem 1.2rem;margin:0.6rem 0 1rem;">
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem;font-size:0.86rem;">
                <div>
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Revenue (current FY)</div>
                    <div style="color:rgba(255,255,255,0.55);"><span style="color:#f87171;">{sym}{rev_low:.2f}B</span> low / <strong style="color:#fff;">{sym}{rev_avg:.2f}B</strong> avg / <span style="color:#4ade80;">{sym}{rev_high:.2f}B</span> high</div>
                </div>
                <div>
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">EPS (current FY)</div>
                    <div style="color:rgba(255,255,255,0.55);"><span style="color:#f87171;">{sym}{eps_low:.2f}</span> low / <strong style="color:#fff;">{sym}{eps_avg:.2f}</strong> avg / <span style="color:#4ade80;">{sym}{eps_high:.2f}</span> high</div>
                </div>
                <div>
                    <div style="font-size:0.62rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:rgba(255,255,255,0.4);margin-bottom:0.3rem;">Price Target</div>
                    <div style="color:rgba(255,255,255,0.55);"><span style="color:#f87171;">{sym}{pt_low:.0f}</span> low / <strong style="color:#fff;">{sym}{pt_med:.0f}</strong> median / <span style="color:#4ade80;">{sym}{pt_high:.0f}</span> high</div>
                </div>
            </div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.35);margin-top:0.7rem;">Source: yfinance — forward consensus from sell-side analysts, refreshed within days of earnings. Used as a HARD floor for our bull/base/bear scenario revenue.</div>
        </div>''', unsafe_allow_html=True)

    if a.get("reverse_dcf_commentary"):
        st.markdown('<div class="sec">Reverse DCF <span class="vtag">Implied Growth Check</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["reverse_dcf_commentary"]))}</div>', unsafe_allow_html=True)

    # ── Monitoring KPI dashboard ──
    monitoring_kpis = a.get("monitoring_kpis", [])
    if monitoring_kpis:
        st.markdown('<div class="sec">Monitoring Dashboard <span class="vtag">KPI Framework</span></div>', unsafe_allow_html=True)
        if monitoring_kpis:
            kpi_header = "<tr><th>KPI</th><th>Baseline</th><th>Constructive</th><th>Adverse</th></tr>"
            kpi_rows = "".join(
                f'<tr>'
                f'<td style="font-weight:600;">{strip_html(k.get("name",""))}</td>'
                f'<td style="color:rgba(255,255,255,0.6);">{strip_html(k.get("fy_baseline",""))}</td>'
                f'<td style="color:#4ade80;">{strip_html(k.get("constructive_trajectory",""))}</td>'
                f'<td style="color:#f87171;">{strip_html(k.get("adverse_trajectory",""))}</td>'
                f'</tr>'
                for k in monitoring_kpis
            )
            st.markdown(pt_table(kpi_header, kpi_rows), unsafe_allow_html=True)

    # ── Catalysts ──
    catalysts = a.get("catalysts", [])
    if catalysts:
        st.markdown('<div class="sec">Catalysts to Watch</div>', unsafe_allow_html=True)
        cat_header = "<tr><th>Date</th><th>Event</th><th>Bull Signal</th><th>Bear Signal</th></tr>"
        cat_rows = "".join(
            f'<tr>'
            f'<td class="nowrap" style="font-weight:600;">{strip_html(c.get("date",""))}</td>'
            f'<td>{strip_html(c.get("event",""))}</td>'
            f'<td style="color:#4ade80;">{strip_html(c.get("bull_signal", c.get("positive_signal", "")))}</td>'
            f'<td style="color:#f87171;">{strip_html(c.get("bear_signal", c.get("negative_signal", "")))}</td>'
            f'</tr>'
            for c in catalysts
        )
        st.markdown(pt_table(cat_header, cat_rows), unsafe_allow_html=True)

    # ── Math notes footer ──
    pass3       = a.get("pass3", {})
    flags       = pass3.get("consistency_flags", []) if isinstance(pass3, dict) else []
    nums_out    = pass3.get("numbers_outside_source", []) if isinstance(pass3, dict) else []
    tone_mismatch = pass3.get("tone_label_mismatch", False) if isinstance(pass3, dict) else False
    dq_warns    = [w for w in (a.get("data_quality_warnings", []) or []) if w]
    mono_viol   = sm.get("monotonicity_violation", False)
    bull_below  = sm.get("bull_below_current", False)
    div_flag    = (sm.get("diagnostic") or {}).get("divergence_flag", False)
    deg_sections = sm.get("degraded_sections", []) or []

    all_notes = []
    if mono_viol:
        all_notes.append(("warn", "Monotonicity", sm.get("violation_msg", "Non-monotonic price targets — review driver inputs.")))
    if bull_below:
        all_notes.append(("warn", "Bull < Current", sm.get("bull_below_msg", "Bull-case target below current price — scenario set may be anchored on stale forward baselines.")))
    if div_flag:
        all_notes.append(("info", "Divergence", "Fundamentals signals diverge from driver-derived probabilities by >15pp — see diagnostic panel."))
    for f in flags:
        all_notes.append((f.get("severity","info"), f.get("field",""), f.get("issue","")))
    for n in nums_out:
        all_notes.append(("warn", n.get("field",""), f"Number outside source: {n.get('number','')} — {n.get('context','')}"))
    if tone_mismatch:
        ev_str = pass3.get("tone_label_evidence","") if isinstance(pass3, dict) else ""
        all_notes.append(("warn", "Tone/Label", f"Narrative tone may contradict recommendation label. {ev_str}"))
    for w in dq_warns:
        all_notes.append(("info", "Data quality", str(w)))
    for s in deg_sections:
        all_notes.append(("warn", "Degraded", f"Section unavailable: {s}"))

    if all_notes:
        with st.expander(f"Math notes & audit flags ({len(all_notes)})", expanded=False):
            sev_color = {"error": "#f87171", "warn": "#fbbf24", "info": "rgba(255,255,255,0.4)"}
            for sev, field, msg in all_notes:
                color = sev_color.get(sev, "rgba(255,255,255,0.4)")
                st.markdown(
                    f'<div style="display:flex;gap:0.75rem;font-size:0.8rem;padding:0.2rem 0;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04);">'
                    f'<span style="color:{color};font-weight:700;min-width:3.5rem;flex-shrink:0;">{sev.upper()}</span>'
                    f'<span style="color:rgba(255,255,255,0.45);min-width:6rem;flex-shrink:0;">{strip_html(field)}</span>'
                    f'<span style="color:rgba(255,255,255,0.65);">{strip_html(msg)}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    if a.get("conclusion"):
        st.markdown('<div class="sec">Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{clean_latex(strip_html(a["conclusion"]))}</div>', unsafe_allow_html=True)

    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")} &nbsp;/&nbsp;
        Math: Python deterministic (driver-derived probabilities) &nbsp;/&nbsp; Report #{st.session_state.report_count}</div>''', unsafe_allow_html=True)

    _sc.html("""
<button onclick="window.parent.print()"
  style="display:block;margin:0.8rem auto 0;background:rgba(255,255,255,0.05);
         border:1px solid rgba(255,255,255,0.12);color:rgba(255,255,255,0.5);
         font-size:0.78rem;padding:0.35rem 1rem;border-radius:5px;cursor:pointer;
         font-family:inherit;letter-spacing:0.02em;">
  &#8595; Save as PDF
</button>""", height=48, scrolling=False)

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
    suggested_target = sm.get("price_target", {}).get("base", 0.0)
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

header_left, _hspace, header_signin = st.columns([2.5, 1.2, 0.85])
with header_left:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:0.7rem;">'
        '<span style="font-size:2.3rem;font-weight:900;letter-spacing:-0.025em;color:#fff;">'
        'Pick<span style="color:#e74c3c;">R</span></span>'
        '<span style="font-size:0.9rem;color:rgba(255,255,255,0.55);font-weight:500;">'
        'equity research, free.</span>'
        '</div>',
        unsafe_allow_html=True
    )

if not authenticated:
    with header_signin:
        st.markdown('<div class="pickr-signout-col" style="padding-top:0.05rem;">', unsafe_allow_html=True)
        if st.button("Sign in", key="elegantsignin", use_container_width=True):
            st.session_state.show_auth = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

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

    links_html = "".join(
        f'<a href="?_qt={pick.get("ticker","")}" target="_self"'
        f' style="display:inline-block;font-size:0.78rem;font-weight:700;'
        f'color:rgba(255,255,255,0.55);background:rgba(255,255,255,0.05);'
        f'border:1px solid rgba(255,255,255,0.10);border-radius:4px;'
        f'padding:0.15rem 0.55rem;text-decoration:none;white-space:nowrap;'
        f'margin:0.15rem 0.2rem 0 0;">'
        f'{clean_ticker(pick.get("ticker",""))} →</a>'
        for pick in picks
    )
    st.markdown(f'<div style="margin-top:0.5rem;line-height:2;">{links_html}</div>', unsafe_allow_html=True)

# ── Load screener data ──
# screener_error is carried to the QGLP section below so an unavailable
# screener renders a visible explanation instead of a silently absent section.
screener_data  = None
screener_error = None
try:
    screener_data = load_screener_results()
    if not screener_data:
        screener_error = "unavailable"
except Exception as _e:
    print(f"  screener load failed: {type(_e).__name__}: {_e}")
    screener_error = "unavailable"

render_peg_tape(screener_data)

# ── Two-column landing layout ──────────────────────────────────
left_col, right_col = st.columns([2.2, 1], gap="large")

with left_col:
    st.markdown(
        '<div style="padding:1.5rem 1.4rem;background:rgba(255,255,255,0.03);'
        'border:1px solid rgba(255,255,255,0.07);border-radius:10px;margin-top:0.5rem">'
        '<h1 style="font-size:2rem;font-weight:800;color:#fff;margin:0 0 0.5rem;'
        'line-height:1.25;letter-spacing:-0.02em;">'
        'AI assisted <span style="color:#c03030">stock research</span>.</h1>'
        '<p style="font-size:1.02rem;color:rgba(255,255,255,0.55);line-height:1.8;'
        'max-width:620px;margin:0 0 1rem;">'
        'Sell-side research is biased. Reddit is noise. PickR runs a structured quality, '
        'growth, and valuation analysis across three price scenarios — for any US or Indian stock.</p>'
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;">'
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
                st.markdown(
                    f'<a href="?_qt={sq.upper()}" target="_self"'
                    f' style="font-size:0.82rem;color:rgba(255,255,255,0.45);'
                    f'text-decoration:underline;text-underline-offset:3px;">'
                    f'Try \'{sq.upper()}\' as a ticker anyway</a>',
                    unsafe_allow_html=True
                )
    else:
        pop_keys   = [k for k in POPULAR if k]
        recent_rev = list(reversed(st.session_state.recent[-6:]))

        _chip_css = """
<style>
.nav-chip-label{font-size:0.65rem;font-weight:800;text-transform:uppercase;
    letter-spacing:0.14em;color:rgba(255,255,255,0.4);margin:0.8rem 0 0.4rem;display:block;}
.nav-chip{color:rgba(255,255,255,0.7);font-weight:600;
    background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
    border-radius:4px;padding:0.15rem 0.55rem;text-decoration:none;
    font-size:0.82rem;white-space:nowrap;}
.nav-chip:hover{background:rgba(255,255,255,0.1);color:#fff;}
.nav-chips{display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.3rem;}
</style>"""

        if pop_keys:
            chips_html = "".join(
                f'<a href="?_qt={POPULAR[k]}" target="_self" class="nav-chip">'
                f'{k.split("(")[0].strip()}</a>'
                for k in pop_keys[:10]
            )
            st.markdown(
                f'{_chip_css}<span class="nav-chip-label">Popular</span>'
                f'<div class="nav-chips">{chips_html}</div>',
                unsafe_allow_html=True
            )
            _chip_css = ""  # inject CSS only once

        if recent_rev:
            recent_chips = "".join(
                f'<a href="?_qt={r}" target="_self" class="nav-chip">{clean_ticker(r)}</a>'
                for r in recent_rev
            )
            st.markdown(
                f'{_chip_css}<span class="nav-chip-label" style="margin-top:0.6rem;">Recent</span>'
                f'<div class="nav-chips">{recent_chips}</div>',
                unsafe_allow_html=True
            )

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
                if st.session_state.get("resolved"):
                    st.session_state["auto_generate"] = True
                st.session_state["show_auth"] = True
                st.rerun()
        with _cta_c2:
            if st.button("Create free account →", key="cta_signup_btn", type="primary", use_container_width=True):
                if st.session_state.get("resolved"):
                    st.session_state["auto_generate"] = True
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
        if st.session_state.get("authenticated"):
            st.session_state["_generating"] = True
        else:
            # Save the generate intent so it fires after login, then redirect to auth
            st.session_state["auto_generate"] = True
            st.session_state["show_auth"] = True
            st.rerun()

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

    if not authenticated:
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
        st.markdown('<div class="pickr-textlink">', unsafe_allow_html=True)
        if st.button("Sign up free →", key="rc_signup_btn", use_container_width=True):
            if st.session_state.get("resolved"):
                st.session_state["auto_generate"] = True
            st.session_state["show_auth"] = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

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
    _stale_days = _screener_age_days(last_updated)
    if _stale_days is not None and _stale_days > 3:
        st.markdown(
            f'<div style="background:rgba(180,140,20,0.10);border:1px solid rgba(220,180,40,0.28);'
            f'border-radius:8px;padding:0.7rem 1rem;margin-bottom:1rem;font-size:0.84rem;'
            f'color:rgba(255,255,255,0.65);">These picks are <strong>{_stale_days} days old</strong> — '
            f'the nightly screener has not refreshed. Prices and rankings may have moved.</div>',
            unsafe_allow_html=True
        )
    render_picks_table(screener_data.get("us_picks", [])[:5], "United States", "us_pick_select")
    render_picks_table(screener_data.get("india_picks", [])[:5], "India", "india_pick_select")

elif screener_error and not report_already_run:
    # Say so out loud. Rendering nothing here is what made an expired token
    # look like "the screener feature disappeared".
    st.markdown(
        '<div style="padding:2rem 0 0.8rem;">'
        '<div style="font-size:0.9rem;font-weight:900;text-transform:uppercase;'
        'letter-spacing:0.16em;color:rgba(255,255,255,0.7);">QGLP Top Picks</div>'
        '<div style="height:2px;background:linear-gradient(90deg,#8b1a1a,transparent);'
        'margin-top:0.6rem;border-radius:1px;"></div></div>'
        '<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);'
        'border-radius:8px;padding:1.2rem 1.4rem;font-size:0.88rem;color:rgba(255,255,255,0.55);'
        'line-height:1.7;">Top picks are temporarily unavailable — we could not load the screener '
        'data. Search for any ticker above to generate a report as normal.</div>',
        unsafe_allow_html=True
    )

# (auth redirect is now handled inline in the generate button block above)

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
        # Re-read the authoritative count before charging anything. If the
        # store is unreachable we must NOT fall through with a stale or zero
        # count — that would silently hand out unlimited free reports.
        try:
            from auth import load_users_result
            _res = load_users_result()
            if _res.broken or _res.unconfigured:
                st.error("We can't verify your report allowance right now. "
                         "Please try again in a few minutes.")
                print(f"  generation blocked: user store unavailable ({_res.describe()})")
                st.stop()
            if username in (_res.content or {}):
                st.session_state.report_count = _res.content[username].get("report_count", 0)
                report_count = st.session_state.report_count
        except Exception as _e:
            print(f"  generation blocked: allowance check raised {type(_e).__name__}: {_e}")
            st.error("We can't verify your report allowance right now. "
                     "Please try again in a few minutes.")
            st.stop()

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
            from session_cookie import clear_session_cookie
            clear_session_cookie()  # drop the guest cookie before wiping state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.stop()

    elif not is_guest and not _is_admin and report_count >= USER_LIMIT:
        st.warning(f"You've used all {USER_LIMIT} free reports. Paid tiers are coming soon.")
        st.stop()

    if is_guest:
        from auth import load_guest_counts
        fp     = st.session_state.get("guest_fingerprint", "unknown")
        counts = load_guest_counts()
        if counts.get(fp, 0) >= GUEST_LIMIT:
            st.error("This device has already used its free guest report. Please create an account.")
            st.stop()

    if ticker not in st.session_state.recent:
        st.session_state.recent.append(ticker)

    # NOTE: the report allowance is deliberately NOT charged here. It used to
    # be — increment_guest_count() and report_count += 1 both ran before a
    # single token was spent — so any downstream failure cost the user their
    # quota AND produced nothing. Both now happen after cached_report is set.

    st.session_state.cached_html          = None
    st.session_state.generate_html        = False
    st.session_state.html_just_generated  = False

    with status_area:
        with st.status(f"Analyzing {ticker}...", expanded=True) as status:
            st.markdown(
                "This may take 60–90 seconds. We're fetching live financials and "
                "building a scenario model across bull, base, and bear cases."
            )

            _failure = None
            a = None

            # Test seam (inert unless PICKR_OFFLINE=1): substitutes the whole
            # fetch → calc → run_pipeline chain with a fixture so the app-flow
            # suite can exercise gating, charging, failure handling and
            # rendering without a network. The maths is covered separately by
            # tests_methodology.py.
            if _offline_mode is not None:
                st.write("Step 1 of 6 - Fetching financial data (offline fixture)...")
                try:
                    m, a, sd = _offline_mode.generate(ticker)
                    company_name = m.get("company_name", ticker)
                except Exception as _exc:
                    import traceback
                    traceback.print_exc()
                    _failure = f"{type(_exc).__name__}: {_exc}"
            else:
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
                st.write("Step 2 of 6 - Computing financial metrics...")
                m = calc(sd)
                if "error" in m:
                    st.error(m["error"]); st.stop()
                st.write("Metrics computed")

                # Build §5.1 baseline (units in billions, §5.1 field names)
                consensus_pack   = fmp_api.fetch_consensus_pack(ticker)
                baseline         = calc_baseline(sd, consensus_pack=consensus_pack)
                if "error" in baseline:
                    st.error(baseline["error"]); st.stop()
                analysis_input_str = json.dumps(
                    {k: v for k, v in baseline.items() if k not in ["recent_news", "history_3y"]},
                    sort_keys=True, default=str)

                status.update(label=f"Analyzing {ticker}... (Step 3–6 of 6: AI + compute)")
                st.write("Step 3 of 6 - Running three-pass analysis (drivers → math → narrative → self-check)...")
                # run_pipeline returns an error dict for the validation paths it
                # anticipates, but LLMCallCeilingError and anything raised inside
                # run_methodology_math / run_pass3_audit escape it. Unwrapped, those
                # surfaced to the user as a raw Streamlit traceback.
                try:
                    a = _cached_analysis(ticker, analysis_input_str)
                except Exception as _exc:
                    import traceback
                    traceback.print_exc()
                    a = None
                    _failure = f"{type(_exc).__name__}: {_exc}"

            if _failure is None and isinstance(a, dict) and a.get("error"):
                _failure = a.get("error")
                for d in a.get("details", []):
                    print(f"  pipeline detail: {d}")

            if _failure is not None:
                status.update(label="Analysis failed", state="error")
                st.session_state["_generating"] = False
                _render_generation_failure(ticker, _failure,
                                           details=(a or {}).get("details", []) if isinstance(a, dict) else [],
                                           is_admin=_is_admin)
                st.stop()

            st.write("Analysis complete")
            rec = a.get("recommendation", "WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state["_generating"] = False
    st.session_state.cached_report = {"ticker": ticker, "metrics": m, "analysis": a, "data": sd}
    st.session_state["_scroll_to_report"] = True

    # ── Charge for the report only now that it demonstrably exists ──
    st.session_state.report_count = st.session_state.get("report_count", 0) + 1

    if is_guest:
        try:
            from auth import increment_guest_count
            increment_guest_count(st.session_state.get("guest_fingerprint", "unknown"))
        except Exception as _e:
            print(f"Could not persist guest count: {_e}")
        # Guests have no server-side account, so the authoritative allowance
        # rides in the signed cookie — otherwise a page reload (which every
        # ?_qt= chip triggers) resets it to zero.
        try:
            from session_cookie import set_guest_report_count
            set_guest_report_count(st.session_state.report_count)
        except Exception as _e:
            print(f"Could not update guest cookie count: {_e}")
    else:
        try:
            from auth import load_users_result, save_users_github
            _res = load_users_result()
            if _res.ok and username in _res.content:
                _res.content[username]["report_count"] = st.session_state.report_count
                save_users_github(_res.content, _res.sha)
            elif _res.broken:
                print(f"  report count not persisted: {_res.describe()}")
        except Exception as e:
            print(f"Could not persist report count: {e}")

    try:
        st.query_params["ticker"] = ticker
    except Exception:
        pass  # URL cosmetics only — deliberately silent (sweep-reviewed)

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
    if save_key not in st.session_state:
        try:
            if is_guest:
                # Guests used to get no persistence at all, so a single page
                # reload destroyed a report they had already spent tokens on.
                from report_store import save_guest_report
                from session_cookie import set_guest_report_ref
                _, _err = save_guest_report(
                    st.session_state.get("guest_fingerprint", ""), c_ticker, c_m, c_a)
                if not _err:
                    set_guest_report_ref(c_ticker)
                else:
                    print(f"Guest report save failed: {_err}")
            else:
                from report_store import save_report
                _, _err = save_report(username, c_ticker, c_m, c_a)
                if _err:
                    # Don't claim it was saved when it wasn't.
                    print(f"Report save failed: {_err}")
                    st.toast(f"{c_ticker} could not be saved to history.", icon="⚠️")
                else:
                    st.toast(f"{c_ticker} saved to history.", icon="💾")
            st.session_state[save_key] = True
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
                    pass  # URL cosmetics only — deliberately silent (sweep-reviewed)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        _has_stmts = any(c_data.get(k) is not None for k in ("inc", "bs", "cf"))
        if _has_stmts:
            _analysis_tab, _fin_tab = st.tabs(["Analysis", "Financials"])
            with _analysis_tab:
                render(c_ticker, c_m, c_a, c_data)
            with _fin_tab:
                _render_financials(c_data, cur=c_m.get("currency", "USD"))
        else:
            render(c_ticker, c_m, c_a, c_data)
        render_track_box(c_ticker, c_m, c_a)

        st.markdown('<hr class="div" style="margin-top:2rem;">', unsafe_allow_html=True)
        st.markdown('<div style="text-align:center;padding:0.8rem 0 0.5rem;"><div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div></div>', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)
        sm = c_a.get("scenario_math", {})
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
                "prob_positive": sm.get("prob_positive"),
                "price_target": sm.get("price_target"), "eps": sm.get("eps"),
                "final_probabilities": sm.get("final_probabilities"),
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