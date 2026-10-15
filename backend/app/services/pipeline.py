"""Job orchestration: captions -> (optional) speech-to-text -> TXT/JSON."""

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from app.config import get_settings
from app.core.errors import (
    EXTRACTION_FAILED_MESSAGE,
    LIVE_UNSUPPORTED_MESSAGE,
    NO_CAPTIONS_MESSAGE,
    AppError,
    JobCancelled,
)
from app.schemas import LiveStats, TranscriptRequest, VideoInfo
from app.services import audio, captions, stt
from app.services.formatting import build_txt, now_iso, result_to_json, sort_and_clean
from app.services.jobs import Job, store
from app.services.metadata import fetch_video_info
from app.services.segments import SegmentCollector
from app.services.youtube_url import ParsedYouTubeUrl

log = logging.getLogger(__name__)

# Captions errors after which speech-to-text is a sensible fallback.
_STT_FALLBACK_CODES = {
    "no_captions",
    "captions_disabled",
    "unsupported_language",
    "empty_transcript",
    "captions_unavailable",
    "rate_limited",
    "captions_failed",
}

_stt_slots: Optional[threading.BoundedSemaphore] = None
_stt_slots_lock = threading.Lock()


def _slots() -> threading.BoundedSemaphore:
    global _stt_slots
    with _stt_slots_lock:
        if _stt_slots is None:
            _stt_slots = threading.BoundedSemaphore(max(1, get_settings().max_concurrent_stt_jobs))
        return _stt_slots


def _acquire_stt_slot(job: Job) -> None:
    sem = _slots()
    while not sem.acquire(timeout=0.5):
        if job.cancel_event.is_set():
            raise JobCancelled()


def _upload_hint() -> Optional[str]:
    ok, _ = stt.stt_status()
    if ok:
        return "You can upload an audio/video file you have permission to process to transcribe it with speech-to-text."
    return None


async def _guard(job: Job, coro) -> None:
    try:
        await coro
    except JobCancelled:
        job.cancel()
    except asyncio.CancelledError:
        job.cancel()
        raise
    except AppError as err:
        if job.cancel_event.is_set():
            job.cancel()
        else:
            job.fail(err)
    except Exception:  # noqa: BLE001
        log.exception("Job %s crashed", job.id)
        job.fail(AppError("extraction_failed", EXTRACTION_FAILED_MESSAGE, 500))
    finally:
        job.cleanup_files()


def _check_cancel(job: Job) -> None:
    if job.cancel_event.is_set():
        raise JobCancelled()


async def _finalize(job: Job, segments) -> None:
    _check_cancel(job)
    job.set_stage("process")
    segments = sort_and_clean(segments)
    if not segments:
        raise AppError("empty_transcript", "No transcript text was found for this media.", 422)
    job.set_stage("text")
    build_txt(segments, job.include_timestamps)
    job.set_stage("json")
    result = job.build_result(segments)
    result_to_json(result)
    job.complete(result)


# --------------------------------------------------------------------------- videos


def start_video_job(parsed: ParsedYouTubeUrl, req: TranscriptRequest, client: httpx.AsyncClient) -> Job:
    job = store.add(Job("video", req.include_timestamps))
    job.task = asyncio.ensure_future(_guard(job, _run_video(job, parsed, req, client)))
    return job


