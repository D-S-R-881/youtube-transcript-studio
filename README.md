# YouTube Transcript Studio

Convert YouTube videos, Shorts, completed livestreams, active livestreams (where a real source exists), and your own audio/video files into clean **TXT** and structured **JSON** transcripts.

- **Frontend:** Next.js 15 (App Router) · TypeScript · Tailwind CSS v4 · shadcn/ui · Lucide · Framer Motion
- **Backend:** FastAPI · youtube-transcript-api · Faster-Whisper (optional) · FFmpeg (optional) · yt-dlp (optional, opt-in) · Server-Sent Events

There are no placeholder transcripts or simulated live text. Every transcript shown in the UI comes from a real caption track, a real speech-to-text run, or text you pasted. If extraction fails, the UI shows the error and never a "successful" empty result.

---

## What works, and what it needs

| Capability | Out of the box | Requires |
|---|---|---|
| URL validation (watch, youtu.be, `/live/`, `/shorts/`, `/embed/`, `m.`/`music.`, `feature=share`, `list=`, `t=`) | ✅ | — |
| Video metadata and type detection (regular / Short / live / completed live / upcoming / private / deleted / restricted) | ✅ (watch page and oEmbed) | `YOUTUBE_API_KEY` for more reliable data |
| Captions: manual preferred over auto-generated, language choice, YouTube translation | ✅ | — |
| Completed livestream (replay) captions | ✅ when YouTube has published captions for the replay | — |
| Uploaded audio/video file → transcript | ❌ | `pip install -r requirements-stt.txt` (Faster-Whisper). FFmpeg is recommended for video containers |
| Speech-to-text fallback for YouTube videos without captions | ❌ (disabled by default) | STT stack, `ENABLE_YOUTUBE_AUDIO_INGESTION=true`, and **your permission to process that media** |
| Active livestream: live captions | ⚠️ Polled when YouTube exposes a caption track for the live broadcast (uncommon) | — |
| Active livestream: real-time speech-to-text | ❌ | STT stack, FFmpeg, yt-dlp, `ENABLE_YOUTUBE_AUDIO_INGESTION=true` |
| TXT / SRT / VTT → JSON converter | ✅ | — |

`GET /api/capabilities` reports exactly which of these are enabled on the running server, and the UI adapts. For example, the upload tab explains when STT isn't installed.

When an active livestream has no reachable source, the job fails with:

> This livestream is active, but live transcription is not available through the configured sources.

and a hint that names the missing piece (no live captions, STT not installed, or audio ingestion disabled).

### Honest limitations

- **YouTube may block caption requests** from cloud/datacenter IPs (`RequestBlocked` / `IpBlocked`). This is common on AWS/GCP/Azure/Render/Fly. Configure `CAPTIONS_PROXY_HTTP(S)` with a residential or rotating proxy if you deploy to a cloud host. Locally on a home connection it normally works.
- **Live captions are rarely available** while a stream is in progress. Most broadcasts only get captions after they end. True live transcription needs audio access plus STT.
- **Audio download from YouTube is off by default.** A public URL does not grant permission to download its audio. Enable it only for content you own or are licensed to process, and in line with YouTube's Terms of Service.
- **STT accuracy and speed** depend on the Whisper model and hardware. `base` on CPU runs roughly at real time or better for short files; long files take a while. Live STT adds the chunk length (default 15 s) plus inference time as delay, and the UI shows the measured delay.
- **Timestamps:** imported TXT without timestamps produces segments with `start/end/duration = null`. The converter never invents timings.
- **Storage is in-memory.** Jobs and transcripts are deleted after `JOB_TTL_SECONDS` (default 1 h) and are never written to disk, apart from temporary media files that are deleted when the job ends. Run a **single backend instance**: multiple workers or replicas do not share jobs.

---

## Project layout

