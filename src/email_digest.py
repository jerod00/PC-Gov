"""Renders and sends the ranked HTML digest via SMTP (Gmail/Google
Workspace). Each opportunity gets two mailto: feedback links whose subject
line encodes the dedup_key + verdict — feedback.py's IMAP scanner picks
these up on the next run.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from urllib.parse import quote

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _feedback_link(recipient: str, dedup_key: str, verdict: str) -> str:
    subject = quote(f"FEEDBACK {verdict.upper()} {dedup_key}")
    return f"mailto:{recipient}?subject={subject}"


def _format_value(value):
    if not value:
        return "Not listed"
    return f"${value:,.0f}"


def _format_deadline(deadline_str):
    return deadline_str or "Not listed"


def _row_html(row: dict, recipient: str) -> str:
    good_link = _feedback_link(recipient, row["dedup_key"], "good")
    bad_link = _feedback_link(recipient, row["dedup_key"], "bad")
    return f"""
    <tr style="border-bottom:1px solid #ddd;">
      <td style="padding:12px;">
        <div style="font-size:15px;font-weight:600;">
          <a href="{escape(row['url'])}" style="color:#1a4d8f;text-decoration:none;">{escape(row['title'])}</a>
        </div>
        <div style="font-size:13px;color:#555;margin-top:4px;">{escape(row.get('agency') or '')}</div>
        <div style="font-size:12px;color:#777;margin-top:6px;">
          NAICS: {escape(row.get('naics_code') or '—')} &nbsp;|&nbsp;
          PSC: {escape(row.get('psc_code') or '—')} &nbsp;|&nbsp;
          Value: {_format_value(row.get('value'))} &nbsp;|&nbsp;
          Deadline: {_format_deadline(row.get('response_deadline'))}
        </div>
        <div style="font-size:13px;color:#2a6b2a;margin-top:6px;">{escape(row.get('reason') or '')}</div>
        <div style="font-size:12px;margin-top:8px;">
          <a href="{good_link}" style="color:#1a7a1a;margin-right:14px;">&#128077; Good match</a>
          <a href="{bad_link}" style="color:#a02020;">&#128078; Not relevant</a>
        </div>
      </td>
      <td style="padding:12px;text-align:right;vertical-align:top;font-size:18px;font-weight:700;color:#1a4d8f;">
        {row['score']:.0f}
      </td>
    </tr>
    """


def build_html(rows: list, recipient: str) -> str:
    if not rows:
        return """
        <html><body style="font-family:Arial,sans-serif;">
          <h2>PC-Gov Opportunity Digest</h2>
          <p>No new relevant opportunities today. The system ran fine — nothing new matched your criteria.</p>
        </body></html>
        """
    items = "\n".join(_row_html(r, recipient) for r in rows)
    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;">
      <h2 style="color:#1a4d8f;">PC-Gov Opportunity Digest — {len(rows)} new opportunit{'y' if len(rows) == 1 else 'ies'}</h2>
      <table style="width:100%;border-collapse:collapse;">
        {items}
      </table>
      <p style="font-size:12px;color:#999;margin-top:20px;">
        Click a thumbs-up/down link to send feedback — it's read on the next run and
        nudges keyword weights over time.
      </p>
    </body></html>
    """


def send_digest(html: str, subject: str, gmail_address: str, gmail_app_password: str, recipient: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [recipient], msg.as_string())
