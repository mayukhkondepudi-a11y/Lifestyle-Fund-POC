"""Per-user report persistence on GitHub."""
from datetime import datetime
from gh_api import gh_get_json, gh_put_json


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
    gh_put_json(report_path, report,
                message=f"report: {ticker} for {username} on {date}")

    # Update index
    index_path = f"reports/{username}/index.json"
    index, sha = gh_get_json(index_path)
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
    gh_put_json(index_path, index, sha,
                message=f"report index: update for {username}")

    return report_id


def load_user_index(username):
    """Load the user's report index."""
    index_path = f"reports/{username}/index.json"
    index, _ = gh_get_json(index_path)
    return index or []


def load_report(username, report_id):
    """Load a specific saved report."""
    report_path = f"reports/{username}/{report_id}.json"
    report, _ = gh_get_json(report_path)
    return report
