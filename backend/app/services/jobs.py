"""In-memory, time-limited job store.

Jobs live only in process memory and are purged after JOB_TTL_SECONDS, so
transcripts are never persisted. For multi-instance deployments, put a sticky
load balancer in front or swap this store for Redis (see README).
"""

import asyncio
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.config import get_settings
from app.core.errors import AppError
from app.schemas import (
    JobError,
    JobStatus,
    LiveStats,
    Segment,
    StageInfo,
    TranscriptResult,
    VideoInfo,
)
from app.services.formatting import build_full_text, now_iso
from app.services.segments import SegmentCollector

STAGES = [
    ("validate", "Validating YouTube URL"),
    ("metadata", "Checking video information"),
    ("captions", "Checking caption availability"),
    ("extract", "Extracting captions or preparing permitted audio transcription"),
    ("process", "Processing transcript segments"),
    ("text", "Building plain-text transcript"),
    ("json", "Converting transcript into JSON"),
    ("complete", "Complete"),
]
UPLOAD_STAGES = [
    ("validate", "Validating uploaded file"),
    ("extract", "Transcribing audio with speech-to-text"),
    ("process", "Processing transcript segments"),
    ("text", "Building plain-text transcript"),
    ("json", "Converting transcript into JSON"),
    ("complete", "Complete"),
]
TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Job:
    def __init__(self, kind: str, include_timestamps: bool, stages=STAGES) -> None:
        settings = get_settings()
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.include_timestamps = include_timestamps
        self.state = "queued"
        self.stage_labels = OrderedDict(stages)
        self.stage_status: Dict[str, str] = {k: "pending" for k, _ in stages}
        self.stage = stages[0][0]
        self.progress: Optional[float] = None
        self.message: Optional[str] = None
        self.video: Optional[VideoInfo] = None
        self.error: Optional[JobError] = None
        self.collector = SegmentCollector()
        self.meta: Dict[str, object] = {}
        self.result: Optional[TranscriptResult] = None
        self.live: Optional[LiveStats] = None
        self.live_started_monotonic: Optional[float] = None
        self.created = time.time()
        self.updated = self.created
        self.ttl = settings.job_ttl_seconds
        self.cancel_event = threading.Event()
        self.stop_event = threading.Event()  # live: stop gracefully, keep transcript
        self.task: Optional[asyncio.Task] = None
        self.version = 0
        self._lock = threading.RLock()
        self._temp_dir: Optional[Path] = None

    # ----------------------------------------------------------------- helpers
    @property
    def expires_at(self) -> float:
        return self.updated + self.ttl

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def temp_dir(self) -> Path:
        with self._lock:
            if self._temp_dir is None:
                self._temp_dir = Path(tempfile.mkdtemp(prefix=f"yts_{self.id[:8]}_"))
            return self._temp_dir

    def cleanup_files(self) -> None:
        with self._lock:
            if self._temp_dir is not None:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                self._temp_dir = None

    def touch(self) -> None:
        with self._lock:
            self.updated = time.time()
            self.version += 1

    # ----------------------------------------------------------------- state
    def set_stage(self, key: str, message: Optional[str] = None, progress: Optional[float] = None) -> None:
        with self._lock:
            if self.is_terminal:
                return
            if self.state == "queued":
                self.state = "running"
            for k in self.stage_status:
                if k == key:
                    break
                if self.stage_status[k] in ("pending", "active"):
                    self.stage_status[k] = "done"
            self.stage_status[key] = "active"
            self.stage = key
            self.message = message or self.stage_labels.get(key)
            self.progress = progress
        self.touch()

    def skip_stage(self, key: str) -> None:
        with self._lock:
            if self.stage_status.get(key) == "pending":
                self.stage_status[key] = "skipped"
        self.touch()

    def set_progress(self, progress: Optional[float], message: Optional[str] = None) -> None:
        with self._lock:
            self.progress = None if progress is None else max(0.0, min(1.0, progress))
            if message:
                self.message = message
        self.touch()

    def fail(self, err: AppError) -> None:
        with self._lock:
            if self.is_terminal:
                return
            self.stage_status[self.stage] = "error"
            self.state = "failed"
            self.error = JobError(code=err.code, message=err.message, hint=err.hint)
            self.message = err.message
            self.progress = None
            self.result = None
        self.touch()

    def cancel(self) -> None:
        with self._lock:
            if self.is_terminal:
                return
            self.cancel_event.set()
            self.stop_event.set()
            self.state = "cancelled"
            self.stage_status[self.stage] = "error"
            self.message = "Cancelled by user."
            self.progress = None
            self.result = None
        self.touch()

    def complete(self, result: TranscriptResult) -> None:
        with self._lock:
            if self.is_terminal:
                return
            for k in self.stage_status:
                if self.stage_status[k] in ("pending", "active"):
                    self.stage_status[k] = "done"
            self.stage = "complete"
            self.state = "completed"
            self.result = result
            self.progress = 1.0
            self.message = "Complete"
        self.touch()

    # ----------------------------------------------------------------- results
    def build_result(self, segments: Optional[List[Segment]] = None) -> TranscriptResult:
        segs = segments if segments is not None else self.collector.snapshot()
        v = self.video
        if self.kind == "live":
            is_live: Optional[bool] = bool(self.meta.get("broadcast_live", True))
        else:
            is_live = bool(v.is_live) if v else None
        return TranscriptResult(
            video_id=v.video_id if v else None,
            video_url=v.video_url if v else None,
            title=(v.title if v else None) or self.meta.get("title"),  # type: ignore[arg-type]
            channel=v.channel if v else None,
            video_type=self.meta.get("video_type") or (v.video_type if v else None),  # type: ignore[arg-type]
            language=self.meta.get("language"),  # type: ignore[arg-type]
            transcript_source=self.meta.get("transcript_source", "youtube_captions"),  # type: ignore[arg-type]
            is_live=is_live,
            duration_seconds=(v.duration_seconds if v else None) or self.meta.get("duration_seconds"),  # type: ignore[arg-type]
            transcript=segs,
            full_text=build_full_text(segs),
            total_segments=len(segs),
            language_name=self.meta.get("language_name"),  # type: ignore[arg-type]
            caption_type=self.meta.get("caption_type"),  # type: ignore[arg-type]
            translated_from=self.meta.get("translated_from"),  # type: ignore[arg-type]
            has_timestamps=True,
            timestamp_reference=self.meta.get("timestamp_reference", "video_start"),  # type: ignore[arg-type]
            generated_at=now_iso(),
        )

    def current_result(self) -> Optional[TranscriptResult]:
        """Final result, or the partial transcript collected so far for live sessions."""
        if self.result is not None:
            return self.result
        if self.kind == "live" and len(self.collector) and self.state != "cancelled":
            return self.build_result()
        return None

    def status(self, include_result: bool = False) -> JobStatus:
        with self._lock:
            live = None
            if self.live is not None:
                live = self.live.model_copy(update={"collected_segments": len(self.collector)})
            return JobStatus(
                job_id=self.id,
                kind=self.kind,  # type: ignore[arg-type]
                state=self.state,  # type: ignore[arg-type]
                stage=self.stage,
                stages=[StageInfo(key=k, label=self.stage_labels[k], status=v) for k, v in self.stage_status.items()],  # type: ignore[arg-type]
                progress=self.progress,
                message=self.message,
                video=self.video,
                error=self.error,
                segments_count=len(self.collector) if self.result is None else self.result.total_segments,
                live=live,
                include_timestamps=self.include_timestamps,
                created_at=_iso(self.created),
                updated_at=_iso(self.updated),
                expires_at=_iso(self.expires_at),
                result=self.current_result() if include_result else None,
            )


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._expired: "OrderedDict[str, None]" = OrderedDict()
        self._lock = threading.Lock()

    def add(self, job: Job) -> Job:
        settings = get_settings()
        self.purge_expired()
        with self._lock:
            if len(self._jobs) >= settings.max_jobs:
                raise AppError("server_busy", "The server is handling too many jobs. Please retry shortly.", 503)
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            expired = job_id in self._expired
        if job is not None and job.is_terminal and job.expires_at < time.time():
            self._expire(job)
            job, expired = None, True
        if job is None:
            if expired:
                raise AppError("job_expired", "This transcript has expired and was deleted. Please generate it again.", 410)
            raise AppError("job_not_found", "Transcript job not found.", 404)
        return job

    def active_live_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.kind == "live" and j.state == "live")

    def active_count(self, kind: str) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.kind == kind and not j.is_terminal)

    def _expire(self, job: Job) -> None:
        job.cancel_event.set()
        job.stop_event.set()
        job.cleanup_files()
        with self._lock:
            self._jobs.pop(job.id, None)
            self._expired[job.id] = None
            while len(self._expired) > 5000:
                self._expired.popitem(last=False)

    def purge_expired(self) -> int:
        now = time.time()
        with self._lock:
            victims = [j for j in self._jobs.values() if j.is_terminal and j.expires_at < now]
        for j in victims:
            self._expire(j)
        return len(victims)

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for j in jobs:
            j.cancel_event.set()
            j.stop_event.set()
            j.cleanup_files()


store = JobStore()
