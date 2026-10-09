"""Email telling an author a SuperAdmin has switched their Studio account
on - after a suspension is lifted, for instance. Sign-ins activate authors
on their own, so this is the only activation nobody sees happen."""
import logging
from html import escape

from pecha_api.config import get
from pecha_api.notification.email_provider import send_email
from pecha_api.plans.groups.group_invite_email import BRAND_PRIMARY, SHELL_LIGHT, TEXT_MUTED


def _studio_url(path: str) -> str:
    return f"{get('WEBUDDHIST_STUDIO_BASE_URL').rstrip('/')}{path}"


def _wrap(*, heading: str, body_html: str, button_label: str, button_url: str) -> str:
    logo_url = get("WEBUDDHIST_EMAIL_LOGO_URL")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{heading}</title>
</head>
<body style="margin:0;padding:0;background-color:{SHELL_LIGHT};font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:{SHELL_LIGHT};padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:#181818;padding:28px 32px;text-align:center;">
              <img src="{logo_url}" alt="WeBuddhist" width="56" height="56" style="display:block;margin:0 auto 12px;border-radius:8px;" />
              <p style="margin:0;font-size:18px;font-weight:600;color:#ffffff;letter-spacing:0.02em;">WeBuddhist Studio</p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h1 style="margin:0 0 16px;font-size:22px;font-weight:700;color:#1a1a1a;">{heading}</h1>
              {body_html}
              <table role="presentation" cellspacing="0" cellpadding="0" align="center" style="margin:24px auto;">
                <tr>
                  <td style="border-radius:8px;background-color:{BRAND_PRIMARY};">
                    <a href="{button_url}" target="_blank" rel="noopener noreferrer"
                       style="display:inline-block;padding:14px 32px;font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;">
                      {button_label}
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0;font-size:14px;word-break:break-all;color:{TEXT_MUTED};">
                <a href="{button_url}" style="color:{BRAND_PRIMARY};">{button_url}</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background-color:#fafafa;border-top:1px solid #eeeeee;">
              <p style="margin:0;font-size:12px;color:{TEXT_MUTED};text-align:center;">&copy; WeBuddhist Studio</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_account_activated_email(*, to_email: str, first_name: str) -> None:
    html = _wrap(
        heading="Your WeBuddhist Studio account is active",
        body_html=(
            f'<p style="margin:0;font-size:16px;line-height:1.6;color:#333333;">'
            f"Hi {escape(first_name or '')}, a Studio admin has activated your WeBuddhist Studio account. "
            f"Sign in the same way as before to carry on creating.</p>"
        ),
        button_label="Open WeBuddhist Studio",
        button_url=_studio_url("/login"),
    )
    try:
        send_email(to_email=to_email, subject="Your WeBuddhist Studio account is active", message=html)
    except Exception:
        logging.exception("Failed to send Studio activation email to %s", to_email)
