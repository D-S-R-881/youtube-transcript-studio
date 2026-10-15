"""Incremental, ordered, de-duplicated segment collection (used for live + chunked STT)."""

import re
import threading
from collections import deque
from typing import Deque, List, Optional, Set, Tuple

from app.schemas import Segment
from app.services.formatting import make_segment, normalize_text

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

NEAR_DUPLICATE_WINDOW_SECONDS = 8.0
ORDER_TOLERANCE_SECONDS = 0.5


def _norm_key(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def strip_overlap(previous: str, new: str, max_words: int = 15, min_words: int = 2) -> str:
    """Remove a word-level prefix of `new` that repeats the tail of `previous`."""
    prev_words = previous.split()
    new_words = new.split()
    prev_keys = [_norm_key(w) for w in prev_words]
    new_keys = [_norm_key(w) for w in new_words]
    limit = min(max_words, len(prev_words), len(new_words))
    for k in range(limit, min_words - 1, -1):
        if prev_keys[-k:] == new_keys[:k] and any(prev_keys[-k:]):
            return " ".join(new_words[k:])
    return new


class SegmentCollector:
    """Thread-safe append-only collector that keeps segments ordered and unique."""

    def __init__(self, near_duplicate_window: float = NEAR_DUPLICATE_WINDOW_SECONDS) -> None:
        self.near_duplicate_window = near_duplicate_window
        self._lock = threading.Lock()
        self._segments: List[Segment] = []
        self._keys: Set[Tuple[Optional[float], str]] = set()
        self._recent: Deque[Segment] = deque(maxlen=6)
        self.dropped_duplicates = 0
        self.dropped_out_of_order = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._segments)

    @property
    def last_end(self) -> Optional[float]:
        with self._lock:
            if not self._segments:
                return None
            last = self._segments[-1]
            return last.end if last.end is not None else last.start

    def snapshot(self, start_index: int = 0) -> List[Segment]:
        with self._lock:
            return list(self._segments[start_index:])

    def add(self, start: Optional[float], end: Optional[float], text: str) -> Optional[Segment]:
        text = normalize_text(text)
        key_text = _norm_key(text)
        if not key_text:
            return None
        with self._lock:
            key = (round(start, 1) if start is not None else None, key_text)
            if key in self._keys:
                self.dropped_duplicates += 1
                return None

            last = self._segments[-1] if self._segments else None
            if last is not None and start is not None and last.start is not None:
                if start < last.start - ORDER_TOLERANCE_SECONDS:
                    self.dropped_out_of_order += 1
                    return None

            for recent in self._recent if self.near_duplicate_window > 0 else ():
                if _norm_key(recent.text) == key_text and (
                    start is None
                    or recent.start is None
                    or abs(start - recent.start) <= self.near_duplicate_window
                ):
                    self.dropped_duplicates += 1
                    return None

            if (
                self.near_duplicate_window > 0
                and last is not None
                and last.end is not None
                and start is not None
                and start < last.end + 1.0
            ):
                text = strip_overlap(last.text, text)
                if not _norm_key(text):
                    self.dropped_duplicates += 1
                    return None

            seg = make_segment(len(self._segments) + 1, start, end, text)
            self._segments.append(seg)
            self._keys.add(key)
            self._recent.append(seg)
            return seg
