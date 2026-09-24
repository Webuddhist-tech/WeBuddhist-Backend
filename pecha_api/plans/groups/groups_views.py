from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from pecha_api.chat.service import close_group_chat_sockets
from pecha_api.plans.groups.groups_enums import (
    AuthorGroupInviteStatus,
    AuthorGroupJoinRequestStatus,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.groups.groups_response_models import (
    AuthorGroupDetailDTO,
    AuthorGroupListResponse,
    CreateAuthorGroupRequest,
    CreateGroupInviteRequest,
    CreateGroupJoinRequest,
    GroupAccumulationsResponse,
    GroupBanDTO,
    GroupBanListResponse,
    GroupInviteCreatedResponse,
    GroupInviteDTO,
    GroupInviteListResponse,
    GroupJoinedUsersListResponse,
    GroupJoinRequestDTO,
    GroupJoinRequestListResponse,
    GroupMemberAccumulationsResponse,
    GroupPermissionDTO,
    GroupPracticesFeedResponse,
    GroupPracticesResponse,
    PublicAuthorGroupDetailDTO,
    PublicAuthorGroupListResponse,
    RemoveGroupUserRequest,
    ReplaceGroupSocialLinksRequest,
    ReplaceGroupTagsRequest,
    UpdateAuthorGroupRequest,
    UpdateAuthorGroupStatusRequest,
    TransferGroupOwnershipRequest,
    UpdateGroupMemberRoleRequest,
    UserFollowedAuthorGroupDTO,
    UserFollowedAuthorGroupListResponse,
    UserJoinedAuthorGroupDTO,
    UserJoinedAuthorGroupListResponse,
    AuthorGroupMemberProfileDTO,
    AuthorGroupMembersListResponse,
)
from pecha_api.plans.groups.groups_service import (
    accept_group_invite_by_id,
    approve_group_join_request,
    create_author_group,
    create_group_member_invite,
    delete_author_group,
    delete_group_member,
    follow_group,
    get_author_group_detail,
    get_cms_group_detail,
    get_followed_group,
    get_group_accumulations,
    get_group_member_accumulations,
    get_group_permission,
    get_group_practices,
    get_group_practices_feed,
    get_joined_group,
    join_group,
    leave_group,
    lift_group_ban_by_id,
    list_cms_group_joined_users,
    list_cms_groups,
    list_followed_groups,
    list_group_bans,
    list_joined_groups,
    list_group_members,
    list_group_invites,
    list_group_join_requests,
    list_my_pending_group_invites,
    list_public_groups,
    reject_group_invite_by_id,
    reject_group_join_request,
    remove_and_ban_group_user,
    submit_group_join_request,
    replace_group_social_links_by_id,
    replace_group_tags,
    revoke_group_invite,
    unfollow_group,
    update_author_group,
    update_group_status,
    transfer_group_ownership,
    update_group_member_role,
)

oauth2_scheme = HTTPBearer()
optional_oauth2_scheme = HTTPBearer(auto_error=False)

cms_groups_router = APIRouter(prefix="/cms/author/groups", tags=["CMS Author Groups"])
_LANGUAGE_QUERY_DESCRIPTION = (
    "Render group metadata in this language; falls back to English (en) per group when missing. "
    "All groups are returned regardless of available metadata languages."
)
public_groups_router = APIRouter(prefix="/author/groups", tags=["Public Author Groups"])
user_groups_router = APIRouter(
    prefix="/users/me/following/author/groups",
    tags=["User Author Groups"],
)
user_joined_groups_router = APIRouter(
    prefix="/users/me/joined/author/groups",
    tags=["User Author Groups"],
)
user_permission_router = APIRouter(
    prefix="/users/me/permission",
    tags=["User Group Permission"],
)


@cms_groups_router.post("", status_code=status.HTTP_201_CREATED, response_model=AuthorGroupDetailDTO)
def post_cms_group(
    create_group_request: CreateAuthorGroupRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return create_author_group(
        token=authentication_credential.credentials,
        request=create_group_request,
    )


def _update_cms_group(
    group_id: UUID,
    update_group_request: UpdateAuthorGroupRequest,
    token: str,
) -> AuthorGroupDetailDTO:
    return update_author_group(
        token=token,
        group_id=group_id,
        request=update_group_request,
    )


@cms_groups_router.put("/{group_id}", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def put_cms_group(
    group_id: UUID,
    update_group_request: UpdateAuthorGroupRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return _update_cms_group(
        group_id=group_id,
        update_group_request=update_group_request,
        token=authentication_credential.credentials,
    )


@cms_groups_router.patch("/{group_id}", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def patch_cms_group(
    group_id: UUID,
    update_group_request: UpdateAuthorGroupRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return _update_cms_group(
        group_id=group_id,
        update_group_request=update_group_request,
        token=authentication_credential.credentials,
    )


@cms_groups_router.patch(
    "/{group_id}/status",
    status_code=status.HTTP_200_OK,
    response_model=AuthorGroupDetailDTO,
)
async def patch_cms_group_status(
    group_id: UUID,
    update_group_status_request: UpdateAuthorGroupStatusRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> AuthorGroupDetailDTO:
    """Publish a group or hide it again. OWNER and ADMIN only.

    Only PUBLISHED groups appear on the app side, independent of is_public.
    """
    detail = update_group_status(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=update_group_status_request,
    )
    if detail.status != AuthorGroupStatus.PUBLISHED:
        await close_group_chat_sockets(group_id=group_id)
    return detail


@cms_groups_router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cms_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    delete_author_group(
        token=authentication_credential.credentials,
        group_id=group_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cms_groups_router.get(
    "/invites/me",
    status_code=status.HTTP_200_OK,
    response_model=GroupInviteListResponse,
)
def get_my_pending_group_invites(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return list_my_pending_group_invites(token=authentication_credential.credentials)


@cms_groups_router.get("/{group_id}", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def get_cms_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[Optional[str], Query(description=language_query_description("Filter group metadata by language", lowercase_example=True))] = None,
):
    return get_cms_group_detail(
        token=authentication_credential.credentials,
        group_id=group_id,
        language=language,
    )


@cms_groups_router.get("", status_code=status.HTTP_200_OK, response_model=AuthorGroupListResponse)
def get_cms_groups(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    search: Annotated[Optional[str], Query()] = None,
    language: Annotated[Optional[str], Query()] = None,
    tag_id: Annotated[Optional[UUID], Query()] = None,
    is_public: Annotated[Optional[bool], Query(description="Filter by public visibility; omit to include all groups")] = None,
    group_type: Annotated[Optional[AuthorGroupType], Query(description="Filter by group type: PAGE or COMMUNITY")] = None,
    group_status: Annotated[
        Optional[AuthorGroupStatus],
        Query(
            alias="status",
            description="Filter by publication status: DRAFT, PUBLISHED or UNPUBLISHED; omit to include all",
        ),
    ] = None,
    for_transfer: Annotated[bool, Query(description="When true, list all groups for transfer target selection")] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return list_cms_groups(
        token=authentication_credential.credentials,
        search=search,
        language=language,
        tag_id=tag_id,
        is_public=is_public,
        group_type=group_type,
        group_status=group_status,
        for_transfer=for_transfer,
        skip=skip,
        limit=limit,
    )


@cms_groups_router.put("/{group_id}/tags", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def put_cms_group_tags(
    group_id: UUID,
    request: ReplaceGroupTagsRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return replace_group_tags(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@cms_groups_router.put("/{group_id}/social-links", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def put_cms_group_social_links(
    group_id: UUID,
    request: ReplaceGroupSocialLinksRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return replace_group_social_links_by_id(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@cms_groups_router.post("/{group_id}/members/invites", status_code=status.HTTP_201_CREATED, response_model=GroupInviteCreatedResponse)
def post_cms_group_invite(
    group_id: UUID,
    request: CreateGroupInviteRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return create_group_member_invite(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@cms_groups_router.get(
    "/{group_id}/members/invites",
    status_code=status.HTTP_200_OK,
    response_model=GroupInviteListResponse,
)
def get_cms_group_invites(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    status_filter: Annotated[Optional[AuthorGroupInviteStatus], Query(alias="status")] = None,
):
    return list_group_invites(
        token=authentication_credential.credentials,
        group_id=group_id,
        status_filter=status_filter,
    )


@cms_groups_router.post(
    "/invites/{invite_id}/accept",
    status_code=status.HTTP_200_OK,
    response_model=AuthorGroupDetailDTO,
)
def post_accept_group_invite_by_id(
    invite_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return accept_group_invite_by_id(
        token=authentication_credential.credentials,
        invite_id=invite_id,
    )


@cms_groups_router.post(
    "/invites/{invite_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=GroupInviteDTO,
)
def post_reject_group_invite_by_id(
    invite_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return reject_group_invite_by_id(
        token=authentication_credential.credentials,
        invite_id=invite_id,
    )


@cms_groups_router.get(
    "/{group_id}/join-requests",
    status_code=status.HTTP_200_OK,
    response_model=GroupJoinRequestListResponse,
)
def get_cms_group_join_requests(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    status_filter: Annotated[
        Optional[AuthorGroupJoinRequestStatus],
        Query(alias="status", description="Filter by request status; defaults to PENDING"),
    ] = AuthorGroupJoinRequestStatus.PENDING,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return list_group_join_requests(
        token=authentication_credential.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
    )


@cms_groups_router.post(
    "/{group_id}/join-requests/{request_id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=GroupJoinRequestDTO,
)
def post_cms_approve_group_join_request(
    group_id: UUID,
    request_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return approve_group_join_request(
        token=authentication_credential.credentials,
        group_id=group_id,
        request_id=request_id,
    )


@cms_groups_router.post(
    "/{group_id}/join-requests/{request_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=GroupJoinRequestDTO,
)
def post_cms_reject_group_join_request(
    group_id: UUID,
    request_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return reject_group_join_request(
        token=authentication_credential.credentials,
        group_id=group_id,
        request_id=request_id,
    )


@cms_groups_router.get(
    "/{group_id}/joined-users",
    status_code=status.HTTP_200_OK,
    response_model=GroupJoinedUsersListResponse,
)
def get_cms_group_joined_users(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GroupJoinedUsersListResponse:
    """Community users who joined this group, newest first.

    Distinct from `/members`, which lists the group's staff authors and roles.
    """
    return list_cms_group_joined_users(
        token=authentication_credential.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
    )


# POST rather than DELETE: the call carries a body (ban length and reason).
@cms_groups_router.post(
    "/{group_id}/joined-users/{user_id}/remove",
    status_code=status.HTTP_200_OK,
    response_model=GroupBanDTO,
)
def post_cms_remove_group_joined_user(
    group_id: UUID,
    user_id: UUID,
    request: RemoveGroupUserRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> GroupBanDTO:
    """Remove a joined user and block them from rejoining for `ban_duration_days`."""
    return remove_and_ban_group_user(
        token=authentication_credential.credentials,
        group_id=group_id,
        user_id=user_id,
        request=request,
    )


@cms_groups_router.get(
    "/{group_id}/bans",
    status_code=status.HTTP_200_OK,
    response_model=GroupBanListResponse,
)
def get_cms_group_bans(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    active_only: Annotated[
        bool,
        Query(description="When false, also returns expired and lifted bans as a history."),
    ] = True,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GroupBanListResponse:
    return list_group_bans(
        token=authentication_credential.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
        active_only=active_only,
    )


@cms_groups_router.post(
    "/{group_id}/bans/{ban_id}/lift",
    status_code=status.HTTP_200_OK,
    response_model=GroupBanDTO,
)
def post_cms_lift_group_ban(
    group_id: UUID,
    ban_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> GroupBanDTO:
    """End a ban early. The user may rejoin, but is not re-added automatically."""
    return lift_group_ban_by_id(
        token=authentication_credential.credentials,
        group_id=group_id,
        ban_id=ban_id,
    )


@cms_groups_router.post("/{group_id}/members/invites/{invite_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def post_revoke_group_invite(
    group_id: UUID,
    invite_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    revoke_group_invite(
        token=authentication_credential.credentials,
        group_id=group_id,
        invite_id=invite_id,
    )
    return None


@cms_groups_router.post(
    "/{group_id}/transfer-ownership",
    status_code=status.HTTP_200_OK,
    response_model=AuthorGroupDetailDTO,
)
def post_transfer_group_ownership(
    group_id: UUID,
    request: TransferGroupOwnershipRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return transfer_group_ownership(
        token=authentication_credential.credentials,
        group_id=group_id,
        new_owner_author_id=request.new_owner_author_id,
    )


@cms_groups_router.patch("/{group_id}/members/{author_id}/role", status_code=status.HTTP_200_OK, response_model=AuthorGroupDetailDTO)
def patch_group_member_role(
    group_id: UUID,
    author_id: UUID,
    request: UpdateGroupMemberRoleRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return update_group_member_role(
        token=authentication_credential.credentials,
        group_id=group_id,
        author_id=author_id,
        request=request,
    )


@cms_groups_router.delete("/{group_id}/members/{author_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group_member_by_id(
    group_id: UUID,
    author_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    delete_group_member(
        token=authentication_credential.credentials,
        group_id=group_id,
        author_id=author_id,
    )
    return None


# NOTE: must be registered before the "/{group_id}" routes so the literal
# "practices" path segment is not captured as a group_id.
@public_groups_router.get(
    "/practices",
    status_code=status.HTTP_200_OK,
    response_model=GroupPracticesFeedResponse,
)
def get_group_practices_feed_endpoint(
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    group_id: Annotated[Optional[UUID], Query(description="Filter practices to a single group")] = None,
    should_include_unfollowed: Annotated[
        bool,
        Query(
            alias="include_unfollowed",
            description=(
                "false = practices from joined groups only; "
                "true = practices from all public groups. "
                "Guests always see public groups."
            ),
        ),
    ] = False,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted practices are hidden for Chinese timezones."),
    ] = None,
):
    """Merged feed of practices (series, group accumulators, plans not in a
    series, and recitation collections) across author groups, sorted newest
    first.

    Optional auth. Guests see published public groups. Logged-in users default
    to groups they joined; pass ``include_unfollowed=true`` to include all
    public groups.
    """
    return get_group_practices_feed(
        token=authentication_credential.credentials if authentication_credential else None,
        group_id=group_id,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        language=language,
        timezone_name=x_timezone,
    )


@public_groups_router.get("/{group_id}", status_code=status.HTTP_200_OK, response_model=PublicAuthorGroupDetailDTO)
def get_public_group(
    group_id: UUID,
    response: Response,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
):
    response.headers["Cache-Control"] = "no-store"
    return get_author_group_detail(
        group_id=group_id,
        language=language,
        token=authentication_credential.credentials if authentication_credential else None,
    )


@public_groups_router.get(
    "/{group_id}/practices",
    status_code=status.HTTP_200_OK,
    response_model=GroupPracticesResponse,
)
async def get_public_group_practices(
    group_id: UUID,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted practices are hidden for Chinese timezones."),
    ] = None,
):
    """List a public group's practices (series, accumulators, and collections) as a single merged, sorted feed of cards."""
    return await get_group_practices(
        group_id=group_id,
        skip=skip,
        limit=limit,
        language=language,
        token=authentication_credential.credentials if authentication_credential else None,
        timezone_name=x_timezone,
    )


@public_groups_router.get(
    "/{group_id}/members",
    status_code=status.HTTP_200_OK,
    response_model=AuthorGroupMembersListResponse,
)
async def get_public_group_members(
    group_id: UUID,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List a group's members, for both public and private groups.

    Intentionally unauthenticated: the frontend gates who sees the members
    list. See list_group_members for the rationale and its trade-off. The
    optional token only decides whether staff roles are revealed for a
    private group (joiners only).
    """
    return await list_group_members(
        group_id=group_id,
        skip=skip,
        limit=limit,
        token=authentication_credential.credentials if authentication_credential else None,
    )


@public_groups_router.get("", status_code=status.HTTP_200_OK, response_model=PublicAuthorGroupListResponse)
def get_public_groups(
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    search: Annotated[Optional[str], Query()] = None,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
    tag_id: Annotated[Optional[UUID], Query()] = None,
    group_type: Annotated[
        AuthorGroupType,
        Query(description="Filter by group type: PAGE or COMMUNITY"),
    ] = AuthorGroupType.COMMUNITY,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted groups are hidden for Chinese timezones."),
    ] = None,
):
    return list_public_groups(
        search=search,
        language=language,
        tag_id=tag_id,
        group_type=group_type,
        skip=skip,
        limit=limit,
        token=authentication_credential.credentials if authentication_credential else None,
        timezone_name=x_timezone,
    )


@public_groups_router.post("/{group_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def post_follow_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    follow_group(token=authentication_credential.credentials, group_id=group_id)
    return None


@public_groups_router.delete("/{group_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def delete_follow_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    unfollow_group(token=authentication_credential.credentials, group_id=group_id)
    return None


@public_groups_router.post("/{group_id}/join", status_code=status.HTTP_204_NO_CONTENT)
def post_join_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    join_group(token=authentication_credential.credentials, group_id=group_id)
    return None


@public_groups_router.delete("/{group_id}/join", status_code=status.HTTP_204_NO_CONTENT)
def delete_join_group(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    leave_group(token=authentication_credential.credentials, group_id=group_id)
    return None


@public_groups_router.post(
    "/{group_id}/join-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupJoinRequestDTO,
)
def post_group_join_request(
    group_id: UUID,
    request: CreateGroupJoinRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Ask to join a private COMMUNITY group; a Studio moderator reviews it."""
    return submit_group_join_request(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@user_groups_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=UserFollowedAuthorGroupDTO | UserFollowedAuthorGroupListResponse,
)
def get_my_followed_groups(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    group_id: Annotated[Optional[UUID], Query(description="Return this group if the user is following it")] = None,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    if group_id is not None:
        return get_followed_group(
            token=authentication_credential.credentials,
            group_id=group_id,
            language=language,
        )
    return list_followed_groups(
        token=authentication_credential.credentials,
        skip=skip,
        limit=limit,
        language=language,
    )


@user_joined_groups_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=UserJoinedAuthorGroupDTO | UserJoinedAuthorGroupListResponse,
)
def get_my_joined_groups(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    group_id: Annotated[Optional[UUID], Query(description="Return this group if the user has joined it")] = None,
    language: Annotated[Optional[str], Query(description=_LANGUAGE_QUERY_DESCRIPTION)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    if group_id is not None:
        return get_joined_group(
            token=authentication_credential.credentials,
            group_id=group_id,
            language=language,
        )
    return list_joined_groups(
        token=authentication_credential.credentials,
        skip=skip,
        limit=limit,
        language=language,
    )



@public_groups_router.get("/{group_id}/accumulations", status_code=status.HTTP_200_OK, response_model=GroupAccumulationsResponse)
def get_group_accumulations_endpoint(
    group_id: UUID,
    language: Annotated[Optional[str], Query(description=language_query_description("Language code for mantra titles", lowercase_example=True))] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return get_group_accumulations(
        group_id=group_id,
        language=language,
        skip=skip,
        limit=limit,
    )


@public_groups_router.get("/{group_id}/accumulations/{accumulation_id}/members", status_code=status.HTTP_200_OK, response_model=GroupMemberAccumulationsResponse)
def get_group_member_accumulations_endpoint(
    group_id: UUID,
    accumulation_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return get_group_member_accumulations(
        group_id=group_id,
        accumulation_id=accumulation_id,
        skip=skip,
        limit=limit,
    )


@user_permission_router.get(
    "/{group_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupPermissionDTO,
)
def get_my_group_permission(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> GroupPermissionDTO:
    """Check if the authenticated user has CMS permission to manage the specified group.

    Returns permission details including the user's role and whether they can manage the group.
    Never returns 403 - denied users receive has_permission=false instead.
    """
    return get_group_permission(
        token=authentication_credential.credentials,
        group_id=group_id,
    )