```
youtube-transcript-studio/
├── backend/                 FastAPI service
│   ├── app/
│   │   ├── api/             routes (transcripts, live, convert, info)
│   │   ├── core/            errors, rate limiting
│   │   ├── services/        url parser, metadata, captions, stt, audio, jobs, pipeline, formatting, txt parser
│   │   ├── config.py        environment settings
│   │   └── main.py          app factory, CORS, middleware, janitor
│   ├── tests/               pytest suite (mocks only here)
│   ├── requirements.txt     core dependencies (what the production image installs)
│   ├── requirements-dev.txt core + pytest
│   ├── requirements-stt.txt optional STT stack
│   ├── .env.example
│   └── Dockerfile
├── frontend/                Next.js app
│   ├── src/app/             layout, page, global styles
│   ├── src/components/      UI (input, settings, preview, processing, results, JSON viewer, converter)
│   ├── src/hooks/           job orchestration (SSE + polling fallback)
│   ├── src/lib/             API client, URL parser, formatting, clipboard, downloads (+ tests)
│   ├── .env.example
│   └── Dockerfile
├── docker-compose.yml
└── render.yaml              Render Blueprint for the backend
```

---

## Installation and local development

### Prerequisites

- **Python 3.9+** (3.11 recommended)
- **Node.js 20+** and npm
- Optional: **FFmpeg** on `PATH` (required for live STT and recommended for video uploads)

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt   # core API + pytest
# Optional speech-to-text (Faster-Whisper + yt-dlp):
pip install -r requirements-stt.txt

cp .env.example .env        # Windows: copy .env.example .env
uvicorn app.main:app --reload --reload-dir app --port 8000
```

`--reload-dir app` keeps package installs in `.venv` from restarting the server. Restarts clear in-progress jobs, because jobs are held in memory.

The API runs at <http://localhost:8000>, with interactive docs at <http://localhost:8000/docs>.

The first STT job downloads the configured Whisper model (about 150 MB for `base`) into the Hugging Face cache.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local  # Windows: copy .env.example .env.local
npm run dev
```

Open <http://localhost:3000>.

### 3. Tests

```bash
# Backend: URL parsing, formatting, TXT parser, dedupe, caption selection,
# metadata parsing, API endpoints, jobs, live sessions, cancel, expiry, rate limiting
cd backend && pytest

# Frontend: URL validation, TXT/JSON formatting, filenames, clipboard,
# downloads, SSE segment merging
cd frontend && npm test
npm run typecheck
npm run lint
```

---

## Configuration

### Backend (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated exact frontend origins (no trailing slash; `*` is ignored) |
| `CORS_ORIGIN_REGEX` | — | Optional regex for extra origins, e.g. Vercel preview URLs |
| `YOUTUBE_API_KEY` | — | Optional YouTube Data API v3 key (server-side only) |
| `CAPTIONS_PROXY_HTTP` / `CAPTIONS_PROXY_HTTPS` | — | Proxy for caption requests |
| `STT_ENABLED` | `true` | Use Faster-Whisper if installed |
| `WHISPER_MODEL` | `base` | `tiny`, `base`, `small`, `medium`, `large-v3`, … |
| `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | `cpu` / `int8` | e.g. `cuda` / `float16` on GPU |
| `MAX_CONCURRENT_STT_JOBS` | `1` | Concurrent transcription slots |
| `ENABLE_YOUTUBE_AUDIO_INGESTION` | `false` | Allow yt-dlp audio access for YouTube URLs (permission required) |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg binary |
| `MAX_AUDIO_DURATION_SECONDS` | `10800` | Reject longer media for STT |
| `MAX_UPLOAD_MB` / `MAX_TXT_CONVERT_MB` | `500` / `20` | Upload limits |
| `LIVE_MAX_SESSIONS` | `2` | Concurrent live sessions |
| `LIVE_MAX_SESSION_SECONDS` | `14400` | Hard cap per live session |
| `LIVE_CHUNK_SECONDS` | `15` | Live STT audio chunk length |
| `LIVE_CAPTION_POLL_SECONDS` | `20` | Live caption polling interval |
| `JOB_TTL_SECONDS` / `MAX_JOBS` | `3600` / `500` | In-memory retention |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_JOB_CREATE_PER_MINUTE` | `30` / `6` | Per-IP limits |
| `TRUST_PROXY_HEADERS` | `false` | Use `X-Forwarded-For` for client IP (only behind a trusted proxy) |

