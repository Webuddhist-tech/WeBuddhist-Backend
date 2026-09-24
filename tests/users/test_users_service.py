import jose
import pytest
from uuid import uuid4
from jose.exceptions import JWTClaimsError
from jwt import ExpiredSignatureError
from starlette import status
from pecha_api.image_utils import ImageUtils
from pecha_api.utils import Utils
from pecha_api.error_contants import ErrorConstants
from pecha_api.users.users_service import get_user_info, update_user_info, \
    validate_and_extract_user_details, verify_admin_access, get_social_profile, update_social_profiles, \
    get_publisher_info_by_username, fetch_user_by_email, validate_user_exists, get_user_info_by_username, \
    update_username, _generate_username_suggestions, delete_user_account
from pecha_api.users.user_response_models import UserInfoRequest, SocialMediaProfile, PublisherInfoResponse, \
    UserInfoResponse, UpdateUsernameRequest, UpdateUsernameResponse
from pecha_api.users.users_models import Users, SocialMediaAccount
from pecha_api.users.users_enums import SocialProfile
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException, UploadFile
from pecha_api.users.users_service import upload_user_image
import io


@pytest.mark.asyncio
async def test_get_user_info_success():
    token = "valid_token"
    user = Users(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Developer",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About John",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "john.doe@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=user):
        response = await get_user_info(token)
        assert response.firstname == "John"
        assert response.lastname == "Doe"
        assert response.username == "johndoe"
        assert response.email == "john.doe@example.com"


@pytest.mark.asyncio
async def test_get_user_info_with_social_accounts():
    token = "valid_token"
    user = Users(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Developer",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About John",
        social_media_accounts=[
            SocialMediaAccount(platform_name="EMAIL", profile_url="john.doe@gmail.com"),
            SocialMediaAccount(platform_name="LinkedIn", profile_url="http://linkedin.com/in/johndoe")
        ]
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "john.doe@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=user):
        response = await get_user_info(token)
        assert response.firstname == "John"
        assert response.lastname == "Doe"
        assert response.username == "johndoe"
        assert response.email == "john.doe@example.com"
        assert len(response.social_profiles) == 2
        assert response.social_profiles[0].account.name == SocialProfile.EMAIL.name
        assert response.social_profiles[0].url == "john.doe@gmail.com"
        assert response.social_profiles[1].account.name == SocialProfile.LINKEDIN.name
        assert response.social_profiles[1].url == "http://linkedin.com/in/johndoe"


@pytest.mark.asyncio
async def test_get_user_info_invalid_token():
    token = "invalid_token"

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": None}):
        with pytest.raises(HTTPException) as exc_info:
            await get_user_info(token)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == 'Invalid or no token found'


def test_update_user_info_success():
    token = "valid_token"
    user_info_request = UserInfoRequest(
        firstname="Jane",
        lastname="Doe",
        title="Manager",
        organization="ExampleOrg",
        educations=["BSc", "MBA"],
        avatar_url="http://example.com/avatar.jpg",
        about_me="About Jane",
        social_profiles=[]
    )
    user = Users(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Developer",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About John",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "john.doe@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=user), \
            patch("pecha_api.users.users_service.update_user") as mock_update_user:
        update_user_info(token, user_info_request)
        mock_update_user.assert_called_once()


def test_update_user_info_invalid_token():
    token = "invalid_token"
    user_info_request = UserInfoRequest(
        firstname="Jane",
        lastname="Doe",
        title="Manager",
        organization="ExampleOrg",
        educations=["BSc", "MBA"],
        avatar_url="http://example.com/avatar.jpg",
        about_me="About Jane",
        social_profiles=[]
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": None}):
        try:
            update_user_info(token, user_info_request)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == 'Invalid or no token found'


def test_update_user_info_500_db_error():
    token = "valid_token"
    user_info_request = UserInfoRequest(
        firstname="Jane",
        lastname="Doe",
        title="Manager",
        organization="ExampleOrg",
        educations=["BSc", "MBA"],
        avatar_url="http://example.com/avatar.jpg",
        about_me="About Jane",
        social_profiles=[]
    )
    user = Users(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Developer",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About John",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "john.doe@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=user), \
            patch("pecha_api.users.users_service.update_user", side_effect=Exception("Db Error")):
        try:
            update_user_info(token, user_info_request)
        except HTTPException as e:
            assert e.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert e.detail == 'Internal Server Error'


def test_upload_user_image_success():
    token = "valid_token"
    file_content = io.BytesIO(b"fake_image_data")

    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=MagicMock(id="user_id")), \
            patch("pecha_api.image_utils.ImageUtils.validate_and_compress_image", return_value=file_content), \
            patch("pecha_api.users.users_service.delete_file") as mock_delete_file, \
            patch("pecha_api.users.users_service.update_user") as mock_update_user, \
            patch("pecha_api.users.users_service.upload_bytes", return_value="s3_key"), \
            patch("pecha_api.users.users_service.generate_presigned_access_url",
                  return_value="http://example.com/presigned_url"):
        response = upload_user_image(token, file)
        mock_update_user.assert_called_once()
        mock_delete_file.assert_called_once_with(file_path="images/profile_images/user_id.webp")
        assert response == "http://example.com/presigned_url"


def test_upload_user_image_invalid_token():
    token = "invalid_token"
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.users.users_service.validate_and_extract_user_details",
               side_effect=HTTPException(status_code=401, detail="Invalid or no token found")):
        try:
            upload_user_image(token, file)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == 'Invalid or no token found'


def test_validate_and_compress_image_success():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.image_utils.get_int", side_effect=[5, 75]), \
            patch("PIL.Image.open") as mock_open:
        mock_image = MagicMock()
        mock_image.mode = 'RGB'  # Set the mode to RGB
        mock_open.return_value = mock_image
        mock_image.save = MagicMock()
        image_utils = ImageUtils()
        compressed_image = image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
        assert isinstance(compressed_image, io.BytesIO)
        mock_image.save.assert_called_once_with(compressed_image, format="WEBP", quality=75)


def test_validate_and_compress_image_invalid_file_type():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.txt", file=file_content)
    try:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="text/plain")
    except HTTPException as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
        assert e.detail == 'Only image files are allowed'


def test_validate_and_compress_image_file_too_large():
    file_content = io.BytesIO(b"fake_image_data" * 1024 * 1024 * 6)  # 6 MB
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.image_utils.get_int", return_value=5), \
            pytest.raises(HTTPException) as exc_info:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "File size exceeds 1MB limit"


def test_validate_and_compress_image_processing_failure():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.image_utils.get_int", side_effect=[5, 75]), \
            patch("pecha_api.image_utils.Image.open", side_effect=Exception("Processing error")), \
            pytest.raises(HTTPException) as exc_info:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to process the image"


def test_validate_and_extract_user_details_invalid_token():
    token = "invalid_token"

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": None}):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or no token found"


def test_validate_and_extract_user_details_user_not_found():
    token = "valid_token"

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "missing@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE


def test_validate_and_extract_user_details_user_not_found_raises_404():
    token = "valid_token"

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "missing@example.com"}), \
            patch(
                "pecha_api.users.user_resolution.get_user_by_email",
                side_effect=HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ErrorConstants.USER_NOT_FOUND,
                ),
            ):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == ErrorConstants.TOKEN_ERROR_MESSAGE


