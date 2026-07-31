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


# ── Reading: server-side, from the initial HTTP request ───────
#
# st.context.cookies (Streamlit >= 1.37) exposes the cookies the browser sent
# with the page request. It is resolved SERVER-SIDE and is available on the very
# first script run — no iframe, no browser round-trip, no race.
#
# The old code read through the CookieManager component instead, which returns
# {} until its iframe mounts and reports back. That is what the retry loop,
# hydration gate and time.sleep() in app.py existed to paper over, and it is
# why a reload could look like a sign-out. Reading server-side removes the
# entire failure mode (and ~1.2s of latency from every page load).

def read_raw_cookie() -> str:
    """The raw session token from the request, or "" if absent.

    Prefers st.context.cookies; falls back to the component only where the
    context is unavailable (older Streamlit, or AppTest).
    """
    try:
        token = (st.context.cookies or {}).get(COOKIE_NAME)
        if token:
            return token
    except Exception:
        pass

    mgr = get_cookie_mgr()
    if mgr is None:
        return ""
    try:
        return mgr.get(COOKIE_NAME) or ""
    except Exception:
        return ""


def read_identity() -> dict:
    """Return the verified identity currently in the cookie, or {}."""
    token = read_raw_cookie()
    return (verify_token(token) or {}) if token else {}


# ── Writing: must happen on a run that COMPLETES ──────────────
#
# mgr.set() does not write a cookie. It renders a component whose JavaScript
# writes document.cookie once the browser mounts the iframe. Calling st.rerun()
# straight afterwards aborts the run before that can happen, so the cookie was
# never stored — the actual cause of "logged out on reload".
#
# Callers must therefore NOT rerun immediately after these. app.py drains
# _pending_cookie / _pending_cookie_clear at the top of a normal run instead;
# see queue_session_cookie() below.

def set_session_cookie(identity: dict) -> None:
    """Write the signed identity token to the browser cookie.

    Only safe to call on a run that will finish rendering. To set a cookie from
    a handler that reruns (login, register, guest entry), use
    queue_session_cookie() instead.
    """
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
    """Delete the session cookie. Same completing-run requirement as above."""
    mgr = get_cookie_mgr()
    if mgr is None:
        return
    try:
        mgr.delete(COOKIE_NAME)
    except Exception:
        pass


def queue_session_cookie(identity: dict) -> None:
    """Ask app.py to write this cookie at the top of the next run.

    Use from any handler that calls st.rerun(), which is all of them.
    """
    st.session_state["_pending_cookie"] = dict(identity)
    st.session_state.pop("_pending_cookie_clear", None)


def queue_clear_session_cookie() -> None:
    """Ask app.py to delete the cookie at the top of the next run.

    Must be set AFTER any session_state wipe, or the flag is wiped with it.
    """
    st.session_state["_pending_cookie_clear"] = True
    st.session_state.pop("_pending_cookie", None)


def drain_pending_cookie() -> str:
    """Apply any queued cookie write/delete. Called once per run by app.py,
    immediately after the CookieManager is instantiated and never followed by
    an immediate rerun. Returns what it did, for logging."""
    if st.session_state.pop("_pending_cookie_clear", False):
        clear_session_cookie()
        return "cleared"
    pending = st.session_state.pop("_pending_cookie", None)
    if pending:
        set_session_cookie(pending)
        return "written"
    return ""


def _guest_identity_from_session() -> dict:
    """Rebuild the guest identity from session_state.

    Deliberately NOT read from the cookie: st.context.cookies is a snapshot of
    the initial request, so a cookie written earlier in this same session is not
    visible yet. session_state is the live truth mid-session.
    """
    if not st.session_state.get("is_guest"):
        return {}
    return {
        "username":          st.session_state.get("username", ""),
        "is_guest":          True,
        "name":              st.session_state.get("user_name", ""),
        "guest_fingerprint": st.session_state.get("guest_fingerprint", "unknown"),
        "report_count":      int(st.session_state.get("report_count", 0) or 0),
        "report_ticker":     st.session_state.get("_guest_report_ticker", ""),
    }


