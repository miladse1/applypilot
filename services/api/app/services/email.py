"""Outgoing email over SMTP.

Credentials come from the environment only. Messages are sent synchronously;
password reset is the only mail ApplyPilot sends.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings, get_settings

log = logging.getLogger("applypilot.email")


class EmailError(Exception):
    pass


def send_email(to: str, subject: str, text: str, html: str | None = None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.email_configured:
        raise EmailError("Email is not configured.")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    security = settings.smtp_security.lower()
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Could not send email ({exc.__class__.__name__}).") from exc


def password_reset_email(name: str, link: str, minutes: int) -> tuple[str, str, str]:
    subject = "Reset your ApplyPilot password"
    text = (
        f"Hi {name},\n\n"
        "Someone asked to reset the password for your ApplyPilot account. If it was you, open this link to choose a new password:\n\n"
        f"{link}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not ask for this, ignore this email; your password stays the same.\n"
    )
    html = f"""<p>Hi {name},</p>
<p>Someone asked to reset the password for your ApplyPilot account. If it was you, choose a new password:</p>
<p><a href="{link}" style="display:inline-block;padding:10px 16px;background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none">Reset password</a></p>
<p style="color:#5b6474">The link works once and expires in {minutes} minutes. If you did not ask for this, ignore this email; your password stays the same.</p>"""
    return subject, text, html
