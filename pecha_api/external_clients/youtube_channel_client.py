"""Find a YouTube channel's live streams through the Data API v3.

Mirrors what Studio's "Choose from group channel" picker does in the browser.
It reads the channel's uploads playlist instead of `search?eventType=live`,
because a search call costs 100 quota units and this path costs about 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Literal, Optional
from urllib.parse import unquote, urlparse

import httpx

from pecha_api import config

logger = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/youtube/v3"
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_VIDEO_IDS_PER_REQUEST = 50
_NON_CHANNEL_PATHS = {"watch", "playlist", "shorts", "live", "embed", "results"}

LiveStatus = Literal["live", "upcoming", "completed"]


class YoutubeChannelError(Exception):
    """The channel could not be resolved or the API refused the request."""


@dataclass(frozen=True)
class YoutubeChannelRef:
    kind: Literal["id", "handle", "username", "custom"]
    value: str


@dataclass(frozen=True)
class YoutubeLiveVideo:
    id: str
    title: str
    url: str
    status: LiveStatus


def parse_channel_url(raw: str) -> Optional[YoutubeChannelRef]:
    """`/channel/UC…`, `/@handle`, `/user/…`, `/c/…` or a bare `/<custom>`.
    Video, playlist and other non-channel URLs return None."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return None
    if not trimmed.lower().startswith(("http://", "https://")):
        trimmed = f"https://{trimmed}"
    try:
        parsed = urlparse(trimmed)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if not parts:
        return None
    first = parts[0]
    second = parts[1] if len(parts) > 1 else None

    if first.startswith("@"):
        return YoutubeChannelRef("handle", first)
    if first == "channel" and second:
        return YoutubeChannelRef("id", second)
    if first == "user" and second:
        return YoutubeChannelRef("username", second)
    if first == "c" and second:
        return YoutubeChannelRef("custom", second)
    if first in _NON_CHANNEL_PATHS:
        return None
    return YoutubeChannelRef("custom", first)


def find_group_channel_url(social_links: Iterable[object]) -> Optional[str]:
    """The group's YouTube social link that names a channel. A link to a
    single video has no streams to look through, so it counts as none."""
    for link in social_links or []:
        platform = (getattr(link, "platform", "") or "").strip().lower()
        url = getattr(link, "url", None)
        if platform == "youtube" and url and parse_channel_url(url) is not None:
            return url
    return None


def _api_key() -> str:
    key = (config.get("YOUTUBE_API_KEY") or "").strip()
    if not key:
        raise YoutubeChannelError("YOUTUBE_API_KEY is not configured")
    return key


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    try:
        response = client.get(
            f"{_API_BASE}/{path}", params={**params, "key": _api_key()}
        )
        payload = response.json() if response.content else {}
    except httpx.HTTPError as error:
        raise YoutubeChannelError(f"YouTube request failed: {type(error).__name__}") from error
    except ValueError as error:
        raise YoutubeChannelError("YouTube returned a non-JSON response") from error
    if response.status_code >= 400 or payload.get("error"):
        message = (payload.get("error") or {}).get("message") or response.reason_phrase
        raise YoutubeChannelError(f"YouTube API error: {message}")
    return payload


def _uploads_playlist_id(client: httpx.Client, ref: YoutubeChannelRef) -> str:
    # A channel id UCxxxx has its uploads in the playlist UUxxxx, so no lookup.
    if ref.kind == "id" and ref.value.startswith("UC"):
        return "UU" + ref.value[2:]

    if ref.kind == "id":
        lookup = {"id": ref.value}
    elif ref.kind == "handle":
        lookup = {"forHandle": ref.value}
    elif ref.kind == "username":
        lookup = {"forUsername": ref.value}
    else:
        # Legacy custom URLs have no direct lookup; YouTube turned them into
        # handles of the same name. A channel search is deliberately not
        # tried: its top hit can be an unrelated channel, and this would then
        # copy someone else's streams onto the group's events.
        lookup = {"forHandle": f"@{ref.value}"}

    payload = _get(client, "channels", {"part": "contentDetails", **lookup})
    items = payload.get("items") or []
    uploads = (
        (items[0].get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
        if items
        else None
    )
    if not uploads:
        raise YoutubeChannelError("YouTube channel not found")
    return uploads


def fetch_channel_live_videos(
    channel_url: str, max_uploads: int = 50
) -> List[YoutubeLiveVideo]:
    """Live streams (live now, upcoming and finished) among the channel's most
    recent uploads, newest first."""
    ref = parse_channel_url(channel_url)
    if ref is None:
        raise YoutubeChannelError("The YouTube link is not a channel URL")

    with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        playlist_id = _uploads_playlist_id(client, ref)
        playlist = _get(
            client,
            "playlistItems",
            {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": str(min(max(max_uploads, 1), _MAX_VIDEO_IDS_PER_REQUEST)),
            },
        )
        ids = [
            (item.get("contentDetails") or {}).get("videoId")
            for item in playlist.get("items") or []
        ]
        ids = [video_id for video_id in ids if video_id]
        if not ids:
            return []

        videos = _get(
            client,
            "videos",
            {"part": "snippet,liveStreamingDetails", "id": ",".join(ids)},
        )

    result: List[YoutubeLiveVideo] = []
    for item in videos.get("items") or []:
        if not item.get("liveStreamingDetails"):
            continue
        snippet = item.get("snippet") or {}
        broadcast = snippet.get("liveBroadcastContent")
        status: LiveStatus = (
            "live" if broadcast == "live" else "upcoming" if broadcast == "upcoming" else "completed"
        )
        video_id = item["id"]
        result.append(
            YoutubeLiveVideo(
                id=video_id,
                title=snippet.get("title") or video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                status=status,
            )
        )
    return result
