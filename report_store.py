"""Per-user report persistence on GitHub."""
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime


def _gh_headers():
    import config
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _gh_get_json(filepath):
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return None, None
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{filepath}"
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            content = json.loads(base64.b64decode(data["content"]).decode())
            return content, data["sha"]
    except urllib.error.HTTPError:
        return None, None
    except Exception:
        return None, None


def _gh_put_json(filepath, content, sha=None, message=None):
    import config
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        return False
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{filepath}"
    if message is None:
        message = f"report: update {filepath}"
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
        req = urllib.request.Request(url, data=data,
                                     headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception as e:
        print(f"Report save failed: {e}")
        return False


def save_report(username, ticker, metrics, analysis):
    """Save a completed report and update the user's index."""
    date = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    report = {
        "ticker": ticker,
        "date": date,
        "timestamp": timestamp,
        "company_name": metrics.get("company_name", ticker),
        "recommendation": analysis.get("recommendation"),
        "conviction": analysis.get("conviction"),
        "expected_value": analysis.get("scenario_math", {}).get("expected_value"),
        "expected_return": analysis.get("scenario_math", {}).get("expected_return"),
        "risk_adjusted_score": analysis.get("scenario_math", {}).get(
            "risk_adjusted_score"),
        "metrics": {k: v for k, v in metrics.items()
                    if k not in ["description", "news", "revenue_history",
                                 "net_income_history"]},
        "analysis": analysis,
    }

    report_id = f"{ticker}_{date}"
    report_path = f"reports/{username}/{report_id}.json"
    _gh_put_json(report_path, report,
                 message=f"report: {ticker} for {username} on {date}")

    # Update index
    index_path = f"reports/{username}/index.json"
    index, sha = _gh_get_json(index_path)
    if index is None:
        index = []

    # Remove duplicate same ticker + date
    index = [r for r in index
             if not (r["ticker"] == ticker and r["date"] == date)]

    index.append({
        "report_id": report_id,
        "ticker": ticker,
        "company_name": metrics.get("company_name", ticker),
        "date": date,
        "timestamp": timestamp,
        "recommendation": analysis.get("recommendation"),
        "expected_return": analysis.get("scenario_math", {}).get(
            "expected_return"),
    })

    # Keep last 50
    index = index[-50:]
    _gh_put_json(index_path, index, sha,
                 message=f"report index: update for {username}")

    return report_id


def load_user_index(username):
    """Load the user's report index."""
    index_path = f"reports/{username}/index.json"
    index, _ = _gh_get_json(index_path)
    return index or []


def load_report(username, report_id):
    """Load a specific saved report."""
    report_path = f"reports/{username}/{report_id}.json"
    report, _ = _gh_get_json(report_path)
    return report
