from unittest.mock import patch

import pytest

from pecha_api.plans.auth.studio_access_service import StudioAdmission


@pytest.fixture(autouse=True)
def _no_studio_admission():
    """plan_auth_services tests run on mocked sessions, where the real
    admission rules (tested in test_studio_access_service) would read the
    mock as pending invites. Tests that care patch admit_author themselves."""
    with patch(
        "pecha_api.plans.auth.plan_auth_services.admit_author",
        return_value=StudioAdmission(),
    ) as mock_admit:
        yield mock_admit
