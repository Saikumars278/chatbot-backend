import os
import re
import requests
from django.conf import settings

def send_brevo_email(to_email, subject, text_content, html_content=None, recipient_name=None):
    """
    Sends an email using Brevo's HTTPS REST API (POST https://api.brevo.com/v3/smtp/email).
    Uses BREVO_API_KEY and BREVO_SENDER_EMAIL from Django settings or environment variables.
    """
    api_key = getattr(settings, 'BREVO_API_KEY', None) or os.getenv('BREVO_API_KEY', '') or os.getenv('BREVO_SMTP_PASSWORD', '')
    sender_raw = getattr(settings, 'BREVO_SENDER_EMAIL', None) or os.getenv('BREVO_SENDER_EMAIL', '') or getattr(settings, 'DEFAULT_FROM_EMAIL', 'b61a24001@smtp-brevo.com')

    # Parse clean email address out of sender_raw (e.g. "SmartBot Workspace <b61a24001@smtp-brevo.com>")
    match = re.search(r'<([^>]+)>', sender_raw)
    sender_email = match.group(1).strip() if match else sender_raw.strip()

    sender_name = "SmartBot Security Team"
    if '<' in sender_raw:
        possible_name = sender_raw.split('<')[0].strip()
        if possible_name:
            sender_name = possible_name

    to_email = str(to_email).strip()
    if not to_email:
        return False, "Recipient email address is required."

    if not api_key:
        print(f"[LOCAL DEV EMAIL LOG] BREVO_API_KEY not configured. Simulated send to {to_email}: {subject}")
        print(f"[LOCAL DEV EMAIL CONTENT]:\n{text_content}")
        return True, "Simulated email send (Local dev mode)"

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key.strip(),
        "content-type": "application/json"
    }

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email
        },
        "to": [
            {
                "email": to_email,
                "name": recipient_name or to_email
            }
        ],
        "subject": subject,
        "textContent": text_content,
        "htmlContent": html_content or f"<div style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>{text_content.replace(chr(10), '<br>')}</div>"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201, 202]:
            return True, "Email sent successfully via Brevo API"
        else:
            error_msg = f"Brevo API error ({response.status_code}): {response.text}"
            print("Brevo API error:", error_msg)
            return False, error_msg
    except Exception as exc:
        error_msg = f"Failed to send email via Brevo API: {str(exc)}"
        print("Brevo API exception:", error_msg)
        return False, error_msg
