"""
check_prices.py — run daily by GitHub Actions.
Checks every tracked stock, fires thesis re-eval + email when target is hit.
"""

import json
import os
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf
from openai import OpenAI

TRACKER_FILE   = "tracked_stocks.json"
GMAIL_SENDER   = os.environ["GMAIL_SENDER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-coder:free",
    "deepseek/deepseek-chat-v3-5:free",
    "microsoft/phi-4-reasoning-plus:free",
    "google/gemma-3-12b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
]


def load_tracker():
    if not os.path.exists(TRACKER_FILE):
        return []
    with open(TRACKER_FILE) as f:
        return json.load(f)


def save_tracker(data):
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_current_price(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except:
        return None


def get_current_metrics(ticker):
    try:
        info = yf.Ticker(ticker).info
        return {
            "trailing_pe":      info.get("trailingPE"),
            "forward_pe":       info.get("forwardPE"),
            "peg_ratio":        info.get("pegRatio"),
            "operating_margin": info.get("operatingMargins"),
            "roe":              info.get("returnOnEquity"),
            "revenue_growth":   info.get("revenueGrowth"),
            "fcf_yield":        (info.get("freeCashflow") / info.get("marketCap")
                                 if info.get("freeCashflow") and info.get("marketCap") else None),
            "debt_to_equity":   info.get("debtToEquity"),
            "ev_to_ebitda":     info.get("enterpriseToEbitda"),
        }
    except:
        return {}


def run_ai(messages, max_tokens=800):
    for model in FREE_MODELS:
        try:
            r = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.3,
                extra_headers={"HTTP-Referer": "https://pickr.streamlit.app", "X-Title": "PickR"},
            )
            return r.choices[0].message.content.strip(), model
        except Exception as e:
            print(f"  Model {model} failed: {str(e)[:80]}")
            time.sleep(2)
    return None, None


def parse_json(raw):
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    if raw.startswith("json"):
        raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except:
        # Best-effort bracket repair
        last = raw.rfind("}")
        if last != -1:
            raw = raw[:last+1]
        try:
            return json.loads(raw)
        except:
            return None


def thesis_check(ticker, company, original_metrics, original_thesis, current_metrics):
    messages = [
        {"role": "system", "content": (
            "You are a senior equity research analyst performing a thesis integrity check. "
            "Respond ONLY with valid JSON, no fences."
        )},
        {"role": "user", "content": f"""THESIS CHECK: {ticker} ({company})

ORIGINAL THESIS:
{original_thesis}

ORIGINAL METRICS:
{json.dumps(original_metrics, default=str)}

CURRENT METRICS:
{json.dumps(current_metrics, default=str)}

Respond with exactly this JSON:
{{
  "thesis_intact": true,
  "confidence": "High",
  "updated_action": "BUY",
  "key_changes": ["Change 1", "Change 2"],
  "rationale": "2-3 sentence summary of whether the thesis holds."
}}

thesis_intact: true if the core investment case is still valid.
updated_action: exactly BUY, WATCH, or PASS.
confidence: High, Medium, or Low."""}
    ]
    raw, model = run_ai(messages, max_tokens=800)
    result = parse_json(raw)
    if not result:
        result = {
            "thesis_intact": True,
            "confidence": "Low",
            "updated_action": "WATCH",
            "key_changes": ["AI evaluation unavailable at this time."],
            "rationale": "Automated thesis check could not be completed. Please review manually.",
        }
    return result


