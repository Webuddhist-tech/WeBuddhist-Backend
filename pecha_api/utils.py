from typing import Optional, List, Union
import hashlib
import io
import logging
from beanie import PydanticObjectId
from fastapi import HTTPException
from bson.errors import InvalidId
from starlette import status
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from .config import get_int
from pecha_api.error_contants import ErrorConstants
from .config import get

from .constants import Constants


class Utils:

    @staticmethod
    def generate_hash_key(payload: List[Union[str, int]]) -> str:
        params_str = "".join(str(param) for param in payload)
        hash_value = hashlib.sha256(params_str.encode()).hexdigest()
        return hash_value

    @staticmethod
    def get_utc_date_time() -> str:
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def time_passed(published_time: int, language: str) -> str:
        try:
            current_time = datetime.now(timezone.utc)
            
            post_time = datetime.strptime(published_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            
            time_difference = current_time - post_time
            if time_difference < timedelta(minutes=1):
                return Utils.get_word_by_language(word='Now', language=language)
            elif time_difference < timedelta(hours=1):
                minutes = int(time_difference.total_seconds() / Constants.MINUTE_IN_SECONDS)
                minute_value = Utils.get_number_by_language(value=minutes, language=language)
                return f"{minute_value} {Utils.get_word_by_language(word='Min', language=language)}"
            elif time_difference < timedelta(days=1):
                hours = int(time_difference.total_seconds() / Constants.HOUR_IN_SECONDS)
                hour_value = Utils.get_number_by_language(value=hours, language=language)
                return f"{hour_value} {Utils.get_word_by_language(word='Hr', language=language)}"
            elif time_difference < timedelta(weeks=1):
                days = int(time_difference.total_seconds() / Constants.DAY_IN_SECONDS)
                days_value = Utils.get_number_by_language(value=days, language=language)
                return f"{days_value} {Utils.get_word_by_language(word='Day', language=language)}"
            elif time_difference.total_seconds() < Constants.MONTH_IN_SECONDS:
                weeks = int(time_difference.total_seconds() / Constants.WEEK_IN_SECONDS)
                weeks_value = Utils.get_number_by_language(value=weeks, language=language)
                return f"{weeks_value} {Utils.get_word_by_language(word='Week', language=language)}"
            elif time_difference.total_seconds() < Constants.YEAR_IN_SECONDS:
                months = int(time_difference.total_seconds() / Constants.MONTH_IN_SECONDS)
                months_value = Utils.get_number_by_language(value=months, language=language)
                return f"{months_value} {Utils.get_word_by_language(word='Month', language=language)}"
            else:
                years = int(time_difference.total_seconds() / Constants.YEAR_IN_SECONDS)
                years_value = Utils.get_number_by_language(value=years, language=language)
                return f"{years_value} {Utils.get_word_by_language(word='Year', language=language)}"
                
        except ValueError as e:
            logging.error(f"Error in time_passed: {e}")
            raise ValueError(f"Invalid datetime format. Expected '%Y-%m-%d %H:%M:%S', got: {published_time}")

    @staticmethod
    def get_word_by_language(word: str, language: str) -> str:
        if language is None:
            language = get("DEFAULT_LANGUAGE")
        return Constants.TIME_PASSED_NOW[word][language]

    @staticmethod
    def get_value_from_dict(values: dict[str, str], language: str):
        value = "" if not isinstance(values, dict) or not values else values.get(language, "")
        return value

    @staticmethod
    def get_parent_id(parent_id: Optional[str]):
        topic_parent_id = None
        if parent_id is not None:
            try:
                topic_parent_id = PydanticObjectId(parent_id)
            except InvalidId as e:
                logging.debug(f"error with id: ${e}")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Parent id")

        return topic_parent_id

    @staticmethod
    def get_number_by_language(value: int, language: str) -> str:
        if not language:
            language = "en"  # default language
        return "".join(
            [Constants.LANGUAGE_NUMBER[language][char] if "0" <= char <= "9" else char for char in str(value)])

    @staticmethod
    def extract_s3_key(presigned_url: str) -> str:
        if not presigned_url:
            return ""
        parsed_url = urlparse(presigned_url)
        # Extract the path and remove the leading '/'
        s3_key = parsed_url.path.lstrip('/')
        if not s3_key:
            return ""
        return s3_key

    @staticmethod
    def _url_host(value: str) -> str:
        """The bare hostname, or "" for an address we refuse to resolve.

        A host is returned only when a browser reads it the same way we do.
        `urlparse` follows RFC 3986, browsers follow the WHATWG rules, and the
        two part company over a backslash: it is an ordinary hostname
        character here but a path separator there, so the authority in
        "https://attacker.test\\@trusted.example/x" is trusted.example to us
        and attacker.test to whoever loads the image. Whitespace and control
        characters split the parsers the same way. A real image address spells
        any of these percent-encoded, so their presence is refused outright
        rather than parsed into a host one side will disagree with.

        Userinfo is the same trick spelled with "@", which both parsers do
        agree on: `urlparse` leaves it in `netloc` together with the port, so
        the host is what follows the last "@" and precedes the ":".
        """
        if any(
            character == "\\" or character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
            for character in value
        ):
            return ""
        netloc = urlparse(value).netloc.lower()
        return netloc.rpartition("@")[2].partition(":")[0]

    @staticmethod
    def is_social_picture_url(value: Optional[str]) -> bool:
        """Whether an https address may be stored verbatim as an avatar.

        Only the identity providers' own image hosts qualify, because that is
        where Auth0's `picture` claim points. Any other address is a third
        party of the submitter's choosing, and storing it would have every
        viewer's browser fetch the avatar from a server outside ours - handing
        whoever runs it the viewers' addresses, and control over what they see.
        """
        if not value or not str(value).strip():
            return False
        reference = str(value).strip()
        if not reference.startswith("https://"):
            return False
        host = Utils._url_host(reference)
        return any(
            host == suffix or host.endswith("." + suffix)
            for suffix in Constants.SOCIAL_PICTURE_HOSTS
        )

    @staticmethod
    def stored_avatar_reference(value: Optional[str]) -> str:
        """What to keep in users.avatar_url.

        A normal path, or a presigned link to our bucket, is the object's key
        in S3. An https address on an identity provider's image host is the
        image itself (Auth0's profile photo) and is kept as given. Anything
        else external is dropped: this value comes straight from whoever is
        editing the profile, and it is served back to everyone who views it.
        """
        if not value or not str(value).strip():
            return ""
        reference = str(value).strip()
        if reference.startswith("https://") or reference.startswith("http://"):
            host = Utils._url_host(reference)
            bucket = (get("AWS_BUCKET_NAME") or "").strip().lower()
            is_s3_link = (
                host == "amazonaws.com"
                or host.endswith(".amazonaws.com")
                or (bucket and bucket in host)
            )
            if is_s3_link:
                return Utils.extract_s3_key(reference)
            if Utils.is_social_picture_url(reference):
                return reference
            return ""
        return reference.lstrip("/")