def test_validate_and_extract_user_details_expired_signature():
    token = "expired_token"

    with patch("pecha_api.users.users_service.validate_token", side_effect=ExpiredSignatureError):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or no token found"


def test_validate_and_extract_user_details_jose_expired_signature():
    token = "expired_token"

    with patch("pecha_api.users.users_service.validate_token", side_effect=jose.ExpiredSignatureError):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or no token found"


def test_validate_and_extract_user_details_jwt_claims_error():
    token = "invalid_claims_token"

    with patch("pecha_api.users.users_service.validate_token", side_effect=JWTClaimsError):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or no token found"


def test_validate_and_extract_user_details_value_error():
    token = "value_error_token"

    with patch("pecha_api.users.users_service.validate_token", side_effect=ValueError("Invalid or no token found")):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_extract_user_details(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or no token found"


def test_verify_admin_access_true():
    token = "valid_admin_token"
    user = Users(
        firstname="Admin",
        lastname="User",
        username="adminuser",
        email="admin.user@example.com",
        title="Admin",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About Admin",
        social_media_accounts=[],
        is_admin=True
    )

    with patch("pecha_api.users.users_service.validate_token", return_value={"email": "admin.user@example.com"}), \
            patch("pecha_api.users.user_resolution.get_user_by_email", return_value=user):
        assert verify_admin_access(token) is True


def test_verify_admin_access_false():
    token = "valid_non_admin_token"
    user = Users(
        firstname="Regular",
        lastname="User",
        username="regularuser",
        email="regular.user@example.com",
        title="User",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About User",
        social_media_accounts=[],
        is_admin=False
    )

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=user):
        assert verify_admin_access(token) is False


