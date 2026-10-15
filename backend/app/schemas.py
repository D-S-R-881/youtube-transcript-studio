from typing import List, Literal, Optional

from pydantic import BaseModel, Field

VideoType = Literal["regular", "short", "live", "live_replay", "upcoming", "unavailable", "unknown"]
Availability = Literal["available", "private", "deleted", "restricted", "unavailable", "unknown"]
LiveStatus = Literal["live", "upcoming", "was_live", "not_live"]
TranscriptSource = Literal[
    "youtube_captions",
    "speech_to_text",
    "youtube_live_captions",
    "live_speech_to_text",
    "uploaded_file_stt",
    "txt_import",
]
JobState = Literal["queued", "running", "live", "completed", "failed", "cancelled"]
StageStatus = Literal["pending", "active", "done", "skipped", "error"]


class Segment(BaseModel):
    id: int
    start: Optional[float] = None
    end: Optional[float] = None
    duration: Optional[float] = None
    text: str


class CaptionTrack(BaseModel):
    language_code: str
    language: str
    is_generated: bool
    is_translatable: bool


class TranslationLanguage(BaseModel):
    language_code: str
    language: str


class VideoInfo(BaseModel):
    video_id: str
    video_url: str
    title: Optional[str] = None
    channel: Optional[str] = None
    channel_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    video_type: VideoType = "unknown"
    is_live: Optional[bool] = None
    live_status: Optional[LiveStatus] = None
    scheduled_start: Optional[str] = None
    actual_start: Optional[str] = None
    availability: Availability = "unknown"
    availability_reason: Optional[str] = None
    metadata_source: str = "none"
    caption_tracks: Optional[List[CaptionTrack]] = None
    translation_languages: Optional[List[TranslationLanguage]] = None
    captions_status: Optional[str] = None
    captions_message: Optional[str] = None


class TranscriptRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    language: str = Field("auto", max_length=16, pattern=r"^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*)$")
    include_timestamps: bool = True
    source: Literal["auto", "captions", "speech_to_text"] = "auto"
    live_mode: Literal["continuous", "timed"] = "continuous"
    live_max_minutes: Optional[int] = Field(None, ge=1, le=240)


class TranscriptResult(BaseModel):
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    title: Optional[str] = None
    channel: Optional[str] = None
    video_type: Optional[str] = None
    language: Optional[str] = None
    transcript_source: TranscriptSource
    is_live: Optional[bool] = None
    duration_seconds: Optional[float] = None
    transcript: List[Segment]
    full_text: str
    total_segments: int
    language_name: Optional[str] = None
    caption_type: Optional[Literal["manual", "auto_generated"]] = None
    translated_from: Optional[str] = None
    has_timestamps: bool = True
    timestamp_reference: Optional[Literal["video_start", "stream_start", "session_start"]] = None
    generated_at: str


class JobError(BaseModel):
    code: str
    message: str
    hint: Optional[str] = None


class StageInfo(BaseModel):
    key: str
    label: str
    status: StageStatus


class LiveStats(BaseModel):
    mode: Literal["captions", "audio"]
    is_live: bool
    started_at: str
    collected_segments: int
    delay_seconds: Optional[float] = None
    audio_seconds_processed: Optional[float] = None
    max_session_seconds: int
    stopped: bool = False
    stop_reason: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    kind: Literal["video", "live", "upload"]
    state: JobState
    stage: str
    stages: List[StageInfo]
    progress: Optional[float] = Field(None, description="0..1 when measurable, null when indeterminate")
    message: Optional[str] = None
    video: Optional[VideoInfo] = None
    error: Optional[JobError] = None
    segments_count: int = 0
    live: Optional[LiveStats] = None
    include_timestamps: bool = True
    created_at: str
    updated_at: str
    expires_at: str
    result: Optional[TranscriptResult] = None


class TxtToJsonRequest(BaseModel):
    text: str
    title: Optional[str] = Field(None, max_length=300)


class Capabilities(BaseModel):
    captions: bool
    speech_to_text: bool
    speech_to_text_reason: Optional[str] = None
    youtube_audio_ingestion: bool
    youtube_audio_reason: Optional[str] = None
    live_captions: bool
    live_audio: bool
    file_upload: bool
    ffmpeg: bool
    metadata_source: str
    whisper_model: Optional[str] = None
    max_upload_mb: int
    max_audio_duration_seconds: int
    job_ttl_seconds: int
