"""Automatic content moderation for chat messages.

Every user-sent chat message (REST or WebSocket) is validated here before it
is stored or broadcast. Messages containing profanity are rejected and a
system-generated moderation report is filed against the sender.
"""
import logging

from better_profanity import profanity
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageReportSource
from pecha_api.chat.models import ChatMessageReport, ChatRoom
from pecha_api.chat.repository import create_report, get_unresolved_automatic_report
from pecha_api.users.users_models import Users

logger = logging.getLogger(__name__)

# `better_profanity`'s bundled wordlist is monolingual English and flags a
# number of words that are ordinary vocabulary for this community. Left in, it
# rejects the message *and* files an automatic report against the sender, so a
# member discussing the precepts is recorded as a content violator.
#
# Each group below is a false positive in this app's context, not a relaxation
# of the standard: genuine profanity is untouched.

# Buddhist doctrine and practice. "kill" is the first precept, "sex" the third,
# "god" and "hell" are unavoidable in doctrine and cosmology, "lust" is a
# klesha, "oral" appears in oral transmission, and "womb" in Tathagatagarbha.
# Inflected forms are separate entries in the wordlist, so each one that
# carries the innocent sense is listed too ("sexual misconduct", "transmitted
# orally", "lusting after"). The "goddamn" family stays blocked.
_DHARMA_TERMS = (
    "god", "hell", "kill", "womb",
    "lust", "lusting",
    "sex", "sexual",
    "oral", "orally",
)

# Fifth-precept discussion, and ordinary household words in their own right
# ("pot" far more often means a cooking pot).
_INTOXICANT_TERMS = ("weed", "hemp", "pot")

# Ordinary names and words in users' own languages. "wang" is Tibetan dbang
# (empowerment) and the surname 王; "dong" is a Vietnamese/Chinese name and the
# currency; "fook" is a romanization of 福, fortune.
_LOANWORDS_AND_NAMES = ("wang", "dong", "fook")

# Neutral self-description. Blocking this auto-reports members for saying who
# they are. Slurs are deliberately not included here.
# "gaylord" and "gaysex" stay blocked.
_IDENTITY_TERMS = ("gay", "gays")

ALLOWED_TERMS = (
    _DHARMA_TERMS + _INTOXICANT_TERMS + _LOANWORDS_AND_NAMES + _IDENTITY_TERMS
)

profanity.load_censor_words(whitelist_words=list(ALLOWED_TERMS))

INAPPROPRIATE_LANGUAGE = "INAPPROPRIATE_LANGUAGE"
INAPPROPRIATE_LANGUAGE_MESSAGE = (
    "Your message contains inappropriate language. Please edit it and try again."
)


def contains_inappropriate_language(message: str) -> bool:
    return profanity.contains_profanity(message)


def validate_message_content(db: Session, room: ChatRoom, user: Users, body: str) -> None:
    """Reject a message containing profanity before it is stored or broadcast.

    Raises HTTPException 400 with an INAPPROPRIATE_LANGUAGE payload and files
    an automatic moderation report against the sender (deduplicated, so a
    retried send of the same rejected message does not create another one).
    """
    if not contains_inappropriate_language(body):
        return

    _create_automatic_report(db=db, room=room, user=user, body=body)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "success": False,
            "code": INAPPROPRIATE_LANGUAGE,
            "message": INAPPROPRIATE_LANGUAGE_MESSAGE,
        },
    )


def _create_automatic_report(db: Session, room: ChatRoom, user: Users, body: str) -> None:
    existing = get_unresolved_automatic_report(
        db=db, room_id=room.id, reported_user_id=user.id, message_text=body
    )
    if existing:
        return

    try:
        create_report(
            db=db,
            report=ChatMessageReport(
                reported_user_id=user.id,
                room_id=room.id,
                source=ChatMessageReportSource.AUTOMATIC.value,
                reason=ChatMessageReportReason.INAPPROPRIATE_LANGUAGE.value,
                message_text=body,
            ),
        )
    except IntegrityError:
        # A concurrent identical submission won the race past the lookup; the
        # partial unique index (uq_chat_message_reports_auto_unresolved)
        # guarantees one open report, which is exactly the state we wanted.
        db.rollback()
        return
    logger.info(
        "Auto-filed inappropriate-language report for user %s in room %s",
        user.id,
        room.id,
    )