async def _run_video(job: Job, parsed: ParsedYouTubeUrl, req: TranscriptRequest, client: httpx.AsyncClient) -> None:
    job.set_stage("validate")
    job.set_stage("metadata")
    info = await fetch_video_info(client, parsed.video_id, parsed.url_kind)
    job.video = info
    job.touch()
    _check_cancel(job)

    if info.availability == "private":
        raise AppError("video_private", "This video is private, so its transcript cannot be accessed.", 403)
    if info.availability == "deleted":
        raise AppError("video_deleted", "This video has been deleted or removed.", 404)
    if info.availability == "unavailable":
        raise AppError("video_unavailable", info.availability_reason or "This video is unavailable.", 404)
    if info.video_type == "upcoming":
        when = f" It is scheduled for {info.scheduled_start}." if info.scheduled_start else ""
        raise AppError(
            "upcoming_livestream",
            f"This livestream has not started yet.{when} Try again once it is live.",
            409,
        )
    if info.video_type == "live":
        await _run_live(job, info, req, client)
        return

    vid = parsed.video_id
    caption_error: Optional[AppError] = None
    if req.source in ("auto", "captions"):
        job.set_stage("captions")
        try:
            tracks = await asyncio.to_thread(captions.list_raw_tracks, vid)
            _check_cancel(job)
            job.set_stage("extract", "Extracting captions")
            cap = await asyncio.to_thread(captions.fetch_from_tracks, tracks, req.language)
        except AppError as err:
            caption_error = err
        else:
            job.meta.update(
                transcript_source="youtube_captions",
                language=cap.language_code,
                language_name=cap.language_name,
                caption_type="auto_generated" if cap.is_generated else "manual",
                translated_from=cap.translated_from,
                timestamp_reference="video_start",
            )
            await _finalize(job, cap.segments)
            return
        if req.source == "captions" or caption_error.code not in _STT_FALLBACK_CODES:
            if caption_error.code in ("no_captions", "captions_disabled") and not caption_error.hint:
                caption_error.hint = _upload_hint()
            raise caption_error
    else:
        job.skip_stage("captions")

    await _run_video_stt(job, info, req, caption_error)


async def _run_video_stt(job: Job, info: VideoInfo, req: TranscriptRequest, caption_error: Optional[AppError]) -> None:
    settings = get_settings()
    stt_ok, stt_reason = stt.stt_status()
    audio_ok, audio_reason = audio.youtube_audio_status()
    if not (stt_ok and audio_ok):
        reason = stt_reason if not stt_ok else audio_reason
        hint = " ".join(h for h in (reason, _upload_hint()) if h)
        if caption_error is not None:
            msg = caption_error.message if caption_error.code in ("rate_limited", "unsupported_language") else NO_CAPTIONS_MESSAGE
            raise AppError(caption_error.code, msg, caption_error.status_code, hint or caption_error.hint)
        raise AppError("audio_access_disabled", reason or "Speech-to-text is unavailable.", 403, _upload_hint())

    if info.duration_seconds and info.duration_seconds > settings.max_audio_duration_seconds:
        raise AppError(
            "too_long",
            f"This video is longer than the {settings.max_audio_duration_seconds // 60}-minute speech-to-text limit.",
            413,
        )

    job.set_stage("extract", "Downloading permitted audio", progress=None)
    src = await asyncio.to_thread(
        audio.download_audio,
        info.video_id,
        job.temp_dir(),
        job.cancel_event,
        lambda p: job.set_progress(p, "Downloading audio"),
    )
    job.set_progress(None, "Converting audio to 16 kHz mono")
    wav = await asyncio.to_thread(audio.convert_to_wav, src, job.temp_dir(), job.cancel_event)
    await _transcribe_file(job, wav, req.language, "speech_to_text")


async def _transcribe_file(job: Job, path: Path, language: str, source: str) -> None:
    job.collector = SegmentCollector(near_duplicate_window=0)
    job.set_stage("process", "Waiting for a free speech-to-text worker")
    await asyncio.to_thread(_acquire_stt_slot, job)
    try:
        job.set_stage("process", "Transcribing audio with speech-to-text", progress=0.0)

        def on_segment(raw):
            job.collector.add(*raw)
            job.touch()

        _, detected, duration = await asyncio.to_thread(
            stt.transcribe_source,
            str(path),
            language,
            job.cancel_event,
            on_segment,
            lambda p: job.set_progress(p),
        )
    finally:
        _slots().release()
    job.cleanup_files()
    job.meta.update(
        transcript_source=source,
        language=detected if language == "auto" else language,
        timestamp_reference="video_start",
    )
    if duration and not (job.video and job.video.duration_seconds):
        job.meta["duration_seconds"] = round(duration, 3)
    await _finalize(job, job.collector.snapshot())


