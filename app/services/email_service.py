"""
Email Service — Gmail SMTP (simplest possible approach).

How to get your App Password (2 minutes, one-time):
  1. Open  https://myaccount.google.com/security
  2. Under "How you sign in to Google" → turn on 2-Step Verification
     (just needs your phone number — takes 1 min)
  3. Back on the same Security page → scroll down →
     "App passwords"  (search for it if you don't see it)
  4. Select app: Mail  /  Select device: Windows Computer  → Generate
  5. Google shows you a 16-character password like:  abcd efgh ijkl mnop
  6. Copy it (without spaces) into .env as GMAIL_APP_PASSWORD

That's it. No new accounts, no Google Cloud, no projects.
Just your existing Gmail + the special password Google gives you.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from loguru import logger


def _cfg():
    from app.core.config import get_settings
    s = get_settings()
    return s.GMAIL_ADDRESS, s.GMAIL_APP_PASSWORD


def _is_ready() -> bool:
    addr, pwd = _cfg()
    return bool(addr and pwd)


def _send(to_email: str, subject: str, html: str, plain: str) -> bool:
    """Send via Gmail SMTP SSL."""
    if not to_email or "@" not in to_email:
        logger.warning("Skipping email — invalid address: %r", to_email)
        return False

    if not _is_ready():
        logger.warning(
            "Email not configured. Add GMAIL_ADDRESS + GMAIL_APP_PASSWORD to .env\n"
            "  How to get App Password → https://myaccount.google.com/apppasswords"
        )
        return False

    gmail_address, app_password = _cfg()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"RecruitAI <{gmail_address}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, to_email, msg.as_string())
        logger.info("✓ Email sent → %s | %s", to_email, subject)
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed.\n"
            "  → Make sure GMAIL_APP_PASSWORD is the 16-char App Password\n"
            "     (not your regular Gmail login password)\n"
            "  → Get it at: https://myaccount.google.com/apppasswords"
        )
        return False

    except Exception as e:
        logger.error("Email failed for %s: %s", to_email, e)
        return False


def send_interview_invite(
    to_email: str,
    candidate_name: str,
    job_title: str,
    interview_url: str,
    company_name: str = "RecruitAI",
) -> bool:
    """Send a branded interview invitation email with the interview link."""

    subject = f"Your Interview Invitation — {job_title}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:40px 20px;">
  <tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

    <!-- Header -->
    <tr><td style="background:#0d0f18;border-radius:12px 12px 0 0;padding:28px 40px;text-align:center;">
      <span style="display:inline-block;width:34px;height:34px;background:#6366f1;border-radius:8px;text-align:center;line-height:34px;font-size:16px;vertical-align:middle;">🎯</span>
      <span style="font-size:20px;font-weight:700;color:#e1e4f0;vertical-align:middle;margin-left:10px;">RecruitAI</span>
    </td></tr>

    <!-- Body -->
    <tr><td style="background:#ffffff;padding:40px;">
      <p style="margin:0 0 6px 0;font-size:24px;font-weight:700;color:#111827;">Hello, {candidate_name}! 👋</p>
      <p style="margin:0 0 28px 0;font-size:15px;color:#4b5563;line-height:1.7;">
        Congratulations — you have been shortlisted for the
        <strong>{job_title}</strong> position at <strong>{company_name}</strong>.
        Please complete a short AI-powered online interview at your earliest convenience.
      </p>

      <!-- Details box -->
      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:#f8f7ff;border:1px solid #e0e0f5;border-radius:10px;margin-bottom:28px;">
        <tr><td style="padding:20px 24px;">
          <p style="margin:0 0 4px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6b7280;">Position</p>
          <p style="margin:0 0 16px;font-size:16px;font-weight:600;color:#111827;">{job_title}</p>
          <p style="margin:0 0 4px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6b7280;">Format</p>
          <p style="margin:0;font-size:15px;color:#111827;">AI Voice Interview &nbsp;·&nbsp; ~15 to 25 minutes</p>
        </td></tr>
      </table>

      <!-- CTA Button -->
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
        <tr><td align="center">
          <a href="{interview_url}"
            style="display:inline-block;padding:14px 48px;background:#6366f1;color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;border-radius:10px;">
            🎙&nbsp; Start Your Interview &rarr;
          </a>
        </td></tr>
      </table>

      <p style="margin:0 0 4px;font-size:12px;color:#9ca3af;text-align:center;">Or paste this link in your browser:</p>
      <p style="margin:0 0 28px;font-size:12px;color:#6366f1;text-align:center;word-break:break-all;">{interview_url}</p>

      <!-- Tips -->
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border-radius:10px;margin-bottom:28px;">
        <tr><td style="padding:20px 24px;">
          <p style="margin:0 0 10px;font-size:14px;font-weight:600;color:#111827;">📋 Before you begin</p>
          <ul style="margin:0;padding-left:18px;font-size:14px;color:#4b5563;line-height:2.2;">
            <li>Use a laptop or desktop with a working microphone</li>
            <li>Find a quiet space with minimal background noise</li>
            <li>Open the link in <strong>Chrome or Edge</strong> for best results</li>
            <li>Allow microphone access when the browser asks</li>
            <li>This link is unique to you — please do not share it</li>
          </ul>
        </td></tr>
      </table>

      <p style="margin:0;font-size:14px;color:#4b5563;line-height:1.6;">
        If you face any technical issues, reply to this email and we'll help you.
        Best of luck! 🙌
      </p>
    </td></tr>

    <!-- Footer -->
    <tr><td style="background:#f3f4f6;border-radius:0 0 12px 12px;padding:20px 40px;text-align:center;">
      <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
        Sent by {company_name} via RecruitAI &nbsp;&middot;&nbsp; This link is unique to you.
      </p>
    </td></tr>

  </table>
  </td></tr>
</table>
</body></html>"""

    plain = (
        f"Hello {candidate_name},\n\n"
        f"Congratulations — you've been shortlisted for {job_title} at {company_name}.\n\n"
        f"Complete your interview here:\n{interview_url}\n\n"
        f"Tips: Use Chrome/Edge, allow microphone, find a quiet place.\n\n"
        f"Best of luck!\n— RecruitAI"
    )

    return _send(to_email, subject, html, plain)


def send_bulk_email(
    to_email: str,
    candidate_name: str,
    subject: str,
    body_text: str,
) -> bool:
    """Send a template email (selection / rejection)."""
    html = (
        "<html><body style='font-family:sans-serif;color:#111827;line-height:1.8;"
        "padding:32px;max-width:600px;margin:auto;'>"
        f"<pre style='white-space:pre-wrap;font-family:inherit;font-size:15px;'>{body_text}</pre>"
        "</body></html>"
    )
    return _send(to_email, subject, html, body_text)
