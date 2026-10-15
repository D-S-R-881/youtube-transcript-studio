"""API tests. External YouTube calls are replaced with mocks here only."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.main import create_app
from app.schemas import VideoInfo
from app.services import captions, pipeline
from app.services.captions import CaptionResult
from app.services.formatting import make_segment
from app.services.jobs import store

VID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VID}"


def video_info(video_type="regular", **kw):
    data = dict(video_id=VID, video_url=URL, title="Title", channel="Chan", duration_seconds=15.0,
                video_type=video_type, is_live=video_type == "live", availability="available",
                metadata_source="test")
    data.update(kw)
    return VideoInfo(**data)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def mock_info(monkeypatch):
    holder = {"info": video_info()}

    async def fake_fetch(_client, video_id, url_kind):
        return holder["info"]

    monkeypatch.setattr(pipeline, "fetch_video_info", fake_fetch)
    return holder


def caption_result():
    segs = [make_segment(1, 0.0, 4.5, "Hello everyone, welcome to today's video."),
            make_segment(2, 5.0, 11.0, "Today we are going to discuss artificial intelligence."),
            make_segment(3, 12.0, 15.0, "Let's get started.")]
    return CaptionResult(segments=segs, language_code="en", language_name="English", is_generated=False)


def wait_terminal(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/transcript/{job_id}").json()
        if data["state"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_invalid_url_rejected_before_any_fetch(client):
    r = client.post("/api/transcript", json={"url": "https://evil.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_url"


def test_invalid_language_rejected(client):
    r = client.post("/api/transcript", json={"url": URL, "language": "../../x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_full_caption_job_and_downloads(client, mock_info, monkeypatch):
    monkeypatch.setattr(captions, "list_raw_tracks", lambda vid: ["track"])
    monkeypatch.setattr(captions, "fetch_from_tracks", lambda tracks, lang: caption_result())

    r = client.post("/api/transcript", json={"url": URL + "&feature=share"})
    assert r.status_code == 202
    job = wait_terminal(client, r.json()["job_id"])
    assert job["state"] == "completed"
    assert all(s["status"] == "done" for s in job["stages"])
    res = job["result"]
    assert res["transcript_source"] == "youtube_captions" and res["caption_type"] == "manual"
    assert res["total_segments"] == 3 and res["is_live"] is False and res["language"] == "en"
    assert res["transcript"][0]["start"] == 0.0 and isinstance(res["transcript"][0]["end"], float)

    txt = client.get(f"/api/transcript/{job['job_id']}/download/txt")
    assert txt.status_code == 200
    assert txt.headers["content-type"].startswith("text/plain")
    assert 'filename="youtube_transcript_dQw4w9WgXcQ.txt"' in txt.headers["content-disposition"]
    assert txt.text.startswith("[00:00:00] Hello everyone")
    plain = client.get(f"/api/transcript/{job['job_id']}/download/txt?timestamps=false").text
    assert "[00:" not in plain

    js = client.get(f"/api/transcript/{job['job_id']}/download/json")
    assert 'youtube_transcript_dQw4w9WgXcQ.json' in js.headers["content-disposition"]
    parsed = json.loads(js.content.decode("utf-8"))
    assert parsed["video_id"] == VID and parsed["total_segments"] == 3


def test_events_stream_ends_with_done(client, mock_info, monkeypatch):
    monkeypatch.setattr(captions, "list_raw_tracks", lambda vid: ["track"])
    monkeypatch.setattr(captions, "fetch_from_tracks", lambda tracks, lang: caption_result())
    job_id = client.post("/api/transcript", json={"url": URL}).json()["job_id"]
    wait_terminal(client, job_id)
    with client.stream("GET", f"/api/transcript/{job_id}/events") as r:
        body = "".join(r.iter_text())
    assert "event: status" in body and "event: done" in body


def test_missing_captions_without_stt_fails_clearly(client, mock_info, monkeypatch):
    def raise_no_caps(vid):
        raise AppError("no_captions", captions.NO_CAPTIONS_MESSAGE, 404)

    monkeypatch.setattr(captions, "list_raw_tracks", raise_no_caps)
    job_id = client.post("/api/transcript", json={"url": URL}).json()["job_id"]
    job = wait_terminal(client, job_id)
    assert job["state"] == "failed" and job["result"] is None
    assert job["error"]["message"].startswith("Captions are not available for this video.")
    r = client.get(f"/api/transcript/{job_id}/download/txt")
    assert r.status_code == 409


def test_empty_transcript_is_failure(client, mock_info, monkeypatch):
    monkeypatch.setattr(captions, "list_raw_tracks", lambda vid: ["t"])
    empty = CaptionResult(segments=[make_segment(1, 0, 1, "  ")], language_code="en", language_name="English", is_generated=True)
    monkeypatch.setattr(captions, "fetch_from_tracks", lambda t, l: empty)
    job = wait_terminal(client, client.post("/api/transcript", json={"url": URL}).json()["job_id"])
    assert job["state"] == "failed" and job["error"]["code"] == "empty_transcript"


@pytest.mark.parametrize(
    "info_kwargs,code",
    [
        ({"availability": "private", "video_type": "unavailable"}, "video_private"),
        ({"availability": "deleted", "video_type": "unavailable"}, "video_deleted"),
        ({"video_type": "upcoming", "scheduled_start": "2030-01-01T00:00:00Z"}, "upcoming_livestream"),
    ],
)
def test_unavailable_and_upcoming(client, mock_info, info_kwargs, code):
    mock_info["info"] = video_info(**info_kwargs)
    job = wait_terminal(client, client.post("/api/transcript", json={"url": URL}).json()["job_id"])
    assert job["state"] == "failed" and job["error"]["code"] == code


def test_live_without_supported_source_reports_limitation(client, mock_info, monkeypatch):
    mock_info["info"] = video_info("live", duration_seconds=None)

    def no_caps(vid, lang):
        raise AppError("no_captions", captions.NO_CAPTIONS_MESSAGE, 404)

    monkeypatch.setattr(captions, "fetch_captions_sync", no_caps)
    job = wait_terminal(client, client.post("/api/transcript", json={"url": f"https://www.youtube.com/live/{VID}"}).json()["job_id"])
    assert job["state"] == "failed" and job["kind"] == "live"
    assert job["error"]["message"] == (
        "This livestream is active, but live transcription is not available through the configured sources."
    )


def test_live_caption_session_collects_dedupes_and_stops(client, mock_info, monkeypatch):
    mock_info["info"] = video_info("live", duration_seconds=None, actual_start="2026-01-01T00:00:00Z")
    monkeypatch.setattr(pipeline.get_settings(), "live_caption_poll_seconds", 0.1)
    calls = {"n": 0}

    def growing(vid, lang):
        calls["n"] += 1
        n = min(calls["n"], 4)
        segs = [make_segment(i + 1, i * 2.0, i * 2.0 + 2, f"line {i}") for i in range(n)]
        return CaptionResult(segments=segs, language_code="en", language_name="English", is_generated=True)

    monkeypatch.setattr(captions, "fetch_captions_sync", growing)
    job_id = client.post("/api/transcript", json={"url": f"https://www.youtube.com/live/{VID}"}).json()["job_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        st = client.get(f"/api/transcript/{job_id}").json()
        if st["state"] == "live" and st["segments_count"] >= 4:
            break
        time.sleep(0.05)
    assert st["live"]["mode"] == "captions" and st["live"]["is_live"] is True
    # Partial export available while live.
    partial = client.get(f"/api/live/{job_id}/export/json")
    assert partial.status_code == 200 and "youtube_live_transcript_" in partial.headers["content-disposition"]
    assert json.loads(partial.content)["is_live"] is True

    stopped = client.post(f"/api/live/{job_id}/stop").json()
    final = wait_terminal(client, job_id)
    assert final["state"] == "completed", stopped
    texts = [s["text"] for s in final["result"]["transcript"]]
    assert texts == ["line 0", "line 1", "line 2", "line 3"]
    assert final["result"]["transcript_source"] == "youtube_live_captions"
    assert final["result"]["video_type"] == "live"


def test_cancel_running_job(client, mock_info, monkeypatch):
    gate = threading.Event()

    def slow_list(vid):
        gate.wait(5)
        return ["t"]

    monkeypatch.setattr(captions, "list_raw_tracks", slow_list)
    monkeypatch.setattr(captions, "fetch_from_tracks", lambda t, l: caption_result())
    job_id = client.post("/api/transcript", json={"url": URL}).json()["job_id"]
    time.sleep(0.2)
    r = client.post(f"/api/transcript/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    gate.set()
    time.sleep(0.3)
    final = client.get(f"/api/transcript/{job_id}").json()
    assert final["state"] == "cancelled" and final["result"] is None
    assert client.post(f"/api/transcript/{job_id}/cancel").status_code == 409
    assert client.get(f"/api/transcript/{job_id}/download/json").status_code == 409


def test_expired_job_returns_410(client, mock_info, monkeypatch):
    monkeypatch.setattr(captions, "list_raw_tracks", lambda vid: ["t"])
    monkeypatch.setattr(captions, "fetch_from_tracks", lambda t, l: caption_result())
    job_id = client.post("/api/transcript", json={"url": URL}).json()["job_id"]
    wait_terminal(client, job_id)
    store.get(job_id).updated -= 10 ** 6
    r = client.get(f"/api/transcript/{job_id}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "job_expired"


def test_unknown_job_404(client):
    assert client.get("/api/transcript/" + "0" * 32).status_code == 404
    assert client.get("/api/transcript/../../etc").status_code == 404


def test_convert_txt_json_body(client):
    r = client.post("/api/convert/txt-to-json", json={"text": "[00:00:01] Hi\n[00:00:03] 世界", "title": "t"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_segments"] == 2 and data["transcript"][1]["text"] == "世界" and data["has_timestamps"]


def test_convert_txt_file_upload(client):
    content = "Para one\nwraps.\n\nPara two.".encode("utf-8")
    r = client.post("/api/convert/txt-to-json", files={"file": ("notes.txt", content, "text/plain")})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "notes" and [s["text"] for s in data["transcript"]] == ["Para one wraps.", "Para two."]
    assert data["transcript"][0]["start"] is None


def test_convert_rejects_bad_input(client):
    assert client.post("/api/convert/txt-to-json", json={"text": "   "}).status_code == 422
    assert client.post("/api/convert/txt-to-json", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post("/api/convert/txt-to-json", files={"file": ("x.txt", b"\xff\xfe\x00bad", "text/plain")}).status_code == 415


def test_upload_requires_stt(client, monkeypatch):
    from app.services import stt

    monkeypatch.setattr(stt, "stt_status", lambda: (False, "not installed"))
    r = client.post("/api/transcript/upload", files={"file": ("a.mp3", b"123", "audio/mpeg")})
    assert r.status_code == 503 and r.json()["error"]["code"] == "stt_unavailable"


def test_upload_rejects_oversized_before_reading(client, monkeypatch):
    from app.services import stt

    monkeypatch.setattr(stt, "stt_status", lambda: (True, None))
    huge = str(10 * 1024 * 1024 * 1024)
    r = client.post("/api/transcript/upload", content=b"x", headers={"content-length": huge, "content-type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_cors_allows_configured_origins_only(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CORS_ORIGINS", "https://studio.example.com/, *")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"^https://studio-[a-z0-9]+-team\.vercel\.app$")
    get_settings.cache_clear()
    try:
        assert get_settings().cors_origin_list == ["https://studio.example.com"]
        with TestClient(create_app()) as c:
            def allowed(origin):
                return c.get("/api/health", headers={"Origin": origin}).headers.get("access-control-allow-origin")

            assert allowed("https://studio.example.com") == "https://studio.example.com"
            assert allowed("https://studio-abc123-team.vercel.app") == "https://studio-abc123-team.vercel.app"
            assert allowed("https://evil.example.com") is None
    finally:
        get_settings.cache_clear()


def test_rate_limiter_blocks():
    from app.core.rate_limit import SlidingWindowLimiter

    lim = SlidingWindowLimiter()
    assert all(lim.hit("1.2.3.4", "b", 3) is None for _ in range(3))
    assert lim.hit("1.2.3.4", "b", 3) is not None
    assert lim.hit("5.6.7.8", "b", 3) is None


def test_capabilities(client):
    data = client.get("/api/capabilities").json()
    assert data["captions"] is True and "speech_to_text" in data
