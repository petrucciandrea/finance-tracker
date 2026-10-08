"""
Outgoing email over plain SMTP, so any provider works (no vendor SDK).

Meant to run as a FastAPI background task: a slow or failing mail server must
never turn a registration into a 500, so errors are logged and swallowed here.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from:
        # Development: the message (links included) goes to the log instead.
        # In production the settings validator refuses to boot without SMTP
        # when approval mode needs it, so this branch is not a silent drop.
        logger.warning("SMTP not configured, email not sent. To: %s | %s\n%s", to, subject, body)
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        logger.info("Email sent to %s (%s)", to, subject)
    except (OSError, smtplib.SMTPException):
        # Not the body: it carries the approval link, which is a credential.
        logger.exception("Failed to send email to %s (%s)", to, subject)
