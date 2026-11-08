import json
import os
import smtplib
import ssl
from email.message import EmailMessage


class DeliveryUnavailable(Exception):
    pass


def send(details: str, diagnostics: dict) -> None:
    host = os.environ.get("STUDIO_SUPPORT_SMTP_HOST", "").strip()
    sender = os.environ.get("STUDIO_SUPPORT_FROM", "").strip()
    recipient = os.environ.get("STUDIO_SUPPORT_EMAIL", "olekskazakov@tvc.verily.health").strip()
    security = os.environ.get("STUDIO_SUPPORT_SMTP_SECURITY", "starttls").strip().lower()
    if not host or not sender or not recipient or security not in {"ssl", "starttls", "plain"}:
        raise DeliveryUnavailable("Issue reporting is not configured.")
    if security == "plain" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise DeliveryUnavailable("Issue reporting is not configured.")
    try:
        port = int(os.environ.get("STUDIO_SUPPORT_SMTP_PORT", "465" if security == "ssl" else "587"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid SMTP port")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = "Cohort Browser issue"
        message.set_content(details)
        message.add_attachment(json.dumps(diagnostics, indent=2).encode(), maintype="application", subtype="json",
                               filename="cohort-browser-diagnostics.json")
        factory = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
        with factory(host, port, timeout=10) as client:
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
            username = os.environ.get("STUDIO_SUPPORT_SMTP_USERNAME", "")
            if username:
                client.login(username, os.environ.get("STUDIO_SUPPORT_SMTP_PASSWORD", ""))
            client.send_message(message)
    except (OSError, ValueError, smtplib.SMTPException) as exc:
        raise DeliveryUnavailable("Could not send the report. Try again or contact an administrator.") from exc
