import logging
import random
import string
from typing import Any, Dict, List, Optional

import jose
from fastapi import HTTPException, status, UploadFile
from jose import JWTError
from jose.exceptions import JWTClaimsError
from jwt import ExpiredSignatureError
from starlette.concurrency import run_in_threadpool

from pecha_api.error_contants import ErrorConstants
from .user_response_models import (
    UserInfoRequest,
    UserInfoResponse,
    SocialMediaProfile,
    PublisherInfoResponse,
    UpdateUsernameRequest,
    UpdateUsernameResponse,
    OnboardingStatusResponse,
    UpdateOnboardingStatusRequest,
)
from .users_enums import SocialProfile
from .reserved_usernames import is_reserved_username
from .users_models import Users, SocialMediaAccount
from ..auth.auth_repository import validate_token
from .users_repository import (
    delete_user,
    find_user_by_username,
    get_user_by_email,
    get_user_by_username,
    update_user,
)
from .user_resolution import resolve_user_from_payload
from ..uploads.S3_utils import delete_file, upload_bytes, generate_presigned_access_url
from ..db.database import SessionLocal
from ..config import get

from pecha_api.utils import Utils
from pecha_api.image_utils import ImageUtils

async def get_user_info(token: str) -> UserInfoResponse:
    # Token validation and response building are both synchronous SQLAlchemy,
    # so they run in one worker thread rather than on the event loop.
    return await run_in_threadpool(_get_user_info_sync, token=token)


def _get_user_info_sync(token: str) -> UserInfoResponse:
    current_user = validate_and_extract_user_details(token=token)
    return generate_user_info_response(user=current_user)


async def get_user_info_by_username(username: str) -> UserInfoResponse:
    return await run_in_threadpool(_get_user_info_by_username_sync, username=username)


def _get_user_info_by_username_sync(username: str) -> UserInfoResponse:
    with SessionLocal() as db_session:
        user = get_user_by_username(db=db_session, username=username)
        db_session.close()
    return generate_user_info_response(user=user)

def fetch_user_by_email(email: str) -> Optional[UserInfoResponse]:
    with SessionLocal() as db_session:
        user = get_user_by_email(db=db_session, email=email)
        db_session.close()
    return generate_user_info_response(user=user)


def generate_user_info_response(user: Users) -> Optional[UserInfoResponse]:
    if user:
        social_media_profiles = []
        with SessionLocal() as db_session:
            db_session.add(user)
            for account in user.social_media_accounts:
                social_media_profile = SocialMediaProfile(
                    account=get_social_profile(value=account.platform_name),
                    url=account.profile_url
                )
                social_media_profiles.append(social_media_profile)

            user_info_response = UserInfoResponse(
                id=user.id,
                firstname=user.firstname,
                lastname=user.lastname,
                username=user.username,
                email=user.email,
                title=user.title,
                organization=user.organization,
                location=user.location,
                educations=user.education.split(',') if user.education else [],
                avatar_url=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=user.avatar_url),
                about_me=user.about_me,
                followers=0,
                following=0,
                social_profiles=social_media_profiles
            )
            return user_info_response
    return None


def update_user_info(token: str, user_info_request: UserInfoRequest) -> Users:
    current_user = validate_and_extract_user_details(token=token)
    current_user.firstname = user_info_request.firstname
    current_user.lastname = user_info_request.lastname
    current_user.title = user_info_request.title
    current_user.organization = user_info_request.organization
    current_user.location = user_info_request.location
    current_user.education = ','.join(user_info_request.educations)
    current_user.avatar_url = Utils.extract_s3_key(presigned_url=user_info_request.avatar_url)
    current_user.about_me = user_info_request.about_me
    with SessionLocal() as db_session:
        try:
            db_session.add(current_user)
            update_social_profiles(user=current_user, social_profiles=user_info_request.social_profiles)
            updated_user = update_user(db=db_session, user=current_user)
            return updated_user
        except Exception as e:
            db_session.rollback()
            logging.error(f"Failed to update user info: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")


def update_social_profiles(user: Users, social_profiles: List[SocialMediaProfile]) -> None:
    existing_profiles = {profile.platform_name: profile for profile in user.social_media_accounts}

    for profile_data in social_profiles or []:
        platform = profile_data.account.name
        url = profile_data.url

        if platform in existing_profiles:
            # Update existing profile
            existing_profiles[platform].profile_url = url
        else:
            # Add new profile
            user.social_media_accounts.append(SocialMediaAccount(
                user_id=user.id,
                platform_name=platform,
                profile_url=url
            ))


def upload_user_image(token: str, file: UploadFile) -> str:
    current_user = validate_and_extract_user_details(token=token)
    # Validate and compress the uploaded image
    image_utils = ImageUtils()
    compressed_image = image_utils.validate_and_compress_image(file=file, content_type=file.content_type)
    file_path = f'images/profile_images/{current_user.id}.webp'
    delete_file(file_path=file_path)
    upload_key = upload_bytes(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=file_path,
        file=compressed_image,
        content_type="image/webp"
    )
    presigned_url = generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=upload_key
    )
    current_user.avatar_url = Utils.extract_s3_key(presigned_url=presigned_url)
    with SessionLocal() as db_session:
        update_user(db=db_session, user=current_user)
        return presigned_url


