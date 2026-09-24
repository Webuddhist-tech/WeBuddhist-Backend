import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from pecha_api.auth.auth_enums import RegistrationSource
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_repository import (
    find_author_by_email,
    find_author_by_user_id,
    get_author_by_phone,
    link_author_to_user,
    save_author,
)
from pecha_api.users.users_models import Users
from pecha_api.users.users_repository import (
    get_user_by_email_or_none,
    get_user_by_id,
    get_user_by_phone,
    save_user,
)


def link_or_create_author_for_user(db: Session, user: Users) -> Optional[Author]:
    """Ensure `user` has a linked Author record, so CMS/group-permission
    checks that key off Author.user_id resolve for this account: link an
    existing Author sharing the same email/phone, or create one. Call this
    once, right when `user` is created - not on every login. Best-effort:
    failures are logged, never raised, so they can't block signup.
    """
    try:
        existing = find_author_by_user_id(db=db, user_id=user.id)
        if existing is not None:
            return existing

        author = find_author_by_email(db=db, email=user.email) if user.email else None
        if author is None and user.phone_number:
            author = get_author_by_phone(db=db, phone_number=user.phone_number)

        if author is not None:
            if author.user_id is None:
                author = link_author_to_user(db=db, author=author, user_id=user.id)
            return author

        if not user.email and not user.phone_number:
            return None

        new_author = Author(
            first_name=user.firstname,
            last_name=user.lastname or user.firstname,
            email=user.email,
            phone_number=user.phone_number,
            user_id=user.id,
            created_by=user.email or user.phone_number or str(user.id),
        )
        return save_author(db=db, author=new_author)
    except Exception:
        logging.exception(f"Failed to link/create Author for User {user.id}")
        return None


def link_or_create_user_for_author(db: Session, author: Author) -> Optional[Users]:
    """Symmetric counterpart to link_or_create_author_for_user, called once
    when `author` is created."""
    try:
        if author.user_id is not None:
            try:
                return get_user_by_id(db=db, user_id=author.user_id)
            except HTTPException:
                pass

        user = get_user_by_email_or_none(db=db, email=author.email) if author.email else None
        if user is None and author.phone_number:
            user = get_user_by_phone(db=db, phone_number=author.phone_number)

        if user is not None:
            link_author_to_user(db=db, author=author, user_id=user.id)
            return user

        if not author.email and not author.phone_number:
            return None

        new_user = Users(
            email=author.email,
            phone_number=author.phone_number,
            firstname=author.first_name,
            lastname=author.last_name,
            registration_source=(
                RegistrationSource.EMAIL.value if author.email else RegistrationSource.PHONE.value
            ),
            is_active=True,
        )
        saved_user = save_user(db=db, user=new_user)
        link_author_to_user(db=db, author=author, user_id=saved_user.id)
        return saved_user
    except Exception:
        logging.exception(f"Failed to link/create User for Author {author.id}")
        return None
