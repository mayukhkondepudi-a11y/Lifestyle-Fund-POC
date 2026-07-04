"""Persisted-session cookie for PickR.

Streamlit's ``st.session_state`` is tied to the websocket session and is wiped
on every full page reload. PickR's stock-selection chips are HTML anchor links
(``?_qt=TICKER``) that trigger a full reload, which previously logged the user
out. This module persists a signed identity token in a browser cookie so auth
survives reloads (and ordinary refreshes).

The cookie only *asserts identity* — it carries no password, hash, or privilege.
On restore, non-guest users are re-loaded from ``users.json`` (the source of
truth). The token is HMAC-signed (tamper-evident) and time-limited.
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import streamlit as st

from config import PICKR_SESSION_SECRET

COOKIE_NAME = "pickr_session"
_TTL_SECONDS = 7 * 24 * 3600  # 7-day expiry


# ── Token sign / verify ───────────────────────────────────────

def make_token(identity: dict) -> str:
    """Build a signed token from an identity dict.

    Payload = base64(json(identity + exp)); token = "<payload>.<hmac_hex>".
    """
    payload = dict(identity)
    payload["exp"] = int(time.time()) + _TTL_SECONDS
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).decode()
    sig = hmac.new(PICKR_SESSION_SECRET.encode(), payload_b64.encode(),
                   hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str):
    """Return the identity dict if the token is authentic and unexpired, else None."""
    if not token or "." not in token:
        return None
    payload_b64, _, sig = token.rpartition(".")
    expected = hmac.new(PICKR_SESSION_SECRET.encode(), payload_b64.encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


# ── Cookie manager access ─────────────────────────────────────

def get_cookie_mgr():
    """Return the per-run CookieManager instantiated by app.py (or None)."""
    return st.session_state.get("_cookie_mgr")


def set_session_cookie(identity: dict) -> None:
    """Write the signed identity token to the browser cookie."""
    mgr = get_cookie_mgr()
    if mgr is None:
        return
    try:
        mgr.set(COOKIE_NAME, make_token(identity),
                expires_at=datetime.now() + timedelta(seconds=_TTL_SECONDS),
                same_site="lax")
    except Exception:
        pass


def clear_session_cookie() -> None:
    """Delete the session cookie (called on every sign-out path)."""
    mgr = get_cookie_mgr()
    if mgr is None:
        return
    try:
        mgr.delete(COOKIE_NAME)
    except Exception:
        pass


# ── Restore ───────────────────────────────────────────────────

def restore_session_from_cookie() -> bool:
    """If not already authenticated, restore identity from a valid cookie.

    Returns True if a session was restored. Non-guest identities are re-verified
    against users.json; if the user no longer exists, the cookie is ignored.
    """
    if st.session_state.get("authenticated"):
        return False
    mgr = get_cookie_mgr()
    if mgr is None:
        return False
    token = mgr.get(COOKIE_NAME)
    identity = verify_token(token) if token else None
    if not identity:
        return False

    username = identity.get("username", "")
    is_guest = bool(identity.get("is_guest"))

    if not is_guest:
        # users.json is the source of truth — re-load the record.
        try:
            from auth import load_users_github
            users, _ = load_users_github()
        except Exception:
            return False
        user = users.get(username)
        if not user:
            return False  # account gone / renamed → treat as logged out
        st.session_state["authenticated"] = True
        st.session_state["username"]      = username
        st.session_state["user_name"]     = user.get("name", identity.get("name", ""))
        st.session_state["user_email"]    = user.get("email", identity.get("email", ""))
        st.session_state["is_guest"]      = False
        st.session_state["report_count"]  = user.get("report_count", 0)
        return True

    # Guest: identity lives entirely in the token (no server record).
    st.session_state["authenticated"]     = True
    st.session_state["username"]          = username
    st.session_state["user_name"]         = identity.get("name", "")
    st.session_state["user_email"]        = ""
    st.session_state["is_guest"]          = True
    st.session_state["guest_fingerprint"] = identity.get("guest_fingerprint", "unknown")
    return True
