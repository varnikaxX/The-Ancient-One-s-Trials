"""Email over plain HTTPS (urllib only): Resend first, SendGrid as fallback. Optional .ics attachment.

send_email() RAISES on failure so the outbox worker can retry; with no API keys configured and
EMAIL_DRY_RUN=true (default) it only logs, so local demos work offline."""
import base64
import json
import logging
import urllib.error
import urllib.request

from app.config import settings

log = logging.getLogger("trials.email")
TIMEOUT = 10


class EmailError(Exception):
    pass


def _post(url: str, headers: dict, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(headers, **{"Content-Type": "application/json"}), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        raise EmailError(f"HTTP {exc.code}: {exc.read()[:200]!r}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EmailError(f"network error: {exc}")


def _resend(to, subject, text, ics):
    body = {"from": settings.email_from, "to": [to], "subject": subject, "text": text}
    if ics:
        body["attachments"] = [{"filename": "interview.ics", "content": base64.b64encode(ics).decode()}]
    return _post("https://api.resend.com/emails", {"Authorization": f"Bearer {settings.resend_api_key}"}, body)


def _sendgrid(to, subject, text, ics):
    body = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": settings.email_from},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text}],
    }
    if ics:
        body["attachments"] = [{"content": base64.b64encode(ics).decode(), "type": "text/calendar",
                                "filename": "interview.ics", "disposition": "attachment"}]
    return _post("https://api.sendgrid.com/v3/mail/send", {"Authorization": f"Bearer {settings.sendgrid_api_key}"}, body)


def _smtp(to, subject, text, ics):
    import smtplib
    import ssl
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if ics:
        msg.add_attachment(ics, maintype="text", subtype="calendar", filename="interview.ics")
    ctx = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT, context=ctx) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT) as s:
                s.starttls(context=ctx)
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"smtp error: {exc}")
    return 200


def send_email(to: str, subject: str, text: str, ics: bytes = None):
    providers = []
    if settings.resend_api_key:
        providers.append(("resend", _resend))
    if settings.sendgrid_api_key:
        providers.append(("sendgrid", _sendgrid))
    if settings.smtp_host and settings.smtp_user:
        providers.append(("smtp", _smtp))
    if not providers:
        if settings.email_dry_run:
            log.info("[dry-run email] to=%s subject=%s attachment=%s", to, subject, bool(ics))
            return "dry-run"
        raise EmailError("no email provider configured")
    last = None
    for name, fn in providers:
        try:
            fn(to, subject, text, ics)
            return name
        except EmailError as exc:
            log.warning("%s failed: %s", name, exc)
            last = exc
    raise last