def test_verify_admin_access_no_attribute_false():
    token = "valid_non_admin_token"
    user = Users(
        firstname="Regular",
        lastname="User",
        username="regularuser",
        email="regular.user@example.com",
        title="User",
        organization="ExampleOrg",
        education="BSc, MSc",
        avatar_url="http://example.com/avatar.jpg",
        about_me="About User",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=user):
        assert verify_admin_access(token) is False


def test_get_social_profile_valid():
    assert get_social_profile("EMAIL") == SocialProfile.EMAIL
    assert get_social_profile("LinkedIn") == SocialProfile.LINKEDIN
    assert get_social_profile("X_COM") == SocialProfile.X_COM
    assert get_social_profile("FACEBOOK") == SocialProfile.FACEBOOK
    assert get_social_profile("YOUTUBE") == SocialProfile.YOUTUBE


def test_get_social_profile_invalid():
    with pytest.raises(ValueError) as exc_info:
        get_social_profile("INVALID_PROFILE")
    assert str(exc_info.value) == "'INVALID_PROFILE' is not a valid SocialProfile"


def test_extract_s3_key_valid_url():
    presigned_url = "https://example-bucket.s3.amazonaws.com/images/profile_images/user_id.jpg"
    assert Utils.extract_s3_key(presigned_url) == "images/profile_images/user_id.jpg"


def test_extract_s3_key_empty_url():
    assert Utils.extract_s3_key("") == ""


def test_extract_s3_key_invalid_url():
    presigned_url = "https://example-bucket.s3.amazonaws.com/"
    assert Utils.extract_s3_key(presigned_url) == ""


def test_update_social_profiles():
    user = Users(
        id="user_id",
        social_media_accounts=[
            SocialMediaAccount(platform_name="EMAIL", profile_url="john.doe@gmail.com")
        ]
    )
    social_profiles = [
        SocialMediaProfile(account=SocialProfile.EMAIL, url="john.doe@newemail.com"),
        SocialMediaProfile(account=SocialProfile.LINKEDIN, url="http://linkedin.com/in/johndoe")
    ]

    update_social_profiles(user, social_profiles)

    assert len(user.social_media_accounts) == 2
    assert user.social_media_accounts[0].platform_name == "EMAIL"
    assert user.social_media_accounts[0].profile_url == "john.doe@newemail.com"
    assert user.social_media_accounts[1].platform_name == "LINKEDIN"
    assert user.social_media_accounts[1].profile_url == "http://linkedin.com/in/johndoe"


def test_get_publisher_info_by_username_success_with_avatar():
    username = "johndoe"
    user = Users(
        id="123e4567-e89b-12d3-a456-426614174000",
        firstname="tenzin",
        lastname="yama",
        username="tenya",
        avatar_url="images/profile_images/user_123.jpg"
    )

    with patch("pecha_api.users.users_service.get_user_by_username", return_value=user), \
            patch("pecha_api.users.users_service.generate_presigned_access_url", 
                  return_value="https://example.com/presigned_avatar.jpg"):
        response = get_publisher_info_by_username(username)
        
        assert response is not None
        assert isinstance(response, PublisherInfoResponse)
        assert response.id == "123e4567-e89b-12d3-a456-426614174000"
        assert response.username == "tenya"
        assert response.firstname == "tenzin"
        assert response.lastname == "yama"
        assert response.avatar_url == "https://example.com/presigned_avatar.jpg"


