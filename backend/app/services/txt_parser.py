"""Parse plain-text transcripts into structured segments.

Supported timestamp styles at the start of a line:
  [00:00:05] text        [0:05] text         (00:05) text
  00:00:05 text          00:00:05 - text     [00:00:05.250] text
  [00:00:05 - 00:00:09] text                 00:00:05,000 --> 00:00:09,000  (SRT/VTT cue)
Text without any timestamps is split into paragraphs (blank-line separated);
no timestamps are invented for it.
"""

import re
from typing import List, Optional, Tuple

from app.schemas import Segment, TranscriptResult
from app.services.formatting import build_full_text, make_segment, now_iso, normalize_text

_TS = r"(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_LINE_RE = re.compile(
    r"^\s*(?P<open>[\[(])?\s*(?P<start>" + _TS + r")"
    r"(?:\s*(?:-->|\u2192|-|\u2013|\u2014|to)\s*(?P<end>" + _TS + r"))?"
    r"\s*(?(open)[\])])(?P<rest>.*)$"
)
_SEP_RE = re.compile(r"^\s*(?:[-\u2013\u2014:|>]\s*)?")
_SRT_INDEX_RE = re.compile(r"^\s*\d+\s*$")
_VTT_HEADER_RE = re.compile(r"^\s*(WEBVTT|NOTE\b|STYLE\b|REGION\b)")
_VTT_TAG_RE = re.compile(r"<[^>]{1,40}>")


def parse_timestamp(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"Invalid timestamp: {value!r}")
    seconds = float(parts[-1])
    minutes = int(parts[-2])
    hours = int(parts[0]) if len(parts) == 3 else 0
    if seconds >= 60 or minutes >= 60 and len(parts) == 3:
        raise ValueError(f"Invalid timestamp: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def _match_timestamp_line(line: str) -> Optional[Tuple[float, Optional[float], str]]:
    m = _LINE_RE.match(line)
    if not m:
        return None
    rest = m.group("rest")
    # A bare "12:30" must be followed by whitespace/separator or end of line, so
    # ordinary text like "10:30am" isn't treated as a timestamp.
    if not m.group("open") and rest and not rest[0].isspace() and rest[0] not in "-\u2013\u2014:|>":
        return None
    try:
        start = parse_timestamp(m.group("start"))
        end = parse_timestamp(m.group("end")) if m.group("end") else None
    except ValueError:
        return None
    text = _SEP_RE.sub("", rest, count=1)
    return start, end, text


def parse_txt(text: str) -> Tuple[List[Segment], bool]:
    """Return (segments, has_timestamps)."""
    text = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    has_timestamps = any(_match_timestamp_line(line) for line in lines if line.strip())
    if not has_timestamps:
        paragraphs = re.split(r"\n\s*\n", text)
        segments = [
            make_segment(i, None, None, p)
            for i, p in enumerate((p for p in paragraphs if normalize_text(p)), start=1)
        ]
        return segments, False

    raw: List[List] = []  # [start, end, [text parts]]
    for line in lines:
        stripped = line.strip()
        if not stripped or _VTT_HEADER_RE.match(stripped):
            continue
        matched = _match_timestamp_line(stripped)
        if matched:
            start, end, rest = matched
            raw.append([start, end, [rest] if rest.strip() else []])
            continue
        if _SRT_INDEX_RE.match(stripped):
            continue
        cleaned = _VTT_TAG_RE.sub("", stripped)
        if not raw:
            raw.append([None, None, [cleaned]])
        else:
            raw[-1][2].append(cleaned)

    segments: List[Segment] = []
    for start, end, parts in raw:
        body = normalize_text(" ".join(parts))
        if body:
            segments.append(make_segment(len(segments) + 1, start, end, body))
    return segments, True


def txt_to_result(text: str, title: Optional[str] = None) -> TranscriptResult:
    segments, has_ts = parse_txt(text)
    return TranscriptResult(
        video_id=None,
        video_url=None,
        title=normalize_text(title) if title else None,
        channel=None,
        video_type=None,
        language=None,
        transcript_source="txt_import",
        is_live=None,
        duration_seconds=None,
        transcript=segments,
        full_text=build_full_text(segments),
        total_segments=len(segments),
        has_timestamps=has_ts,
        timestamp_reference="video_start" if has_ts else None,
        generated_at=now_iso(),
    )
