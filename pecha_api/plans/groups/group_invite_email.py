import logging
from typing import Optional
from urllib.parse import quote

from pecha_api.config import get, get_bool
from pecha_api.notification.email_provider import send_email
from pecha_api.plans.groups.group_invite_token import invite_expiry_label

BRAND_PRIMARY = "#A51C21"
BRAND_PRIMARY_HOVER = "#8a171c"
SHELL_LIGHT = "#F5F5F5"
TEXT_MUTED = "#666666"


def _invite_expiry_label() -> str:
    return invite_expiry_label()


def _build_invitation_html(
    *,
    inviter_name: str,
    inviter_email: str,
    group_title: str,
    invite_role: str,
    invitations_url: str,
    login_url: str,
    logo_url: str,
    one_step_join: bool = False,
) -> str:
    expiry_label = _invite_expiry_label()
    if one_step_join:
        button_label = "Accept invitation"
        account_help = (
            "New to WeBuddhist? The button lets you create your account and join in one step &mdash; "
            "no separate email confirmation needed. Already have an account? "
            f'<a href="{login_url}" style="color:{BRAND_PRIMARY};font-weight:600;text-decoration:none;">Log in to WeBuddhist Studio</a> '
            "with this email address to accept."
        )
    else:
        button_label = "View invitation"
        account_help = (
            "Already have a WeBuddhist account? "
            f'<a href="{login_url}" style="color:{BRAND_PRIMARY};font-weight:600;text-decoration:none;">Log in to WeBuddhist Studio</a> '
            "to view and respond to this invitation. New to WeBuddhist? The login page has a link to sign up."
        )
    role_label = invite_role.replace("_", " ").title()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Group invitation</title>
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
              <h1 style="margin:0 0 16px;font-size:22px;font-weight:700;color:#1a1a1a;">You&rsquo;re invited to join a group</h1>
              <p style="margin:0 0 20px;font-size:16px;line-height:1.6;color:#333333;">
                <strong>{inviter_name}</strong>
                (<a href="mailto:{inviter_email}" style="color:{BRAND_PRIMARY};text-decoration:none;">{inviter_email}</a>)
                invited you to join <strong>{group_title}</strong> on WeBuddhist.
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;background-color:#fdf2f2;border-radius:8px;border:1px solid rgba(165,28,33,0.2);">
                <tr>
                  <td style="padding:16px 20px;">
                    <p style="margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:0.06em;color:{TEXT_MUTED};">Invitation details</p>
                    <p style="margin:0 0 4px;font-size:15px;"><strong>Group:</strong> {group_title}</p>
                    <p style="margin:0 0 4px;font-size:15px;"><strong>Role:</strong> {role_label}</p>
                    <p style="margin:0;font-size:15px;"><strong>Expires in:</strong> {expiry_label}</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" cellspacing="0" cellpadding="0" align="center" style="margin:0 auto 24px;">
                <tr>
                  <td style="border-radius:8px;background-color:{BRAND_PRIMARY};">
                    <a href="{invitations_url}" target="_blank" rel="noopener noreferrer"
                       style="display:inline-block;padding:14px 32px;font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;">
                      {button_label}
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:14px;line-height:1.5;color:{TEXT_MUTED};">
                If the button does not work, copy and paste this link into your browser:
              </p>
              <p style="margin:0 0 24px;font-size:14px;word-break:break-all;">
                <a href="{invitations_url}" style="color:{BRAND_PRIMARY};">{invitations_url}</a>
              </p>
              <p style="margin:0;font-size:14px;line-height:1.5;color:#333333;">
                {account_help}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background-color:#fafafa;border-top:1px solid #eeeeee;">
              <p style="margin:0;font-size:12px;line-height:1.5;color:{TEXT_MUTED};text-align:center;">
                This invitation expires in {expiry_label}. If you did not expect this email, you can safely ignore it.
              </p>
              <p style="margin:8px 0 0;font-size:12px;color:{TEXT_MUTED};text-align:center;">
                &copy; WeBuddhist Studio
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_group_invitation_email(
    *,
    target_email: str,
    inviter_name: str,
    inviter_email: str,
    group_title: str,
    invite_role: str,
    invite_token: Optional[str] = None,
) -> None:
    base_url = get("WEBUDDHIST_STUDIO_BASE_URL").rstrip("/")
    one_step_join = bool(invite_token) and get_bool("STUDIO_JOIN_PAGE_ENABLED")
    if one_step_join:
        invitations_url = f"{base_url}/join?invite={quote(invite_token, safe='')}"
    else:
        invitations_url = f"{base_url}/groups"
    login_url = f"{base_url}/login"
    logo_url = get("WEBUDDHIST_EMAIL_LOGO_URL")
    subject = f"You have been invited to join {group_title}"
    html = _build_invitation_html(
        inviter_name=inviter_name,
        inviter_email=inviter_email,
        group_title=group_title,
        invite_role=invite_role,
        invitations_url=invitations_url,
        login_url=login_url,
        logo_url=logo_url,
        one_step_join=one_step_join,
    )
    try:
        send_email(to_email=target_email, subject=subject, message=html)
    except Exception:
        logging.exception("Failed to send group invitation email to %s", target_email)