def test_get_publisher_info_by_username_success_without_avatar():
    username = "janedoe"
    user = Users(
        id="456e7890-e89b-12d3-a456-426614174001",
        firstname="tenzin",
        lastname="yama",
        username="tenya",
        avatar_url=None
    )

    with patch("pecha_api.users.users_service.get_user_by_username", return_value=user):
        response = get_publisher_info_by_username(username)
        
        assert response is not None
        assert isinstance(response, PublisherInfoResponse)
        assert response.id == "456e7890-e89b-12d3-a456-426614174001"
        assert response.username == "tenya"
        assert response.firstname == "tenzin"
        assert response.lastname == "yama"
        assert response.avatar_url is None


def test_get_publisher_info_by_username_success_empty_avatar():
    username = "testuser"
    user = Users(
        id="789e1234-e89b-12d3-a456-426614174002",
        firstname="Test",
        lastname="User",
        username="testuser",
        avatar_url=""
    )

    with patch("pecha_api.users.users_service.get_user_by_username", return_value=user):
        response = get_publisher_info_by_username(username)
        
        assert response is not None
        assert isinstance(response, PublisherInfoResponse)
        assert response.id == "789e1234-e89b-12d3-a456-426614174002"
        assert response.username == "testuser"
        assert response.firstname == "Test"
        assert response.lastname == "User"
        assert response.avatar_url is None


def test_get_publisher_info_by_username_user_not_found():
    username = "nonexistentuser"

    with patch("pecha_api.users.users_service.get_user_by_username", return_value=None):
        response = get_publisher_info_by_username(username)
        
        assert response is None


def test_get_publisher_info_by_username_database_exception():
    username = "problematicuser"

    with patch("pecha_api.users.users_service.get_user_by_username", 
               side_effect=Exception("Database connection error")), \
            patch("pecha_api.users.users_service.logging.error") as mock_logger:
        response = get_publisher_info_by_username(username)
        
        assert response is None
        mock_logger.assert_called_once_with("Error getting publisher info by username: Database connection error")


def test_get_publisher_info_by_username_presigned_url_exception():
    username = "urlproblems"
    user = Users(
        id="999e8888-e89b-12d3-a456-426614174003",
        firstname="URL",
        lastname="Problems", 
        username="urlproblems",
        avatar_url="images/profile_images/user_999.jpg"
    )

    with patch("pecha_api.users.users_service.get_user_by_username", return_value=user), \
            patch("pecha_api.users.users_service.generate_presigned_access_url", 
                  side_effect=Exception("S3 connection error")), \
            patch("pecha_api.users.users_service.logging.error") as mock_logger:
        response = get_publisher_info_by_username(username)
        
        assert response is None
        mock_logger.assert_called_once_with("Error getting publisher info by username: S3 connection error")


@pytest.mark.asyncio
async def test_get_user_info_cache_none_success():
    mock_user = type('Users', (), {
        "id": "user_id",
        "firstname": "tenzin",
        "lastname": "tenzin",
        "username": "tenya",
        "avatar_url": "images/profile_images/user_123.jpg",
    })

    mock_user_info_response = UserInfoResponse(
        id=uuid4(),
        firstname="tenzin",
        lastname="tenzin",
        username="tenzin123",
        email="tenzin@gmail.com",
        educations=[],
        followers=0,
        following=0,
        social_profiles=[]
    )
    token = "valid_token"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=mock_user), \
        patch("pecha_api.users.users_service.generate_user_info_response", return_value=mock_user_info_response):

        response = await get_user_info(token)

        assert response is not None
        assert isinstance(response, UserInfoResponse)
        assert response.firstname == "tenzin"
        assert response.lastname == "tenzin"
        assert response.username == "tenzin123"


@pytest.mark.asyncio
async def test_fetch_user_by_email_success():
    mock_user = type('Users', (), {
        "id": "user_id",
        "firstname": "tenzin",
        "lastname": "tenzin",
        "username": "tenya",
        "avatar_url": "images/profile_images/user_123.jpg",
    })

    mock_user_info_response = UserInfoResponse(
        id=uuid4(),
        firstname="tenzin",
        lastname="tenzin",
        username="tenzin123",
        email="tenzin@gmail.com",
        educations=[],
        followers=0,
        following=0,
        social_profiles=[]
    )
    email = "tenzin@gmail.com"
    with patch("pecha_api.users.users_service.get_user_by_email", return_value=mock_user), \
        patch("pecha_api.users.users_service.generate_user_info_response", return_value=mock_user_info_response):

        response = fetch_user_by_email(email)

        assert response is not None
        assert isinstance(response, UserInfoResponse)
        assert response.firstname == "tenzin"
        assert response.lastname == "tenzin"
        assert response.username == "tenzin123"

