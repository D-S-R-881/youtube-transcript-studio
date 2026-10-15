import asyncio
import json
import re
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import get_settings
from app.core.errors import AppError
from app.schemas import JobStatus, TranscriptRequest
from app.services import pipeline, stt
from app.services.formatting import build_txt, export_filename, result_to_json
from app.services.jobs import Job, store
from app.services.metadata import fetch_video_info
from app.services.youtube_url import InvalidYouTubeUrl, parse_youtube_url

router = APIRouter(prefix="/api")

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MEDIA_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma",
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi",
}
_LANG_RE = re.compile(r"^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*)$")


def _parse_url(url: str):
    try:
        return parse_youtube_url(url)
    except InvalidYouTubeUrl as exc:
        raise AppError("invalid_url", str(exc), 422) from exc


def _get_job(job_id: str) -> Job:
    if not _JOB_ID_RE.match(job_id):
        raise AppError("job_not_found", "Transcript job not found.", 404)
    return store.get(job_id)


def _is_live_export(job: Job) -> bool:
    result = job.current_result()
    return job.kind == "live" or bool(result and result.video_type in ("live", "live_replay"))


# --------------------------------------------------------------------------- jobs


@router.post("/transcript", response_model=JobStatus, status_code=202)
async def create_transcript(req: TranscriptRequest, request: Request) -> JobStatus:
    parsed = _parse_url(req.url)
    job = pipeline.start_video_job(parsed, req, request.app.state.http)
    return job.status()


@router.post("/transcript/upload", response_model=JobStatus, status_code=202)
async def upload_media(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    include_timestamps: bool = Form(True),
) -> JobStatus:
    stt.require_stt()
    if not _LANG_RE.match(language):
        raise AppError("invalid_language", "Invalid language code.", 422)
    name = Path(file.filename or "upload").name[:200]
    ext = Path(name).suffix.lower()
    if ext not in _MEDIA_EXTENSIONS:
        raise AppError("unsupported_media", f"Unsupported file type '{ext or 'unknown'}'.", 415,
                       "Supported: " + ", ".join(sorted(_MEDIA_EXTENSIONS)))
    limit = get_settings().max_upload_mb * 1024 * 1024
    tmp_dir = Path(tempfile.mkdtemp(prefix="yts_upload_"))
    dest = tmp_dir / f"input{ext}"
    size = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise AppError("file_too_large", f"File exceeds the {limit // (1024 * 1024)} MB upload limit.", 413)
                fh.write(chunk)
        if size == 0:
            raise AppError("empty_file", "The uploaded file is empty.", 422)
    except Exception:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    job = pipeline.start_upload_job(dest, name, language, include_timestamps)
    return job.status()


@router.get("/transcript/{job_id}", response_model=JobStatus)
async def get_transcript(job_id: str, include_result: bool = True) -> JobStatus:
    return _get_job(job_id).status(include_result=include_result)


@router.post("/transcript/{job_id}/cancel", response_model=JobStatus)
async def cancel_transcript(job_id: str) -> JobStatus:
    job = _get_job(job_id)
    if job.is_terminal:
        raise AppError("job_finished", f"This job is already {job.state}.", 409)
    job.cancel()
    return job.status()


@router.post("/transcript/{job_id}/stop", response_model=JobStatus)
async def stop_live(job_id: str) -> JobStatus:
    """Stop a live session gracefully and keep everything collected so far."""
    job = _get_job(job_id)
    if job.kind != "live":
        raise AppError("not_live_session", "Only live sessions can be stopped. Use cancel instead.", 409)
    if job.is_terminal:
        raise AppError("job_finished", f"This session is already {job.state}.", 409)
    job.stop_event.set()
    deadline = time.monotonic() + 8
    while not job.is_terminal and time.monotonic() < deadline:
        await asyncio.sleep(0.2)
    return job.status()