### Frontend (`frontend/.env.local`)

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` in development only | Browser-facing backend URL, inlined at **build time**. Production builds have no fallback: if it's missing, the UI shows a configuration error. Public by design and contains no secrets |

All secrets (API key, proxy credentials) stay on the backend. The frontend never sees them.

---

## API reference

All errors use the shape `{"error": {"code", "message", "hint"}}`.

| Method & path | Description |
|---|---|
| `GET /api/health` | Liveness |
| `GET /api/capabilities` | Which sources are enabled (captions, STT, audio ingestion, FFmpeg, limits) |
| `GET /api/video/info?url=` | Validate a URL and return metadata, video type, and caption tracks |
| `POST /api/transcript` | Start a job: `{url, language="auto", include_timestamps=true, source="auto"\|"captions"\|"speech_to_text", live_mode="continuous"\|"timed", live_max_minutes}` → `202` with job status |
| `POST /api/transcript/upload` | Multipart `file` (+ `language`, `include_timestamps`) → STT job |
| `GET /api/transcript/{id}` | Job status, stages, progress, live stats, result |
| `GET /api/transcript/{id}/events` | SSE stream: `status`, `segments` (with `id`, resumable via `Last-Event-ID`), `done` |
| `POST /api/transcript/{id}/cancel` | Cancel a running job |
| `POST /api/transcript/{id}/stop` | Stop a live session and finalize what was collected |
| `GET /api/transcript/{id}/download/txt` | `youtube_transcript_<id>.txt` or `youtube_live_transcript_<id>.txt` |
| `GET /api/transcript/{id}/download/json` | Same naming, `.json` |
| `POST /api/live` | Start a live session (`409` if the URL is not currently live) |
| `GET /api/live/{id}` · `/events` · `POST /stop` · `GET /export/txt\|json` | Live aliases. Export works mid-session (partial transcript) |
| `POST /api/convert/txt-to-json` | `{text, title?}` JSON or multipart `file` (.txt/.srt/.vtt) → transcript JSON |

Expired jobs return `410`. Downloads requested before completion return `409`.

### JSON output

```json
{
  "video_id": "dQw4w9WgXcQ",
  "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "…",
  "channel": "…",
  "video_type": "regular",
  "language": "en",
  "transcript_source": "youtube_captions",
  "is_live": false,
  "duration_seconds": 213,
  "transcript": [
    { "id": 1, "start": 1.36, "end": 3.04, "duration": 1.68, "text": "♪ We're no strangers to love ♪" }
  ],
  "full_text": "…",
  "total_segments": 61,
  "language_name": "English",
  "caption_type": "manual",
  "translated_from": null,
  "has_timestamps": true,
  "timestamp_reference": "video_start",
  "generated_at": "2026-10-13T12:00:00Z"
}
```

`transcript_source` is one of `youtube_captions`, `youtube_live_captions`, `speech_to_text`, `live_speech_to_text`, `uploaded_file_stt`, or `txt_import`. `timestamp_reference` tells you what `start` is relative to: `video_start`, `stream_start` (live captions), or `session_start` (live STT, where the stream start can't be known).

---

## Deployment

### Free hosting: GitHub + Render (backend) + Vercel (frontend)

Both services build from the same GitHub repository. Deploy the backend first, because the frontend needs its URL at build time.

#### 1. Push to GitHub

```bash
cd youtube-transcript-studio
git init -b main            # skip if already a repo
git add .
git commit -m "YouTube Transcript Studio"
git remote add origin https://github.com/<you>/youtube-transcript-studio.git
git push -u origin main
```

`.gitignore` excludes `.venv`, `node_modules`, `.next`, caches, and every real `.env` file, while keeping both `.env.example` files.

#### 2. Backend on Render (free Docker web service)

**Option A, Blueprint:** Render Dashboard → **New → Blueprint** → pick the repo. `render.yaml` defines the service. Enter `CORS_ORIGINS` when prompted (you can use a placeholder and fix it after step 3). Leave the other prompted values empty if unused.

**Option B, manual:** **New → Web Service** → pick the repo, then set:

| Setting | Value |
|---|---|
| Language / Runtime | Docker |
| Branch | `main` |
| Root Directory | *(empty)* |
| Dockerfile Path | `./backend/Dockerfile` |
| Docker Build Context Directory | `./backend` |
| Docker Command | *(empty: the Dockerfile's CMD binds `0.0.0.0:$PORT`)* |
| Instance Type | Free |
| Health Check Path | `/api/health` |

Environment variables (Render → service → Environment):

| Key | Value | Required |
|---|---|---|
| `CORS_ORIGINS` | `https://<your-project>.vercel.app` (exact, no trailing slash; comma-separate several) | Yes |
| `TRUST_PROXY_HEADERS` | `true` (otherwise every user shares one rate-limit bucket: Render's proxy IP) | Yes |
| `STT_ENABLED` | `false` (the default image doesn't include Whisper) | Recommended |
| `ENABLE_YOUTUBE_AUDIO_INGESTION` | `false` | Recommended |
| `MAX_UPLOAD_MB` | `100` | Optional |
| `CORS_ORIGIN_REGEX` | `^https://<your-project>-[a-z0-9]+-<your-team>\.vercel\.app$` to allow Vercel preview deployments | Optional |
| `CAPTIONS_PROXY_HTTP` / `CAPTIONS_PROXY_HTTPS` | Residential proxy URL (see limitations below) | Often needed in practice |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key | Optional |

Don't set `PORT`: Render provides it (default `10000`), and the container listens on it. After the deploy, check `https://<service>.onrender.com/api/health` → `{"status":"ok"}` and `/api/capabilities`.

What the image contains: `python:3.11-slim` plus `requirements.txt` only (FastAPI, uvicorn, httpx, pydantic, youtube-transcript-api). Caption extraction needs **no OS packages**, so the default image installs no FFmpeg. FFmpeg, Faster-Whisper, and yt-dlp are installed only with the build arg `INSTALL_STT=true`. Don't use that on the free plan: its 512 MB RAM is not enough to run Whisper reliably.

#### 3. Frontend on Vercel (Hobby)

Vercel → **Add New → Project** → import the repo, then set:

| Setting | Value |
|---|---|
| Framework Preset | Next.js (auto-detected) |
| Root Directory | `frontend` |
| Build Command | `npm run build` (default) |
| Install Command | `npm install` (default; uses `package-lock.json`) |
| Output Directory | *(default)* |
| Environment variable | `NEXT_PUBLIC_API_BASE_URL` = `https://<service>.onrender.com` (no trailing slash), for Production (and Preview if you use previews) |

`NEXT_PUBLIC_*` values are inlined at build time, so **redeploy the frontend after changing it**.

#### 4. Connect them

Copy the Vercel production URL (e.g. `https://youtube-transcript-studio.vercel.app`) into Render's `CORS_ORIGINS` and save, which redeploys the backend. Then open the Vercel URL, paste a YouTube link, and generate.

#### What to expect on the free tiers

- **Cold starts:** Render free services sleep after about 15 minutes without traffic, and the first request then takes roughly a minute. The UI retries loading server capabilities and tells the user the server may be waking up.
- **Restarts lose jobs:** jobs live in memory only (by design: nothing is stored permanently). A sleep, redeploy, or crash discards in-progress and finished jobs. The UI then reports "Transcript job not found" with a hint to generate again. Results already shown in the browser can still be copied and downloaded, because those actions run client-side.
- **Ephemeral disk:** only per-job temp files are written, under `/tmp`. They're deleted when the job ends, and stale ones are swept on startup. Nothing relies on the disk surviving a restart.
- **Single instance:** keep one instance and one worker (the default CMD). Scaling out would split the in-memory job store.

#### Cloud-hosting limitations for YouTube

- **Caption requests are frequently blocked from cloud IPs.** YouTube often answers requests from datacenter ranges (Render included) with a block or a sign-in/bot check. Jobs then fail with an honest error rather than empty output. The only reliable fix is a residential/rotating proxy via `CAPTIONS_PROXY_HTTP(S)`, which is usually a paid service. This can't be verified before deploying: test with a few videos right after your first deploy.
- **Metadata** (title, live status) comes from the public watch page and can hit the same blocking. Setting `YOUTUBE_API_KEY` (free quota) makes metadata and live detection independent of that.
- **Live streams:** detection works, but YouTube rarely exposes captions while a stream is running. With the free deployment (no STT, audio ingestion off), most active streams end with: "This livestream is active, but live transcription is not available through the configured sources." Completed streams work like regular videos once YouTube publishes their captions. Render free also isn't suited to multi-hour live sessions: memory, sleep, and restarts all work against them.
- **File uploads** need speech-to-text. They're disabled on the free deployment, and the UI says so; the backend rejects uploads before receiving the body.

### Docker Compose (single host)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

To include STT in the backend image, set `INSTALL_STT: "true"` in `docker-compose.yml`. When the frontend is served from another domain, rebuild it with that domain's `NEXT_PUBLIC_API_BASE_URL` and add the frontend origin to `CORS_ORIGINS`.

### Split hosting

- **Frontend:** deploy `frontend/` to Vercel, Netlify, or any Node host, setting `NEXT_PUBLIC_API_BASE_URL` to your backend URL.
- **Backend:** any container host (Fly.io, Render, Railway, a VM). Run **one instance** with **one worker**, because job state is in memory. Shared state (Redis) would be needed for horizontal scaling and is not implemented.

### Reverse proxy notes

- Disable response buffering for SSE (`/api/transcript/*/events`, `/api/live/*/events`). In nginx, use `proxy_buffering off;` and `proxy_read_timeout 1h;`. The backend also sends `X-Accel-Buffering: no` and 15 s keep-alives.
- Raise the request body limit to at least `MAX_UPLOAD_MB` (nginx: `client_max_body_size`).
- Set `TRUST_PROXY_HEADERS=true` only when the proxy overwrites `X-Forwarded-For`, so rate limiting sees real client IPs.
- Terminate TLS at the proxy and set `CORS_ORIGINS` to your exact frontend origin.

---

## Security

- **SSRF:** user input is reduced to an 11-character video ID by a strict parser with a host allowlist that rejects credentials, odd ports, and non-YouTube hosts. All outbound URLs are built server-side from that ID. Media URLs resolved by yt-dlp for live audio are checked against a Google media host allowlist.
- **Rate limiting:** per-IP sliding window, with a stricter bucket for job creation and conversion.
- **Uploads:** extension allowlist, size limit while streaming to a temp file, server-generated temp names, and deletion after processing.
- **Filenames:** download names are derived from the validated video ID only.
- **Privacy:** no transcript persistence and no analytics. Data expires from memory after the TTL.
- **Secrets:** server-side only. `.env` files are git-ignored.

## Legal

This tool reads publicly published caption tracks and processes media you provide. Downloading YouTube audio is disabled by default and must only be enabled for content you have rights to process. You are responsible for complying with YouTube's Terms of Service and applicable copyright law.
