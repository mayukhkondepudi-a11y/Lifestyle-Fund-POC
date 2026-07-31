"""Canonical GitHub Contents API helpers.

Single source of truth for reading/writing JSON files in the project's
GitHub repos. Replaces the duplicated `_gh_*` helpers previously in
report_store.py, github_store.py, and auth.py.

Two repos are addressed:
  * ``config.GITHUB_REPO``      — public: code + screener_results.json
  * ``config.GITHUB_DATA_REPO`` — private: users.json, guest_counts.json, reports/

THE CENTRAL RULE OF THIS MODULE
-------------------------------
"The file is not there" and "I could not reach the store" are DIFFERENT
ANSWERS and must never collapse into the same value.

The old API returned ``(None, None)`` for a 404, a 401, a timeout and a
parse error alike. Every caller read that as "empty", so an expired token
presented to users as an empty screener, an empty history, and — worst —
"Invalid username or password" for a perfectly valid account. The app had
no way to say it was broken.

``GhResult.status`` now carries that distinction, and ``GhResult.broken``
is the single predicate callers should branch on before treating an empty
result as genuinely empty.
"""
import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

# ── Status values ────────────────────────────────────────────
# "ok"           — request succeeded, content is valid
# "absent"       — 404: the file genuinely does not exist yet (NOT an error)
# "unconfigured" — no token/repo configured; caller decides whether that's fatal
# "auth_error"   — 401/403: token expired, revoked, or lacks scope
# "rate_limited" — 403 with the rate-limit budget exhausted
# "server_error" — 5xx from GitHub
# "network_error"— DNS/TLS/timeout/connection reset
# "parse_error"  — reached GitHub, but the payload was not the JSON we expect
_BROKEN = {"auth_error", "rate_limited", "server_error", "network_error", "parse_error"}


@dataclass(frozen=True)
class GhResult:
    """Outcome of a GitHub Contents API call.

    ``ok``      — the operation did what was asked.
    ``broken``  — the store could not be reached or trusted. Callers MUST NOT
                  treat a broken result as "empty"; surface it instead.
    ``absent``  — the file does not exist. Safe to treat as empty.
    """
    ok: bool
    content: Any = None
    sha: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None
    repo: Optional[str] = None
    path: Optional[str] = None

    @property
    def broken(self) -> bool:
        """True when the store could not be reached or trusted."""
        return self.status in _BROKEN

    @property
    def absent(self) -> bool:
        """True when GitHub confirmed the file simply does not exist."""
        return self.status == "absent"

    @property
    def unconfigured(self) -> bool:
        return self.status == "unconfigured"

    def content_or(self, default):
        """Content when ok, else the supplied default.

        Deliberately does NOT hide brokenness — check ``.broken`` first if the
        difference matters (on any auth or user-data path, it always does).
        """
        return self.content if self.ok else default

    def describe(self) -> str:
        """Short human-readable line for banners and logs."""
        where = f"{self.repo or '?'}/{self.path or '?'}"
        if self.ok:
            return f"{where}: ok"
        if self.absent:
            return f"{where}: not found"
        return f"{where}: {self.status}" + (f" ({self.error})" if self.error else "")


# ── Configuration ─────────────────────────────────────────────

def resolve_repo(repo=None, *, data=False):
    """Return the repo slug to address.

    ``repo``  explicit override wins.
    ``data``  True selects the private data repo (users/reports/guest counts),
              falling back to GITHUB_REPO when GITHUB_DATA_REPO is unset so
              existing single-repo deployments keep working.
    """
    import config
    if repo:
        return repo
    if data:
        return getattr(config, "GITHUB_DATA_REPO", "") or config.GITHUB_REPO
    return config.GITHUB_REPO


def gh_headers():
    """Standard GitHub API request headers."""
    import config
    return {
        "Authorization":        f"Bearer {config.GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":         "application/json",
    }


def _classify_http_error(exc: urllib.error.HTTPError) -> str:
    if exc.code == 404:
        return "absent"
    if exc.code == 401:
        return "auth_error"
    if exc.code == 403:
        # 403 is overloaded: bad scope vs. exhausted rate budget.
        try:
            remaining = exc.headers.get("X-RateLimit-Remaining")
        except Exception:
            remaining = None
        return "rate_limited" if remaining == "0" else "auth_error"
    if exc.code >= 500:
        return "server_error"
    return "server_error"


# ── Read ──────────────────────────────────────────────────────