def test_validate_user_exists_success():
    token = "valid_token"
    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=True):

        response = validate_user_exists(token)

        assert response is True

def test_validate_user_exists_false():
    token = "invalid_token"
    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=False):

        response = validate_user_exists(token)

        assert response is False


@pytest.mark.asyncio
async def test_get_user_info_by_username_success():
    username = "johndoe"
    mock_user = Users(
        id="123e4567-e89b-12d3-a456-426614174000",
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Senior Developer",
        organization="Tech Corp",
        location="San Francisco",
        education="Computer Science, Software Engineering",
        avatar_url="images/profile_images/user_123.jpg",
        about_me="Experienced developer with passion for clean code.",
        social_media_accounts=[]
    )
    
    expected_response = UserInfoResponse(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="johndoe",
        email="john.doe@example.com",
        title="Senior Developer",
        organization="Tech Corp",
        location="San Francisco",
        educations=["Computer Science", " Software Engineering"],
        avatar_url="https://example.com/presigned_avatar.jpg",
        about_me="Experienced developer with passion for clean code.",
        followers=0,
        following=0,
        social_profiles=[]
    )
    
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.get_user_by_username", return_value=mock_user) as mock_get_user, \
         patch("pecha_api.users.users_service.generate_user_info_response", return_value=expected_response) as mock_generate:
        
        mock_db_session = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db_session
        mock_session.return_value.__exit__.return_value = None
        
        result = await get_user_info_by_username(username)
        
        assert result == expected_response
        assert result.username == "johndoe"
        assert result.firstname == "John"
        assert result.lastname == "Doe"
        assert result.email == "john.doe@example.com"
        
        mock_get_user.assert_called_once_with(db=mock_db_session, username=username)
        mock_generate.assert_called_once_with(user=mock_user)
        mock_db_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_info_by_username_user_not_found():
    username = "nonexistent_user"
    
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.get_user_by_username", return_value=None) as mock_get_user, \
         patch("pecha_api.users.users_service.generate_user_info_response", return_value=None) as mock_generate:
        
        mock_db_session = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db_session
        mock_session.return_value.__exit__.return_value = None
        
        result = await get_user_info_by_username(username)
        
        assert result is None
        
        mock_get_user.assert_called_once_with(db=mock_db_session, username=username)
        mock_generate.assert_called_once_with(user=None)
        mock_db_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_info_by_username_with_social_profiles():
    username = "socialuser"
    mock_social_account = SocialMediaAccount(
        platform_name="LINKEDIN",
        profile_url="https://linkedin.com/in/johndoe"
    )
    
    mock_user = Users(
        id="456e7890-e89b-12d3-a456-426614174001",
        firstname="Social",
        lastname="User",
        username="socialuser",
        email="social.user@example.com",
        title="Marketing Manager",
        organization="Social Corp",
        location="New York",
        education="Marketing, Business",
        avatar_url="images/profile_images/social_123.jpg",
        about_me="Social media enthusiast.",
        social_media_accounts=[mock_social_account]
    )
    
    expected_social_profile = SocialMediaProfile(
        account=SocialProfile.LINKEDIN,
        url="https://linkedin.com/in/johndoe"
    )
    
    expected_response = UserInfoResponse(
        id=uuid4(),
        firstname="Social",
        lastname="User",
        username="socialuser",
        email="social.user@example.com",
        title="Marketing Manager",
        organization="Social Corp",
        location="New York",
        educations=["Marketing", " Business"],
        avatar_url="https://example.com/presigned_social_avatar.jpg",
        about_me="Social media enthusiast.",
        followers=0,
        following=0,
        social_profiles=[expected_social_profile]
    )
    
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.get_user_by_username", return_value=mock_user) as mock_get_user, \
         patch("pecha_api.users.users_service.generate_user_info_response", return_value=expected_response) as mock_generate:
        
        mock_db_session = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db_session
        mock_session.return_value.__exit__.return_value = None
        
        result = await get_user_info_by_username(username)
        
        assert result == expected_response
        assert result.username == "socialuser"
        assert len(result.social_profiles) == 1
        assert result.social_profiles[0].account == SocialProfile.LINKEDIN
        mock_get_user.assert_called_once_with(db=mock_db_session, username=username)
        mock_generate.assert_called_once_with(user=mock_user)
        mock_db_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_info_by_username_database_error():
    username = "erroruser"
    
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.get_user_by_username", side_effect=Exception("Database connection error")) as mock_get_user:
        
        mock_db_session = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db_session
        mock_session.return_value.__exit__.return_value = None
        
        with pytest.raises(Exception, match="Database connection error"):
            await get_user_info_by_username(username)
        
        mock_get_user.assert_called_once_with(db=mock_db_session, username=username)


