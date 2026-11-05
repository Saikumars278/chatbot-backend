import os
import re
import requests
from django.conf import settings


def render_otp_email_html(recipient_name, otp_code, purpose="account_verification"):
    clean_name = str(recipient_name or "there").strip()
    if clean_name.lower() not in ["user", "there"]:
        clean_name = clean_name.title()
    otp = str(otp_code).strip()

    if "admin" in purpose.lower() or "reset" in purpose.lower():
        heading = "Reset Your Password"
        friendly_message = f"Hi {clean_name}, use the verification code below to reset your SmartBot administrator password."
    else:
        heading = "Verify Your Email"
        friendly_message = f"Hi {clean_name}, use the verification code below to complete your SmartBot account setup."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{heading}</title>
  <!--[if mso]>
  <style type="text/css">
    table, td, div, p, a, span {{ font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif !important; }}
  </style>
  <![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f8fafc; padding: 48px 16px;">
    <tr>
      <td align="center">
        <!-- Centered Email Card with Clean White Background -->
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 480px; width: 100%; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.05), 0 8px 10px -6px rgba(15, 23, 42, 0.03); overflow: hidden;">
          <tr>
            <td style="padding: 40px 36px 36px; text-align: center;">

              <!-- SmartBot Logo / Name at the Top -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto 28px;">
                <tr>
                  <td style="width: 42px; height: 42px; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); border-radius: 12px; text-align: center; vertical-align: middle; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);">
                    <span style="font-size: 22px; line-height: 42px; display: block;">🤖</span>
                  </td>
                  <td style="padding-left: 12px; vertical-align: middle; text-align: left;">
                    <span style="font-size: 21px; font-weight: 800; color: #0f172a; letter-spacing: -0.4px; display: block;">SmartBot</span>
                  </td>
                </tr>
              </table>

              <!-- Heading: Verify Your Email -->
              <h1 style="margin: 0 0 12px; font-size: 24px; font-weight: 700; color: #0f172a; letter-spacing: -0.4px; line-height: 1.3;">
                {heading}
              </h1>

              <!-- Friendly Message -->
              <p style="margin: 0 0 28px; font-size: 15px; line-height: 1.6; color: #475569;">
                {friendly_message}
              </p>

              <!-- 6-Digit OTP in a Large Bold Box -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto;">
                <tr>
                  <td align="center">
                    <div style="background-color: #f8fafc; border: 1.5px solid #e2e8f0; border-radius: 14px; padding: 18px 28px; text-align: center; display: inline-block;">
                      <span style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Monaco, Courier, monospace; font-size: 38px; font-weight: 800; letter-spacing: 10px; color: #2563eb; display: block; user-select: all; -webkit-user-select: all;">
                        {otp}
                      </span>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Expiry Note -->
              <p style="margin: 14px 0 0; font-size: 13.5px; color: #64748b; font-weight: 500;">
                This code expires in 10 minutes.
              </p>

              <!-- Small Security Note -->
              <p style="margin: 28px 0 0; font-size: 13px; line-height: 1.5; color: #94a3b8;">
                If you didn’t request this code, you can safely ignore this email.
              </p>

              <!-- Clean Footer -->
              <div style="margin-top: 32px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
                <p style="margin: 0; font-size: 12px; color: #94a3b8; font-weight: 400; letter-spacing: 0.2px;">
                  © SmartBot AI • All rights reserved.
                </p>
              </div>

            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_brevo_email(to_email, subject, text_content, html_content=None, recipient_name=None, sender_name="SmartBot Security Team"):
    """
    Sends an email using Brevo's HTTPS REST API (POST https://api.brevo.com/v3/smtp/email).
    Uses BREVO_API_KEY and BREVO_SENDER_EMAIL from Django settings or environment variables.
    """
    api_key = getattr(settings, 'BREVO_API_KEY', None) or os.getenv('BREVO_API_KEY', '') or os.getenv('BREVO_SMTP_PASSWORD', '')
    sender_raw = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or os.getenv('DEFAULT_FROM_EMAIL', '') or getattr(settings, 'BREVO_SENDER_EMAIL', None) or os.getenv('BREVO_SENDER_EMAIL', '') or 'b61a24001@smtp-brevo.com'

    # Parse clean email address out of sender_raw (e.g. "SmartBot Workspace <b61a24001@smtp-brevo.com>")
    match = re.search(r'<([^>]+)>', sender_raw)
    sender_email = match.group(1).strip() if match else sender_raw.strip()

    # Use specified clean sender_name
    final_sender_name = sender_name or "SmartBot Security Team"

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
            "name": final_sender_name,
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