def send_email(to_email, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"PickR Alerts <{GMAIL_SENDER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_SENDER, to_email, msg.as_string())


def build_alert_email(ticker, company, recommendation, target_price, current_price, thesis_eval):
    intact      = thesis_eval.get("thesis_intact", True)
    action      = thesis_eval.get("updated_action", recommendation)
    rationale   = thesis_eval.get("rationale", "")
    key_changes = thesis_eval.get("key_changes", [])
    confidence  = thesis_eval.get("confidence", "Medium")
    color       = "#22c55e" if action == "BUY" else ("#f5c542" if action == "WATCH" else "#ff4d4d")
    intact_color= "#22c55e" if intact else "#ff4d4d"
    intact_text = "INTACT" if intact else "CHANGED"
    changes_html= "".join(
        f"<li style='color:rgba(255,255,255,0.5);font-size:0.88rem;margin:0.3rem 0;'>{c}</li>"
        for c in key_changes
    )
    return f"""
    <div style="font-family:Inter,sans-serif;background:#0c0c0c;padding:2rem;max-width:600px;margin:0 auto;">
      <div style="border-bottom:2px solid #8b1a1a;padding-bottom:1rem;margin-bottom:1.5rem;">
        <span style="font-size:1.4rem;font-weight:900;color:#fff;">Pick<span style="color:#c03030;">R</span></span>
        <span style="font-size:0.75rem;color:rgba(255,255,255,0.3);margin-left:1rem;">Price Alert</span>
      </div>
      <h2 style="color:#fff;font-size:1.5rem;margin:0 0 0.3rem;">{company} ({ticker})</h2>
      <p style="color:rgba(255,255,255,0.4);font-size:0.85rem;">Target reached — {datetime.now().strftime('%B %d, %Y')}</p>
      <div style="background:#141414;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:1.2rem 1.5rem;margin:1.2rem 0;">
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Current Price</span>
          <span style="color:#fff;font-weight:700;">${current_price:,.2f}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Your Target</span>
          <span style="color:#fff;font-weight:600;">${target_price:,.2f}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Thesis Status</span>
          <span style="color:{intact_color};font-weight:700;">{intact_text}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Updated Action</span>
          <span style="color:{color};font-weight:700;">{action}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Confidence</span>
          <span style="color:#fff;font-weight:600;">{confidence}</span>
        </div>
      </div>
      <div style="background:#1a1a1a;border-left:3px solid #8b1a1a;padding:1rem 1.2rem;border-radius:0 6px 6px 0;margin:1rem 0;">
        <p style="color:rgba(255,255,255,0.6);font-size:0.92rem;line-height:1.7;margin:0;font-style:italic;">{rationale}</p>
      </div>
      {"<p style='color:rgba(255,255,255,0.4);font-size:0.82rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;margin:1rem 0 0.4rem;'>Key changes since original thesis:</p><ul style='margin:0;padding-left:1.2rem;'>" + changes_html + "</ul>" if key_changes else ""}
      <p style="color:rgba(255,255,255,0.15);font-size:0.72rem;margin-top:1.5rem;">
        PickR — For informational purposes only. Not financial advice.
      </p>
    </div>
    """


def main():
    tracker = load_tracker()
    if not tracker:
        print("No stocks being tracked.")
        return

    updated = False
    today   = datetime.now().strftime("%Y-%m-%d")

    for i, stock in enumerate(tracker):
        ticker   = stock["ticker"]
        email    = stock["user_email"]
        target   = stock["target_price"]
        rec      = stock["recommendation"]
        company  = stock.get("company_name", ticker)
        sent     = stock.get("alert_sent", False)

        print(f"\n[{i+1}/{len(tracker)}] Checking {ticker} for {email} (target: ${target})")

        if sent:
            print(f"  Alert already sent, skipping.")
            continue

        price = get_current_price(ticker)
        if price is None:
            print(f"  Could not fetch price for {ticker}, skipping.")
            continue

        print(f"  Current: ${price:.2f} | Target: ${target:.2f}")
        tracker[i]["last_checked"] = today
        tracker[i]["last_price"]   = price
        updated = True

        # Check if target reached (handles both BUY targets above and WATCH targets)
        target_reached = price >= target

        if target_reached:
            print(f"  Target reached! Running thesis check...")
            current_metrics  = get_current_metrics(ticker)
            original_metrics = stock.get("original_metrics", {})
            original_thesis  = stock.get("thesis_summary", "")

            thesis_eval = thesis_check(
                ticker, company, original_metrics, original_thesis, current_metrics
            )
            print(f"  Thesis: {'INTACT' if thesis_eval.get('thesis_intact') else 'CHANGED'} | "
                  f"Action: {thesis_eval.get('updated_action')} | "
                  f"Confidence: {thesis_eval.get('confidence')}")

            html_body = build_alert_email(ticker, company, rec, target, price, thesis_eval)
            subject   = f"PickR Alert: {ticker} hit your target (${price:,.2f})"

            try:
                send_email(email, subject, html_body)
                print(f"  Email sent to {email}")
                tracker[i]["alert_sent"]   = True
                tracker[i]["alert_date"]   = today
                tracker[i]["final_price"]  = price
                tracker[i]["thesis_check"] = thesis_eval
                updated = True
            except Exception as e:
                print(f"  Email failed: {e}")

        # Pace requests to avoid hammering yfinance
        time.sleep(1)

    if updated:
        save_tracker(tracker)
        print(f"\nTracker updated.")

    print(f"\nDone. Checked {len(tracker)} stock(s).")


if __name__ == "__main__":
    main()