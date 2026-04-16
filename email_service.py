"""Email dispatch via Resend (primary) and Gmail (fallback)."""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import GMAIL_SENDER, GMAIL_APP_PASS, RESEND_API_KEY


def send_email(to_email, subject, html_body):
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
            return True, None
        except Exception as e:
            print(f"  Resend failed: {e}, trying Gmail...")
    if not GMAIL_SENDER or not GMAIL_APP_PASS:
        return False, "No email provider configured."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"PickR Alerts <{GMAIL_SENDER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASS.replace(" ", "").strip())
            server.sendmail(GMAIL_SENDER, to_email, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def email_confirmation(to_email, ticker, company_name, recommendation,
                       target_price, entry_price):
    color = "#22c55e" if recommendation == "BUY" else "#f5c542"
    sym   = "^" if recommendation == "BUY" else "o"
    body  = f"""
    <div style="font-family:Inter,sans-serif;background:#0c0c0c;padding:2rem;max-width:600px;margin:0 auto;">
      <div style="border-bottom:2px solid #8b1a1a;padding-bottom:1rem;margin-bottom:1.5rem;">
        <span style="font-size:1.4rem;font-weight:900;color:#fff;">Pick<span style="color:#c03030;">R</span></span>
        <span style="font-size:0.75rem;color:rgba(255,255,255,0.3);margin-left:1rem;">Stock Alert Confirmation</span>
      </div>
      <p style="color:rgba(255,255,255,0.7);font-size:1rem;line-height:1.7;">
        You're now tracking <strong style="color:#fff;">{company_name} ({ticker})</strong>.
      </p>
      <div style="background:#141414;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:1.2rem 1.5rem;margin:1.2rem 0;">
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Recommendation</span>
          <span style="color:{color};font-weight:700;">{sym} {recommendation}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Alert Target Price</span>
          <span style="color:#fff;font-weight:600;">{target_price}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:0.4rem 0;">
          <span style="color:rgba(255,255,255,0.35);font-size:0.9rem;">Entry Price (at report)</span>
          <span style="color:#fff;font-weight:600;">{entry_price}</span>
        </div>
      </div>
      <p style="color:rgba(255,255,255,0.35);font-size:0.8rem;line-height:1.6;margin-top:1.5rem;">
        You'll receive an alert when the price reaches your target, along with a fresh AI thesis evaluation.
        Prices are checked daily.
      </p>
      <p style="color:rgba(255,255,255,0.15);font-size:0.72rem;margin-top:1.5rem;">
        PickR - For informational purposes only. Not financial advice.
      </p>
    </div>"""
    return send_email(to_email, f"PickR: Now tracking {ticker} ({recommendation})", body)


def build_alert_email(ticker, company, recommendation, target_price,
                      current_price, thesis_eval):
    intact      = thesis_eval.get("thesis_intact", True)
    action      = thesis_eval.get("updated_action", recommendation)
    rationale   = thesis_eval.get("rationale", "")
    key_changes = thesis_eval.get("key_changes", [])
    confidence  = thesis_eval.get("confidence", "Medium")
    color        = "#22c55e" if action == "BUY" else ("#f5c542" if action == "WATCH" else "#ff4d4d")
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
      <p style="color:rgba(255,255,255,0.4);font-size:0.85rem;">Target reached - {datetime.now().strftime('%B %d, %Y')}</p>
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
        PickR - For informational purposes only. Not financial advice.
      </p>
    </div>"""
