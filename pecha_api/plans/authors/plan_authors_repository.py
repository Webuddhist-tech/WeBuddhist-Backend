from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException
from starlette import status
from uuid import UUID
from pecha_api.plans.response_message import (
    AUTHOR_NOT_FOUND,
    AUTHOR_UPDATE_INVALID,
    AUTHOR_ALREADY_EXISTS,
    BAD_REQUEST,
)
from typing import List, Optional
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.authors.plan_authors_model import Author, AuthorSocialMediaAccount


def save_author(db: Session, author: Author):
    try:
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError as e:
        db.rollback()
        print(f"Integrity error: {e.orig}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{e.orig}")

def get_all_authors(db: Session) -> List[Author]:
    # Only active authors belong in the public directory - author_user_link_
    # service can create an inert (is_active=False) Author for anyone with a
    # website account, and those aren't publishable authors until an admin
    # activates them.
    authors = db.query(Author).filter(Author.is_active.is_(True)).all()
    return authors

def get_author_by_email(db: Session, email: str) -> Author:
    author = find_author_by_email(db=db, email=email)
    if author is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AUTHOR_NOT_FOUND)
    return author


def find_author_by_email(db: Session, email: str) -> Optional[Author]:
    return db.query(Author).options(joinedload(Author.social_media_accounts)).filter(
        Author.email == email,
    ).first()


def get_authors_by_emails(db: Session, emails: List[str]) -> List[Author]:
    """Return authors matching any of the given emails. Missing emails are omitted."""
    if not emails:
        return []
    return db.query(Author).filter(Author.email.in_(emails)).all()

def check_author_exists(db: Session, email: str):
    author = db.query(Author).filter(Author.email == email).first()
    if author:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ResponseError(error=BAD_REQUEST, message=AUTHOR_ALREADY_EXISTS).model_dump())


def get_author_by_id(db: Session, author_id: UUID) -> Author:
    author = db.query(Author).options(joinedload(Author.social_media_accounts)).filter(Author.id == author_id).first()
    if author is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AUTHOR_NOT_FOUND)
    return author


def find_author_by_id(db: Session, author_id: UUID) -> Optional[Author]:
    """Return the Author with the given ID, or None if not found."""
    return db.query(Author).options(joinedload(Author.social_media_accounts)).filter(
        Author.id == author_id,
    ).first()


def get_author_by_phone(
    db: Session,
    phone_number: str,
) -> Optional[Author]:
    return db.query(Author).options(joinedload(Author.social_media_accounts)).filter(
        Author.phone_number == phone_number,
    ).first()


def find_author_by_user_id(db: Session, user_id: UUID) -> Optional[Author]:
    """Return the Author linked to the given website User id, or None."""
    return db.query(Author).options(joinedload(Author.social_media_accounts)).filter(
        Author.user_id == user_id,
    ).first()


def link_author_to_user(db: Session, author: Author, user_id: UUID) -> Author:
    try:
        author.user_id = user_id
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is already linked to another author",
        )


def save_phone_author(
    db: Session,
    author: Author,
) -> Author:
    try:
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone identity is already linked to another author",
        )


def save_google_author(
    db: Session,
    author: Author,
) -> Author:
    try:
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already linked to another author",
        )


def link_author_phone(
    db: Session,
    author: Author,
    phone_number: str,
) -> Author:
    try:
        author.phone_number = phone_number
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone identity is already linked to another author",
        )


def update_author(db: Session, author: Author) -> Author:
    try:
        db.add(author)
        db.commit()
        db.refresh(author)
        return author
    except IntegrityError as e:
        db.rollback()
        print(f"Integrity error: {e.orig}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AUTHOR_UPDATE_INVALID)

