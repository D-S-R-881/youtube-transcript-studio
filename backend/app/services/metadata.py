"""Video metadata + live-status detection.

Order of sources:
1. YouTube Data API v3 (when YOUTUBE_API_KEY is configured) — most reliable.
2. Public watch page player response (ytInitialPlayerResponse).
3. oEmbed (title/channel/thumbnail only).

Every request targets a fixed YouTube host built from a validated video ID.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings
from app.schemas import VideoInfo
from app.services.youtube_url import canonical_watch_url, is_valid_video_id

log = logging.getLogger(__name__)

_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_CONSENT_COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}


def parse_iso8601_duration(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = _ISO_DURATION_RE.match(value)
    if not m:
        return None
    d, h, mi, s = (m.group(k) for k in ("d", "h", "m", "s"))
    total = int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    return float(total)


def default_thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _is_future(iso: Optional[str]) -> bool:
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc)
    except ValueError:
        return False


def _base_type(url_kind: str) -> str:
    return "short" if url_kind == "short" else "regular"


# --------------------------------------------------------------------------- Data API


def info_from_data_api(video_id: str, url_kind: str, payload: Dict[str, Any]) -> VideoInfo:
    items = payload.get("items") or []
    if not items:
        return VideoInfo(
            video_id=video_id,
            video_url=canonical_watch_url(video_id),
            video_type="unavailable",
            availability="unavailable",
            availability_reason="This video is private, deleted, or does not exist.",
            metadata_source="youtube_data_api",
        )
    item = items[0]
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    live = item.get("liveStreamingDetails") or {}
    status = item.get("status") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default") if k in thumbs), None)

    broadcast = snippet.get("liveBroadcastContent")
    if broadcast == "live":
        video_type, live_status, is_live = "live", "live", True
    elif broadcast == "upcoming":
        video_type, live_status, is_live = "upcoming", "upcoming", False
    elif live.get("actualEndTime") or live.get("actualStartTime"):
        video_type, live_status, is_live = "live_replay", "was_live", False
    else:
        video_type, live_status, is_live = _base_type(url_kind), "not_live", False

    availability, reason = "available", None
    if status.get("privacyStatus") == "private":
        availability, reason = "private", "This video is private."
    elif (details.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
        availability, reason = "restricted", "This video is age-restricted."
    elif status.get("uploadStatus") in ("rejected", "deleted", "failed"):
        availability, reason = "deleted", "This video has been removed."

    duration = parse_iso8601_duration(details.get("duration"))
    if is_live or video_type == "upcoming":
        duration = None
    channel_id = snippet.get("channelId")
    return VideoInfo(
        video_id=video_id,
        video_url=canonical_watch_url(video_id),
        title=snippet.get("title"),
        channel=snippet.get("channelTitle"),
        channel_url=f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
        thumbnail_url=thumb or default_thumbnail(video_id),
        duration_seconds=duration or None,
        video_type=video_type,
        is_live=is_live,
        live_status=live_status,
        scheduled_start=live.get("scheduledStartTime"),
        actual_start=live.get("actualStartTime"),
        availability=availability,
        availability_reason=reason,
        metadata_source="youtube_data_api",
    )


# --------------------------------------------------------------------------- Watch page


def extract_player_response(html: str) -> Optional[Dict[str, Any]]:
    marker = "ytInitialPlayerResponse"
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        idx = html.find(marker, pos)
        if idx < 0:
            return None
        brace = html.find("{", idx)
        eq = html.find("=", idx)
        if brace < 0:
            return None
        if eq < 0 or eq > brace:
            pos = idx + len(marker)
            continue
        try:
            obj, _ = decoder.raw_decode(html, brace)
            if isinstance(obj, dict) and ("videoDetails" in obj or "playabilityStatus" in obj):
                return obj
        except ValueError:
            pass
        pos = idx + len(marker)


def info_from_player_response(video_id: str, url_kind: str, pr: Dict[str, Any]) -> VideoInfo:
    vd = pr.get("videoDetails") or {}
    ps = pr.get("playabilityStatus") or {}
    micro = (pr.get("microformat") or {}).get("playerMicroformatRenderer") or {}
    lbd = micro.get("liveBroadcastDetails") or {}

    status = ps.get("status") or "UNKNOWN"
    reason = ps.get("reason") or (ps.get("messages") or [None])[0]
    reason_l = (reason or "").lower()

    is_live = bool(vd.get("isLive") or lbd.get("isLiveNow"))
    is_upcoming = bool(vd.get("isUpcoming")) or status == "LIVE_STREAM_OFFLINE" or _is_future(lbd.get("startTimestamp")) and not lbd.get("endTimestamp") and not is_live
    is_live_content = bool(vd.get("isLiveContent") or lbd)

    availability, avail_reason = "available", None
    if status == "OK":
        pass
    elif status == "LIVE_STREAM_OFFLINE":
        is_upcoming = True
    elif status == "LOGIN_REQUIRED":
        if "private" in reason_l:
            availability, avail_reason = "private", "This video is private."
        elif "age" in reason_l or "inappropriate" in reason_l:
            availability, avail_reason = "restricted", "This video is age-restricted."
        elif "bot" in reason_l:
            availability, avail_reason = "unknown", "YouTube asked this server to sign in (bot check)."
        else:
            availability, avail_reason = "restricted", reason or "Sign-in is required to view this video."
    elif status == "ERROR":
        if any(w in reason_l for w in ("removed", "terminated", "no longer available", "deleted")):
            availability = "deleted"
        else:
            availability = "unavailable"
        avail_reason = reason or "This video is unavailable."
    elif status in ("UNPLAYABLE", "CONTENT_CHECK_REQUIRED", "AGE_CHECK_REQUIRED", "AGE_VERIFICATION_REQUIRED"):
        if is_upcoming:
            pass
        elif "private" in reason_l:
            availability, avail_reason = "private", "This video is private."
        elif "not available" in reason_l or "no longer available" in reason_l:
            availability, avail_reason = "unavailable", reason
        else:
            availability, avail_reason = "restricted", reason or "This video is restricted."
    else:
        availability, avail_reason = "unknown", reason

    if availability in ("deleted", "unavailable", "private"):
        video_type = "unavailable"
        live_status = None
        is_live_flag: Optional[bool] = None
    elif is_live:
        video_type, live_status, is_live_flag = "live", "live", True
    elif is_upcoming:
        video_type, live_status, is_live_flag = "upcoming", "upcoming", False
    elif is_live_content:
        video_type, live_status, is_live_flag = "live_replay", "was_live", False
    else:
        video_type, live_status, is_live_flag = _base_type(url_kind), "not_live", False

    thumbs = ((vd.get("thumbnail") or {}).get("thumbnails")) or []
    thumb = thumbs[-1]["url"] if thumbs and thumbs[-1].get("url") else default_thumbnail(video_id)
    try:
        length = float(vd.get("lengthSeconds") or 0)
    except (TypeError, ValueError):
        length = 0.0
    channel_id = vd.get("channelId")

    return VideoInfo(
        video_id=video_id,
        video_url=canonical_watch_url(video_id),
        title=vd.get("title") or micro.get("title", {}).get("simpleText"),
        channel=vd.get("author") or micro.get("ownerChannelName"),
        channel_url=f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
        thumbnail_url=thumb,
        duration_seconds=length if length > 0 and not is_live else None,
        video_type=video_type,
        is_live=is_live_flag,
        live_status=live_status,
        scheduled_start=lbd.get("startTimestamp") if is_upcoming else None,
        actual_start=lbd.get("startTimestamp") if not is_upcoming else None,
        availability=availability,
        availability_reason=avail_reason,
        metadata_source="youtube_watch_page",
    )


# --------------------------------------------------------------------------- Fetch


async def _fetch_oembed(client: httpx.AsyncClient, video_id: str) -> Optional[Dict[str, Any]]:
    r = await client.get(
        "https://www.youtube.com/oembed",
        params={"url": canonical_watch_url(video_id), "format": "json"},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json()
    return {"_status": r.status_code}


async def fetch_video_info(client: httpx.AsyncClient, video_id: str, url_kind: str) -> VideoInfo:
    if not is_valid_video_id(video_id):
        raise ValueError("invalid video id")
    settings = get_settings()

    if settings.youtube_api_key:
        try:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "id": video_id,
                    "part": "snippet,contentDetails,liveStreamingDetails,status",
                    "key": settings.youtube_api_key,
                },
                timeout=10,
            )
            if r.status_code == 200:
                return info_from_data_api(video_id, url_kind, r.json())
            log.warning("YouTube Data API returned %s", r.status_code)
        except httpx.HTTPError as exc:
            log.warning("YouTube Data API request failed: %s", exc)

    info: Optional[VideoInfo] = None
    try:
        r = await client.get(
            "https://www.youtube.com/watch",
            params={"v": video_id, "hl": "en", "has_verified": "1", "bpctr": "9999999999"},
            headers=_BROWSER_HEADERS,
            cookies=_CONSENT_COOKIES,
            timeout=15,
        )
        if r.status_code == 200:
            pr = extract_player_response(r.text)
            if pr:
                info = info_from_player_response(video_id, url_kind, pr)
    except httpx.HTTPError as exc:
        log.warning("Watch page request failed: %s", exc)

    if info is not None and info.title:
        return info

    try:
        oembed = await _fetch_oembed(client, video_id)
    except httpx.HTTPError:
        oembed = None

    if oembed and "_status" not in oembed:
        base = info or VideoInfo(
            video_id=video_id,
            video_url=canonical_watch_url(video_id),
            video_type="live" if url_kind == "live" else ("short" if url_kind == "short" else "unknown"),
            availability="available",
            metadata_source="oembed",
        )
        return base.model_copy(
            update={
                "title": base.title or oembed.get("title"),
                "channel": base.channel or oembed.get("author_name"),
                "channel_url": base.channel_url or oembed.get("author_url"),
                "thumbnail_url": base.thumbnail_url or oembed.get("thumbnail_url") or default_thumbnail(video_id),
                "metadata_source": base.metadata_source if info else "oembed",
            }
        )

    if info is not None:
        return info

    status = (oembed or {}).get("_status")
    if status in (400, 404):
        return VideoInfo(
            video_id=video_id,
            video_url=canonical_watch_url(video_id),
            video_type="unavailable",
            availability="unavailable",
            availability_reason="This video does not exist or has been removed.",
            metadata_source="oembed",
        )
    if status in (401, 403):
        return VideoInfo(
            video_id=video_id,
            video_url=canonical_watch_url(video_id),
            thumbnail_url=default_thumbnail(video_id),
            video_type="unknown",
            availability="restricted",
            availability_reason="This video is private or restricted.",
            metadata_source="oembed",
        )
    return VideoInfo(
        video_id=video_id,
        video_url=canonical_watch_url(video_id),
        thumbnail_url=default_thumbnail(video_id),
        video_type="unknown",
        availability="unknown",
        availability_reason="Video metadata could not be retrieved right now.",
        metadata_source="none",
    )
