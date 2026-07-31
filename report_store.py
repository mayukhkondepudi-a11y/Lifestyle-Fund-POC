"""Per-user report persistence in the PRIVATE data repo.

Reports contain the user's research history and are stored alongside
users.json in ``config.GITHUB_DATA_REPO`` — never in the public code repo.

Every function here returns enough information for the caller to tell a
genuinely-empty history from an unreachable store, because rendering
"no reports yet" to someone with 40 saved reports is a trust-destroying lie.
"""
from datetime import datetime

from gh_api import gh_read, gh_write


def _report_payload(ticker, metrics, analysis, date, timestamp):
    return {
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


def save_report(username, ticker, metrics, analysis):
    """Save a completed report and update the user's index.

    Returns (report_id, error_or_None). A non-None error means the report was
    NOT persisted — the caller should tell the user rather than implying it
    was saved.
    """
    date = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    report = _report_payload(ticker, metrics, analysis, date, timestamp)
    report_id = f"{ticker}_{date}"
    report_path = f"reports/{username}/{report_id}.json"

    # The report body may already exist (same ticker, same day) — read for its
    # sha so the overwrite is accepted rather than 409-ing.
    existing = gh_read(report_path, data=True)
    if existing.broken:
        return report_id, f"could not reach report store ({existing.status})"

    wrote = gh_write(report_path, report, existing.sha,
                     message=f"report: {ticker} for {username} on {date}",
                     data=True)
    if not wrote.ok:
        return report_id, f"report not saved ({wrote.status})"

    # ── Update the index ──
    idx_path = f"reports/{username}/index.json"
    idx_res = gh_read(idx_path, data=True)
    if idx_res.broken:
        # Body is saved but the index is not — report it rather than pretending.
        return report_id, f"report saved but index not updated ({idx_res.status})"

    index = idx_res.content if idx_res.ok else []
    if not isinstance(index, list):
        index = []

    # Replace any same ticker + date entry
    index = [r for r in index
             if not (r.get("ticker") == ticker and r.get("date") == date)]

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

    index = index[-50:]  # keep last 50
    idx_wrote = gh_write(idx_path, index, idx_res.sha,
                         message=f"report index: update for {username}",
                         data=True)
    if not idx_wrote.ok:
        return report_id, f"report saved but index not updated ({idx_wrote.status})"

    return report_id, None


def load_user_index_result(username):
    """Return the raw GhResult for a user's report index.

    Use this when the UI needs to distinguish "no reports yet" (``absent``)
    from "history is temporarily unavailable" (``broken``).
    """
    return gh_read(f"reports/{username}/index.json", data=True)


def load_user_index(username):
    """Load the user's report index. Empty list when absent OR unreachable —
    prefer load_user_index_result() where that difference is visible to a user."""
    res = load_user_index_result(username)
    content = res.content if res.ok else []
    return content if isinstance(content, list) else []


def load_report(username, report_id):
    """Load a specific saved report. None when absent or unreachable."""
    res = gh_read(f"reports/{username}/{report_id}.json", data=True)
    return res.content if res.ok else None


# ── Guest reports ─────────────────────────────────────────────
# Guests previously had NO persistence at all: cached_report lived only in
# session_state, and the ?_qt= ticker chips trigger a full page reload that
# wipes it. A guest could pay (in tokens) for a report and lose it to a single
# click. Guest reports are keyed by device fingerprint under reports/_guest/.

def save_guest_report(fingerprint, ticker, metrics, analysis):
    """Persist a guest's single report so a page reload cannot destroy it."""
    if not fingerprint:
        return None, "no guest fingerprint"
    date = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = _report_payload(ticker, metrics, analysis, date, timestamp)
    path = f"reports/_guest/{fingerprint}.json"

    existing = gh_read(path, data=True)
    if existing.broken:
        return None, f"could not reach report store ({existing.status})"
    wrote = gh_write(path, report, existing.sha,
                     message=f"guest report: {ticker}", data=True)
    return (path, None) if wrote.ok else (None, f"not saved ({wrote.status})")


def load_guest_report(fingerprint):
    """Restore a guest's report after a page reload. None when absent."""
    if not fingerprint:
        return None
    res = gh_read(f"reports/_guest/{fingerprint}.json", data=True)
    return res.content if res.ok else None
