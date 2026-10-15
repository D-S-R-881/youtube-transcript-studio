import json

from app.services.metadata import (
    extract_player_response,
    info_from_data_api,
    info_from_player_response,
    parse_iso8601_duration,
)

VID = "dQw4w9WgXcQ"


def pr(status="OK", reason=None, **vd):
    base = {"title": "T", "author": "C", "lengthSeconds": "120", "channelId": "UC1"}
    base.update(vd)
    out = {"playabilityStatus": {"status": status}, "videoDetails": base}
    if reason:
        out["playabilityStatus"]["reason"] = reason
    return out


def test_extract_player_response_from_html():
    payload = pr()
    html = f"<script>var x = 1;var ytInitialPlayerResponse = {json.dumps(payload)};var meta = {{}};</script>"
    assert extract_player_response(html)["videoDetails"]["title"] == "T"
    assert extract_player_response("<html>nothing</html>") is None


def test_regular_and_short():
    info = info_from_player_response(VID, "video", pr())
    assert info.video_type == "regular" and info.is_live is False and info.duration_seconds == 120
    assert info_from_player_response(VID, "short", pr()).video_type == "short"


def test_active_live():
    info = info_from_player_response(VID, "live", pr(isLive=True, isLiveContent=True, lengthSeconds="0"))
    assert info.video_type == "live" and info.is_live is True and info.live_status == "live"
    assert info.duration_seconds is None


def test_completed_live_replay():
    data = pr(isLiveContent=True)
    data["microformat"] = {"playerMicroformatRenderer": {"liveBroadcastDetails": {
        "isLiveNow": False, "startTimestamp": "2024-01-01T00:00:00+00:00", "endTimestamp": "2024-01-01T02:00:00+00:00"}}}
    info = info_from_player_response(VID, "video", data)
    assert info.video_type == "live_replay" and info.live_status == "was_live" and info.is_live is False


def test_upcoming():
    info = info_from_player_response(VID, "live", pr(status="LIVE_STREAM_OFFLINE", isUpcoming=True, isLiveContent=True))
    assert info.video_type == "upcoming" and info.live_status == "upcoming"


def test_private_deleted_restricted():
    assert info_from_player_response(VID, "video", pr("LOGIN_REQUIRED", "This video is private")).availability == "private"
    deleted = info_from_player_response(VID, "video", pr("ERROR", "This video has been removed by the uploader"))
    assert deleted.availability == "deleted" and deleted.video_type == "unavailable"
    assert info_from_player_response(VID, "video", pr("ERROR", "Video unavailable")).availability == "unavailable"
    age = info_from_player_response(VID, "video", pr("LOGIN_REQUIRED", "Sign in to confirm your age"))
    assert age.availability == "restricted"
    assert info_from_player_response(VID, "video", pr("UNPLAYABLE", "Members only")).availability == "restricted"
    gone = info_from_player_response(VID, "video", pr("UNPLAYABLE", "This live stream recording is not available.", isLiveContent=True))
    assert gone.availability == "unavailable" and gone.video_type == "unavailable"


def test_iso_duration():
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT45S") == 45
    assert parse_iso8601_duration("P1DT1S") == 86401
    assert parse_iso8601_duration("P0D") == 0
    assert parse_iso8601_duration("garbage") is None
    assert parse_iso8601_duration(None) is None


def test_data_api_parsing():
    payload = {"items": [{
        "snippet": {"title": "Live!", "channelTitle": "Ch", "channelId": "UC1", "liveBroadcastContent": "live",
                    "thumbnails": {"high": {"url": "https://i.ytimg.com/x.jpg"}}},
        "contentDetails": {"duration": "P0D"},
        "liveStreamingDetails": {"actualStartTime": "2026-01-01T00:00:00Z"},
        "status": {"privacyStatus": "public"},
    }]}
    info = info_from_data_api(VID, "video", payload)
    assert info.video_type == "live" and info.is_live and info.actual_start == "2026-01-01T00:00:00Z"
    assert info.duration_seconds is None and info.thumbnail_url == "https://i.ytimg.com/x.jpg"

    missing = info_from_data_api(VID, "video", {"items": []})
    assert missing.availability == "unavailable"

    replay = info_from_data_api(VID, "video", {"items": [{
        "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT2H"},
        "liveStreamingDetails": {"actualStartTime": "x", "actualEndTime": "y"}}]})
    assert replay.video_type == "live_replay" and replay.duration_seconds == 7200
