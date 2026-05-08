"""Canonical GitHub Contents API helpers.

Single source of truth for reading/writing JSON files in the project's
GitHub repo. Replaces the duplicated `_gh_*` helpers previously in
report_store.py, github_store.py, and auth.py.
"""
import json
import base64
import urllib.request
import urllib.error


def gh_headers():
    """Standard GitHub API request headers."""
    import config
    return {
        "Authorization":        f"Bearer {config.GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":         "application/json",
    }


def gh_get_json(filepath):
    """Fetch a JSON file from the repo. Returns (content, sha).

    On any error (404, network, parse), returns (None, None).
    Callers should default to {}, [] etc as appropriate.
    """
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return None, None
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{filepath}"
    try:
        req = urllib.request.Request(url, headers=gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            content = json.loads(base64.b64decode(data["content"]).decode())
            return content, data["sha"]
    except urllib.error.HTTPError:
        return None, None
    except Exception:
        return None, None


def gh_put_json(filepath, content, sha=None, message=None):
    """Write a JSON file to the repo. Returns (ok: bool, error: str | None)."""
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return False, "GitHub not configured"
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{filepath}"
    if message is None:
        message = f"chore: update {filepath}"
    payload = {
        "message": message,
        "content": base64.b64encode(
            json.dumps(content, indent=2, default=str).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True, None
    except Exception as e:
        return False, str(e)
