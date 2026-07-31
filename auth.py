"""PickR authentication — custom login/register with bcrypt + GitHub storage."""
import json
import re
import bcrypt
import streamlit as st
import hashlib
import os
import secrets

from gh_api import gh_read, gh_write

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$')

USERS_FILE = "users.json"

# ── Local-file helpers (kept for CLI tools / local dev only) ──

def load_users():
    """Load users from LOCAL file. Use load_users_github() in production."""
    if not os.path.exists(USERS_FILE):
        return {}, ""
    with open(USERS_FILE, "r") as f:
        raw = f.read()
    sha = hashlib.sha256(raw.encode()).hexdigest()
    return json.loads(raw), sha

def save_users(users, sha=None):
    """Save users to LOCAL file. Use save_users_github() in production."""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

# ── GitHub helpers ────────────────────────────────────────────

def _get_guest_fingerprint() -> str:
    """Best-effort per-visitor identifier.

    The IP-header path is unreliable: st.context.headers is only populated in
    some deployments, and the old private `_get_websocket_headers` import is
    deprecated. When it fails the fallback used to be the literal "unknown" for
    everyone, so sha256("unknown")[:16] == "b23a6a8439c0dde5" became a single
    global counter that every guest on earth shared — one guest anywhere burned
    the free report for all of them.

    A random per-session id is now generated instead, so a failed lookup
    isolates guests rather than merging them. The authoritative per-device
    allowance lives in the signed session cookie (session_cookie.py); this
    fingerprint is only a secondary, best-effort server-side tally.
    """
    ip = ""
    try:
        # Streamlit >= 1.37 public API.
        headers = st.context.headers or {}
        ip = headers.get("X-Forwarded-For", "") or headers.get("X-Real-Ip", "") or ""
        ip = ip.split(",")[0].strip()
    except Exception:
        ip = ""

    if not ip:
        # No usable header — fall back to a stable-per-session random id rather
        # than a shared constant. Kept in session_state so it survives reruns.
        rnd = st.session_state.get("_guest_fp_seed")
        if not rnd:
            rnd = secrets.token_hex(16)
            st.session_state["_guest_fp_seed"] = rnd
        return hashlib.sha256(rnd.encode()).hexdigest()[:16]

    return hashlib.sha256(ip.encode()).hexdigest()[:16]

def load_guest_counts() -> dict:
    """Server-side guest tally. Secondary check only — the authoritative
    per-device count lives in the signed session cookie (see session_cookie).
    A broken store here must not block a legitimate guest, so it degrades
    to an empty dict on purpose."""
    res = gh_read("guest_counts.json", data=True)
    return res.content if res.ok else {}

def increment_guest_count(fingerprint: str) -> int:
    res = gh_read("guest_counts.json", data=True)
    if res.broken:
        # Do not write over a store we could not read — that would clobber
        # every other guest's tally with a single-key file.
        print(f"  guest count: skipping write, store unreadable ({res.describe()})")
        return -1
    counts = res.content if res.ok else {}
    if not isinstance(counts, dict):
        counts = {}
    counts[fingerprint] = counts.get(fingerprint, 0) + 1
    gh_write("guest_counts.json", counts, res.sha,
             message="guest count update", data=True)
    return counts[fingerprint]

def load_users_result():
    """Load users.json from the private data repo. Returns the raw GhResult.

    Callers on the sign-in path MUST branch on ``.broken`` before treating an
    empty dict as "no such account" — that conflation is what turned an expired
    token into "Invalid username or password" for every valid user.

    Uncached on purpose: sign-in and the report-allowance check must both see
    the authoritative record.
    """
    return gh_read("users.json", data=True)


@st.cache_data(ttl=30, show_spinner=False)
def _load_users_result_cached():
    return gh_read("users.json", data=True)


def load_users_result_for_restore():
    """Short-TTL cached read, for session restore only.

    Every ?_qt= ticker chip is a full page reload, and each one re-ran this
    fetch — adding a GitHub round-trip to the very path that was already racing
    the cookie component. A 30s cache removes that cost from the hot path.

    Safe because restore only needs identity: a `report_count` up to 30s stale
    is never acted on, since generation re-reads uncached before charging.
    Never use this for sign-in or the allowance check.
    """
    try:
        return _load_users_result_cached()
    except Exception:
        return load_users_result()

