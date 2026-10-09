from unittest.mock import patch

from pecha_api.plans.groups.group_invite_email import (
    _build_invitation_html,
    _invite_expiry_label,
    send_group_invitation_email,
)


def test_invite_expiry_label_plural_minutes():
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=30):
        assert _invite_expiry_label() == "30 minutes"


def test_invite_expiry_label_singular_minute():
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=1):
        assert _invite_expiry_label() == "1 minute"


def test_invite_expiry_label_uses_days_and_hours():
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=7 * 24 * 60):
        assert _invite_expiry_label() == "7 days"
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=24 * 60):
        assert _invite_expiry_label() == "1 day"
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=180):
        assert _invite_expiry_label() == "3 hours"


def test_invite_expiry_is_capped_at_30_days():
    with patch("pecha_api.plans.groups.group_invite_token.get_int", return_value=10**9):
        assert _invite_expiry_label() == "30 days"


def test_build_invitation_html_contains_group_and_role():
    html = _build_invitation_html(
        inviter_name="Alice",
        inviter_email="alice@example.org",
        group_title="Dharma Group",
        invite_role="AUTHOR",
        invitations_url="https://studio.webuddhist.com/groups",
        login_url="https://studio.webuddhist.com/login",
        logo_url="https://example.com/logo.png",
    )
    assert "Dharma Group" in html
    assert "Author" in html
    assert "alice@example.org" in html


def test_build_invitation_html_contains_login_link():
    html = _build_invitation_html(
        inviter_name="Alice",
        inviter_email="alice@example.org",
        group_title="Dharma Group",
        invite_role="AUTHOR",
        invitations_url="https://studio.webuddhist.com/groups",
        login_url="https://studio.webuddhist.com/login",
        logo_url="https://example.com/logo.png",
    )
    assert 'href="https://studio.webuddhist.com/login"' in html
    assert "Log in to WeBuddhist Studio" in html


def test_send_group_invitation_email_success():
    with patch("pecha_api.plans.groups.group_invite_email.get", side_effect=lambda key: {
        "WEBUDDHIST_STUDIO_BASE_URL": "https://studio.webuddhist.com",
        "WEBUDDHIST_EMAIL_LOGO_URL": "https://example.com/logo.png",
    }[key]), patch(
        "pecha_api.plans.groups.group_invite_token.get_int",
        return_value=30,
    ), patch(
        "pecha_api.plans.groups.group_invite_email.send_email",
    ) as mock_send:
        send_group_invitation_email(
            target_email="invitee@example.org",
            inviter_name="Alice",
            inviter_email="alice@example.org",
            group_title="Dharma Group",
            invite_role="AUTHOR",
        )
    mock_send.assert_called_once()
    message = mock_send.call_args.kwargs["message"]
    assert "Dharma Group" in message
    assert 'href="https://studio.webuddhist.com/login"' in message


def test_send_group_invitation_email_logs_failure():
    with patch("pecha_api.plans.groups.group_invite_email.get", side_effect=lambda key: {
        "WEBUDDHIST_STUDIO_BASE_URL": "https://studio.webuddhist.com/",
        "WEBUDDHIST_EMAIL_LOGO_URL": "https://example.com/logo.png",
    }[key]), patch(
        "pecha_api.plans.groups.group_invite_token.get_int",
        return_value=30,
    ), patch(
        "pecha_api.plans.groups.group_invite_email.send_email",
        side_effect=RuntimeError("smtp down"),
    ), patch(
        "pecha_api.plans.groups.group_invite_email.logging.exception",
    ) as mock_log:
        send_group_invitation_email(
            target_email="invitee@example.org",
            inviter_name="Alice",
            inviter_email="alice@example.org",
            group_title="Dharma Group",
            invite_role="VIEWER",
        )
    mock_log.assert_called_once()


def test_send_group_invitation_email_links_button_to_signed_join_page():
    with patch("pecha_api.plans.groups.group_invite_email.get", side_effect=lambda key: {
        "WEBUDDHIST_STUDIO_BASE_URL": "https://studio.webuddhist.com/",
        "WEBUDDHIST_EMAIL_LOGO_URL": "https://example.com/logo.png",
    }[key]), patch(
        "pecha_api.plans.groups.group_invite_email.get_bool",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.group_invite_token.get_int",
        return_value=10080,
    ), patch(
        "pecha_api.plans.groups.group_invite_email.send_email",
    ) as mock_send:
        send_group_invitation_email(
            target_email="invitee@example.org",
            inviter_name="Alice",
            inviter_email="alice@example.org",
            group_title="Dharma Group",
            invite_role="AUTHOR",
            invite_token="abc.def+ghi",
        )
    message = mock_send.call_args.kwargs["message"]
    assert 'href="https://studio.webuddhist.com/join?invite=abc.def%2Bghi"' in message
    assert "Accept invitation" in message
    assert "7 days" in message


def test_join_page_link_waits_for_the_studio_page():
    with patch("pecha_api.plans.groups.group_invite_email.get", side_effect=lambda key: {
        "WEBUDDHIST_STUDIO_BASE_URL": "https://studio.webuddhist.com",
        "WEBUDDHIST_EMAIL_LOGO_URL": "https://example.com/logo.png",
    }[key]), patch(
        "pecha_api.plans.groups.group_invite_email.get_bool",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.group_invite_token.get_int",
        return_value=10080,
    ), patch(
        "pecha_api.plans.groups.group_invite_email.send_email",
    ) as mock_send:
        send_group_invitation_email(
            target_email="invitee@example.org",
            inviter_name="Alice",
            inviter_email="alice@example.org",
            group_title="Dharma Group",
            invite_role="AUTHOR",
            invite_token="abc",
        )
    message = mock_send.call_args.kwargs["message"]
    assert "/join?" not in message
    assert 'href="https://studio.webuddhist.com/groups"' in message
    assert "View invitation" in message
    assert "one step" not in message
