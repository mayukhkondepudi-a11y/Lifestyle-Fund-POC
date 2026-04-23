"""PickR authentication — custom login/register with bcrypt + GitHub storage."""
import json
import base64
import urllib.request
import urllib.error
import bcrypt
import streamlit as st
import hashlib

def _gh_headers():
    import config
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }

def _get_guest_fingerprint() -> str:
    """Best-effort guest fingerprint using Streamlit's request headers."""
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        ip = headers.get("X-Forwarded-For", headers.get("X-Real-Ip", "unknown"))
    except Exception:
        ip = "unknown"
    return hashlib.sha256(ip.encode()).hexdigest()[:16]

def load_guest_counts() -> dict:
    """Load guest_counts.json from GitHub. Returns {fingerprint: count}."""
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
    """Increment the count for a guest fingerprint. Returns new count."""
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return 1
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/guest_counts.json"
    counts = {}
    sha = None
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            sha = data["sha"]
            counts = json.loads(base64.b64decode(data["content"]).decode())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return 1
    except Exception:
        return 1

    counts[fingerprint] = counts.get(fingerprint, 0) + 1
    payload = {"message": "guest count update", "content": base64.b64encode(json.dumps(counts, indent=2).encode()).decode()}
    if sha:
        payload["sha"] = sha
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass
    return counts[fingerprint]

def _load_users():
    """Load users.json from GitHub."""
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return {}, None
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/users.json"
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
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
        "content": base64.b64encode(
            json.dumps(users, indent=2).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception as e:
        print(f"User save failed: {e}")
        return False


def _hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())


def render_auth_modal():
    """
    Render an inline login/register/guest UI (shown when user clicks Sign In
    or tries to generate a report while not authenticated).
    Returns (name, username, authenticated) after successful login.
    If not authenticated yet, renders the form and returns (None, None, False).
    """
    # Already logged in
    if st.session_state.get("authenticated"):
        return (st.session_state.get("user_name"),
                st.session_state.get("username"),
                True)

    st.markdown("""
    <style>
    .auth-modal-wrap {
        max-width: 460px;
        margin: 1rem auto 2rem;
        background: #161512;
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 14px;
        padding: 2rem 2rem 1.5rem;
    }
    .auth-modal-title {
        font-size: 1.15rem; font-weight: 800; color: #fff;
        margin-bottom: 0.3rem; text-align: center;
    }
    .auth-modal-sub {
        font-size: 0.85rem; color: rgba(255,255,255,0.4);
        text-align: center; margin-bottom: 1.4rem; line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="auth-modal-wrap">
        <div class="auth-modal-title">Sign in to generate reports</div>
        <div class="auth-modal-sub">
            Free account · 3 reports · Save history · Price alerts
        </div>
    </div>
    """, unsafe_allow_html=True)

    # We render the tabs outside the HTML div (Streamlit limitation)
    login_tab, register_tab, guest_tab = st.tabs(["Sign In", "Create Account", "Guest"])

    with login_tab:
        st.markdown('<div style="height:0.3rem;"></div>', unsafe_allow_html=True)
        login_user = st.text_input("Username", key="login_user", placeholder="your username")
        login_pass = st.text_input("Password", type="password", key="login_pass", placeholder="your password")
        if st.button("Sign In", key="login_btn", type="primary", use_container_width=True):
            if not login_user or not login_pass:
                st.error("Please enter both username and password.")
            else:
                users, _ = _load_users()
                user = users.get(login_user.lower().strip())
                if user and _check_password(login_pass, user["password_hash"]):
                    st.session_state["authenticated"] = True
                    st.session_state["username"]  = login_user.lower().strip()
                    st.session_state["user_name"] = user["name"]
                    st.session_state["user_email"] = user["email"]
                    st.session_state["show_auth"] = False
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

    with register_tab:
        st.markdown("""
        <div style="text-align:center;padding:0.4rem 0 0.8rem;">
            <div style="font-size:1rem;font-weight:700;color:#fff;margin-bottom:0.3rem">
                Get 3 free reports
            </div>
            <div style="font-size:0.82rem;color:rgba(255,255,255,0.45);line-height:1.6">
                Save your history · Unlimited browsing · Cancel anytime
            </div>
        </div>
        """, unsafe_allow_html=True)
        reg_name  = st.text_input("Full name",           key="reg_name",  placeholder="Mayukh Kondepudi")
        reg_email = st.text_input("Email",               key="reg_email", placeholder="you@example.com")
        reg_user  = st.text_input("Choose a username",   key="reg_user",  placeholder="mayukh")
        reg_pass  = st.text_input("Choose a password",   type="password", key="reg_pass",  placeholder="min 6 characters")
        reg_pass2 = st.text_input("Confirm password",    type="password", key="reg_pass2", placeholder="re-enter password")
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
                users, sha = _load_users()
                if username_reg in users:
                    st.error("Username already taken. Try another.")
                else:
                    users[username_reg] = {
                        "name": reg_name.strip(),
                        "email": reg_email.strip(),
                        "password_hash": _hash_password(reg_pass),
                    }
                    if _save_users(users, sha):
                        st.session_state["authenticated"] = True
                        st.session_state["username"]  = username_reg
                        st.session_state["user_name"] = reg_name.strip()
                        st.session_state["user_email"] = reg_email.strip()
                        st.session_state["show_auth"] = False
                        st.rerun()
                    else:
                        st.error("Could not save account. Try again.")

    with guest_tab:
        st.markdown("""
        <div style="background:rgba(139,26,26,0.1);border:1px solid rgba(224,48,48,0.2);
        border-radius:8px;padding:1rem 1.2rem;margin-bottom:1rem;">
            <div style="font-size:0.65rem;font-weight:800;text-transform:uppercase;
            letter-spacing:0.12em;color:#e03030;margin-bottom:0.5rem;">Guest Limits</div>
            <div style="font-size:0.88rem;color:rgba(255,255,255,0.7);line-height:1.7;">
                As a guest you get <strong style="color:#fff">1 free report</strong>.
                Create a free account to get <strong style="color:#fff">3 reports</strong>
                and save your history.
            </div>
        </div>
        <p style="color:#888;font-size:0.88rem;margin-bottom:0.8rem">
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
                st.session_state["authenticated"] = True
                st.session_state["username"]  = f"guest_{alias.lower().replace(' ', '_')}"
                st.session_state["user_name"] = alias
                st.session_state["user_email"] = ""
                st.session_state["is_guest"]  = True
                st.session_state["guest_fingerprint"] = fp
                st.session_state["show_auth"] = False
                st.rerun()

    if st.button("← Back to PickR", key="auth_back_btn"):
        st.session_state["show_auth"] = False
        st.rerun()

    return None, None, False


# Keep render_auth as an alias for backward compatibility
def render_auth():
    return render_auth_modal()


def render_sidebar(username, name, authenticator_logout=None):
    """Render the sidebar with user info and logout."""
    with st.sidebar:
        st.markdown(f'''<div style="padding:0.8rem 0 0.6rem;
            border-bottom:1px solid rgba(255,255,255,0.06);">
            <div style="font-size:0.9rem;color:#fff;font-weight:700;">{name}</div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.3);
                margin-top:0.1rem;">@{username}</div>
        </div>''', unsafe_allow_html=True)

        if st.button("Sign out", key="logout_btn", use_container_width=True):
            for key in ["authenticated", "username", "user_name",
                        "user_email", "cached_report"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()