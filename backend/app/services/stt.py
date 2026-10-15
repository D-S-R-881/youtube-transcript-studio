"""Speech-to-text with Faster-Whisper (optional dependency)."""

import importlib.util
import logging
import threading
from typing import Any, Callable, List, Optional, Tuple

from app.config import get_settings
from app.core.errors import AppError, JobCancelled

log = logging.getLogger(__name__)

_model: Any = None
_model_lock = threading.Lock()

RawSegment = Tuple[float, float, str]


def stt_status() -> Tuple[bool, Optional[str]]:
    settings = get_settings()
    if not settings.stt_enabled:
        return False, "Speech-to-text is disabled on this server (STT_ENABLED=false)."
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "Speech-to-text is not installed on this server (pip install -r requirements-stt.txt)."
    return True, None


def require_stt() -> None:
    ok, reason = stt_status()
    if not ok:
        raise AppError("stt_unavailable", reason or "Speech-to-text is unavailable.", 503)


def get_model() -> Any:
    global _model
    require_stt()
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            s = get_settings()
            log.info("Loading Whisper model %s (%s/%s)", s.whisper_model, s.whisper_device, s.whisper_compute_type)
            _model = WhisperModel(
                s.whisper_model,
                device=s.whisper_device,
                compute_type=s.whisper_compute_type,
                num_workers=max(1, s.max_concurrent_stt_jobs + s.live_max_sessions),
            )
        return _model


def transcribe_source(
    audio: Any,
    language: Optional[str],
    cancel_event: threading.Event,
    on_segment: Optional[Callable[[RawSegment], None]] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    vad: bool = True,
) -> Tuple[List[RawSegment], Optional[str], Optional[float]]:
    """Transcribe a file path or 16 kHz float32 array.

    Faster-Whisper decodes and walks long audio in 30 s windows internally and
    yields continuous, non-overlapping timestamps, so no manual chunk merge is
    needed for files. Returns (segments, detected_language, audio_duration).
    """
    model = get_model()
    try:
        segments_iter, info = model.transcribe(
            audio,
            language=None if not language or language == "auto" else language.split("-")[0],
            vad_filter=vad,
            beam_size=5,
            condition_on_previous_text=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Whisper failed to start")
        raise AppError("stt_failed", "Speech-to-text failed to process this audio.", 500) from exc

    duration = float(getattr(info, "duration", 0) or 0) or None
    out: List[RawSegment] = []
    try:
        for seg in segments_iter:
            if cancel_event.is_set():
                raise JobCancelled()
            # Whisper can report an end time past the last sample on the final segment.
            end = min(float(seg.end), duration) if duration else float(seg.end)
            raw = (float(seg.start), max(end, float(seg.start)), seg.text.strip())
            if raw[2]:
                out.append(raw)
                if on_segment:
                    on_segment(raw)
            if on_progress and duration:
                on_progress(min(1.0, seg.end / duration))
    except JobCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("Whisper failed mid-transcription")
        raise AppError("stt_failed", "Speech-to-text failed while processing the audio.", 500) from exc
    return out, getattr(info, "language", None), duration
