FROM python:3.11-slim

# Set INSTALL_STT=true to bake in Faster-Whisper, yt-dlp and FFmpeg.
ARG INSTALL_STT=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-stt.txt ./
RUN if [ "$INSTALL_STT" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* && \
        pip install -r requirements-stt.txt ; \
    else \
        pip install -r requirements.txt ; \
    fi

COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

# Render (and most PaaS hosts) inject PORT; default to 8000 elsewhere.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers --timeout-keep-alive 75"]