def resolve_user_from_token_payload(db, payload: Dict[str, Any]) -> Users:
    return resolve_user_from_payload(
        db=db,
        payload=payload,
        unauthorized_detail=ErrorConstants.TOKEN_ERROR_MESSAGE,
    )


def validate_and_extract_user_details(token: str) -> Users:
    try:
        payload = validate_token(token)
        with SessionLocal() as db_session:
            try:
                user = resolve_user_from_token_payload(db_session, payload)
            except HTTPException as exception:
                if exception.status_code == status.HTTP_404_NOT_FOUND:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=ErrorConstants.TOKEN_ERROR_MESSAGE,
                    ) from exception
                raise
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=ErrorConstants.TOKEN_ERROR_MESSAGE,
                )
            return user
    except ExpiredSignatureError as exception:
        logging.debug(f"exception: {exception}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ErrorConstants.TOKEN_ERROR_MESSAGE)
    except jose.ExpiredSignatureError as exception:
        logging.debug(f"exception: {exception}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ErrorConstants.TOKEN_ERROR_MESSAGE)
    except JWTClaimsError as exception:
        logging.debug(f"exception: {exception}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ErrorConstants.TOKEN_ERROR_MESSAGE)
    except ValueError as value_exception:
        logging.debug(f"exception: {value_exception}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ErrorConstants.TOKEN_ERROR_MESSAGE)
    except JWTError as jwt_exception:
        logging.debug(f"exception: {jwt_exception}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ErrorConstants.TOKEN_ERROR_MESSAGE)


def delete_user_account(token: str) -> None:
    current_user = validate_and_extract_user_details(token=token)
    avatar_key = current_user.avatar_url
    with SessionLocal() as db_session:
        db_session.add(current_user)
        delete_user(db=db_session, user=current_user)
    if avatar_key:
        try:
            delete_file(file_path=avatar_key)
        except Exception as e:
            logging.warning(f"Failed to delete avatar from S3 for user {current_user.id}: {e}")


def verify_admin_access(token: str) -> bool:
    current_user = validate_and_extract_user_details(token=token)
    if hasattr(current_user, 'is_admin') and current_user.is_admin is not None:
        return current_user.is_admin
    else:
        return False


def validate_user_exists(token: str) -> bool:
    current_user = validate_and_extract_user_details(token=token)
    if current_user:
        return True
    else:
        return False


def get_social_profile(value: str) -> SocialProfile:
    try:
        return SocialProfile(value.lower().replace("_", "."))
    except ValueError:
        raise ValueError(f"'{value}' is not a valid SocialProfile")


def get_publisher_info_by_username(username: str) -> Optional[PublisherInfoResponse]:
    try:
        with SessionLocal() as db_session:
            user = get_user_by_username(db=db_session, username=username)
            if user:
                avatar_url = None
                if user.avatar_url:
                    avatar_url = generate_presigned_access_url(
                        bucket_name=get("AWS_BUCKET_NAME"),
                        s3_key=user.avatar_url
                    )

                return PublisherInfoResponse(
                    id=str(user.id),
                    username=user.username,
                    firstname=user.firstname,
                    lastname=user.lastname,
                    avatar_url=avatar_url
                )
    except Exception as e:
        logging.error(f"Error getting publisher info by username: {e}")
    return None


def _generate_username_suggestions(base: str, count: int = 3) -> List[str]:
    base = "".join(base.split())
    suggestions: List[str] = []
    attempts = 0
    with SessionLocal() as db_session:
        while len(suggestions) < count and attempts < 20:
            suffix = ''.join(random.choices(string.digits, k=4))
            candidate = f"{base}{suffix}"
            if is_reserved_username(candidate):
                attempts += 1
                continue
            if not find_user_by_username(db=db_session, username=candidate):
                suggestions.append(candidate)
            attempts += 1
    return suggestions


def get_onboarding_status(token: str) -> OnboardingStatusResponse:
    current_user = validate_and_extract_user_details(token=token)
    return OnboardingStatusResponse(has_seen_onboarding=current_user.has_seen_onboarding)


def update_onboarding_status(token: str, request: UpdateOnboardingStatusRequest) -> OnboardingStatusResponse:
    current_user = validate_and_extract_user_details(token=token)
    current_user.has_seen_onboarding = request.has_seen_onboarding
    with SessionLocal() as db_session:
        try:
            updated_user = update_user(db=db_session, user=current_user)
            return OnboardingStatusResponse(has_seen_onboarding=updated_user.has_seen_onboarding)
        except Exception as e:
            logging.exception(f"Failed to update onboarding status: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")


def update_username(token: str, request: UpdateUsernameRequest) -> UpdateUsernameResponse:
    current_user = validate_and_extract_user_details(token=token)
    new_username = request.username

    with SessionLocal() as db_session:
        existing = find_user_by_username(db=db_session, username=new_username)

    if existing and existing.id != current_user.id:
        suggestions = _generate_username_suggestions(base=new_username)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": ErrorConstants.USER_ALREADY_EXISTS,
                "suggestions": suggestions,
            },
        )

    current_user.username = new_username
    with SessionLocal() as db_session:
        try:
            updated_user = update_user(db=db_session, user=current_user)
            return UpdateUsernameResponse(
                message="Username updated successfully",
                username=updated_user.username,
            )
        except Exception as e:
            logging.exception(f"Failed to update username: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")