async def _events(request: Request, job: Job, since: int) -> AsyncIterator[str]:
    sent = max(0, since)
    last_version = -1
    last_beat = time.monotonic()
    yield "retry: 3000\n\n"
    while True:
        if await request.is_disconnected():
            return
        if job.version != last_version:
            last_version = job.version
            new = job.collector.snapshot(sent)
            if new:
                for i in range(0, len(new), 500):
                    batch = new[i:i + 500]
                    payload = {"from_index": sent, "segments": [s.model_dump(mode="json") for s in batch]}
                    sent += len(batch)
                    yield f"id: {sent}\nevent: segments\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            status = job.status().model_dump(mode="json")
            yield f"event: status\ndata: {json.dumps(status, ensure_ascii=False)}\n\n"
            if job.is_terminal:
                yield f"event: done\ndata: {json.dumps({'state': job.state})}\n\n"
                return
            last_beat = time.monotonic()
        elif time.monotonic() - last_beat > 15:
            last_beat = time.monotonic()
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.4)


@router.get("/transcript/{job_id}/events")
async def transcript_events(
    job_id: str,
    request: Request,
    since: Optional[int] = Query(None, ge=0),
) -> StreamingResponse:
    job = _get_job(job_id)
    last_id = request.headers.get("last-event-id")
    if last_id and last_id.isdigit():
        start = int(last_id)
    else:
        start = since or 0
    return StreamingResponse(
        _events(request, job, start),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _ready_result(job: Job):
    result = job.current_result()
    if result is None:
        if job.state == "failed":
            raise AppError("job_failed", job.error.message if job.error else "Transcript extraction failed.", 409)
        if job.state == "cancelled":
            raise AppError("job_cancelled", "This job was cancelled; no transcript is available.", 409)
        raise AppError("not_ready", "The transcript is not ready yet.", 409)
    return result


@router.get("/transcript/{job_id}/download/txt")
async def download_txt(job_id: str, timestamps: Optional[bool] = None) -> Response:
    job = _get_job(job_id)
    result = _ready_result(job)
    include = job.include_timestamps if timestamps is None else timestamps
    body = build_txt(result.transcript, include)
    name = export_filename(result, _is_live_export(job), "txt")
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.get("/transcript/{job_id}/download/json")
async def download_json(job_id: str) -> Response:
    job = _get_job(job_id)
    result = _ready_result(job)
    name = export_filename(result, _is_live_export(job), "json")
    return Response(
        content=result_to_json(result).encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- live aliases


@router.post("/live", response_model=JobStatus, status_code=202)
async def start_live(req: TranscriptRequest, request: Request) -> JobStatus:
    parsed = _parse_url(req.url)
    info = await fetch_video_info(request.app.state.http, parsed.video_id, parsed.url_kind)
    if info.video_type == "upcoming":
        raise AppError("upcoming_livestream", "This livestream has not started yet.", 409)
    if info.video_type != "live":
        raise AppError("not_live", "This video is not currently live. Use POST /api/transcript instead.", 409)
    job = pipeline.start_video_job(parsed, req, request.app.state.http)
    return job.status()


@router.get("/live/{job_id}", response_model=JobStatus)
async def live_status(job_id: str, include_result: bool = True) -> JobStatus:
    return await get_transcript(job_id, include_result)


@router.get("/live/{job_id}/events")
async def live_events(job_id: str, request: Request, since: Optional[int] = Query(None, ge=0)) -> StreamingResponse:
    return await transcript_events(job_id, request, since)


@router.post("/live/{job_id}/stop", response_model=JobStatus)
async def live_stop(job_id: str) -> JobStatus:
    return await stop_live(job_id)


@router.get("/live/{job_id}/export/{fmt}")
async def live_export(job_id: str, fmt: str, timestamps: Optional[bool] = None) -> Response:
    if fmt == "txt":
        return await download_txt(job_id, timestamps)
    if fmt == "json":
        return await download_json(job_id)
    raise AppError("invalid_format", "Format must be 'txt' or 'json'.", 404)
