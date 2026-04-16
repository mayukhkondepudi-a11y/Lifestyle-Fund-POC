"""GitHub API persistence for tracker and screener results."""
import json
import base64
import os
import urllib.request
import urllib.error
from datetime import datetime
import config

def _gh_headers():
    return {
        "Authorization":        f"Bearer {GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":         "application/json",
    }


def _gh_get_json(filepath):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None, None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            content = json.loads(base64.b64decode(data["content"]).decode())
            return content, data["sha"]
    except urllib.error.HTTPError:
        return [], None
    except Exception:
        return None, None


def _gh_put_json(filepath, content, sha=None, message=None):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False, "GitHub not configured"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    if message is None:
        message = f"chore: update {filepath} [{datetime.now().strftime('%Y-%m-%d %H:%M')}]"
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
        req = urllib.request.Request(url, data=data, headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True, None
    except Exception as e:
        return False, str(e)


# ── Tracker ──────────────────────────────────────────────────

def load_tracker():
    if GITHUB_TOKEN and GITHUB_REPO:
        content, sha = _gh_get_json(TRACKER_FILE)
        if content is not None:
            return content, sha
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                return json.load(f), None
        except Exception:
            pass
    return [], None


def save_tracker(content_list, sha):
    ok, err = _gh_put_json(TRACKER_FILE, content_list, sha,
                           f"chore: update tracker [{datetime.now().strftime('%Y-%m-%d')}]")
    if not ok:
        print(f"GitHub save error: {err}")
    return ok


def add_tracked_stock(ticker, company_name, recommendation, target_price,
                      entry_price, metrics_snapshot, thesis_summary, user_email):
    tracker, sha = load_tracker()
    tracker = [t for t in tracker
               if not (t["ticker"] == ticker and t["user_email"] == user_email)]
    tracker.append({
        "ticker":           ticker,
        "company_name":     company_name,
        "user_email":       user_email,
        "recommendation":   recommendation,
        "target_price":     float(target_price),
        "entry_price":      float(entry_price) if entry_price else None,
        "added_date":       datetime.now().strftime("%Y-%m-%d"),
        "original_metrics": metrics_snapshot,
        "thesis_summary":   thesis_summary,
        "alert_sent":       False,
        "last_checked":     None,
        "last_price":       float(entry_price) if entry_price else None,
    })
    if GITHUB_TOKEN and GITHUB_REPO:
        ok, err = _gh_put_json(TRACKER_FILE, tracker, sha)
        if not ok:
            with open(TRACKER_FILE, "w") as f:
                json.dump(tracker, f, indent=2, default=str)
        return ok, err
    else:
        with open(TRACKER_FILE, "w") as f:
            json.dump(tracker, f, indent=2, default=str)
        return False, "GitHub not configured - saved locally only"


# ── Screener Results ─────────────────────────────────────────

def load_screener_results_raw():
    if GITHUB_TOKEN and GITHUB_REPO:
        content, _ = _gh_get_json(SCREENER_FILE)
        if content:
            return content
    try:
        with open(SCREENER_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def push_screener_results(results):
    _, sha = _gh_get_json(SCREENER_FILE)
    return _gh_put_json(SCREENER_FILE, results, sha,
                        f"screener: update {datetime.now().strftime('%Y-%m-%d')}")
