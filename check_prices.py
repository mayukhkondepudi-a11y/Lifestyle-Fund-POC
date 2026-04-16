"""
check_prices.py — run daily by GitHub Actions.
Uses FMP API (via fmp_api.py) with automatic yfinance fallback.
"""
import time
from datetime import datetime

from config import FREE_MODELS_EXTENDED
from github_store import load_tracker, save_tracker
from email_service import send_email, build_alert_email
from ai import thesis_check
from fmp_api import get_current_price, get_current_metrics


def main():
    print(f"PickR price checker — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Data source: FMP API (with yfinance fallback)")

    tracker, sha = load_tracker()
    if not tracker:
        print("No stocks being tracked.")
        return

    print(f"Loaded {len(tracker)} tracked stock(s).")
    updated = False
    today = datetime.now().strftime("%Y-%m-%d")

    for i, stock in enumerate(tracker):
        ticker  = stock["ticker"]
        email   = stock["user_email"]
        target  = stock["target_price"]
        rec     = stock["recommendation"]
        company = stock.get("company_name", ticker)
        sent    = stock.get("alert_sent", False)

        print(f"\n[{i+1}/{len(tracker)}] {ticker} for {email} (target: ${target})")

        if sent:
            print("  Alert already sent — skipping.")
            continue

        price = get_current_price(ticker)
        if price is None:
            print(f"  Could not fetch price — skipping.")
            continue

        print(f"  Current: ${price:.2f} | Target: ${target:.2f}")
        tracker[i]["last_checked"] = today
        tracker[i]["last_price"]   = price
        updated = True

        if price >= target:
            print("  Target reached! Running thesis check...")
            current_metrics = get_current_metrics(ticker)
            thesis_eval = thesis_check(
                ticker, company,
                stock.get("original_metrics", {}),
                stock.get("thesis_summary", ""),
                current_metrics,
                model="claude-haiku-4-5-20251001",
                free_models=FREE_MODELS_EXTENDED,
            )
            print(f"  Thesis: {'INTACT' if thesis_eval.get('thesis_intact') else 'CHANGED'} | "
                  f"Action: {thesis_eval.get('updated_action')} | "
                  f"Confidence: {thesis_eval.get('confidence')}")

            try:
                html = build_alert_email(ticker, company, rec, target, price,
                                         thesis_eval)
                send_email(email,
                           f"PickR Alert: {ticker} hit your target (${price:,.2f})",
                           html)
                print(f"  Email sent to {email}")
                tracker[i]["alert_sent"]   = True
                tracker[i]["alert_date"]   = today
                tracker[i]["final_price"]  = price
                tracker[i]["thesis_check"] = thesis_eval
            except Exception as e:
                print(f"  Email failed: {e}")

        time.sleep(1)

    if updated and sha:
        save_tracker(tracker, sha)

    print(f"\nDone. Checked {len(tracker)} stock(s).")


if __name__ == "__main__":
    main()