def gh_read(filepath, repo=None, *, data=False, timeout=10) -> GhResult:
    """Fetch a JSON file from a repo. Always returns a GhResult.

    Prefer this over gh_get_json() anywhere the difference between "absent"
    and "broken" affects what the user is told.
    """
    import config
    slug = resolve_repo(repo, data=data)
    if not config.GITHUB_TOKEN or not slug:
        return GhResult(ok=False, status="unconfigured", repo=slug, path=filepath,
                        error="GITHUB_TOKEN or repo not configured")

    url = f"https://api.github.com/repos/{slug}/contents/{filepath}"
    try:
        req = urllib.request.Request(url, headers=gh_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        status = _classify_http_error(exc)
        return GhResult(ok=False, status=status, repo=slug, path=filepath,
                        error=f"HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        return GhResult(ok=False, status="network_error", repo=slug, path=filepath,
                        error=str(getattr(exc, "reason", exc)))
    except Exception as exc:  # socket timeout, TLS, etc.
        return GhResult(ok=False, status="network_error", repo=slug, path=filepath,
                        error=f"{type(exc).__name__}: {exc}")

    try:
        content = json.loads(base64.b64decode(payload["content"]).decode())
    except Exception as exc:
        # Reached GitHub but the body was not what we expect. Never silently
        # downgrade this to "empty" — a corrupt users.json must not read as
        # "no accounts exist".
        return GhResult(ok=False, status="parse_error", repo=slug, path=filepath,
                        error=f"{type(exc).__name__}: {exc}")

    return GhResult(ok=True, content=content, sha=payload.get("sha"),
                    status="ok", repo=slug, path=filepath)


# ── Write ─────────────────────────────────────────────────────

def gh_write(filepath, content, sha=None, message=None, repo=None, *,
             data=False, timeout=10) -> GhResult:
    """Write a JSON file to a repo. Always returns a GhResult.

    Passing ``sha`` makes GitHub reject a stale write with 409 rather than
    silently clobbering a concurrent update — surfaced here as "conflict".
    """
    import config
    slug = resolve_repo(repo, data=data)
    if not config.GITHUB_TOKEN or not slug:
        return GhResult(ok=False, status="unconfigured", repo=slug, path=filepath,
                        error="GITHUB_TOKEN or repo not configured")

    url = f"https://api.github.com/repos/{slug}/contents/{filepath}"
    payload = {
        "message": message or f"chore: update {filepath}",
        "content": base64.b64encode(
            json.dumps(content, indent=2, default=str).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        new_sha = (body.get("content") or {}).get("sha")
        return GhResult(ok=True, content=content, sha=new_sha, status="ok",
                        repo=slug, path=filepath)
    except urllib.error.HTTPError as exc:
        if exc.code == 409 or exc.code == 422:
            # Stale sha: someone else wrote first. The caller should re-read
            # and retry rather than assume its own copy is authoritative.
            return GhResult(ok=False, status="conflict", repo=slug, path=filepath,
                            error=f"HTTP {exc.code} {exc.reason} — stale sha, re-read and retry")
        return GhResult(ok=False, status=_classify_http_error(exc), repo=slug,
                        path=filepath, error=f"HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        return GhResult(ok=False, status="network_error", repo=slug, path=filepath,
                        error=str(getattr(exc, "reason", exc)))
    except Exception as exc:
        return GhResult(ok=False, status="network_error", repo=slug, path=filepath,
                        error=f"{type(exc).__name__}: {exc}")


# ── Reachability probe (used by preflight.py) ─────────────────

def gh_probe(repo=None, *, data=False, timeout=10) -> GhResult:
    """Check that the token can see the repo at all. No file involved."""
    import config
    slug = resolve_repo(repo, data=data)
    if not config.GITHUB_TOKEN or not slug:
        return GhResult(ok=False, status="unconfigured", repo=slug,
                        error="GITHUB_TOKEN or repo not configured")
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{slug}",
                                     headers=gh_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        return GhResult(ok=True, content={"private": body.get("private"),
                                          "full_name": body.get("full_name")},
                        status="ok", repo=slug)
    except urllib.error.HTTPError as exc:
        return GhResult(ok=False, status=_classify_http_error(exc), repo=slug,
                        error=f"HTTP {exc.code} {exc.reason}")
    except Exception as exc:
        return GhResult(ok=False, status="network_error", repo=slug,
                        error=f"{type(exc).__name__}: {exc}")


# ── Backward-compatible shims ─────────────────────────────────
# Kept so the refactor can land incrementally. These intentionally erase the
# absent/broken distinction, so they are ONLY appropriate where an empty
# result is harmless. Anything touching auth or user data must use gh_read().

def gh_get_json(filepath, repo=None, *, data=False):
    """Legacy shim. Returns (content, sha); (None, None) on any failure."""
    res = gh_read(filepath, repo, data=data)
    return (res.content, res.sha) if res.ok else (None, None)


def gh_put_json(filepath, content, sha=None, message=None, repo=None, *, data=False):
    """Legacy shim. Returns (ok, error_string_or_None)."""
    res = gh_write(filepath, content, sha, message, repo, data=data)
    return res.ok, res.error