def _load_users():
    """Legacy tuple accessor: (users_dict, sha). Loses the broken/absent
    distinction, so use load_users_result() on any authentication path."""
    res = load_users_result()
    return (res.content if res.ok else {}), res.sha

def _save_users(users, sha=None):
    """Save users.json to the private data repo."""
    res = gh_write("users.json", users, sha, message="auth: update users", data=True)
    if not res.ok:
        print(f"User save failed: {res.describe()}")
    return res.ok

# ── Public aliases so app.py can import cleanly ──
load_users_github  = _load_users
save_users_github  = _save_users

# ── Password helpers ──────────────────────────────────────────

def _hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

# ══════════════════════════════════════════════════════════════
# AUTH MODAL
# ══════════════════════════════════════════════════════════════

def render_auth_modal():
    """Inline auth overlay (centered card). Replaces @st.dialog version which
    had session-state-loss issues across reruns triggered from chip clicks."""
    if st.session_state.get("authenticated"):
        st.session_state["show_auth"] = False
        return

    # Center the card with column layout
    _l, _mid, _r = st.columns([1, 2, 1])
    if not _mid:
        return  # safety guard; shouldn't happen

    # Render everything inside the middle column
    with _mid:
        st.markdown('<div style="background:rgba(20,20,28,0.96);border:1px solid rgba(255,255,255,0.10);border-radius:12px;padding:1rem 1.6rem 1.4rem;margin:1.5rem 0;box-shadow:0 8px 40px rgba(0,0,0,0.5);">', unsafe_allow_html=True)

        st.markdown("""
    <style>
    /* ── Red primary buttons — override Streamlit's default blue ── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #8b1a1a 0%, #c03030 100%) !important;
        border: 1px solid rgba(192,48,48,0.4) !important;
        color: #fff !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
        box-shadow: 0 2px 12px rgba(139,26,26,0.3) !important;
        transition: all 0.18s ease !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #a52525 0%, #e04040 100%) !important;
        box-shadow: 0 4px 20px rgba(180,40,40,0.4) !important;
        transform: translateY(-1px) !important;
        border-color: rgba(220,60,60,0.5) !important;
    }
    .stButton > button[kind="primary"]:active {
        transform: scale(0.98) translateY(0) !important;
    }
    /* ── Tab styling on auth page ── */
    .stTabs [data-baseweb="tab"] {
        color: rgba(255,255,255,0.45) !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.03em !important;
    }
    .stTabs [aria-selected="true"] {
        color: #fff !important;
        border-bottom-color: #c03030 !important;
    }
    /* ── Inputs ── */
    input[type="text"], input[type="password"] {
        background: #0e0e14 !important;
        border-color: rgba(255,255,255,0.15) !important;
        color: #fff !important;
    }
    </style>
        """, unsafe_allow_html=True)
    
        # Branding header
        st.markdown("""
        <div style="text-align:center;padding:2rem 0 0.5rem;">
            <div style="display:inline-flex;align-items:center;gap:0.6rem;margin-bottom:0.8rem;">
                <svg width="32" height="32" viewBox="0 0 28 28" fill="none">
                    <rect width="28" height="28" rx="7" fill="#8b1a1a"/>
                    <rect x="7" y="6" width="3.5" height="16" rx="1.75" fill="white" opacity="0.9"/>
                    <rect x="12" y="10" width="3.5" height="12" rx="1.75" fill="white" opacity="0.7"/>
                    <rect x="17" y="7" width="3.5" height="15" rx="1.75" fill="white" opacity="0.85"/>
                    <circle cx="18.75" cy="6.5" r="2.2" fill="#f87171"/>
                </svg>
                <span style="font-size:1.6rem;font-weight:900;color:#fff;letter-spacing:-0.02em;">
                    Pick<span style="color:#c03030;">R</span>
                </span>
            </div>
            <div style="font-size:0.9rem;color:rgba(255,255,255,0.4);line-height:1.6;">
                Your research, saved. &nbsp;&middot;&nbsp; 3 free reports &nbsp;&middot;&nbsp; History &amp; alerts
            </div>
        </div>
        """, unsafe_allow_html=True)
    
        guest_tab, login_tab, register_tab = st.tabs(["Continue as Guest", "Sign In", "Create Account"])
    
        with login_tab:
            st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
            login_user = st.text_input("Username", key="login_user", placeholder="your username")
            login_pass = st.text_input("Password", type="password", key="login_pass", placeholder="your password")
            if st.button("Sign In", key="login_btn", type="primary", use_container_width=True):
                if not login_user or not login_pass:
                    st.error("Please enter both username and password.")
                else:
                    # The private data repo is the source of truth.
                    _res  = load_users_result()
                    users = _res.content if _res.ok else {}
                    # An unreachable store is NOT a wrong password. Saying so
                    # is what made an expired token look like deleted accounts.
                    if _res.broken or _res.unconfigured:
                        print(f"  login blocked: user store unavailable ({_res.describe()})")
                        st.error(
                            "Sign-in is temporarily unavailable — we couldn't reach the "
                            "account store. Your account is fine; please try again shortly."
                        )
                        st.stop()
                    user = users.get(login_user.lower().strip())
                    if user and _check_password(login_pass, user["password_hash"]):
                        _uname = login_user.lower().strip()
                        st.session_state["authenticated"] = True
                        st.session_state["username"]      = _uname
                        st.session_state["user_name"]     = user["name"]
                        st.session_state["user_email"]    = user["email"]
                        # Load persisted report count from GitHub, not local file
                        st.session_state.report_count     = user.get("report_count", 0)
                        st.session_state["show_auth"]     = False
                        st.session_state["_just_authed"]  = True
                        from session_cookie import set_session_cookie
                        set_session_cookie({"username": _uname, "is_guest": False,
                                            "name": user["name"], "email": user["email"]})
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")
    
        with register_tab:
            st.markdown("""
            <div style="text-align:center;padding:0.4rem 0 0.8rem;">
                <div style="font-size:1rem;font-weight:700;color:#fff;margin-bottom:0.3rem;">Get 3 free reports</div>
                <div style="font-size:0.82rem;color:rgba(255,255,255,0.4);line-height:1.6;">
                    Save your history &nbsp;&middot;&nbsp; Unlimited browsing &nbsp;&middot;&nbsp; Price alerts
                </div>
            </div>
            """, unsafe_allow_html=True)
            reg_name  = st.text_input("Full name",         key="reg_name",  placeholder="Mayukh Kondepudi")
            reg_email = st.text_input("Email",             key="reg_email", placeholder="you@example.com")
            reg_user  = st.text_input("Choose a username", key="reg_user",  placeholder="mayukh")
            reg_pass  = st.text_input("Choose a password", type="password", key="reg_pass",  placeholder="min 6 characters")
            reg_pass2 = st.text_input("Confirm password",  type="password", key="reg_pass2", placeholder="re-enter password")
            if st.button("Create Account", key="reg_btn", type="primary", use_container_width=True):
                if not all([reg_name, reg_email, reg_user, reg_pass, reg_pass2]):
                    st.error("All fields are required.")
                elif not _EMAIL_RE.match(reg_email.strip()):
                    st.error("Please enter a valid email address (e.g. you@example.com).")
                elif len(reg_user.strip()) < 3:
                    st.error("Username must be at least 3 characters.")
                elif len(reg_pass) < 6:
                    st.error("Password must be at least 6 characters.")
                elif reg_pass != reg_pass2:
                    st.error("Passwords don't match.")
                else:
                    username_reg = reg_user.lower().strip()
                    _res = load_users_result()
                    # Never write over a store we could not read: doing so would
                    # replace every existing account with this single new one.
                    if _res.broken or _res.unconfigured:
                        print(f"  registration blocked: user store unavailable ({_res.describe()})")
                        st.error(
                            "Account creation is temporarily unavailable — we couldn't reach "
                            "the account store. Please try again shortly."
                        )
                        st.stop()
                    users, sha = (_res.content if _res.ok else {}), _res.sha
                    if username_reg in users:
                        st.error("Username already taken. Try another.")
                    else:
                        users[username_reg] = {
                            "name":          reg_name.strip(),
                            "email":         reg_email.strip(),
                            "password_hash": _hash_password(reg_pass),
                            "report_count":  0,          # explicit zero so count always exists
                        }
                        if _save_users(users, sha):
                            st.session_state["authenticated"] = True
                            st.session_state["username"]      = username_reg
                            st.session_state["user_name"]     = reg_name.strip()
                            st.session_state["user_email"]    = reg_email.strip()
                            st.session_state.report_count     = 0
                            st.session_state["show_auth"]     = False
                            st.session_state["_just_authed"]  = True
                            from session_cookie import set_session_cookie
                            set_session_cookie({"username": username_reg, "is_guest": False,
                                                "name": reg_name.strip(), "email": reg_email.strip()})
                            st.rerun()
                        else:
                            st.error("Could not save account. Please try again.")
    
        with guest_tab:
            st.markdown("""
            <div style="background:rgba(139,26,26,0.1);border:1px solid rgba(224,48,48,0.18);
            border-radius:8px;padding:1rem 1.2rem;margin-bottom:1rem;">
                <div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;
                letter-spacing:0.12em;color:#e03030;margin-bottom:0.5rem;">Guest Limits</div>
                <div style="font-size:0.88rem;color:rgba(255,255,255,0.7);line-height:1.7;">
                    As a guest you get <strong style="color:#fff;">1 free report</strong>.
                    Create a free account for <strong style="color:#fff;">3 reports</strong>
                    and saved history.
                </div>
            </div>
            <p style="color:rgba(255,255,255,0.4);font-size:0.88rem;margin-bottom:0.8rem;">
                No account needed — just pick an alias to continue.
            </p>
            """, unsafe_allow_html=True)
            guest_alias = st.text_input("Choose a guest alias", key="guestalias_input",
                                        placeholder="e.g. CuriousInvestor", max_chars=20)
            if st.button("Enter as Guest", key="guestbtn", type="primary", use_container_width=True):
                alias = guest_alias.strip()
                if not alias:
                    st.error("Please enter an alias to continue.")
                elif len(alias) < 2:
                    st.error("Alias must be at least 2 characters.")
                else:
                    fp = _get_guest_fingerprint()
                    _guest_username = f"guest_{alias.lower().replace(' ', '_')}"
                    st.session_state["authenticated"]    = True
                    st.session_state["username"]         = _guest_username
                    st.session_state["user_name"]        = alias
                    st.session_state["user_email"]       = ""
                    st.session_state["is_guest"]         = True
                    st.session_state["guest_fingerprint"] = fp
                    st.session_state["show_auth"]        = False
                    st.session_state["_just_authed"]     = True
                    from session_cookie import set_session_cookie
                    set_session_cookie({"username": _guest_username, "is_guest": True,
                                        "name": alias, "guest_fingerprint": fp})
                    st.rerun()
    
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        if st.button("← Back to PickR", key="auth_back_btn", use_container_width=True):
            st.session_state["show_auth"] = False
            st.rerun()

        # close the wrapping card div
        st.markdown("</div>", unsafe_allow_html=True)
    

# Alias for backward compatibility
def render_auth():
    render_auth_modal()


def render_sidebar(username, name, authenticator_logout=None):
    with st.sidebar:
        st.markdown(f'''<div style="padding:0.8rem 0 0.6rem;
            border-bottom:1px solid rgba(255,255,255,0.06);">
            <div style="font-size:0.9rem;color:#fff;font-weight:700;">{name}</div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.3);margin-top:0.1rem;">@{username}</div>
        </div>''', unsafe_allow_html=True)
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            sign_out()


def sign_out():
    """Fully sign the current user out.

    Must clear the persisted cookie FIRST (it needs the cookie manager, which
    lives in session_state) and must clear `is_guest`. Dropping only a few
    session keys left the cookie in place, so restore_session_from_cookie()
    silently logged the user straight back in on the next run.
    """
    from session_cookie import clear_session_cookie
    clear_session_cookie()
    for key in list(st.session_state.keys()):
        if key == "_cookie_mgr":
            continue  # keep the manager alive for this run's cookie delete
        del st.session_state[key]
    st.rerun()
