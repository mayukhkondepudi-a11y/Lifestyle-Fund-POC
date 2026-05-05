"""PickR authentication — custom login/register with bcrypt + GitHub storage."""
import json
import base64
import urllib.request
import urllib.error
import bcrypt
import streamlit as st
import hashlib
import os

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

def _gh_headers():
    import config
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }

def _get_guest_fingerprint() -> str:
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        ip = headers.get("X-Forwarded-For", headers.get("X-Real-Ip", "unknown"))
    except Exception:
        ip = "unknown"
    return hashlib.sha256(ip.encode()).hexdigest()[:16]

def load_guest_counts() -> dict:
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return {}
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/guest_counts.json"
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return json.loads(base64.b64decode(data["content"]).decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
    except Exception:
        pass
    return {}

def increment_guest_count(fingerprint: str) -> int:
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return 1
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/guest_counts.json"
    counts = {}; sha = None
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            sha    = data["sha"]
            counts = json.loads(base64.b64decode(data["content"]).decode())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return 1
    except Exception:
        return 1
    counts[fingerprint] = counts.get(fingerprint, 0) + 1
    payload = {
        "message": "guest count update",
        "content": base64.b64encode(json.dumps(counts, indent=2).encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception:
        pass
    return counts[fingerprint]

def _load_users():
    """Load users.json from GitHub. Returns (users_dict, sha)."""
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return {}, None
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/users.json"
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data    = json.loads(resp.read().decode())
            content = json.loads(base64.b64decode(data["content"]).decode())
            return content, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}, None
    except Exception:
        pass
    return {}, None

def _save_users(users, sha=None):
    """Save users.json to GitHub."""
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return False
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/users.json"
    payload = {
        "message": "auth: update users",
        "content": base64.b64encode(json.dumps(users, indent=2).encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10): pass
        return True
    except Exception as e:
        print(f"User save failed: {e}")
        return False

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
    """Inline login/register/guest UI."""
    if st.session_state.get("authenticated"):
        return (st.session_state.get("user_name"),
                st.session_state.get("username"), True)

    st.markdown("""
    <style>
    /* ── Auth page container ── */
    .auth-modal-wrap {
        max-width: 460px;
        margin: 1rem auto 2rem;
        background: #12121a;
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 14px;
        padding: 2rem 2rem 1.5rem;
        box-shadow: 0 8px 40px rgba(0,0,0,0.5);
    }
    .auth-modal-title {
        font-size: 1.15rem; font-weight: 800; color: #fff;
        margin-bottom: 0.3rem; text-align: center;
    }
    .auth-modal-sub {
        font-size: 0.85rem; color: rgba(255,255,255,0.4);
        text-align: center; margin-bottom: 1.4rem; line-height: 1.6;
    }
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
            Sign in to generate reports &nbsp;&middot;&nbsp; 3 free · Save history · Price alerts
        </div>
    </div>
    """, unsafe_allow_html=True)

    login_tab, register_tab, guest_tab = st.tabs(["Sign In", "Create Account", "Guest"])

    with login_tab:
        st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
        login_user = st.text_input("Username", key="login_user", placeholder="your username")
        login_pass = st.text_input("Password", type="password", key="login_pass", placeholder="your password")
        if st.button("Sign In", key="login_btn", type="primary", use_container_width=True):
            if not login_user or not login_pass:
                st.error("Please enter both username and password.")
            else:
                # Always use GitHub as source of truth
                users, _ = _load_users()
                user = users.get(login_user.lower().strip())
                if user and _check_password(login_pass, user["password_hash"]):
                    st.session_state["authenticated"] = True
                    st.session_state["username"]      = login_user.lower().strip()
                    st.session_state["user_name"]     = user["name"]
                    st.session_state["user_email"]    = user["email"]
                    # Load persisted report count from GitHub, not local file
                    st.session_state.report_count     = user.get("report_count", 0)
                    st.session_state["show_auth"]     = False
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
            elif "@" not in reg_email:
                st.error("Please enter a valid email address.")
            elif len(reg_user.strip()) < 3:
                st.error("Username must be at least 3 characters.")
            elif len(reg_pass) < 6:
                st.error("Password must be at least 6 characters.")
            elif reg_pass != reg_pass2:
                st.error("Passwords don't match.")
            else:
                username_reg = reg_user.lower().strip()
                users, sha   = _load_users()
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
                st.session_state["authenticated"]    = True
                st.session_state["username"]         = f"guest_{alias.lower().replace(' ', '_')}"
                st.session_state["user_name"]        = alias
                st.session_state["user_email"]       = ""
                st.session_state["is_guest"]         = True
                st.session_state["guest_fingerprint"] = fp
                st.session_state["show_auth"]        = False
                st.rerun()

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
     if st.button("← Back to PickR", key="auth_back_btn", 
                 use_container_width=True):
        st.session_state["show_auth"] = False
        st.session_state["authenticated"] = False
        st.rerun()

    return None, None, False


# Alias for backward compatibility
def render_auth():
    return render_auth_modal()


def render_sidebar(username, name, authenticator_logout=None):
    with st.sidebar:
        st.markdown(f'''<div style="padding:0.8rem 0 0.6rem;
            border-bottom:1px solid rgba(255,255,255,0.06);">
            <div style="font-size:0.9rem;color:#fff;font-weight:700;">{name}</div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.3);margin-top:0.1rem;">@{username}</div>
        </div>''', unsafe_allow_html=True)
        if st.button("Sign out", key="logout_btn", use_container_width=True):
            for key in ["authenticated","username","user_name","user_email","cached_report"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()