def set_guest_report_count(count: int) -> None:
    """Persist a guest's report tally into the signed cookie.

    Guests have no server-side account record, so session_state was the only
    home for their count — and a page reload wipes it. The tally rides in the
    HMAC-signed token instead, so it survives reloads and cannot be hand-edited.

    This is the authoritative per-device allowance; guest_counts.json on the
    server is a secondary, best-effort tally (its fingerprint is unreliable).
    """
    identity = _guest_identity_from_session()
    if not identity:
        return
    st.session_state["report_count"] = int(count)
    identity["report_count"] = int(count)
    set_session_cookie(identity)


def set_guest_report_ref(ticker: str) -> None:
    """Record which ticker the guest's persisted report holds, so it can be
    restored after a reload without a server lookup by guesswork."""
    identity = _guest_identity_from_session()
    if not identity:
        return
    st.session_state["_guest_report_ticker"] = ticker
    identity["report_ticker"] = ticker
    set_session_cookie(identity)


# ── Restore ───────────────────────────────────────────────────

def restore_session_from_cookie() -> bool:
    """If not already authenticated, restore identity from a valid cookie.

    Returns True if a session was restored. Non-guest identities are re-verified
    against users.json; if the user no longer exists, the cookie is ignored.
    """
    if st.session_state.get("authenticated"):
        return False
    # Server-side read from the initial request — succeeds on the FIRST run,
    # so there is nothing to wait for and no reason to rerun-and-retry.
    identity = read_identity()
    if not identity:
        return False

    username = identity.get("username", "")
    is_guest = bool(identity.get("is_guest"))

    if not is_guest:
        # users.json is the source of truth — re-load the record.
        try:
            # Cached (30s): this runs on every page reload, and each ?_qt= chip
            # is a reload. Identity is all we need here; the allowance check at
            # generation time re-reads uncached.
            from auth import load_users_result_for_restore
            res = load_users_result_for_restore()
        except Exception:
            return False

        if res.broken or res.unconfigured:
            # The store is down, NOT the account missing. Logging the user out
            # here is how an expired token became "I got signed out at random"
            # on every reload. The token is HMAC-signed and unexpired, so trust
            # it for identity and degrade only the server-backed fields.
            print(f"  session restore: user store unavailable ({res.describe()}) "
                  f"— trusting signed cookie for '{username}'")
            st.session_state["authenticated"] = True
            st.session_state["username"]      = username
            st.session_state["user_name"]     = identity.get("name", "")
            st.session_state["user_email"]    = identity.get("email", "")
            st.session_state["is_guest"]      = False
            st.session_state["_store_degraded"] = True
            # Leave report_count alone: an unverified 0 would silently hand the
            # user a fresh quota. app.py re-reads it before charging anything.
            return True

        users = res.content if res.ok else {}
        user = users.get(username)
        if not user:
            return False  # account genuinely gone / renamed → treat as logged out
        st.session_state["authenticated"] = True
        st.session_state["username"]      = username
        st.session_state["user_name"]     = user.get("name", identity.get("name", ""))
        st.session_state["user_email"]    = user.get("email", identity.get("email", ""))
        st.session_state["is_guest"]      = False
        st.session_state["report_count"]  = user.get("report_count", 0)
        st.session_state["_store_degraded"] = False
        return True

    # Guest: identity lives entirely in the token (no server record).
    st.session_state["authenticated"]     = True
    st.session_state["username"]          = username
    st.session_state["user_name"]         = identity.get("name", "")
    st.session_state["user_email"]        = ""
    st.session_state["is_guest"]          = True
    st.session_state["guest_fingerprint"] = identity.get("guest_fingerprint", "unknown")
    # The allowance must survive the reload too, or a guest gets unlimited
    # reports simply by clicking a ticker chip (which reloads the page).
    st.session_state["report_count"]      = int(identity.get("report_count", 0) or 0)
    st.session_state["_guest_report_ticker"] = identity.get("report_ticker", "")
    return True
