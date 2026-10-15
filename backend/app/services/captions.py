"""Existing YouTube captions via youtube-transcript-api (>=1.2)."""

import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from app.config import get_settings
from app.core.errors import NO_CAPTIONS_MESSAGE, AppError
from app.schemas import CaptionTrack, Segment, TranslationLanguage
from app.services.formatting import make_segment, normalize_text

log = logging.getLogger(__name__)


@dataclass
class CaptionResult:
    segments: List[Segment]
    language_code: str
    language_name: str
    is_generated: bool
    translated_from: Optional[str] = None


def _api():
    from youtube_transcript_api import YouTubeTranscriptApi

    settings = get_settings()
    proxy_config = None
    if settings.captions_proxy_http or settings.captions_proxy_https:
        from youtube_transcript_api.proxies import GenericProxyConfig

        proxy_config = GenericProxyConfig(
            http_url=settings.captions_proxy_http or None,
            https_url=settings.captions_proxy_https or settings.captions_proxy_http or None,
        )
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def map_caption_exception(exc: Exception) -> AppError:
    """Translate youtube-transcript-api errors into stable app errors."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "TranscriptsDisabled" in names:
        return AppError("captions_disabled", NO_CAPTIONS_MESSAGE, 404,
                        "Captions are disabled by the uploader.")
    if "NoTranscriptFound" in names:
        return AppError("no_captions", NO_CAPTIONS_MESSAGE, 404)
    if "AgeRestricted" in names:
        return AppError("age_restricted", "This video is age-restricted, so its captions cannot be accessed anonymously.", 403)
    if "VideoUnplayable" in names:
        return AppError("video_restricted", "This video is unplayable or restricted (e.g. members-only, region-locked).", 403)
    if "VideoUnavailable" in names:
        return AppError("video_unavailable", "This video is unavailable. It may be private or deleted.", 404)
    if "InvalidVideoId" in names:
        return AppError("invalid_video_id", "The video ID is not valid.", 400)
    if names & {"RequestBlocked", "IpBlocked", "TooManyRequests"}:
        return AppError(
            "rate_limited",
            "YouTube is temporarily blocking caption requests from this server. Please retry later.",
            429,
            "Server operators can configure CAPTIONS_PROXY_HTTP(S) to route caption requests through a proxy.",
        )
    if "PoTokenRequired" in names:
        return AppError("captions_unavailable", "YouTube requires additional verification to serve these captions.", 502)
    if "YouTubeRequestFailed" in names or "ConnectionError" in names or "Timeout" in names:
        return AppError("network_error", "Could not reach YouTube to fetch captions. Please retry.", 502)
    if "CouldNotRetrieveTranscript" in names:
        return AppError("no_captions", NO_CAPTIONS_MESSAGE, 404)
    log.exception("Unexpected caption error", exc_info=exc)
    return AppError("captions_failed", "Caption extraction failed unexpectedly. Please retry.", 502)


def _lang_matches(track_code: str, wanted: str) -> bool:
    t, w = track_code.lower(), wanted.lower()
    return t == w or t.split("-")[0] == w.split("-")[0]


def select_transcript(tracks: List[Any], language: str) -> Tuple[Any, Optional[str]]:
    """Pick the best track. Returns (track, translate_to_code_or_None).

    Rules: manual captions beat auto-generated ones in the same language. With
    "auto", the language of the auto-generated track (the spoken language) is
    preferred; otherwise the first manual track.
    """
    if not tracks:
        raise AppError("no_captions", NO_CAPTIONS_MESSAGE, 404)
    manual = [t for t in tracks if not t.is_generated]
    generated = [t for t in tracks if t.is_generated]

    if language == "auto":
        if generated:
            spoken = generated[0].language_code
            exact_manual = [t for t in manual if t.language_code.lower() == spoken.lower()]
            loose_manual = [t for t in manual if _lang_matches(t.language_code, spoken)]
            return (exact_manual or loose_manual or generated)[0], None
        return manual[0], None

    for pool in (manual, generated):
        exact = [t for t in pool if t.language_code.lower() == language.lower()]
        loose = [t for t in pool if _lang_matches(t.language_code, language)]
        if exact or loose:
            return (exact or loose)[0], None

    for pool in (manual, generated):
        for t in pool:
            if t.is_translatable and any(
                tl.language_code.lower() == language.lower() for tl in t.translation_languages
            ):
                return t, language
    available = ", ".join(sorted({t.language_code for t in tracks}))
    raise AppError(
        "unsupported_language",
        f"Captions are not available in '{language}' and cannot be translated to it.",
        404,
        f"Available caption languages: {available}. Choose one of them or 'Auto-detect'.",
    )


def snippets_to_segments(snippets: List[Any]) -> List[Segment]:
    """Convert caption snippets (text/start/duration) into ordered segments."""
    items = []
    for sn in snippets:
        text = normalize_text(getattr(sn, "text", None) if not isinstance(sn, dict) else sn.get("text"))
        start = getattr(sn, "start", None) if not isinstance(sn, dict) else sn.get("start")
        duration = getattr(sn, "duration", None) if not isinstance(sn, dict) else sn.get("duration")
        if not text:
            continue
        start_f = float(start) if start is not None else None
        end_f = start_f + float(duration) if start_f is not None and duration is not None else None
        items.append((start_f, end_f, text))
    if all(i[0] is not None for i in items):
        items.sort(key=lambda i: i[0])
    return [make_segment(idx, s, e, t) for idx, (s, e, t) in enumerate(items, start=1)]


def list_tracks_sync(video_id: str) -> Tuple[List[CaptionTrack], List[TranslationLanguage]]:
    try:
        tl = _api().list(video_id)
        tracks = list(tl)
    except Exception as exc:  # noqa: BLE001 - mapped below
        raise map_caption_exception(exc) from exc
    out = [
        CaptionTrack(
            language_code=t.language_code,
            language=t.language,
            is_generated=t.is_generated,
            is_translatable=t.is_translatable,
        )
        for t in tracks
    ]
    translations: dict = {}
    for t in tracks:
        if t.is_translatable:
            for lang in t.translation_languages:
                translations.setdefault(lang.language_code, lang.language)
    return out, [TranslationLanguage(language_code=k, language=v) for k, v in sorted(translations.items(), key=lambda kv: kv[1])]


def list_raw_tracks(video_id: str) -> List[Any]:
    try:
        return list(_api().list(video_id))
    except Exception as exc:  # noqa: BLE001
        raise map_caption_exception(exc) from exc


def fetch_captions_sync(video_id: str, language: str = "auto") -> CaptionResult:
    return fetch_from_tracks(list_raw_tracks(video_id), language)


def fetch_from_tracks(tracks: List[Any], language: str = "auto") -> CaptionResult:
    track, translate_to = select_transcript(tracks, language)
    try:
        source = track.translate(translate_to) if translate_to else track
        fetched = source.fetch()
    except Exception as exc:  # noqa: BLE001
        raise map_caption_exception(exc) from exc

    snippets = getattr(fetched, "snippets", fetched)
    segments = snippets_to_segments(list(snippets))
    if not segments:
        raise AppError("empty_transcript", "The caption track exists but contains no text.", 404)
    return CaptionResult(
        segments=segments,
        language_code=getattr(fetched, "language_code", None) or (translate_to or track.language_code),
        language_name=getattr(fetched, "language", None) or track.language,
        is_generated=bool(track.is_generated),
        translated_from=track.language_code if translate_to else None,
    )
