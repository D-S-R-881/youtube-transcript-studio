import type { Capabilities, JobStatus, TranscriptResult, TranscriptSettings, VideoInfo } from "./types";

// Inlined at build time. The localhost fallback applies to development/tests only;
// a production build without it reports a configuration error instead.
const DEV_API_BASE_URL = process.env.NODE_ENV === "production" ? "" : "http://localhost:8000";
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEV_API_BASE_URL).replace(/\/+$/, "");
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public hint: string | null = null,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE_URL) {
    throw new ApiError(
      "config_error",
      "The transcript server URL is not configured. Set NEXT_PUBLIC_API_BASE_URL and redeploy the frontend.",
      0,
    );
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, cache: "no-store" });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(
      "network_error",
      "Could not reach the transcript server. If it was idle it may take up to a minute to wake up — please try again.",
      0,
    );
  }
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; hint?: string | null } } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(
      body.error?.code ?? `http_${res.status}`,
      body.error?.message ?? `Request failed with status ${res.status}.`,
      res.status,
      body.error?.hint ?? null,
    );
  }
  return res.json() as Promise<T>;
}

export const api = {
  capabilities: () => request<Capabilities>("/api/capabilities"),

  videoInfo: (url: string, signal?: AbortSignal) =>
    request<VideoInfo>(`/api/video/info?url=${encodeURIComponent(url)}`, { signal }),

  startTranscript: (url: string, s: TranscriptSettings) =>
    request<JobStatus>("/api/transcript", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        language: s.language,
        include_timestamps: s.includeTimestamps,
        source: s.source,
        live_mode: s.liveMode,
        live_max_minutes: s.liveMode === "timed" ? s.liveMaxMinutes : null,
      }),
    }),

  uploadMedia: (file: File, language: string, includeTimestamps: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("language", language);
    form.append("include_timestamps", String(includeTimestamps));
    return request<JobStatus>("/api/transcript/upload", { method: "POST", body: form });
  },

  job: (id: string) => request<JobStatus>(`/api/transcript/${id}`),
  cancel: (id: string) => request<JobStatus>(`/api/transcript/${id}/cancel`, { method: "POST" }),
  stopLive: (id: string) => request<JobStatus>(`/api/transcript/${id}/stop`, { method: "POST" }),
  eventsUrl: (id: string, since = 0) => `${API_BASE_URL}/api/transcript/${id}/events?since=${since}`,

  convertTxt: (input: { file: File } | { text: string; title?: string }) => {
    if ("file" in input) {
      const form = new FormData();
      form.append("file", input.file);
      return request<TranscriptResult>("/api/convert/txt-to-json", { method: "POST", body: form });
    }
    return request<TranscriptResult>("/api/convert/txt-to-json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  },
};