# --------------------------------------------------------------------------- uploads


def start_upload_job(path: Path, filename: str, language: str, include_timestamps: bool) -> Job:
    from app.services.jobs import UPLOAD_STAGES

    job = store.add(Job("upload", include_timestamps, stages=UPLOAD_STAGES))
    job.meta["title"] = filename
    job._temp_dir = path.parent  # noqa: SLF001 - job owns the upload dir for cleanup
    job.task = asyncio.ensure_future(_guard(job, _run_upload(job, path, language)))
    return job


async def _run_upload(job: Job, path: Path, language: str) -> None:
    job.set_stage("validate")
    stt.require_stt()
    job.set_stage("extract", "Converting audio to 16 kHz mono")
    wav = await asyncio.to_thread(audio.convert_to_wav, path, path.parent, job.cancel_event)
    await _transcribe_file(job, wav, language, "uploaded_file_stt")


# --------------------------------------------------------------------------- live


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _sleep_unless_stopped(job: Job, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if job.stop_event.is_set():
            return
        await asyncio.sleep(min(0.5, end - time.monotonic()))


async def _run_live(job: Job, info: VideoInfo, req: TranscriptRequest, client: httpx.AsyncClient) -> None:
    settings = get_settings()
    job.kind = "live"
    if store.active_live_count() >= settings.live_max_sessions:
        raise AppError(
            "live_capacity",
            "The maximum number of concurrent live sessions is running. Please try again later.",
            429,
        )
    max_seconds = settings.live_max_session_seconds
    if req.live_mode == "timed" and req.live_max_minutes:
        max_seconds = min(max_seconds, req.live_max_minutes * 60)

    job.set_stage("captions", "Checking live caption availability")
    first_caps = None
    caption_error: Optional[AppError] = None
    if req.source in ("auto", "captions"):
        try:
            first_caps = await asyncio.to_thread(captions.fetch_captions_sync, info.video_id, req.language)
        except AppError as err:
            caption_error = err
    else:
        job.skip_stage("captions")

    mode: Optional[str] = "captions" if first_caps else None
    if mode is None and req.source in ("auto", "speech_to_text"):
        audio_ok, audio_reason = audio.youtube_audio_status()
        stt_ok, stt_reason = stt.stt_status()
        if audio_ok and stt_ok:
            mode = "audio"
        else:
            reasons = [r for r in (stt_reason if not stt_ok else None, audio_reason if not audio_ok else None) if r]
            caption_error = AppError(
                "live_unsupported",
                LIVE_UNSUPPORTED_MESSAGE,
                422,
                " ".join(["Live captions could not be retrieved for this broadcast."] + reasons),
            )
    if mode is None:
        if caption_error and caption_error.code in ("rate_limited",):
            raise caption_error
        raise AppError(
            "live_unsupported",
            LIVE_UNSUPPORTED_MESSAGE,
            422,
            caption_error.hint if caption_error and caption_error.code == "live_unsupported" else
            "Live captions could not be retrieved for this broadcast. Try again after the stream ends to use the replay.",
        )

    job.set_stage("extract", "Collecting live transcript")
    job.state = "live"
    job.live_started_monotonic = time.monotonic()
    job.live = LiveStats(
        mode=mode,  # type: ignore[arg-type]
        is_live=True,
        started_at=now_iso(),
        collected_segments=0,
        max_session_seconds=max_seconds,
    )
    job.meta.update(
        transcript_source="youtube_live_captions" if mode == "captions" else "live_speech_to_text",
        timestamp_reference="stream_start" if mode == "captions" else "session_start",
        video_type="live",
        broadcast_live=True,
    )
    job.touch()

    if mode == "captions":
        reason = await _live_caption_loop(job, info, req, client, first_caps, max_seconds)
    else:
        reason = await asyncio.to_thread(_live_audio_worker, job, info, req.language, max_seconds)

    if job.cancel_event.is_set():
        raise JobCancelled()
    ended = reason == "stream_ended"
    job.live = job.live.model_copy(update={"stopped": True, "stop_reason": reason, "is_live": not ended})
    job.meta["broadcast_live"] = not ended
    if ended:
        job.meta["video_type"] = "live_replay"
    snapshot = job.collector.snapshot()
    if not snapshot:
        raise AppError("empty_transcript", "The live session ended before any transcript text was collected.", 422)
    await _finalize(job, snapshot)


async def _live_caption_loop(job, info, req, client, first_caps, max_seconds) -> str:
    settings = get_settings()
    stream_start = _parse_iso(info.actual_start)

    def ingest(cap) -> None:
        if cap.language_code:
            job.meta.update(language=cap.language_code, language_name=cap.language_name,
                            caption_type="auto_generated" if cap.is_generated else "manual")
        for seg in cap.segments:
            job.collector.add(seg.start, seg.end, seg.text)
        delay = None
        last_end = job.collector.last_end
        if stream_start and last_end is not None:
            delay = max(0.0, (datetime.now(timezone.utc) - stream_start).total_seconds() - last_end)
        job.live = job.live.model_copy(update={"delay_seconds": delay})
        job.touch()

    ingest(first_caps)
    failures = 0
    polls = 0
    while True:
        if job.stop_event.is_set():
            return "user_stopped"
        if time.monotonic() - job.live_started_monotonic > max_seconds:
            return "time_limit"
        await _sleep_unless_stopped(job, settings.live_caption_poll_seconds)
        if job.stop_event.is_set():
            return "user_stopped"
        polls += 1
        try:
            cap = await asyncio.to_thread(captions.fetch_captions_sync, info.video_id, req.language)
            failures = 0
            ingest(cap)
        except AppError as err:
            failures += 1
            job.set_progress(None, f"Live captions temporarily unavailable ({err.code}); retrying")
            if failures >= 6:
                return "source_error"
        if polls % 6 == 0:
            try:
                latest = await fetch_video_info(client, info.video_id, "live")
                if latest.video_type != "live":
                    return "stream_ended"
            except Exception:  # noqa: BLE001
                pass


def _live_audio_worker(job: Job, info: VideoInfo, language: str, max_seconds: int) -> str:
    import numpy as np  # provided by the STT extras

    settings = get_settings()
    url = audio.resolve_live_audio_url(info.video_id)
    reader = audio.LivePcmReader(url, settings.live_chunk_seconds)
    offset = 0.0
    lang = None if language == "auto" else language
    started = time.monotonic()
    reason = "stream_ended"
    try:
        for chunk in reader.chunks(job.stop_event):
            if job.cancel_event.is_set():
                raise JobCancelled()
            seconds = len(chunk) / (2 * audio.SAMPLE_RATE)
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            raws, detected, _ = stt.transcribe_source(samples, lang, job.cancel_event)
            if lang is None and detected:
                lang = detected
                job.meta["language"] = detected
            for s, e, t in raws:
                job.collector.add(offset + s, offset + e, t)
            offset += seconds
            job.live = job.live.model_copy(
                update={
                    "audio_seconds_processed": round(offset, 1),
                    "delay_seconds": round(max(0.0, (time.monotonic() - started) - offset), 1),
                }
            )
            job.touch()
            if time.monotonic() - job.live_started_monotonic > max_seconds:
                reason = "time_limit"
                break
        else:
            if job.stop_event.is_set():
                reason = "user_stopped"
    finally:
        reader.close()
    if job.stop_event.is_set() and reason == "stream_ended":
        reason = "user_stopped"
    return reason
