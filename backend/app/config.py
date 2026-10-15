from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cors_origins: str = "http://localhost:3000"
    # Optional regex for extra origins, e.g. Vercel preview deployments.
    cors_origin_regex: str = ""

    youtube_api_key: str = ""
    captions_proxy_http: str = ""
    captions_proxy_https: str = ""

    stt_enabled: bool = True
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    max_concurrent_stt_jobs: int = 1

    enable_youtube_audio_ingestion: bool = False
    ffmpeg_path: str = "ffmpeg"

    max_audio_duration_seconds: int = 3 * 60 * 60
    max_upload_mb: int = 500
    max_txt_convert_mb: int = 20

    live_max_sessions: int = 2
    live_max_session_seconds: int = 4 * 60 * 60
    live_chunk_seconds: int = 15
    live_caption_poll_seconds: int = 20

    job_ttl_seconds: int = 3600
    max_jobs: int = 500

    rate_limit_per_minute: int = 30
    rate_limit_job_create_per_minute: int = 6
    trust_proxy_headers: bool = False

    @property
    def cors_origin_list(self) -> List[str]:
        # A wildcard is never honoured: origins must be listed explicitly.
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip() and o.strip() != "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
