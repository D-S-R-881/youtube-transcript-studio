"""Audio ingestion (opt-in) and FFmpeg helpers.

YouTube audio is only fetched when ENABLE_YOUTUBE_AUDIO_INGESTION=true. The
operator is responsible for ensuring they have permission to process the media.
"""

import importlib.util
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple
from urllib.parse import urlsplit

from app.config import get_settings
from app.core.errors import AppError, JobCancelled
from app.services.youtube_url import canonical_watch_url, is_valid_video_id

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_ALLOWED_MEDIA_HOST_SUFFIXES = (".googlevideo.com", ".youtube.com", ".ytimg.com")


def ffmpeg_binary() -> Optional[str]:
    path = get_settings().ffmpeg_path or "ffmpeg"
    if os.path.isfile(path):
        return path
    return shutil.which(path)


def ytdlp_installed() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def youtube_audio_status() -> Tuple[bool, Optional[str]]:
    s = get_settings()
    if not s.enable_youtube_audio_ingestion:
        return False, (
            "YouTube audio ingestion is disabled on this server. Captions are used when available; "
            "you can upload an audio/video file you have permission to process."
        )
    if not ytdlp_installed():
        return False, "yt-dlp is not installed on this server."
    if not ffmpeg_binary():
        return False, "FFmpeg is not installed on this server."
    return True, None


def _assert_media_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host.endswith(sfx) for sfx in _ALLOWED_MEDIA_HOST_SUFFIXES):
        raise AppError("audio_unavailable", "The media stream resolved to an unexpected host and was rejected.", 502)
    return url


def _ydl_opts(extra: dict) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": False,
        "cachedir": False,
        "socket_timeout": 20,
    }
    ff = ffmpeg_binary()
    if ff:
        opts["ffmpeg_location"] = ff
    opts.update(extra)
    return opts


def _map_ytdlp_error(exc: Exception) -> AppError:
    msg = str(exc).lower()
    if "private" in msg:
        return AppError("video_private", "This video is private.", 403)
    if "sign in" in msg or "age" in msg:
        return AppError("audio_unavailable", "YouTube requires sign-in to access this audio.", 403)
    if "429" in msg or "too many" in msg:
        return AppError("rate_limited", "YouTube is rate limiting audio requests from this server.", 429)
    if "is not a valid url" in msg or "unavailable" in msg:
        return AppError("video_unavailable", "This video is unavailable.", 404)
    return AppError("audio_unavailable", "Audio for this video could not be accessed.", 502)


def download_audio(
    video_id: str,
    dest_dir: Path,
    cancel_event: threading.Event,
    on_progress: Optional[Callable[[Optional[float]], None]] = None,
) -> Path:
    if not is_valid_video_id(video_id):
        raise AppError("invalid_video_id", "Invalid video ID.", 400)
    ok, reason = youtube_audio_status()
    if not ok:
        raise AppError("audio_access_disabled", reason or "Audio access is unavailable.", 403)
    import yt_dlp  # type: ignore

    s = get_settings()

    def hook(d: dict) -> None:
        if cancel_event.is_set():
            raise JobCancelled()
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes")
            on_progress((done / total) if total and done else None)

    def too_long(info: dict, *, incomplete: bool = False) -> Optional[str]:
        if info.get("is_live"):
            return "Use live mode for active livestreams."
        duration = info.get("duration")
        if duration and duration > s.max_audio_duration_seconds:
            return "too long"
        return None

    opts = _ydl_opts(
        {
            "format": "bestaudio[abr<=160]/bestaudio/best[height<=360]",
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [hook],
            "match_filter": too_long,
            "max_filesize": s.max_upload_mb * 1024 * 1024,
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_watch_url(video_id), download=True)
    except JobCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        if isinstance(getattr(exc, "exc_info", [None, None])[1], JobCancelled) or cancel_event.is_set():
            raise JobCancelled() from exc
        raise _map_ytdlp_error(exc) from exc

    if info and info.get("duration") and info["duration"] > s.max_audio_duration_seconds:
        raise AppError(
            "too_long",
            f"This video is longer than the {s.max_audio_duration_seconds // 60}-minute speech-to-text limit.",
            413,
        )
    files = [p for p in dest_dir.iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        raise AppError("audio_unavailable", "Audio download produced no file (it may exceed size limits).", 502)
    return files[0]


def convert_to_wav(src: Path, dest_dir: Path, cancel_event: threading.Event) -> Path:
    """Convert any media to 16 kHz mono PCM WAV (Whisper's native format)."""
    ff = ffmpeg_binary()
    if not ff:
        return src  # Faster-Whisper can decode common formats itself via PyAV.
    out = dest_dir / "audio_16k.wav"
    proc = subprocess.Popen(
        [ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    while True:
        try:
            _, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if cancel_event.is_set():
                proc.kill()
                raise JobCancelled()
    if proc.returncode != 0:
        log.warning("ffmpeg failed: %s", (err or b"")[-500:])
        raise AppError("unsupported_media", "This file could not be decoded as audio.", 415)
    return out


def resolve_live_audio_url(video_id: str) -> str:
    ok, reason = youtube_audio_status()
    if not ok:
        raise AppError("audio_access_disabled", reason or "Audio access is unavailable.", 403)
    import yt_dlp  # type: ignore

    opts = _ydl_opts({"format": "bestaudio/best[height<=360]/best", "skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_watch_url(video_id), download=False)
    except Exception as exc:  # noqa: BLE001
        raise _map_ytdlp_error(exc) from exc
    if not info or not info.get("is_live"):
        raise AppError("not_live", "This video is not currently live.", 409)
    url = info.get("url") or next(
        (f.get("url") for f in reversed(info.get("formats") or []) if f.get("url")), None
    )
    if not url:
        raise AppError("audio_unavailable", "No accessible audio stream was found for this livestream.", 502)
    return _assert_media_url(url)


class LivePcmReader:
    """Reads a live stream through FFmpeg as 16 kHz mono s16le PCM chunks."""

    def __init__(self, url: str, chunk_seconds: int) -> None:
        ff = ffmpeg_binary()
        if not ff:
            raise AppError("ffmpeg_missing", "FFmpeg is required for live audio transcription.", 503)
        self.chunk_bytes = SAMPLE_RATE * 2 * chunk_seconds
        self.proc = subprocess.Popen(
            [ff, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
             "-i", url, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def chunks(self, stop_event: threading.Event) -> Iterator[bytes]:
        assert self.proc.stdout is not None
        buf = bytearray()
        while not stop_event.is_set():
            data = self.proc.stdout.read(min(65536, self.chunk_bytes - len(buf)))
            if not data:
                break
            buf.extend(data)
            if len(buf) >= self.chunk_bytes:
                yield bytes(buf)
                buf.clear()
        if buf and not stop_event.is_set():
            yield bytes(buf)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
