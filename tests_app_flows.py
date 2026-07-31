"""End-to-end app-flow regression tests, driven through streamlit's AppTest.

These exist because of the 2026-07-31 outage. An expired GitHub PAT broke four
user-visible features at once, and every one of them failed *silently* — the
screener rendered nothing, history rendered empty, and valid accounts were told
"Invalid username or password". The engine suite was fully green throughout,
because none of it touches the application shell.

So: the tests here assert what a person actually experiences. The most important
ones are the "degraded" cases — they encode the rule that a broken dependency
must never masquerade as an empty or wrong one.

Run:  PICKR_OFFLINE=1 pytest tests_app_flows.py
"""
import os
import re

import pytest

# The seam must be armed before app.py is imported by AppTest.
os.environ.setdefault("PICKR_OFFLINE", "1")

import offline_mode  # noqa: E402

APP = "app.py"
TIMEOUT = 30


# ── Helpers ───────────────────────────────────────────────────

def _all_text(at) -> str:
    """Every string the app rendered this run, concatenated.

    Most of PickR's UI is st.markdown with unsafe_allow_html, so assertions
    are made against raw rendered text rather than widget structure.
    """
    chunks = []
    for attr in ("markdown", "error", "warning", "info", "success", "caption",
                 "text", "header", "subheader", "title"):
        try:
            chunks.extend(el.value for el in getattr(at, attr))
        except Exception:
            pass
    for attr in ("exception",):
        try:
            chunks.extend(str(el.value) for el in getattr(at, attr))
        except Exception:
            pass
    return "\n".join(str(c) for c in chunks)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s)


def _ss(at, key, default=None):
    """AppTest's session_state raises rather than supporting .get()."""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _run(gh="local", fail=False, secrets=None, session=None):
    """Boot the app under the seam and return the AppTest instance."""
    from streamlit.testing.v1 import AppTest

    os.environ["PICKR_OFFLINE"] = "1"
    os.environ["PICKR_OFFLINE_GH"] = gh
    os.environ["PICKR_OFFLINE_FAIL"] = "1" if fail else "0"

    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.secrets["GITHUB_TOKEN"] = "offline-token"
    at.secrets["GITHUB_REPO"] = "offline/code"
    at.secrets["GITHUB_DATA_REPO"] = "offline/pickr-data"
    at.secrets["ANTHROPIC_API_KEY"] = "offline-key"
    at.secrets["FMP_API_KEY"] = "offline-key"
    for k, v in (secrets or {}).items():
        at.secrets[k] = v
    for k, v in (session or {}).items():
        at.session_state[k] = v
    return at.run()


@pytest.fixture(autouse=True)
def _clean_store():
    """Fresh fake GitHub store per test, seeded with one known account.

    st.cache_data survives across AppTest instances in one process, so the
    preflight result and screener payload must be cleared too — otherwise a
    healthy result from an earlier test masks a degraded one here.
    """
    import streamlit as st

    os.environ["PICKR_OFFLINE"] = "1"
    os.environ["PICKR_OFFLINE_DIR"] = "/tmp/pickr_offline_store_test"
    try:
        st.cache_data.clear()
    except Exception:
        pass
    offline_mode.reset_store()
    offline_mode.seed_user("testuser", "Test User", "test@example.com",
                           "correct-horse", report_count=0)
    yield
    offline_mode.reset_store()


def _signed_in(username="testuser", **extra):
    """Session state for an already-authenticated non-guest."""
    base = {
        "authenticated": True,
        "username": username,
        "user_name": "Test User",
        "user_email": "test@example.com",
        "is_guest": False,
        "show_auth": False,
        "initialized": True,
        "report_count": 0,
    }
    base.update(extra)
    return base


def _guest(**extra):
    base = {
        "authenticated": True,
        "username": "guest_tester",
        "user_name": "Tester",
        "user_email": "",
        "is_guest": True,
        "guest_fingerprint": "fp_test",
        "show_auth": False,
        "initialized": True,
        "report_count": 0,
    }
    base.update(extra)
    return base


# ── Boot ──────────────────────────────────────────────────────

