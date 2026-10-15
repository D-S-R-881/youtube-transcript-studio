import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import AppError
from app.schemas import Capabilities, TxtToJsonRequest, VideoInfo
from app.services import audio, captions, stt
from app.services.metadata import fetch_video_info
from app.services.txt_parser import txt_to_result
from app.services.youtube_url import InvalidYouTubeUrl, parse_youtube_url

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/capabilities", response_model=Capabilities)
async def capabilities() -> Capabilities:
    s = get_settings()
    stt_ok, stt_reason = stt.stt_status()
    audio_ok, audio_reason = audio.youtube_audio_status()
    return Capabilities(
        captions=True,
        speech_to_text=stt_ok,
        speech_to_text_reason=stt_reason,
        youtube_audio_ingestion=audio_ok and stt_ok,
        youtube_audio_reason=audio_reason if not audio_ok else (stt_reason if not stt_ok else None),
        live_captions=True,
        live_audio=audio_ok and stt_ok,
        file_upload=stt_ok,
        ffmpeg=audio.ffmpeg_binary() is not None,
        metadata_source="youtube_data_api" if s.youtube_api_key else "youtube_watch_page",
        whisper_model=s.whisper_model if stt_ok else None,
        max_upload_mb=s.max_upload_mb,
        max_audio_duration_seconds=s.max_audio_duration_seconds,
        job_ttl_seconds=s.job_ttl_seconds,
    )


@router.get("/video/info", response_model=VideoInfo)
async def video_info(request: Request, url: str = Query(..., max_length=2048)) -> VideoInfo:
    try:
        parsed = parse_youtube_url(url)
    except InvalidYouTubeUrl as exc:
        raise AppError("invalid_url", str(exc), 422) from exc

    info_task = fetch_video_info(request.app.state.http, parsed.video_id, parsed.url_kind)
    tracks_task = asyncio.to_thread(captions.list_tracks_sync, parsed.video_id)
    info, tracks = await asyncio.gather(info_task, tracks_task, return_exceptions=True)
    if isinstance(info, BaseException):
        raise info
    if isinstance(tracks, AppError):
        return info.model_copy(update={"captions_status": tracks.code, "captions_message": tracks.message})
    if isinstance(tracks, BaseException):
        return info.model_copy(update={"captions_status": "unknown"})
    track_list, translations = tracks
    return info.model_copy(update={
        "caption_tracks": track_list,
        "translation_languages": translations,
        "captions_status": "available" if track_list else "no_captions",
    })


@router.post("/convert/txt-to-json")
async def convert_txt_to_json(request: Request) -> JSONResponse:
    """Accepts JSON {"text": ..., "title": ...} or multipart/form-data with a `file` field."""
    limit = get_settings().max_txt_convert_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 1024 * 64:
        raise AppError("file_too_large", f"Text exceeds the {limit // (1024 * 1024)} MB limit.", 413)

    ctype = request.headers.get("content-type", "")
    title = None
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise AppError("missing_file", "Attach a .txt file in the 'file' field.", 422)
        name = getattr(upload, "filename", "") or ""
        if name and not name.lower().endswith((".txt", ".srt", ".vtt", ".text")):
            raise AppError("unsupported_file", "Only .txt (or .srt/.vtt) transcript files are supported.", 415)
        raw = await upload.read(limit + 1)
        if len(raw) > limit:
            raise AppError("file_too_large", f"Text exceeds the {limit // (1024 * 1024)} MB limit.", 413)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError("invalid_encoding", "The file must be UTF-8 encoded text.", 415) from exc
        title = name.rsplit(".", 1)[0] if name else None
    else:
        try:
            body = TxtToJsonRequest.model_validate(json.loads(await request.body() or b"{}"))
        except (ValueError, TypeError) as exc:
            raise AppError("invalid_request", "Send JSON like {\"text\": \"...\"}.", 422) from exc
        text, title = body.text, body.title
        if len(text.encode("utf-8")) > limit:
            raise AppError("file_too_large", f"Text exceeds the {limit // (1024 * 1024)} MB limit.", 413)

    if not text.strip():
        raise AppError("empty_text", "The transcript text is empty.", 422)
    result = await asyncio.to_thread(txt_to_result, text, title)
    if not result.transcript:
        raise AppError("empty_text", "No transcript text was found.", 422)
    return JSONResponse(result.model_dump(mode="json"))
