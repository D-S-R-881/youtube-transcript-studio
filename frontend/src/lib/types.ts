// Mirrors backend/app/schemas.py

export type VideoType = "regular" | "short" | "live" | "live_replay" | "upcoming" | "unavailable" | "unknown";
export type JobState = "queued" | "running" | "live" | "completed" | "failed" | "cancelled";
export type StageStatus = "pending" | "active" | "done" | "skipped" | "error";
export type TranscriptSourceSetting = "auto" | "captions" | "speech_to_text";
export type TranscriptSource =
  | "youtube_captions"
  | "speech_to_text"
  | "youtube_live_captions"
  | "live_speech_to_text"
  | "uploaded_file_stt"
  | "txt_import";

export interface Segment {
  id: number;
  start: number | null;
  end: number | null;
  duration: number | null;
  text: string;
}

export interface CaptionTrack {
  language_code: string;
  language: string;
  is_generated: boolean;
  is_translatable: boolean;
}

export interface TranslationLanguage {
  language_code: string;
  language: string;
}

export interface VideoInfo {
  video_id: string;
  video_url: string;
  title: string | null;
  channel: string | null;
  channel_url: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  video_type: VideoType;
  is_live: boolean | null;
  live_status: "live" | "upcoming" | "was_live" | "not_live" | null;
  scheduled_start: string | null;
  actual_start: string | null;
  availability: "available" | "private" | "deleted" | "restricted" | "unavailable" | "unknown";
  availability_reason: string | null;
  metadata_source: string;
  caption_tracks: CaptionTrack[] | null;
  translation_languages: TranslationLanguage[] | null;
  captions_status: string | null;
  captions_message: string | null;
}

export interface TranscriptResult {
  video_id: string | null;
  video_url: string | null;
  title: string | null;
  channel: string | null;
  video_type: string | null;
  language: string | null;
  transcript_source: TranscriptSource;
  is_live: boolean | null;
  duration_seconds: number | null;
  transcript: Segment[];
  full_text: string;
  total_segments: number;
  language_name: string | null;
  caption_type: "manual" | "auto_generated" | null;
  translated_from: string | null;
  has_timestamps: boolean;
  timestamp_reference: "video_start" | "stream_start" | "session_start" | null;
  generated_at: string;
}

export interface JobError {
  code: string;
  message: string;
  hint: string | null;
}

export interface StageInfo {
  key: string;
  label: string;
  status: StageStatus;
}

export interface LiveStats {
  mode: "captions" | "audio";
  is_live: boolean;
  started_at: string;
  collected_segments: number;
  delay_seconds: number | null;
  audio_seconds_processed: number | null;
  max_session_seconds: number;
  stopped: boolean;
  stop_reason: string | null;
}

export interface JobStatus {
  job_id: string;
  kind: "video" | "live" | "upload";
  state: JobState;
  stage: string;
  stages: StageInfo[];
  progress: number | null;
  message: string | null;
  video: VideoInfo | null;
  error: JobError | null;
  segments_count: number;
  live: LiveStats | null;
  include_timestamps: boolean;
  created_at: string;
  updated_at: string;
  expires_at: string;
  result: TranscriptResult | null;
}

export interface Capabilities {
  captions: boolean;
  speech_to_text: boolean;
  speech_to_text_reason: string | null;
  youtube_audio_ingestion: boolean;
  youtube_audio_reason: string | null;
  live_captions: boolean;
  live_audio: boolean;
  file_upload: boolean;
  ffmpeg: boolean;
  metadata_source: string;
  whisper_model: string | null;
  max_upload_mb: number;
  max_audio_duration_seconds: number;
  job_ttl_seconds: number;
}

export interface TranscriptSettings {
  language: string;
  includeTimestamps: boolean;
  source: TranscriptSourceSetting;
  liveMode: "continuous" | "timed";
  liveMaxMinutes: number;
}
