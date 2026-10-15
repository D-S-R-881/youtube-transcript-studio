"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { buildFullText } from "@/lib/transcript-format";
import type { JobError, JobStatus, Segment, TranscriptResult, TranscriptSettings } from "@/lib/types";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const LIVE_META_REFRESH_MS = 5000;

export interface TranscriptJobState {
  job: JobStatus | null;
  result: TranscriptResult | null;
  liveSegments: Segment[];
  requestError: JobError | null;
  starting: boolean;
}

/** Merge an SSE batch that starts at `fromIndex` into the existing list. */
export function mergeSegmentBatch(existing: Segment[], fromIndex: number, batch: Segment[]): Segment[] {
  if (fromIndex > existing.length) return existing; // gap: wait for a resync
  if (fromIndex === existing.length) return existing.concat(batch);
  return existing.slice(0, fromIndex).concat(batch);
}

export function useTranscriptJob() {
  const [state, setState] = useState<TranscriptJobState>({
    job: null,
    result: null,
    liveSegments: [],
    requestError: null,
    starting: false,
  });
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const lastMetaFetch = useRef(0);

  const closeStreams = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  useEffect(() => closeStreams, [closeStreams]);

  const fetchFinal = useCallback(async (id: string) => {
    try {
      const full = await api.job(id);
      if (jobIdRef.current !== id) return;
      setState((s) => ({
        ...s,
        job: full,
        result: full.state === "completed" ? full.result : full.kind === "live" ? full.result : null,
      }));
    } catch (e) {
      const err = e as ApiError;
      setState((s) => ({ ...s, requestError: { code: err.code, message: err.message, hint: err.hint } }));
    }
  }, []);

  const refreshLiveMeta = useCallback(async (id: string) => {
    const now = Date.now();
    if (now - lastMetaFetch.current < LIVE_META_REFRESH_MS) return;
    lastMetaFetch.current = now;
    try {
      const full = await api.job(id);
      if (jobIdRef.current === id && full.result) setState((s) => ({ ...s, result: full.result }));
    } catch {
      /* transient; the stream keeps going */
    }
  }, []);

  const startPolling = useCallback(
    (id: string) => {
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        try {
          const full = await api.job(id);
          if (jobIdRef.current !== id) return;
          setState((s) => ({
            ...s,
            job: full,
            liveSegments: full.kind === "live" && full.result ? full.result.transcript : s.liveSegments,
            result: full.state === "completed" || full.kind === "live" ? full.result : null,
          }));
          if (TERMINAL.has(full.state)) closeStreams();
        } catch (e) {
          const err = e as ApiError;
          if (err.status === 404 || err.status === 410) {
            closeStreams();
            const hint =
              err.hint ??
              (err.status === 404
                ? "The server may have restarted (jobs are kept in memory only). Please generate the transcript again."
                : null);
            setState((s) => ({ ...s, requestError: { code: err.code, message: err.message, hint } }));
          }
        }
      }, 2000);
    },
    [closeStreams],
  );

  const follow = useCallback(
    (initial: JobStatus) => {
      closeStreams();
      jobIdRef.current = initial.job_id;
      lastMetaFetch.current = 0;
      setState({ job: initial, result: null, liveSegments: [], requestError: null, starting: false });

      const id = initial.job_id;
      const es = new EventSource(api.eventsUrl(id, 0));
      esRef.current = es;
      let errors = 0;

      es.addEventListener("segments", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data) as { from_index: number; segments: Segment[] };
        setState((s) => ({ ...s, liveSegments: mergeSegmentBatch(s.liveSegments, data.from_index, data.segments) }));
      });
      es.addEventListener("status", (ev) => {
        errors = 0;
        const status = JSON.parse((ev as MessageEvent).data) as JobStatus;
        setState((s) => ({ ...s, job: { ...status, result: s.job?.result ?? null } }));
        if (status.kind === "live" && status.state === "live") void refreshLiveMeta(id);
        if (TERMINAL.has(status.state)) {
          closeStreams();
          void fetchFinal(id);
        }
      });
      es.addEventListener("done", () => {
        closeStreams();
        void fetchFinal(id);
      });
      es.onerror = () => {
        errors += 1;
        if (es.readyState === EventSource.CLOSED || errors > 3) {
          es.close();
          esRef.current = null;
          startPolling(id);
        }
      };
    },
    [closeStreams, fetchFinal, refreshLiveMeta, startPolling],
  );

  const handleStartError = useCallback((e: unknown) => {
    const err = e instanceof ApiError ? e : new ApiError("unknown", "Something went wrong.", 0);
    setState((s) => ({ ...s, starting: false, requestError: { code: err.code, message: err.message, hint: err.hint } }));
  }, []);

  const start = useCallback(
    async (url: string, settings: TranscriptSettings) => {
      closeStreams();
      jobIdRef.current = null;
      setState({ job: null, result: null, liveSegments: [], requestError: null, starting: true });
      try {
        follow(await api.startTranscript(url, settings));
      } catch (e) {
        handleStartError(e);
      }
    },
    [closeStreams, follow, handleStartError],
  );

  const startUpload = useCallback(
    async (file: File, language: string, includeTimestamps: boolean) => {
      closeStreams();
      jobIdRef.current = null;
      setState({ job: null, result: null, liveSegments: [], requestError: null, starting: true });
      try {
        follow(await api.uploadMedia(file, language, includeTimestamps));
      } catch (e) {
        handleStartError(e);
      }
    },
    [closeStreams, follow, handleStartError],
  );

  const cancel = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    try {
      const status = await api.cancel(id);
      setState((s) => ({ ...s, job: status, result: null }));
    } catch (e) {
      const err = e as ApiError;
      setState((s) => ({ ...s, requestError: { code: err.code, message: err.message, hint: err.hint } }));
    }
  }, []);

  const stopLive = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    try {
      await api.stopLive(id);
    } catch (e) {
      const err = e as ApiError;
      setState((s) => ({ ...s, requestError: { code: err.code, message: err.message, hint: err.hint } }));
    }
    void fetchFinal(id);
  }, [fetchFinal]);

  const reset = useCallback(() => {
    closeStreams();
    jobIdRef.current = null;
    setState({ job: null, result: null, liveSegments: [], requestError: null, starting: false });
  }, [closeStreams]);

  return { ...state, start, startUpload, cancel, stopLive, reset };
}

/** For an in-progress live session, combine server metadata with streamed segments. */
export function liveResultFrom(result: TranscriptResult | null, job: JobStatus, segments: Segment[]): TranscriptResult {
  const v = job.video;
  const base: TranscriptResult = result ?? {
    video_id: v?.video_id ?? null,
    video_url: v?.video_url ?? null,
    title: v?.title ?? null,
    channel: v?.channel ?? null,
    video_type: "live",
    language: null,
    transcript_source: job.live?.mode === "audio" ? "live_speech_to_text" : "youtube_live_captions",
    is_live: true,
    duration_seconds: null,
    transcript: [],
    full_text: "",
    total_segments: 0,
    language_name: null,
    caption_type: null,
    translated_from: null,
    has_timestamps: true,
    timestamp_reference: job.live?.mode === "audio" ? "session_start" : "stream_start",
    generated_at: new Date().toISOString(),
  };
  const transcript = segments.length >= base.transcript.length ? segments : base.transcript;
  return { ...base, transcript, full_text: buildFullText(transcript), total_segments: transcript.length };
}
