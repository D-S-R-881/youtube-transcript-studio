import json

import pytest

from app.schemas import TranscriptResult
from app.services.formatting import (
    build_full_text,
    build_txt,
    format_timestamp,
    make_segment,
    result_to_json,
    safe_filename,
    sort_and_clean,
)


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "00:00:00"), (5.9, "00:00:05"), (65, "00:01:05"), (3599.99, "00:59:59"), (3600, "01:00:00"),
     (36000 + 61, "10:01:01"), (None, "00:00:00"), (-3, "00:00:00"), (float("nan"), "00:00:00")],
)
def test_format_timestamp(seconds, expected):
    assert format_timestamp(seconds) == expected


def test_make_segment_numeric_times_and_duration():
    seg = make_segment(1, 1.23456, 5.0, "  Hello \n world  ")
    assert seg.start == 1.235 and seg.end == 5.0 and seg.duration == 3.765
    assert seg.text == "Hello world"
    assert isinstance(seg.start, float)


def test_make_segment_end_before_start_is_clamped():
    seg = make_segment(1, 5.0, 4.0, "x")
    assert seg.end == 5.0 and seg.duration == 0.0


def test_sort_and_clean_orders_and_renumbers():
    segs = [make_segment(1, 10, 12, "c"), make_segment(2, 0, 2, "a"), make_segment(3, 5, 6, "  "), make_segment(4, 3, 4, "b")]
    out = sort_and_clean(segs)
    assert [s.text for s in out] == ["a", "b", "c"]
    assert [s.id for s in out] == [1, 2, 3]


def _sample():
    return [
        make_segment(1, 0.0, 4.5, "Hello everyone, welcome to today's video."),
        make_segment(2, 5.0, 11.0, "Today we are going to discuss artificial intelligence."),
        make_segment(3, 12.0, 15.0, "Let's get started."),
    ]


def test_build_txt_with_timestamps():
    txt = build_txt(_sample(), include_timestamps=True)
    assert txt == (
        "[00:00:00] Hello everyone, welcome to today's video.\n\n"
        "[00:00:05] Today we are going to discuss artificial intelligence.\n\n"
        "[00:00:12] Let's get started.\n"
    )


def test_build_txt_without_timestamps_paragraphs_on_gaps():
    segs = [make_segment(1, 0, 2, "One."), make_segment(2, 2.2, 3, "Two."), make_segment(3, 10, 11, "Three.")]
    assert build_txt(segs, include_timestamps=False) == "One. Two.\n\nThree.\n"


def test_build_txt_empty():
    assert build_txt([], True) == ""


def test_unicode_preserved_in_txt_and_json():
    segs = [
        make_segment(1, 0, 1, "こんにちは世界"),
        make_segment(2, 1, 2, "Привет, мир"),
        make_segment(3, 2, 3, "مرحبا بالعالم"),
        make_segment(4, 3, 4, "नमस्ते 🌍 ♪"),
    ]
    txt = build_txt(segs, True)
    assert "こんにちは世界" in txt and "🌍" in txt
    result = TranscriptResult(
        transcript_source="youtube_captions", transcript=segs, full_text=build_full_text(segs),
        total_segments=len(segs), generated_at="2026-01-01T00:00:00Z",
    )
    raw = result_to_json(result)
    assert "こんにちは世界" in raw  # not \u-escaped
    parsed = json.loads(raw)
    assert parsed["transcript"][3]["text"] == "नमस्ते 🌍 ♪"
    assert raw.encode("utf-8").decode("utf-8") == raw


def test_json_schema_shape_and_numeric_times():
    segs = _sample()
    result = TranscriptResult(
        video_id="VIDEO_ID", video_url="https://www.youtube.com/watch?v=VIDEO_ID", title=None, channel=None,
        video_type="regular", language="en", transcript_source="youtube_captions", is_live=False,
        duration_seconds=None, transcript=segs, full_text=build_full_text(segs), total_segments=3,
        generated_at="2026-01-01T00:00:00Z",
    )
    data = json.loads(result_to_json(result))
    for key in ("video_id", "video_url", "title", "channel", "video_type", "language", "transcript_source",
                "is_live", "duration_seconds", "transcript", "full_text", "total_segments"):
        assert key in data
    assert data["title"] is None and data["duration_seconds"] is None
    assert data["transcript"][1] == {"id": 2, "start": 5.0, "end": 11.0, "duration": 6.0,
                                     "text": "Today we are going to discuss artificial intelligence."}
    assert data["full_text"].startswith("Hello everyone, welcome to today's video. Today")
    assert data["total_segments"] == len(data["transcript"])


@pytest.mark.parametrize(
    "vid,live,ext,expected",
    [
        ("dQw4w9WgXcQ", False, "txt", "youtube_transcript_dQw4w9WgXcQ.txt"),
        ("dQw4w9WgXcQ", True, "json", "youtube_live_transcript_dQw4w9WgXcQ.json"),
        ("../../etc/passwd", False, "txt", "youtube_transcript_etcpasswd.txt"),
        (None, False, "json", "youtube_transcript_transcript.json"),
        ('a"b\r\nc', False, "t/x\"t", "youtube_transcript_abc.txt"),
    ],
)
def test_safe_filename(vid, live, ext, expected):
    assert safe_filename(vid, live, ext) == expected


def test_export_filename_uses_title_for_uploads():
    from app.schemas import TranscriptResult
    from app.services.formatting import export_filename

    def res(**kw):
        return TranscriptResult(transcript_source="uploaded_file_stt", transcript=[], full_text="",
                                total_segments=0, generated_at="2026-01-01T00:00:00Z", **kw)

    assert export_filename(res(title="My Talk (final).mp4"), False, "txt") == "transcript_My_Talk_final_mp4.txt"
    assert export_filename(res(title="../../"), False, "json") == "transcript_file.json"
    assert export_filename(res(video_id="dQw4w9WgXcQ", title="x"), True, "txt") == "youtube_live_transcript_dQw4w9WgXcQ.txt"