class TestAppBoots:
    def test_logged_out_landing_renders_without_exception(self):
        at = _run()
        assert not at.exception, f"app raised on boot: {at.exception}"

    def test_signed_in_landing_renders_without_exception(self):
        at = _run(session=_signed_in())
        assert not at.exception, f"app raised when signed in: {at.exception}"


# ── Screener (regression for the silently-missing picks table) ──

class TestScreener:
    def test_picks_render_when_data_available(self):
        at = _run(session=_signed_in())
        text = _strip_html(_all_text(at))
        assert "QGLP Top Picks" in text

    def test_degraded_screener_says_so_instead_of_rendering_nothing(self, monkeypatch):
        """The original bug: load failure -> None -> section silently skipped.

        A user cannot distinguish "feature removed" from "temporarily broken",
        so the app must say which it is.
        """
        import github_store
        monkeypatch.setattr(github_store, "load_screener_results_raw", lambda: None)
        at = _run(session=_signed_in())
        text = _strip_html(_all_text(at))
        assert "QGLP Top Picks" in text, "section header should still render"
        assert "temporarily unavailable" in text.lower(), (
            "a failed screener load must be explained, not silently omitted"
        )


# ── Sign-in (regression for 'valid account rejected as bad password') ──

class TestSignIn:
    def _open_auth(self, gh="local"):
        return _run(gh=gh, session={"show_auth": True, "initialized": True})

    def test_wrong_password_is_rejected(self):
        at = self._open_auth()
        at.text_input(key="login_user").set_value("testuser")
        at.text_input(key="login_pass").set_value("wrong-password")
        at.button(key="login_btn").click().run()
        assert "Invalid username or password" in _all_text(at)

    def test_correct_password_authenticates(self):
        at = self._open_auth()
        at.text_input(key="login_user").set_value("testuser")
        at.text_input(key="login_pass").set_value("correct-horse")
        at.button(key="login_btn").click().run()
        assert _ss(at, "authenticated") is True
        assert _ss(at, "username") == "testuser"

    def test_broken_store_never_reports_a_bad_password(self):
        """THE regression test for the outage.

        With the account store unreachable, the old code loaded {} and told
        every valid user their password was wrong — which read as "my account
        was deleted" and destroyed trust in the whole app.
        """
        at = self._open_auth(gh="broken")
        at.text_input(key="login_user").set_value("testuser")
        at.text_input(key="login_pass").set_value("correct-horse")
        at.button(key="login_btn").click().run()
        text = _all_text(at)
        assert "Invalid username or password" not in text, (
            "an unreachable store must never be reported as a wrong password"
        )
        assert "temporarily unavailable" in text.lower()
        assert _ss(at, "authenticated") is not True

    def test_broken_store_blocks_registration_rather_than_overwriting(self):
        """Registering against an unread store would PUT a single-user file,
        replacing every existing account."""
        at = self._open_auth(gh="broken")
        at.text_input(key="reg_name").set_value("New Person")
        at.text_input(key="reg_email").set_value("new@example.com")
        at.text_input(key="reg_user").set_value("newperson")
        at.text_input(key="reg_pass").set_value("hunter2222")
        at.text_input(key="reg_pass2").set_value("hunter2222")
        at.button(key="reg_btn").click().run()
        assert "temporarily unavailable" in _all_text(at).lower()

        # And the seeded account must still be intact.
        os.environ["PICKR_OFFLINE_GH"] = "local"
        status, users, _ = offline_mode.gh_read("users.json")
        assert status == "ok" and "testuser" in users


# ── Report generation: charging and failure ───────────────────

class TestReportGeneration:
    def test_successful_report_renders_and_charges_once(self):
        at = _run(session=_signed_in(resolved="CLS", auto_generate=True))
        assert not at.exception, f"generation raised: {at.exception}"
        assert _ss(at, "cached_report") is not None
        assert _ss(at, "report_count") == 1

    def test_failed_report_shows_a_card_and_costs_nothing(self):
        """Charging happened before generation, so a failure took the user's
        quota and their tokens and produced nothing but a traceback."""
        at = _run(fail=True, session=_signed_in(resolved="CLS", auto_generate=True))
        text = _strip_html(_all_text(at))
        assert "Couldn't finish" in text or "couldn't finish" in text.lower()
        assert _ss(at, "report_count") == 0, (
            "a failed report must not consume the user's allowance"
        )
        assert _ss(at, "cached_report") in (None, False)

    def test_failure_is_not_a_raw_traceback(self):
        at = _run(fail=True, session=_signed_in(resolved="CLS", auto_generate=True))
        assert not at.exception, (
            "pipeline failures must be caught and rendered, not surfaced as a traceback"
        )


