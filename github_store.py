"""GitHub API persistence for tracker and screener results."""
import json
import os
from datetime import datetime
import config
from gh_api import gh_get_json, gh_put_json


# ── Tracker ──────────────────────────────────────────────────

def load_tracker():
    if config.GITHUB_TOKEN and config.GITHUB_REPO:
        content, sha = gh_get_json(config.TRACKER_FILE)
        if content is not None:
            return content, sha
    if os.path.exists(config.TRACKER_FILE):
        try:
            with open(config.TRACKER_FILE) as f:
                return json.load(f), None
        except Exception:
            pass
    return [], None


def save_tracker(content_list, sha):
    ok, err = gh_put_json(config.TRACKER_FILE, content_list, sha,
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
    if config.GITHUB_TOKEN and config.GITHUB_REPO:
        ok, err = gh_put_json(config.TRACKER_FILE, tracker, sha)
        if not ok:
            with open(config.TRACKER_FILE, "w") as f:
                json.dump(tracker, f, indent=2, default=str)
        return ok, err
    else:
        with open(config.TRACKER_FILE, "w") as f:
            json.dump(tracker, f, indent=2, default=str)
        return False, "GitHub not configured - saved locally only"


# ── Screener Results ─────────────────────────────────────────

def load_screener_results_raw():
    if config.GITHUB_TOKEN and config.GITHUB_REPO:
        content, _ = gh_get_json(config.SCREENER_FILE)
        if content:
            return content
    try:
        with open(config.SCREENER_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def push_screener_results(results):
    _, sha = gh_get_json(config.SCREENER_FILE)
    return gh_put_json(config.SCREENER_FILE, results, sha,
                       f"screener: update {datetime.now().strftime('%Y-%m-%d')}")
