import asyncio
import logging
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import misc, transcripts
from app.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import RateLimitMiddleware
from app.services import stt
from app.services.jobs import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "hint": None}})


def _sweep_stale_temp_dirs(max_age_seconds: float) -> None:
    """Remove temp dirs left behind by a previous process that was killed mid-job."""
    cutoff = time.time() - max_age_seconds
    for path in Path(tempfile.gettempdir()).glob("yts_*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


async def _janitor() -> None:
    while True:
        await asyncio.sleep(60)
        store.purge_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _sweep_stale_temp_dirs(get_settings().job_ttl_seconds)
    app.state.http = httpx.AsyncClient(follow_redirects=False, timeout=15)
    janitor = asyncio.ensure_future(_janitor())
    try:
        yield
    finally:
        janitor.cancel()
        store.shutdown()
        await app.state.http.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="YouTube Transcript Studio API", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def upload_guard(request: Request, call_next):
        # The multipart body is fully received before the route runs, so reject
        # uploads that can't be processed or are oversized before reading them.
        if request.method == "POST" and request.url.path.rstrip("/") == "/api/transcript/upload":
            ok, reason = stt.stt_status()
            if not ok:
                return _error(503, "stt_unavailable", reason or "Speech-to-text is unavailable.")
            limit = settings.max_upload_mb * 1024 * 1024
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit + 1024 * 1024:
                return _error(413, "file_too_large", f"File exceeds the {settings.max_upload_mb} MB upload limit.")
        return await call_next(request)

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
        expose_headers=["Content-Disposition", "Retry-After"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"Invalid request{f' ({field})' if field else ''}: {first.get('msg', 'validation error')}"
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": msg, "hint": None}})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": f"http_{exc.status_code}", "message": str(exc.detail), "hint": None}},
        )

    app.include_router(misc.router)
    app.include_router(transcripts.router)
    return app


app = create_app()
