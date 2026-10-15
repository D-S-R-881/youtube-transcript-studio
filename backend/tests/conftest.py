import os

os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("RATE_LIMIT_JOB_CREATE_PER_MINUTE", "100000")
os.environ.setdefault("YOUTUBE_API_KEY", "")
os.environ.setdefault("ENABLE_YOUTUBE_AUDIO_INGESTION", "false")
