"""Boot-time health check for every external dependency PickR needs.

Why this exists
---------------
On 2026-07-31 an expired GitHub PAT presented to users as four unrelated
symptoms — a missing screener, an empty history, unsaved report counts, and
"Invalid username or password" for valid accounts — because every read path
mapped failure onto an empty value. Nothing in the app could say it was broken.

This module answers one question: *which of my dependencies are actually
working right now?* Run it at boot, render the result, and config rot becomes
a banner instead of a week of mystery bug reports.

Standalone use:
    python -c "import preflight; print(preflight.report())"
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# Screener data older than this is stale enough to warn about — the nightly
# Action should refresh it daily, so 3 days means the Action is failing.
SCREENER_STALE_DAYS = 3

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str                      # OK | WARN | FAIL
    detail: str = ""
    remedy: str = ""                 # what the operator should do about it

    @property
    def healthy(self) -> bool:
        return self.status == OK


@dataclass
class Health:
    checks: List[Check] = field(default_factory=list)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def ok(self) -> bool:
        return not self.failures and not self.warnings

    @property
    def degraded(self) -> bool:
        return bool(self.failures or self.warnings)

    def get(self, name: str) -> Optional[Check]:
        return next((c for c in self.checks if c.name == name), None)

    def failed(self, name: str) -> bool:
        c = self.get(name)
        return bool(c and c.status == FAIL)

    def as_text(self) -> str:
        icon = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
        lines = [f"[{icon[c.status]}] {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)


# ── Individual checks ─────────────────────────────────────────

def _check_api_key(name, value, remedy) -> Check:
    if not value:
        return Check(name, FAIL, "not configured", remedy)
    return Check(name, OK, "configured")


def _check_github() -> List[Check]:
    """Token validity and, critically, whether user data sits in a public repo."""
    import config
    from gh_api import gh_probe, resolve_repo

    out: List[Check] = []

    if not config.GITHUB_TOKEN:
        out.append(Check("GitHub token", FAIL, "GH_PAT / GITHUB_TOKEN not set",
                         "Set GH_PAT in .streamlit/secrets.toml and Streamlit Cloud secrets."))
        return out

    code_repo = resolve_repo(data=False)
    data_repo = resolve_repo(data=True)

    probe = gh_probe(data=False)
    if probe.ok:
        out.append(Check("GitHub token", OK, f"valid for {code_repo}"))
    elif probe.status == "auth_error":
        out.append(Check("GitHub token", FAIL,
                         f"REJECTED by GitHub ({probe.error}) — the token is expired or revoked",
                         "Rotate the PAT: see docs/OPERATIONS.md §1. This single failure "
                         "disables login, history, screener and report saving."))
        return out
    elif probe.status == "rate_limited":
        out.append(Check("GitHub token", WARN, "rate limit exhausted",
                         "Wait for the hourly window to reset."))
    else:
        out.append(Check("GitHub token", FAIL, f"cannot reach GitHub ({probe.error})",
                         "Check network egress from the deployment host."))
        return out

    # Data repo: reachable, and private?
    if not getattr(config, "GITHUB_DATA_REPO", ""):
        out.append(Check("User data repo", FAIL,
                         f"GITHUB_DATA_REPO unset — user data is falling back to {code_repo}",
                         "Create a PRIVATE repo and set GITHUB_DATA_REPO. Emails and "
                         "password hashes must not live in a public repo."))
    else:
        dprobe = gh_probe(data=True)
        if not dprobe.ok:
            out.append(Check("User data repo", FAIL,
                             f"{data_repo} unreachable ({dprobe.error})",
                             "Confirm the PAT has contents access to the data repo."))
        elif (dprobe.content or {}).get("private") is False:
            out.append(Check("User data repo", FAIL,
                             f"{data_repo} is PUBLIC — emails and password hashes are exposed",
                             "Make the repo private in GitHub settings immediately."))
        else:
            out.append(Check("User data repo", OK, f"{data_repo} reachable and private"))

    return out


def _check_users() -> Check:
    """The account store must be readable, or nobody can sign in."""
    from auth import load_users_result
    res = load_users_result()
    if res.ok:
        n = len(res.content) if isinstance(res.content, dict) else 0
        return Check("Account store", OK, f"{n} accounts loaded")
    if res.absent:
        return Check("Account store", WARN, "users.json does not exist yet",
                     "Normal on a fresh deployment; it is created on first signup.")
    return Check("Account store", FAIL, f"unreadable ({res.status}: {res.error})",
                 "Sign-in is disabled until this is fixed. See docs/OPERATIONS.md §1.")


def _check_screener() -> Check:
    """Screener data present, parseable, and actually being refreshed."""
    from github_store import load_screener_results_raw
    data = load_screener_results_raw()
    if not data:
        return Check("Screener data", FAIL, "unavailable from GitHub and local disk",
                     "Check the QGLP Screener Action; it uses the same PAT.")

    last = data.get("last_updated", "")
    us = len(data.get("us_picks", []) or [])
    ind = len(data.get("india_picks", []) or [])
    try:
        ts = datetime.strptime(last[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).days
    except Exception:
        return Check("Screener data", WARN, f"{us} US / {ind} India picks, unparseable date '{last}'")

    if age > SCREENER_STALE_DAYS:
        return Check("Screener data", WARN,
                     f"{age} days stale (last updated {last})",
                     "The nightly screener Action is likely failing — check its GH_PAT secret.")
    return Check("Screener data", OK, f"{us} US / {ind} India picks, updated {last}")


# ── Entry points ──────────────────────────────────────────────

def run() -> Health:
    """Run every check. Never raises — a broken check reports itself as FAIL."""
    import config
    checks: List[Check] = []

    checks.extend(_check_github())
    checks.append(_check_api_key(
        "Anthropic API key", config.ANTHROPIC_API_KEY,
        "Set ANTHROPIC_API_KEY — report generation cannot run without it."))
    checks.append(_check_api_key(
        "FMP API key", config.FMP_API_KEY,
        "Set FMP_API_KEY — financial data falls back to yfinance without it."))

    # Only probe stores when the token itself is usable; otherwise every
    # downstream check just restates the same root cause.
    token_check = next((c for c in checks if c.name == "GitHub token"), None)
    if token_check and token_check.status == FAIL:
        checks.append(Check("Account store", FAIL, "skipped — GitHub token is not usable"))
    else:
        try:
            checks.append(_check_users())
        except Exception as exc:
            checks.append(Check("Account store", FAIL, f"check raised {type(exc).__name__}: {exc}"))

    try:
        checks.append(_check_screener())
    except Exception as exc:
        checks.append(Check("Screener data", FAIL, f"check raised {type(exc).__name__}: {exc}"))

    return Health(checks=checks)


def report() -> str:
    """Plain-text health report, for CLI use."""
    return run().as_text()


def cached() -> Health:
    """Streamlit-cached health check (5 min TTL) for use in the app."""
    import streamlit as st

    @st.cache_data(ttl=300, show_spinner=False)
    def _run():
        return run()

    try:
        return _run()
    except Exception:
        # Never let the health check itself take the app down.
        return Health(checks=[])


if __name__ == "__main__":
    h = run()
    print(h.as_text())
    print()
    for c in h.failures + h.warnings:
        if c.remedy:
            print(f"→ {c.name}: {c.remedy}")
    raise SystemExit(1 if h.failures else 0)
