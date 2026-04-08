"""
check_prices.py — run daily by GitHub Actions.
Uses FMP API (via fmp_api.py) with automatic yfinance fallback.
"""

import base64
import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from openai import OpenAI
from fmp_api import get_current_price, get_current_metrics

TRACKER_FILE    = "tracked_stocks.json"
GMAIL_SENDER    = os.environ.get("GMAIL_SENDER", "")
GMAIL_APP_PASS  = os.environ.get("GMAIL_APP_PASS", "").replace(" ", "").strip()
OPENROUTER_KEY  = os.environ["OPENROUTER_API_KEY"]
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN    = os.environ.get("GH_PAT", os.environ.get("GITHUB_TOKEN", ""))
GITHUB_REPO     = os.environ["GITHUB_REPO"]
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "")

# ── Clients ──
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None

FREE_MODELS = [
    "z-ai/glm-4.5-air:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "arcee-ai/trinity-large-preview:free",
    "qwen/qwen3-coder:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-3-27b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-3-12b-it:free",
]


def run_ai(messages, max_tokens=800):
    """Try Anthropic first, then fall back to OpenRouter free models."""

    # ── Anthropic (primary) ──
    if anthropic_client:
        try:
            system_msg = ""
            user_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)

            r = anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                system=system_msg,
                messages=user_msgs,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            text = r.content[0].text.strip()
            print(f"  AI response via claude-haiku-4.5 ({len(text)} chars)")
            return text, "claude-haiku-4.5"
        except Exception as e:
            print(f"  Claude failed: {str(e)[:120]}, falling back to OpenRouter...")

    # ── OpenRouter free models (fallback) ──
    for model in FREE_MODELS:
        try:
            r = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.3,
                extra_headers={"HTTP-Referer": "https://pickr.streamlit.app", "X-Title": "PickR"},
            )
            text = r.choices[0].message.content.strip()
            print(f"  AI response via {model} ({len(text)} chars)")
            return text, model
        except Exception as e:
            print(f"  Model {model} failed: {str(e)[:80]}")
            time.sleep(3)
    return None, None

def _gh_headers():
    return {
        "Authorization":        f"Bearer {GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":         "application/json",
    }

def gh_load_tracker():
    tracker = []
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                tracker = json.load(f)
        except Exception as e:
            print(f"Local file read error: {e}")

    sha = None
    if GITHUB_TOKEN and GITHUB_REPO:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TRACKER_FILE}"
        try:
            req = urllib.request.Request(url, headers=_gh_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                sha  = data["sha"]
        except Exception as e:
            print(f"GitHub SHA fetch error: {e}")

    return tracker, sha

def gh_save_tracker(content_list, sha):
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{TRACKER_FILE}"
    payload = {
        "message": f"chore: update tracker [{datetime.now().strftime('%Y-%m-%d')}]",
        "content":  base64.b64encode(
            json.dumps(content_list, indent=2, default=str).encode()
        ).decode(),
        "sha": sha,
    }
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, headers=_gh_headers(), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
        print("Tracker saved to GitHub successfully.")
        return True
    except Exception as e:
        print(f"GitHub save error: {e}")
        return False

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
            time.sleep(3)
    return None, None


def parse_json(raw):
    if not raw:
        return None
    raw = raw.strip()
    for prefix in ("```json", "```", "json"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except:
        last = raw.rfind("}")
        if last != -1:
            try: return json.loads(raw[:last+1])
            except: pass
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
    raw, _ = run_ai(messages, max_tokens=800)
    result = parse_json(raw)
    if not result:
        result = {
            "thesis_intact":  True,
            "confidence":     "Low",
            "updated_action": "WATCH",
            "key_changes":    ["AI evaluation unavailable at this time."],
            "rationale":      "Automated thesis check could not be completed. Please review manually.",
        }
    return result


def send_email(to_email, subject, html_body):
    # Try Resend first
    if RESEND_API_KEY:
        try:
            import resend
            resend.api_key = RESEND_API_KEY
            r = resend.Emails.send({
                "from": "PickR <onboarding@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            })
            print(f"  Email sent via Resend: {r.get('id', r)}")
            return
        except Exception as e:
            print(f"  Resend failed: {e}, trying Gmail...")

    # Gmail fallback
    if not GMAIL_SENDER or not GMAIL_APP_PASS:
        print("  No email provider configured.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"PickR Alerts <{GMAIL_SENDER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_SENDER, to_email, msg.as_string())

def build_alert_email(ticker, company, recommendation, target_price, current_price, thesis_eval):
    intact       = thesis_eval.get("thesis_intact", True)
    action       = thesis_eval.get("updated_action", recommendation)
    rationale    = thesis_eval.get("rationale", "")
    key_changes  = thesis_eval.get("key_changes", [])
    confidence   = thesis_eval.get("confidence", "Medium")
    color        = "#22c55e" if action=="BUY" else ("#f5c542" if action=="WATCH" else "#ff4d4d")
    intact_color = "#22c55e" if intact else "#ff4d4d"
    intact_text  = "INTACT" if intact else "CHANGED"
    changes_html = "".join(
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
    print(f"PickR price checker — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Data source: FMP API (with yfinance fallback)")

    tracker, sha = gh_load_tracker()
    if not tracker:
        print("No stocks being tracked.")
        return

    print(f"Loaded {len(tracker)} tracked stock(s).")
    updated = False
    today   = datetime.now().strftime("%Y-%m-%d")

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
            )
            print(f"  Thesis: {'INTACT' if thesis_eval.get('thesis_intact') else 'CHANGED'} | "
                  f"Action: {thesis_eval.get('updated_action')} | "
                  f"Confidence: {thesis_eval.get('confidence')}")

            try:
                send_email(
                    email,
                    f"PickR Alert: {ticker} hit your target (${price:,.2f})",
                    build_alert_email(ticker, company, rec, target, price, thesis_eval),
                )
                print(f"  Email sent to {email}")
                tracker[i]["alert_sent"]   = True
                tracker[i]["alert_date"]   = today
                tracker[i]["final_price"]  = price
                tracker[i]["thesis_check"] = thesis_eval
            except Exception as e:
                print(f"  Email failed: {e}")

        time.sleep(1)

    if updated:
        gh_save_tracker(tracker, sha)

    print(f"\nDone. Checked {len(tracker)} stock(s).")


if __name__ == "__main__":
    main()