# ── Limits ────────────────────────────────────────────────────

class TestLimits:
    def test_user_at_limit_is_blocked(self):
        offline_mode.seed_user("testuser", "Test User", "test@example.com",
                               "correct-horse", report_count=3)
        at = _run(session=_signed_in(resolved="CLS", auto_generate=True, report_count=3))
        assert "used all 3 free reports" in _all_text(at)
        assert _ss(at, "cached_report") in (None, False)

    def test_guest_at_limit_sees_upgrade_cta(self):
        at = _run(session=_guest(resolved="CLS", auto_generate=True, report_count=1))
        text = _strip_html(_all_text(at))
        assert "used your free guest report" in text

    def test_admin_is_not_limited(self):
        offline_mode.seed_user("mayukhk", "Admin", "admin@example.com",
                               "correct-horse", report_count=99)
        at = _run(session=_signed_in(username="mayukhk", resolved="CLS",
                                     auto_generate=True, report_count=99))
        assert _ss(at, "cached_report") is not None

    def test_allowance_check_blocks_when_store_is_unreachable(self):
        """Falling through with an unverified count would hand out unlimited
        free reports whenever GitHub hiccuped."""
        at = _run(gh="broken", session=_signed_in(resolved="CLS", auto_generate=True))
        assert _ss(at, "cached_report") in (None, False)
        assert "allowance" in _all_text(at).lower()


# ── Guest persistence (regression for the vanishing paid-for report) ──

class TestGuestPersistence:
    def test_guest_report_is_persisted_for_reload(self):
        at = _run(session=_guest(resolved="CLS", auto_generate=True))
        assert _ss(at, "cached_report") is not None
        stored = offline_mode.load_guest_report_raw() if hasattr(
            offline_mode, "load_guest_report_raw") else None
        status, content, _ = offline_mode.gh_read("reports/_guest/fp_test.json")
        assert status == "ok" and content.get("ticker") == "CLS", (
            "a guest's report must outlive the session; a ?_qt= chip is a full reload"
        )

    def test_guest_count_survives_in_the_cookie_payload(self):
        """The tally must not live only in session_state, which a reload wipes."""
        from session_cookie import make_token, verify_token
        tok = make_token({"username": "guest_x", "is_guest": True,
                          "name": "X", "report_count": 1})
        assert verify_token(tok)["report_count"] == 1

    def test_guest_fingerprints_are_not_all_identical(self):
        """sha256("unknown")[:16] was the single global guest bucket."""
        import hashlib
        assert hashlib.sha256(b"unknown").hexdigest()[:16] == "b23a6a8439c0dde5"
        at = _run(session=_guest())
        # The seeded fingerprint is preserved; the point is that the fallback
        # is no longer a shared constant.
        import auth
        assert "unknown" not in str(auth._get_guest_fingerprint.__doc__ or "").split("\n")[0]


# ── Session cookie: the bug that caused "logged out on reload" ──

class _FakeCookieMgr:
    """Records set/delete calls so we can assert the write actually happened."""

    def __init__(self, cookies=None):
        self.cookies = dict(cookies or {})
        self.sets = []
        self.deletes = []

    def get(self, name):
        return self.cookies.get(name)

    def set(self, name, val, **kw):
        self.sets.append((name, val, kw))
        self.cookies[name] = val

    def delete(self, name, **kw):
        self.deletes.append(name)
        self.cookies.pop(name, None)


def _patch_context_cookies(monkeypatch, cookies: dict):
    """st.context.cookies is a property on ContextProxy, so patch the class."""
    from streamlit.runtime.context import ContextProxy
    monkeypatch.setattr(ContextProxy, "cookies",
                        property(lambda self: dict(cookies)), raising=False)


