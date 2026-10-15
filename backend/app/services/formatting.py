"""Transcript text/JSON builders. Kept in sync with frontend/src/lib/transcript-format.ts."""

import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from app.schemas import Segment, TranscriptResult

_WS_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"[.!?\u3002\uff01\uff1f\u0964\u061f\u2026][\"')\]\u201d\u2019]*$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")

PARAGRAPH_GAP_SECONDS = 2.0
PARAGRAPH_SOFT_CHARS = 400


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\u200b", "")).strip()


def round_time(value: Optional[float]) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(max(0.0, float(value)), 3)


def format_timestamp(seconds: Optional[float]) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        seconds = 0
    total = int(math.floor(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def make_segment(index: int, start: Optional[float], end: Optional[float], text: str) -> Segment:
    start_r = round_time(start)
    end_r = round_time(end)
    if start_r is not None and end_r is not None and end_r < start_r:
        end_r = start_r
    duration = round(end_r - start_r, 3) if start_r is not None and end_r is not None else None
    return Segment(id=index, start=start_r, end=end_r, duration=duration, text=normalize_text(text))


def renumber(segments: Iterable[Segment]) -> List[Segment]:
    return [s.model_copy(update={"id": i}) for i, s in enumerate(segments, start=1)]


def sort_and_clean(segments: Iterable[Segment]) -> List[Segment]:
    """Drop empty segments and order by start time (stable, untimed keep position)."""
    cleaned = [s for s in segments if normalize_text(s.text)]
    if all(s.start is not None for s in cleaned):
        cleaned = sorted(cleaned, key=lambda s: s.start)
    return renumber(cleaned)


def build_full_text(segments: Sequence[Segment]) -> str:
    return normalize_text(" ".join(s.text for s in segments))


def build_txt(segments: Sequence[Segment], include_timestamps: bool) -> str:
    if not segments:
        return ""
    if include_timestamps:
        lines = []
        for s in segments:
            prefix = f"[{format_timestamp(s.start)}] " if s.start is not None else ""
            lines.append(prefix + s.text)
        return "\n\n".join(lines) + "\n"
    return "\n\n".join(build_paragraphs(segments)) + "\n"


def build_paragraphs(segments: Sequence[Segment]) -> List[str]:
    paragraphs: List[str] = []
    current: List[str] = []
    length = 0
    prev: Optional[Segment] = None
    for s in segments:
        if current and prev is not None:
            untimed = s.start is None or prev.start is None
            gap = None
            if not untimed:
                prev_end = prev.end if prev.end is not None else prev.start
                gap = s.start - prev_end
            soft_break = length >= PARAGRAPH_SOFT_CHARS and bool(_SENTENCE_END_RE.search(current[-1]))
            if untimed or (gap is not None and gap >= PARAGRAPH_GAP_SECONDS) or soft_break:
                paragraphs.append(" ".join(current))
                current, length = [], 0
        current.append(s.text)
        length += len(s.text) + 1
        prev = s
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def result_to_json(result: TranscriptResult) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"


def safe_filename(video_id: Optional[str], is_live: bool, ext: str) -> str:
    ident = _SAFE_ID_RE.sub("", video_id or "")[:64] or "transcript"
    prefix = "youtube_live_transcript" if is_live else "youtube_transcript"
    ext = _SAFE_ID_RE.sub("", ext)[:8] or "txt"
    return f"{prefix}_{ident}.{ext}"


def export_filename(result: TranscriptResult, is_live: bool, ext: str) -> str:
    """Filename for a result; uploads/imports (no video id) are named after their title."""
    if not result.video_id and result.title:
        base = unicodedata.normalize("NFKD", result.title)
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_")[:64]
        ext = _SAFE_ID_RE.sub("", ext)[:8] or "txt"
        return f"transcript_{base or 'file'}.{ext}"
    return safe_filename(result.video_id, is_live, ext)