def _mock_session_ctx(mock_session_cls):
    mock_db = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_db
    mock_session_cls.return_value.__exit__.return_value = None
    return mock_db


def test_update_username_success():
    token = "valid_token"
    request = UpdateUsernameRequest(username="newuser")
    current_user = Users(
        id="user-id-123",
        firstname="John",
        lastname="Doe",
        username="olduser",
        email="john@example.com",
        social_media_accounts=[]
    )
    updated_user = Users(
        id="user-id-123",
        firstname="John",
        lastname="Doe",
        username="newuser",
        email="john@example.com",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=current_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=None), \
         patch("pecha_api.users.users_service.update_user", return_value=updated_user):

        _mock_session_ctx(mock_session)
        result = update_username(token=token, request=request)

    assert isinstance(result, UpdateUsernameResponse)
    assert result.message == "Username updated successfully"
    assert result.username == "newuser"


def test_update_username_conflict_raises_409_with_suggestions():
    token = "valid_token"
    request = UpdateUsernameRequest(username="takenuser")
    current_user = Users(
        id="user-id-123",
        firstname="John",
        lastname="Doe",
        username="olduser",
        email="john@example.com",
        social_media_accounts=[]
    )
    existing_user = Users(
        id="other-id",
        username="takenuser",
        email="other@example.com",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=current_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=existing_user), \
         patch("pecha_api.users.users_service._generate_username_suggestions",
               return_value=["takenuser1234", "takenuser5678", "takenuser9012"]):

        _mock_session_ctx(mock_session)
        with pytest.raises(HTTPException) as exc_info:
            update_username(token=token, request=request)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    detail = exc_info.value.detail
    assert detail["message"] == ErrorConstants.USER_ALREADY_EXISTS
    assert detail["suggestions"] == ["takenuser1234", "takenuser5678", "takenuser9012"]


def test_update_username_invalid_token_raises_401():
    token = "bad_token"
    request = UpdateUsernameRequest(username="anyuser")

    with patch("pecha_api.users.users_service.validate_and_extract_user_details",
               side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or no token found")):
        with pytest.raises(HTTPException) as exc_info:
            update_username(token=token, request=request)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_update_username_db_error_raises_500():
    token = "valid_token"
    request = UpdateUsernameRequest(username="newuser")
    current_user = Users(
        id="user-id-123",
        firstname="John",
        lastname="Doe",
        username="olduser",
        email="john@example.com",
        social_media_accounts=[]
    )

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=current_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=None), \
         patch("pecha_api.users.users_service.update_user", side_effect=Exception("DB failure")):

        _mock_session_ctx(mock_session)
        with pytest.raises(HTTPException) as exc_info:
            update_username(token=token, request=request)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Internal Server Error"


def test_generate_username_suggestions_returns_three_unique():
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=None):

        _mock_session_ctx(mock_session)
        suggestions = _generate_username_suggestions(base="testuser", count=3)

    assert len(suggestions) == 3
    for suggestion in suggestions:
        assert suggestion.startswith("testuser")
        assert len(suggestion) == len("testuser") + 4
        assert " " not in suggestion