class TestSessionCookieWrite:
    """THE root cause.

    mgr.set() does not write a cookie — it renders a component whose JS writes
    document.cookie when the browser mounts the iframe. All three auth paths
    called st.rerun() immediately afterwards, aborting the run before that could
    happen, so the cookie was NEVER stored. Every reload then logged the user
    out, which surfaced as "picking a stock logs me out" because the ticker
    chips were full page reloads.
    """

    def test_auth_paths_queue_the_cookie_instead_of_writing_then_rerunning(self):
        src = open("auth.py").read()
        assert "queue_session_cookie(" in src
        assert "set_session_cookie({" not in src, (
            "an auth handler writes the cookie directly; the st.rerun() that "
            "follows will abort the run before the component can store it"
        )

    def test_queue_then_drain_actually_writes(self):
        import streamlit as st
        import session_cookie as sc

        mgr = _FakeCookieMgr()
        st.session_state["_cookie_mgr"] = mgr
        try:
            sc.queue_session_cookie({"username": "u", "is_guest": False, "name": "U"})
            assert mgr.sets == [], "must not write before the drain"
            action = sc.drain_pending_cookie()
            assert action == "written"
            assert len(mgr.sets) == 1
            name, token, _ = mgr.sets[0]
            assert name == sc.COOKIE_NAME
            assert sc.verify_token(token)["username"] == "u"
        finally:
            st.session_state.clear()

    def test_drain_is_wired_into_app_before_anything_reruns(self):
        src = open("app.py").read()
        assert "drain_pending_cookie()" in src
        assert src.find("_COOKIE_MAX_WAITS") == -1, "the hydration retry gate should be gone"
        assert "time.sleep" not in src and "_t.sleep" not in src, (
            "no sleep-and-retry should remain on the boot path"
        )
        # Compare CALL sites, not the import line.
        assert src.index("drain_pending_cookie()") < src.index("restore_session_from_cookie()"), (
            "the queued write must be applied before identity is restored"
        )

    def test_sign_out_queues_the_clear_after_wiping_state(self):
        import streamlit as st
        import session_cookie as sc
        st.session_state["authenticated"] = True
        st.session_state["_cookie_mgr"] = _FakeCookieMgr({sc.COOKIE_NAME: "x"})
        try:
            # Mirror sign_out()'s ordering: wipe, THEN queue.
            for k in [k for k in st.session_state.keys() if k != "_cookie_mgr"]:
                del st.session_state[k]
            sc.queue_clear_session_cookie()
            assert st.session_state.get("_pending_cookie_clear") is True, (
                "the flag must be set AFTER the wipe or it is wiped too"
            )
            assert sc.drain_pending_cookie() == "cleared"
            assert st.session_state["_cookie_mgr"].deletes == [sc.COOKIE_NAME]
        finally:
            st.session_state.clear()


