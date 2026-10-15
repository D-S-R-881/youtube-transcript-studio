"""Strict YouTube URL parsing.

This module is the SSRF boundary of the application: user input is reduced to
an 11-character video ID, and every outbound request is built from that ID
against fixed YouTube hosts. The raw user URL is never fetched.
"""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlsplit

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_URL_LENGTH = 2048

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


class InvalidYouTubeUrl(ValueError):
    pass


@dataclass(frozen=True)
class ParsedYouTubeUrl:
    video_id: str
    # Hint derived from the URL shape only: "video", "short" or "live".
    url_kind: str

    @property
    def canonical_url(self) -> str:
        return canonical_watch_url(self.video_id)


def canonical_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def is_valid_video_id(value: str) -> bool:
    return bool(VIDEO_ID_RE.match(value or ""))


def _path_id(segment: str) -> Optional[str]:
    candidate = segment.split("/")[0]
    return candidate if is_valid_video_id(candidate) else None


def parse_youtube_url(raw: str) -> ParsedYouTubeUrl:
    if not isinstance(raw, str):
        raise InvalidYouTubeUrl("URL must be a string.")
    url = raw.strip()
    if not url:
        raise InvalidYouTubeUrl("Please paste a YouTube URL.")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidYouTubeUrl("URL is too long.")
    if any(ch.isspace() for ch in url) or any(ord(ch) < 32 for ch in url):
        raise InvalidYouTubeUrl("URL contains invalid characters.")

    if "://" not in url:
        url = "https://" + url

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise InvalidYouTubeUrl("Malformed URL.") from exc

    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidYouTubeUrl("Only http(s) YouTube links are supported.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise InvalidYouTubeUrl("URLs with credentials are not allowed.")
    if port not in (None, 80, 443):
        raise InvalidYouTubeUrl("Custom ports are not allowed.")

    host = (parts.hostname or "").lower().rstrip(".")
    path = parts.path or "/"
    query = parse_qs(parts.query)

    if host in _SHORT_HOSTS:
        vid = _path_id(path.lstrip("/"))
        if vid:
            return ParsedYouTubeUrl(vid, "video")
        raise InvalidYouTubeUrl("Could not find a video ID in this youtu.be link.")

    if host not in _YOUTUBE_HOSTS:
        raise InvalidYouTubeUrl("This is not a YouTube URL.")

    if path.rstrip("/") == "/watch":
        values = query.get("v") or []
        if values and is_valid_video_id(values[0]):
            return ParsedYouTubeUrl(values[0], "video")
        raise InvalidYouTubeUrl("This YouTube link has no valid video ID.")

    for prefix, kind in (("/live/", "live"), ("/shorts/", "short"), ("/embed/", "video"), ("/v/", "video"), ("/e/", "video")):
        if path.startswith(prefix):
            vid = _path_id(path[len(prefix):])
            if vid:
                return ParsedYouTubeUrl(vid, kind)
            raise InvalidYouTubeUrl("This YouTube link has no valid video ID.")

    raise InvalidYouTubeUrl(
        "Unsupported YouTube link. Use a video, Shorts or live URL (channel and playlist pages are not supported)."
    )
