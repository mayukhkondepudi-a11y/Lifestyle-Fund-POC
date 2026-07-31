"""Session/cookie diagnostics, shown at ``?_debug=1``.

Why this exists
---------------
The "logged out on reload" bug was misdiagnosed twice, because the cookie's
actual state was never visible — only inferred from behaviour. Both fixes
assumed a cookie existed; it did not. This panel makes the state observable on
the deployed app so the next question is answered by looking, not guessing.

Deliberately exposes only presence and validity — never a token, hash, or
secret value. Safe to leave enabled.
"""
import streamlit as st

_DEV_SECRET = "pickr-dev-insecure-session-secret"


def _row(label, value, ok=None):
    colour = {True: "#4ade80", False: "#f87171", None: "rgba(255,255,255,0.75)"}[ok]
    return (
        f'<div style="display:flex;gap:0.75rem;padding:0.28rem 0;'
        f'border-bottom:1px solid rgba(255,255,255,0.05);">'
        f'<div style="flex:0 0 240px;color:rgba(255,255,255,0.45);">{label}</div>'
        f'<div style="color:{colour};font-weight:600;word-break:break-all;">{value}</div></div>'
    )


def _context_cookies():
    """Cookies from the initial HTTP request — server-side, no iframe."""
    try:
        return dict(st.context.cookies or {})
    except Exception as exc:
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def _component_cookies():
    """What the CookieManager iframe has reported back (may lag or never arrive)."""
    mgr = st.session_state.get("_cookie_mgr")
    if mgr is None:
        return None
    try:
        return dict(getattr(mgr, "cookies", None) or {})
    except Exception as exc:
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def render():
    """Render the diagnostics panel. Returns True if it rendered."""
    from session_cookie import COOKIE_NAME, verify_token

    ctx_cookies  = _context_cookies()
    comp_cookies = _component_cookies()

    ctx_has  = COOKIE_NAME in ctx_cookies
    comp_has = bool(comp_cookies) and COOKIE_NAME in comp_cookies

    # Token verdict — the thing that actually decides whether you stay logged in.
    raw = ctx_cookies.get(COOKIE_NAME) or (comp_cookies or {}).get(COOKIE_NAME)
    if not raw:
        verdict, verdict_ok = "absent — no cookie to verify", False
    else:
        identity = verify_token(raw)
        if identity:
            verdict, verdict_ok = (
                f"VALID (user={identity.get('username')}, "
                f"guest={bool(identity.get('is_guest'))})", True)
        else:
            # verify_token folds these together; separate them for diagnosis.
            import base64, json, time
            try:
                payload_b64, _, _sig = raw.rpartition(".")
                payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
                expired = payload.get("exp", 0) < time.time()
                verdict = ("EXPIRED" if expired
                           else "BAD SIGNATURE — secret changed or token forged")
            except Exception:
                verdict = "MALFORMED — not a valid token"
            verdict_ok = False

    try:
        from config import PICKR_SESSION_SECRET
        secret_is_dev = PICKR_SESSION_SECRET == _DEV_SECRET
    except Exception:
        secret_is_dev = True

    # Resolved config. Streamlit Cloud rejects secret names starting with
    # GITHUB_, so these must come from GH_PAT / PICKR_REPO / PICKR_DATA_REPO.
    # An unset data repo silently breaks sign-in AND report saving.
    try:
        import config
        from gh_api import resolve_repo
        _tok = bool(config.GITHUB_TOKEN)
        _code = resolve_repo(data=False) or "(unset)"
        _data_set = bool(getattr(config, "GITHUB_DATA_REPO", ""))
        _data = resolve_repo(data=True) or "(unset)"
    except Exception as exc:
        _tok, _code, _data, _data_set = False, f"error: {exc}", "?", False

    rows = [
        _row("GitHub token (GH_PAT)", "present" if _tok else "MISSING", _tok),
        _row("Code repo (PICKR_REPO)", _code, _code != "(unset)"),
        _row("Data repo (PICKR_DATA_REPO)",
             _data if _data_set else f"NOT SET — falling back to {_data}",
             _data_set),
        _row("st.context.cookies keys",
             ", ".join(sorted(ctx_cookies)) or "(none)"),
        _row(f"'{COOKIE_NAME}' in context cookies",
             "YES" if ctx_has else "NO", ctx_has),
        _row("CookieManager component",
             "not instantiated" if comp_cookies is None
             else (", ".join(sorted(comp_cookies)) or "(reported empty)"),
             None if comp_cookies is None else bool(comp_cookies)),
        _row(f"'{COOKIE_NAME}' in component",
             "YES" if comp_has else "NO", comp_has),
        _row("Token verdict", verdict, verdict_ok),
        _row("session_state.authenticated",
             str(st.session_state.get("authenticated")),
             bool(st.session_state.get("authenticated"))),
        _row("session_state.username",
             str(st.session_state.get("username") or "(none)")),
        _row("session_state.is_guest", str(st.session_state.get("is_guest"))),
        _row("_pending_cookie queued",
             "YES" if st.session_state.get("_pending_cookie") else "no"),
        _row("PICKR_SESSION_SECRET",
             "DEV DEFAULT — tokens are forgeable" if secret_is_dev else "configured",
             not secret_is_dev),
    ]

    st.markdown(
        '<div style="background:rgba(10,10,16,0.95);border:1px solid rgba(255,255,255,0.12);'
        'border-radius:10px;padding:1rem 1.3rem;margin:1rem 0;font-size:0.8rem;'
        'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">'
        '<div style="font-weight:800;color:#fff;letter-spacing:0.08em;margin-bottom:0.6rem;">'
        'SESSION DIAGNOSTICS <span style="color:rgba(255,255,255,0.35);font-weight:500;">'
        '&nbsp;?_debug=1</span></div>'
        + "".join(rows) +
        '<div style="margin-top:0.7rem;color:rgba(255,255,255,0.35);font-size:0.75rem;">'
        'The cookie is READ server-side from the initial request '
        '(st.context.cookies) and WRITTEN by the CookieManager component. '
        'If the context row says NO after a sign-in and reload, the write never landed.'
        '</div></div>',
        unsafe_allow_html=True
    )
    return True
