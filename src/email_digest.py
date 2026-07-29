"""Renders and sends the ranked HTML digest via SMTP (Gmail/Google
Workspace). Each opportunity gets two mailto: feedback links whose subject
line encodes the dedup_key + verdict — feedback.py's IMAP scanner picks
these up on the next run — plus a blank-recipient "Share" mailto: link
prefilled with the job's details, for forwarding to a subcontractor,
estimator, or anyone else outside this project's own recipient list.
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


def _format_contact(row: dict) -> str:
    """Plain-text 'Name (email, phone)' from whatever poc_* fields are
    present, or '' if the source has none (currently only SAM.gov)."""
    bits = [row[k] for k in ("poc_name", "poc_email", "poc_phone") if row.get(k)]
    return " / ".join(bits)


def _share_link(row: dict) -> str:
    """Blank-recipient mailto: so whoever's forwarding it just types in who
    it's going to -- prefilled with everything about the job so nobody has
    to hand-copy details out of the digest."""
    subject = quote(f"Opportunity: {row['title']}")
    location = ", ".join(part for part in (row.get("city"), row.get("state")) if part)
    contact = _format_contact(row)
    body_lines = [
        row["title"],
        f"Agency: {row.get('agency') or 'Not listed'}",
        f"Location: {location or 'Not listed'}",
        f"NAICS: {row.get('naics_code') or '—'}    PSC: {row.get('psc_code') or '—'}",
        f"Estimated value: {_format_value(row.get('value'))}",
        f"Response deadline: {_format_deadline(row.get('response_deadline'))}",
        f"Point of contact: {contact}" if contact else None,
        "",
        f"Details / submit: {row['url']}",
        "",
        (row.get("reason") or "").strip(),
    ]
    body = quote("\n".join(line for line in body_lines if line is not None))
    return f"mailto:?subject={subject}&body={body}"


def _contact_html(row: dict) -> str:
    """'' when the source has no point-of-contact data (most sources) --
    currently only SAM.gov populates poc_*."""
    if not row.get("poc_name") and not row.get("poc_email") and not row.get("poc_phone"):
        return ""
    bits = [escape(row["poc_name"])] if row.get("poc_name") else []
    if row.get("poc_email"):
        bits.append(f'<a href="mailto:{escape(row["poc_email"])}" style="color:#1a4d8f;">{escape(row["poc_email"])}</a>')
    if row.get("poc_phone"):
        bits.append(escape(row["poc_phone"]))
    return f'<div style="font-size:12px;color:#777;margin-top:4px;">Contact: {" &nbsp;/&nbsp; ".join(bits)}</div>'


def _row_html(row: dict, feedback_address: str) -> str:
    good_link = _feedback_link(feedback_address, row["dedup_key"], "good")
    bad_link = _feedback_link(feedback_address, row["dedup_key"], "bad")
    share_link = _share_link(row)
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
        {_contact_html(row)}
        <div style="font-size:13px;color:#2a6b2a;margin-top:6px;">{escape(row.get('reason') or '')}</div>
        <div style="font-size:12px;margin-top:8px;">
          <a href="{good_link}" style="color:#1a7a1a;margin-right:14px;">&#128077; Good match</a>
          <a href="{bad_link}" style="color:#a02020;margin-right:14px;">&#128078; Not relevant</a>
          <a href="{share_link}" style="color:#1a4d8f;">&#128228; Share</a>
        </div>
      </td>
      <td style="padding:12px;text-align:right;vertical-align:top;font-size:18px;font-weight:700;color:#1a4d8f;">
        {row['score']:.0f}
      </td>
    </tr>
    """


def build_html(rows: list, feedback_address: str) -> str:
    """feedback_address is always the IMAP-monitored Gmail account (GMAIL_ADDRESS),
    never the digest's (possibly multi-address) recipient list — feedback.py only
    scans that one mailbox, so every feedback link must resolve back to it
    regardless of how many people the digest itself goes out to."""
    if not rows:
        return """
        <html><body style="font-family:Arial,sans-serif;">
          <h2>PC-Gov Opportunity Digest</h2>
          <p>No new relevant opportunities today. The system ran fine — nothing new matched your criteria.</p>
        </body></html>
        """
    items = "\n".join(_row_html(r, feedback_address) for r in rows)
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


def send_digest(html: str, subject: str, gmail_address: str, gmail_app_password: str, recipients: list):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, recipients, msg.as_string())
