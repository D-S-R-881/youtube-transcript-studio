from types import SimpleNamespace

import pytest

from app.core.errors import NO_CAPTIONS_MESSAGE, AppError
from app.services import captions


def track(code, generated, translatable=True, translations=()):
    t = SimpleNamespace(
        language_code=code,
        language=code.upper(),
        is_generated=generated,
        is_translatable=translatable,
        translation_languages=[SimpleNamespace(language_code=c, language=c) for c in translations],
    )
    return t


def test_auto_prefers_manual_in_spoken_language():
    tracks = [track("de", False), track("en", True), track("en", False)]
    chosen, tr = captions.select_transcript(tracks, "auto")
    assert chosen.language_code == "en" and not chosen.is_generated and tr is None


def test_auto_falls_back_to_generated_when_no_matching_manual():
    tracks = [track("de", False), track("en", True)]
    chosen, _ = captions.select_transcript(tracks, "auto")
    assert chosen.language_code == "en" and chosen.is_generated


def test_auto_without_generated_uses_first_manual():
    chosen, _ = captions.select_transcript([track("fr", False), track("es", False)], "auto")
    assert chosen.language_code == "fr"


def test_requested_language_prefers_manual_then_regional_match():
    tracks = [track("en", True), track("en-GB", False)]
    chosen, _ = captions.select_transcript(tracks, "en")
    assert chosen.language_code == "en-GB" and not chosen.is_generated
    chosen, _ = captions.select_transcript([track("en-US", False), track("en", True)], "en-US")
    assert chosen.language_code == "en-US" and not chosen.is_generated


def test_translation_used_when_language_missing():
    tracks = [track("en", False, translations=("fr", "hi"))]
    chosen, tr = captions.select_transcript(tracks, "hi")
    assert chosen.language_code == "en" and tr == "hi"


def test_unsupported_language():
    with pytest.raises(AppError) as exc:
        captions.select_transcript([track("en", False, translatable=False)], "zz")
    assert exc.value.code == "unsupported_language"
    assert "en" in exc.value.hint


def test_no_tracks():
    with pytest.raises(AppError) as exc:
        captions.select_transcript([], "auto")
    assert exc.value.code == "no_captions" and exc.value.message == NO_CAPTIONS_MESSAGE


def test_snippets_to_segments_order_end_and_unicode():
    snippets = [
        SimpleNamespace(text="second\nline", start=5.0, duration=2.5),
        SimpleNamespace(text="première ♪", start=0.0, duration=4.0),
        SimpleNamespace(text="   ", start=8.0, duration=1.0),
        {"text": "dict snippet", "start": 9.0, "duration": 1.0},
    ]
    segs = captions.snippets_to_segments(snippets)
    assert [s.text for s in segs] == ["première ♪", "second line", "dict snippet"]
    assert [s.id for s in segs] == [1, 2, 3]
    assert segs[0].end == 4.0 and segs[1].end == 7.5 and segs[1].duration == 2.5


def _exc(name):
    return type(name, (Exception,), {})("boom")


@pytest.mark.parametrize(
    "name,code,status",
    [
        ("TranscriptsDisabled", "captions_disabled", 404),
        ("NoTranscriptFound", "no_captions", 404),
        ("VideoUnavailable", "video_unavailable", 404),
        ("AgeRestricted", "age_restricted", 403),
        ("RequestBlocked", "rate_limited", 429),
        ("IpBlocked", "rate_limited", 429),
        ("YouTubeRequestFailed", "network_error", 502),
        ("SomethingElse", "captions_failed", 502),
    ],
)
def test_exception_mapping(name, code, status):
    err = captions.map_caption_exception(_exc(name))
    assert err.code == code and err.status_code == status


def test_fetch_from_tracks_with_mock_track():
    fetched = SimpleNamespace(
        snippets=[SimpleNamespace(text="hola", start=0.0, duration=1.0)],
        language_code="es",
        language="Spanish",
    )
    t = track("es", False)
    t.fetch = lambda: fetched
    res = captions.fetch_from_tracks([t], "auto")
    assert res.language_code == "es" and res.segments[0].text == "hola" and not res.is_generated


def test_empty_caption_track_is_an_error():
    t = track("en", False)
    t.fetch = lambda: SimpleNamespace(snippets=[], language_code="en", language="English")
    with pytest.raises(AppError) as exc:
        captions.fetch_from_tracks([t], "auto")
    assert exc.value.code == "empty_transcript"
