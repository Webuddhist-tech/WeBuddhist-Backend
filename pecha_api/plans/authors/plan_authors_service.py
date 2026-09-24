import logging
from typing import List, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from jose import JWTError
from jose.exceptions import JWTClaimsError
from jwt import ExpiredSignatureError
from starlette import status

from pecha_api.config import get
from pecha_api.auth.auth_repository import validate_token
from pecha_api.db.database import SessionLocal
from pecha_api.error_contants import ErrorConstants
from pecha_api.plans.authors.plan_authors_model import Author, AuthorSocialMediaAccount
from pecha_api.plans.authors.plan_authors_repository import get_author_by_id, get_all_authors, \
    update_author, find_author_by_id, find_author_by_user_id
from pecha_api.users.user_resolution import resolve_user_from_payload
import jose

from pecha_api.plans.authors.plan_authors_response_models import AuthorInfoResponse, SocialMediaProfile, \
    AuthorsResponse, AuthorInfoRequest, AuthorUpdateResponse, AuthorPlanDTO, AuthorPlansResponse, \
    ImageUrlModel, AuthorInfoPublicResponse
from pecha_api.plans.plans_response_models import PlansResponse

from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.shared.permissions import build_author_access_context, get_platform_role, require_active_author
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_service import get_social_profile
from pecha_api.plans.shared.utils import convert_plan_model_to_dto
from pecha_api.utils import Utils

from pecha_api.plans.public.plan_repository import get_published_plans_by_author_id


async def get_authors() -> AuthorsResponse:
    with SessionLocal() as db_session:
        authors = get_all_authors(db=db_session)
        authors_response = [AuthorInfoResponse(
            id=author.id,
            firstname=author.first_name,
            lastname=author.last_name,
            email=author.email,
            image_url=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key= author.image_url),
            bio=author.bio,
            social_profiles=_get_author_social_profile(author=author)
        ) for author in authors]
        return AuthorsResponse(
            authors=authors_response,
            skip=0,
            limit=20,
            total=len(authors)
        )

async def get_author_details(token: str) -> AuthorInfoResponse:
    author = validate_and_extract_author_details(token=token)
    social_media_profiles = _get_author_social_profile(author=author)
    with SessionLocal() as db_session:
        access = build_author_access_context(db=db_session, author=author)
    return AuthorInfoResponse(
        id=author.id,
        firstname=author.first_name,
        lastname=author.last_name,
        email=author.email,
        platform_role=access["platform_role"],
        is_verified=access["is_verified"],
        is_active=access["is_active"],
        has_group=access["has_group"],
        can_create_content=access["can_create_content"],
        image_url=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key= author.image_url),
        bio=author.bio,
        social_profiles=social_media_profiles
    )

def update_social_profiles(author: Author, social_profiles: List[SocialMediaProfile]) -> None:
    existing_profiles = {profile.platform_name: profile for profile in author.social_media_accounts}

    for profile_data in social_profiles or []:
        platform = profile_data.account.name
        url = profile_data.url

        if platform in existing_profiles:
            # Update existing profile
            existing_profiles[platform].profile_url = url
        else:
            # Add new profile
            author.social_media_accounts.append(AuthorSocialMediaAccount(
                author_id=author.id,
                platform_name=platform,
                profile_url=url
            ))
    delete_social_profiles(author=author, social_profiles=social_profiles, existing_profiles=existing_profiles)

async def update_author_info(token: str, author_info_request: AuthorInfoRequest) -> AuthorUpdateResponse:
    current_author = validate_and_extract_author_details(token=token)
    current_author.first_name = author_info_request.firstname
    current_author.last_name = author_info_request.lastname
    current_author.bio = author_info_request.bio
    current_author.image_url = Utils.extract_s3_key(presigned_url=author_info_request.image_url)
    with SessionLocal() as db_session:
        try:
            db_session.add(current_author)
            update_social_profiles(author=current_author, social_profiles=author_info_request.social_profiles)
            updated_user = update_author(db=db_session, author=current_author)
            return AuthorUpdateResponse(
                id=updated_user.id,
                firstname=updated_user.first_name,
                lastname=updated_user.last_name,
                email=updated_user.email,
                image_url=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key= updated_user.image_url),
                image_key=updated_user.image_url,
                bio=updated_user.bio
            )
        except Exception as e:
            db_session.rollback()
            logging.error(f"Failed to update user info: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

def get_image_url(image_url: Optional[str]) -> Optional[ImageUrlModel]:
    if not image_url:
        return None
        
    thumbnail_url = image_url.replace("original", "thumbnail")
    medium_url = image_url.replace("original", "medium")
    original_url = image_url
    return ImageUrlModel(
        thumbnail=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=thumbnail_url),
        medium=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=medium_url),
        original=generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=original_url)
    )