def test_generate_username_suggestions_strip_spaces_from_base():
    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=None):

        _mock_session_ctx(mock_session)
        suggestions = _generate_username_suggestions(base="john doe", count=3)

    assert len(suggestions) == 3
    for suggestion in suggestions:
        assert " " not in suggestion
        assert suggestion.startswith("johndoe")
        assert len(suggestion) == len("johndoe") + 4


def test_update_username_request_normalizes_to_lowercase():
    req = UpdateUsernameRequest(username="HelloWorld")
    assert req.username == "helloworld"


def test_update_username_request_rejects_spaces():
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="  hello  ")
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="hello world")


def test_update_username_request_rejects_emojis():
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="user😀123")


def test_update_username_request_rejects_invalid_characters():
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="user@name")
    with pytest.raises(Exception):
        UpdateUsernameRequest(username=".username")
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="username-")


def test_update_username_request_allows_valid_special_characters():
    req = UpdateUsernameRequest(username="test.user-123")
    assert req.username == "test.user-123"


def test_update_username_request_too_short():
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="ab")


def test_update_username_request_empty():
    with pytest.raises(Exception):
        UpdateUsernameRequest(username="   ")


def test_delete_user_account_success_with_avatar():
    token = "valid_token"
    mock_user = MagicMock()
    mock_user.avatar_url = "images/profile_images/user_123.jpg"
    mock_user.id = "user-id-123"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=mock_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.delete_user") as mock_delete_user, \
         patch("pecha_api.users.users_service.delete_file") as mock_delete_file:

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = None

        delete_user_account(token)

        mock_delete_user.assert_called_once_with(db=mock_db, user=mock_user)
        mock_delete_file.assert_called_once_with(file_path="images/profile_images/user_123.jpg")


def test_delete_user_account_success_no_avatar():
    token = "valid_token"
    mock_user = MagicMock()
    mock_user.avatar_url = None
    mock_user.id = "user-id-456"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=mock_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.delete_user") as mock_delete_user, \
         patch("pecha_api.users.users_service.delete_file") as mock_delete_file:

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = None

        delete_user_account(token)

        mock_delete_user.assert_called_once_with(db=mock_db, user=mock_user)
        mock_delete_file.assert_not_called()


def test_delete_user_account_invalid_token():
    token = "invalid_token"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details",
               side_effect=HTTPException(status_code=401, detail="Invalid or no token found")):
        with pytest.raises(HTTPException) as exc_info:
            delete_user_account(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or no token found"


def test_delete_user_account_s3_delete_warning():
    token = "valid_token"
    mock_user = MagicMock()
    mock_user.avatar_url = "images/profile_images/user_789.jpg"
    mock_user.id = "user-id-789"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=mock_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.delete_user"), \
         patch("pecha_api.users.users_service.delete_file", side_effect=Exception("S3 unavailable")), \
         patch("pecha_api.users.users_service.logging") as mock_logging:

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = None

        delete_user_account(token)

        mock_logging.warning.assert_called_once()
        warning_msg = mock_logging.warning.call_args[0][0]
        assert "user-id-789" in warning_msg
        assert "S3 unavailable" in warning_msg


def test_delete_user_account_db_error():
    token = "valid_token"
    mock_user = MagicMock()
    mock_user.avatar_url = None
    mock_user.id = "user-id-000"

    with patch("pecha_api.users.users_service.validate_and_extract_user_details", return_value=mock_user), \
         patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.delete_user",
               side_effect=HTTPException(status_code=500, detail="Failed to delete user account")):

        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_user_account(token)
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to delete user account"


def test_generate_username_suggestions_skips_reserved_candidates():
    # The first candidate is treated as reserved and must not be suggested.
    reserved_calls = {"count": 0}

    def _is_reserved(candidate: str) -> bool:
        reserved_calls["count"] += 1
        return reserved_calls["count"] == 1

    with patch("pecha_api.users.users_service.SessionLocal") as mock_session, \
         patch("pecha_api.users.users_service.find_user_by_username", return_value=None), \
         patch("pecha_api.users.users_service.is_reserved_username", side_effect=_is_reserved):

        _mock_session_ctx(mock_session)
        suggestions = _generate_username_suggestions(base="testuser", count=3)

    assert len(suggestions) == 3
    assert reserved_calls["count"] == 4
