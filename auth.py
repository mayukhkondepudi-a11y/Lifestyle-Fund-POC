"""PickR authentication — custom login/register with bcrypt + GitHub storage."""
import json
import base64
import urllib.request
import urllib.error
import bcrypt
import streamlit as st


def _gh_headers():
    import config
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


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


def render_auth():
    """
    Render login/register UI. Returns (name, username, authenticated).
    Call at top of app.py. If not authenticated, caller should st.stop().
    """
    # Already logged in this session
    if st.session_state.get("authenticated"):
        return (st.session_state.get("user_name"),
                st.session_state.get("username"),
                True)

    # Auth UI
    st.markdown('''<div style="text-align:center;padding:3rem 0 1rem;">
        <h1 style="font-size:3.5rem;font-weight:900;margin:0;">
            <span style="background:linear-gradient(180deg,#fff 0%,#e0e0e0 75%,#e8e8e8 100%);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;">Pick</span><span
            style="background:linear-gradient(135deg,#a52525,#e04040 30%,#ff8a8a 50%,#e04040 70%,#a52525);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;">R</span></h1>
        <div style="font-size:1rem;color:rgba(255,255,255,0.35);margin-top:0.3rem;">
            AI Assisted Equity Research</div>
    </div>''', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        login_tab, register_tab = st.tabs(["Sign In", "Create Account"])

        with login_tab:
            st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
            login_user = st.text_input("Username", key="login_user",
                                        placeholder="your username")
            login_pass = st.text_input("Password", type="password",
                                        key="login_pass",
                                        placeholder="your password")

            if st.button("Sign In", key="login_btn", type="primary",
                         use_container_width=True):
                if not login_user or not login_pass:
                    st.error("Please enter both username and password.")
                else:
                    users, _ = _load_users()
                    user = users.get(login_user.lower().strip())
                    if user and _check_password(login_pass, user["password_hash"]):
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = login_user.lower().strip()
                        st.session_state["user_name"] = user["name"]
                        st.session_state["user_email"] = user["email"]
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

        with register_tab:
            st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
            reg_name  = st.text_input("Full name", key="reg_name",
                                       placeholder="Mayukh Kondepudi")
            reg_email = st.text_input("Email", key="reg_email",
                                       placeholder="you@example.com")
            reg_user  = st.text_input("Choose a username", key="reg_user",
                                       placeholder="mayukh")
            reg_pass  = st.text_input("Choose a password", type="password",
                                       key="reg_pass",
                                       placeholder="min 6 characters")
            reg_pass2 = st.text_input("Confirm password", type="password",
                                       key="reg_pass2",
                                       placeholder="re-enter password")

            if st.button("Create Account", key="reg_btn", type="primary",
                         use_container_width=True):
                # Validation
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
                    username = reg_user.lower().strip()
                    users, sha = _load_users()

                    if username in users:
                        st.error("Username already taken. Try another.")
                    else:
                        users[username] = {
                            "name": reg_name.strip(),
                            "email": reg_email.strip(),
                            "password_hash": _hash_password(reg_pass),
                        }
                        if _save_users(users, sha):
                            st.success("Account created! Switch to Sign In.")
                        else:
                            st.error("Could not save account. Try again.")

    # Not authenticated
    return None, None, False


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
