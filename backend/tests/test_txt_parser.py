import json

import pytest

from app.services.formatting import build_txt, result_to_json
from app.services.txt_parser import parse_timestamp, parse_txt, txt_to_result


@pytest.mark.parametrize(
    "value,expected",
    [("00:00:05", 5), ("0:05", 5), ("01:02:03", 3723), ("1:02:03.5", 3723.5), ("00:00:01,250", 1.25), ("75:30", 4530)],
)
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["1:99", "00:61:00", "abc", "1"])
def test_parse_timestamp_invalid(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


def test_bracketed_timestamps_roundtrip():
    text = (
        "[00:00:00] Hello everyone, welcome to today's video.\n\n"
        "[00:00:05] Today we are going to discuss artificial intelligence.\n\n"
        "[00:00:12] Let's get started.\n"
    )
    segs, has_ts = parse_txt(text)
    assert has_ts
    assert [(s.id, s.start, s.text) for s in segs] == [
        (1, 0.0, "Hello everyone, welcome to today's video."),
        (2, 5.0, "Today we are going to discuss artificial intelligence."),
        (3, 12.0, "Let's get started."),
    ]
    # End times are not invented.
    assert all(s.end is None and s.duration is None for s in segs)
    # Our own TXT export parses back to the same text/starts.
    again, _ = parse_txt(build_txt(segs, True))
    assert [(s.start, s.text) for s in again] == [(s.start, s.text) for s in segs]


def test_multiline_continuation_and_varied_formats():
    text = "Intro line before any stamp\n(0:01) first\ncontinues here\n00:00:04 - second\n[00:07 - 00:09] ranged\n"
    segs, has_ts = parse_txt(text)
    assert has_ts
    assert segs[0].start is None and segs[0].text == "Intro line before any stamp"
    assert segs[1].start == 1.0 and segs[1].text == "first continues here"
    assert segs[2].start == 4.0 and segs[2].text == "second"
    assert segs[3].start == 7.0 and segs[3].end == 9.0 and segs[3].duration == 2.0


def test_srt_format():
    text = "1\n00:00:01,000 --> 00:00:03,500\nHello\nworld\n\n2\n00:00:04,000 --> 00:00:05,000\nBye\n"
    segs, has_ts = parse_txt(text)
    assert has_ts
    assert [(s.start, s.end, s.text) for s in segs] == [(1.0, 3.5, "Hello world"), (4.0, 5.0, "Bye")]


def test_vtt_format():
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Speaker>Hi there</v>\n"
    segs, _ = parse_txt(text)
    assert [(s.start, s.text) for s in segs] == [(1.0, "Hi there")]


def test_plain_paragraphs_without_timestamps():
    text = "\ufeffFirst paragraph line one\nline two.\r\n\r\nSecond paragraph.\n\n\n\nThird."
    segs, has_ts = parse_txt(text)
    assert not has_ts
    assert [s.text for s in segs] == ["First paragraph line one line two.", "Second paragraph.", "Third."]
    assert all(s.start is None and s.end is None for s in segs)


def test_time_words_in_prose_are_not_timestamps():
    segs, has_ts = parse_txt("We met at 10:30am for coffee.\n\nThen left.")
    assert not has_ts and len(segs) == 2


def test_unicode_and_json_result():
    result = txt_to_result("[00:00:01] 你好，世界\n[00:00:03] Ça va? 😀", title="Mon fichier")
    data = json.loads(result_to_json(result))
    assert data["transcript_source"] == "txt_import"
    assert data["has_timestamps"] is True
    assert data["transcript"][0]["text"] == "你好，世界"
    assert data["full_text"] == "你好，世界 Ça va? 😀"
    assert data["total_segments"] == 2
    assert data["video_id"] is None


def test_large_input_is_linear():
    text = "\n".join(f"[{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}] line {i}" for i in range(50_000))
    segs, _ = parse_txt(text)
    assert len(segs) == 50_000 and segs[-1].start == 49_999


def test_empty_text():
    segs, has_ts = parse_txt("   \n\n  ")
    assert segs == [] and not has_ts