def safe_get_image_url(
    image_url: Optional[str], *, resource_id: UUID, resource_type: str
) -> Optional[ImageUrlModel]:
    if not image_url:
        return None
    try:
        return get_image_url(image_url=image_url)
    except Exception:
        logging.exception(
            f"Failed to generate image URLs for {resource_type} {resource_id}"
        )
        return None


async def get_selected_author_details(author_id: UUID) -> AuthorInfoPublicResponse:
    author = await _get_author_details_by_id(author_id=author_id)
    author_image: Optional[ImageUrlModel] = get_image_url(image_url=author.image_url)
    social_media_profiles = _get_author_social_profile(author=author)
    return AuthorInfoPublicResponse(
        id=author.id,
        firstname=author.first_name,
        lastname=author.last_name,
        email=author.email,
        image=author_image,
        bio=author.bio,
        social_profiles=social_media_profiles
    )

async def get_plans_by_author(author_id: UUID,skip: int, limit: int) -> AuthorPlansResponse:
    await _get_author_details_by_id(author_id=author_id)
    with SessionLocal() as db_session:
        published_plans, total = get_published_plans_by_author_id(db=db_session, author_id=author_id, skip=skip, limit=limit)

        author_plan_dtos = [
            AuthorPlanDTO(
                id=aggregate.plan.id,
                title=aggregate.plan.title,
                description=aggregate.plan.description,
                language=aggregate.plan.language,
                total_days=aggregate.total_days,
                subscription_count=aggregate.subscription_count,
                image=get_image_url(aggregate.plan.image_url),
            )
            for aggregate in published_plans
        ]

        return AuthorPlansResponse(
            plans=author_plan_dtos,
            skip=skip,
            limit=limit,
            total=total,
        )

async def _get_author_details_by_id(author_id: UUID) -> Author:
    with SessionLocal() as db_session:
        author = get_author_by_id(db=db_session,author_id=author_id)
        if author is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ErrorConstants.AUTHOR_NOT_FOUND)
        return author

def _get_author_social_profile(author: Author) -> List[SocialMediaProfile]:
    social_media_profiles = []
    for account in author.social_media_accounts:
        social_media_profile = SocialMediaProfile(
            account=get_social_profile(value=account.platform_name),
            url=account.profile_url
        )
        social_media_profiles.append(social_media_profile)
    return social_media_profiles

def validate_and_extract_author_details(token: str) -> Author:
    try:
        payload = validate_token(token)
        with SessionLocal() as db_session:
            subject = payload.get("sub")
            try:
                author_id = UUID(str(subject)) if subject is not None else None
            except (TypeError, ValueError):
                author_id = None

            author = find_author_by_id(db=db_session, author_id=author_id) if author_id is not None else None
            if author is None:
                # Not a CMS Author token. Resolve the caller as a website
                # User instead - the same identity resolution the group
                # permission check uses (UUID sub, then phone, then email;
                # see groups_service._resolve_permission_caller) - then look
                # up the Author only via the persisted Author.user_id link,
                # never through the token's own email/phone claims directly
                # (see auth_service.create_user's Author collision check for
                # why). This also covers raw, non-exchanged Auth0 tokens
                # whose subject isn't a UUID at all.
                try:
                    user = resolve_user_from_payload(
                        db=db_session,
                        payload=payload,
                        unauthorized_detail=ErrorConstants.TOKEN_ERROR_MESSAGE,
                    )
                    author = find_author_by_user_id(db=db_session, user_id=user.id)
                except HTTPException:
                    author = None
            if author is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=ErrorConstants.TOKEN_ERROR_MESSAGE,
                )
            return author
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


def validate_cms_author_details(token: str) -> Author:
    author = validate_and_extract_author_details(token=token)
    require_active_author(author)
    return author

def delete_social_profiles(author: Author, social_profiles: List[SocialMediaProfile], existing_profiles: Dict[str, SocialMediaProfile]) -> None:
    social_profile_names = [social_profile.account.name for social_profile in social_profiles]
    for profile in existing_profiles.keys():
        if profile not in social_profile_names:
            social_profile_to_delete = existing_profiles[profile]
            author.social_media_accounts.remove(social_profile_to_delete)