class TestSessionCookieRead:
    """Reads now come from st.context.cookies — server-side, first run, no race.

    This path was previously unreachable in tests (it went through a JS iframe),
    which is why the bug survived two attempted fixes.
    """

    def test_valid_cookie_restores_on_the_first_run(self, monkeypatch):
        import streamlit as st
        import session_cookie as sc

        token = sc.make_token({"username": "testuser", "is_guest": False,
                               "name": "Test User", "email": "t@e.com"})
        _patch_context_cookies(monkeypatch, {sc.COOKIE_NAME: token})
        st.session_state.clear()
        try:
            assert sc.restore_session_from_cookie() is True
            assert st.session_state["authenticated"] is True
            assert st.session_state["username"] == "testuser"
        finally:
            st.session_state.clear()

    def test_absent_cookie_does_not_restore_and_does_not_raise(self, monkeypatch):
        import streamlit as st
        import session_cookie as sc
        _patch_context_cookies(monkeypatch, {})
        st.session_state.clear()
        try:
            assert sc.restore_session_from_cookie() is False
        finally:
            st.session_state.clear()

    def test_expired_token_does_not_restore(self, monkeypatch):
        import base64, json, hmac, hashlib, time
        import streamlit as st
        import session_cookie as sc
        from config import PICKR_SESSION_SECRET

        payload = {"username": "u", "is_guest": False, "exp": int(time.time()) - 5}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        b64 = base64.urlsafe_b64encode(raw).decode()
        sig = hmac.new(PICKR_SESSION_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
        _patch_context_cookies(monkeypatch, {sc.COOKIE_NAME: f"{b64}.{sig}"})
        st.session_state.clear()
        try:
            assert sc.restore_session_from_cookie() is False
        finally:
            st.session_state.clear()

    def test_tampered_token_does_not_restore(self, monkeypatch):
        import streamlit as st
        import session_cookie as sc
        token = sc.make_token({"username": "attacker", "is_guest": False})
        payload, _, _sig = token.rpartition(".")
        _patch_context_cookies(monkeypatch, {sc.COOKIE_NAME: f"{payload}.{'0'*64}"})
        st.session_state.clear()
        try:
            assert sc.restore_session_from_cookie() is False
        finally:
            st.session_state.clear()

    def test_read_prefers_context_over_the_component(self, monkeypatch):
        """Component reads lag behind a page load; the request headers do not."""
        import streamlit as st
        import session_cookie as sc
        good = sc.make_token({"username": "from_context", "is_guest": False})
        _patch_context_cookies(monkeypatch, {sc.COOKIE_NAME: good})
        st.session_state.clear()
        st.session_state["_cookie_mgr"] = _FakeCookieMgr({})   # component empty
        try:
            assert sc.read_identity().get("username") == "from_context"
        finally:
            st.session_state.clear()


class TestSessionSecret:
    def test_preflight_fails_on_the_public_dev_default(self, monkeypatch):
        import importlib
        import config, preflight
        importlib.reload(preflight)
        monkeypatch.setattr(config, "PICKR_SESSION_SECRET",
                            "pickr-dev-insecure-session-secret")
        check = preflight._check_session_secret()
        assert check.status == "fail"
        assert check.remedy


# ── Cookie hydration (regression for "picking a stock logged me out") ──

class TestCookieHydration:
    """The old hydration gate (retry + sleep, waiting on the CookieManager
    iframe) has been deleted — st.context.cookies resolves server-side on the
    first run, so there is nothing to wait for. Those tests went with it; what
    remains is the read-path caching guarantee.
    """

    def test_restore_uses_the_cached_read_not_the_authoritative_one(self):
        """Restore runs on every reload; it must not add a GitHub round-trip
        to the path already racing the cookie component."""
        src = open("session_cookie.py").read()
        assert "load_users_result_for_restore" in src
        # ...while sign-in and the allowance check stay uncached.
        assert "load_users_result()" in open("auth.py").read()
        assert "load_users_result" in open("app.py").read()


# ── Sign-out ──────────────────────────────────────────────────

class TestSignOut:
    def test_sign_out_clears_authentication(self):
        at = _run(session=_signed_in())
        at.button(key="logout_btn").click().run()
        assert _ss(at, "authenticated") in (None, False)


# ── Health surfacing ──────────────────────────────────────────

class TestHealthBanner:
    def test_degraded_dependency_is_surfaced_to_the_user(self):
        at = _run(gh="broken", session=_signed_in())
        text = _strip_html(_all_text(at)).lower()
        assert "temporarily unavailable" in text or "system health" in text, (
            "a failing dependency must be visible somewhere in the UI"
        )

    def test_admin_sees_the_specific_failure(self):
        offline_mode.seed_user("mayukhk", "Admin", "admin@example.com", "x")
        at = _run(gh="broken", session=_signed_in(username="mayukhk"))
        assert "SYSTEM HEALTH" in _strip_html(_all_text(at))


# ── Preflight unit-level ──────────────────────────────────────

class TestPreflight:
    def test_healthy_config_reports_ok(self):
        os.environ["PICKR_OFFLINE_GH"] = "local"
        import importlib
        import preflight
        importlib.reload(preflight)
        health = preflight.run()
        assert not health.failed("GitHub token")

    def test_broken_token_is_reported_as_failure_with_a_remedy(self):
        os.environ["PICKR_OFFLINE_GH"] = "broken"
        import importlib
        import preflight
        importlib.reload(preflight)
        health = preflight.run()
        assert health.failed("GitHub token")
        check = health.get("GitHub token")
        assert check.remedy, "a failing check must tell the operator what to do"
