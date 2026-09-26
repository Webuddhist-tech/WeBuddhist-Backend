from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import ChatRoomMemberRole
from pecha_api.chat.models import ChatRoomMember
from pecha_api.chat.repository import (
    add_member,
    count_active_members,
    get_active_member,
    get_member,
    list_active_members,
)
from pecha_api.chat.response_models import ChatRoomMemberDTO, ChatRoomMembersResponse
from pecha_api.chat.service import _get_room_or_404, _isoformat, _require_active_member
from pecha_api.db.database import SessionLocal
from pecha_api.plans.groups.groups_repository import (
    is_user_following_group,
    is_user_joined_group,
)
from pecha_api.plans.response_message import FORBIDDEN, NOT_FOUND
from pecha_api.users.users_models import Users


def _build_member_dto(member: ChatRoomMember) -> ChatRoomMemberDTO:
    return ChatRoomMemberDTO(
        user_id=member.user_id,
        email=(member.user.email if member.user else None) or "unknown@example.com",
        firstname=member.user.firstname if member.user else "",
        lastname=member.user.lastname if member.user else None,
        role=member.role,
        joined_at=_isoformat(member.joined_at),
    )


def list_room_members_service(
    room_id: UUID,
    user: Users,
    skip: int = 0,
    limit: int = 20,
) -> ChatRoomMembersResponse:
    with SessionLocal() as db:
        _get_room_or_404(db=db, room_id=room_id)
        _require_active_member(db=db, room_id=room_id, user_id=user.id)

        members, total = list_active_members(db=db, room_id=room_id, skip=skip, limit=limit)
        return ChatRoomMembersResponse(
            members=[_build_member_dto(member) for member in members],
            skip=skip,
            limit=limit,
            total=total,
        )


def add_room_members_service(
    room_id: UUID,
    user: Users,
    user_ids: List[UUID],
) -> ChatRoomMembersResponse:
    with SessionLocal() as db:
        room = _get_room_or_404(db=db, room_id=room_id)

        if room.group_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add members to a private chat",
            )

        caller = _require_active_member(db=db, room_id=room_id, user_id=user.id)
        if caller.role != ChatRoomMemberRole.CREATOR.value:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)

        added_members = []
        for candidate_id in user_ids:
            if candidate_id == user.id:
                continue
            eligible = is_user_joined_group(
                db=db, group_id=room.group_id, user_id=candidate_id
            ) or is_user_following_group(db=db, group_id=room.group_id, user_id=candidate_id)
            if not eligible:
                continue

            existing = get_member(db=db, room_id=room_id, user_id=candidate_id)
            if existing and existing.left_at is None:
                continue
            if existing and existing.left_at is not None:
                existing.left_at = None
                db.commit()
                db.refresh(existing)
                added_members.append(existing)
                continue

            added_members.append(
                add_member(
                    db=db,
                    member=ChatRoomMember(
                        room_id=room_id,
                        user_id=candidate_id,
                        role=ChatRoomMemberRole.MEMBER.value,
                    ),
                )
            )

        members, total = list_active_members(db=db, room_id=room_id, skip=0, limit=1000)
        return ChatRoomMembersResponse(
            members=[_build_member_dto(member) for member in members],
            skip=0,
            limit=1000,
            total=total,
        )


def remove_room_member_service(room_id: UUID, user: Users, target_user_id: UUID) -> None:
    with SessionLocal() as db:
        room = _get_room_or_404(db=db, room_id=room_id)
        caller = _require_active_member(db=db, room_id=room_id, user_id=user.id)

        target_member = get_active_member(db=db, room_id=room_id, user_id=target_user_id)
        if not target_member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)

        is_self_leave = target_user_id == user.id
        if not is_self_leave and caller.role != ChatRoomMemberRole.CREATOR.value:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN)

        if target_member.role == ChatRoomMemberRole.CREATOR.value:
            other_active_count = count_active_members(db=db, room_id=room_id) - 1
            if other_active_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Creator must remove all other members (or delete the room) before leaving",
                )

        target_member.left_at = datetime.now(timezone.utc)
        db.commit()
