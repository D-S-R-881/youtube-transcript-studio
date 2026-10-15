// Client-side mirror of backend/app/services/youtube_url.py. The backend
// re-validates everything; this gives instant feedback before any request.

export type UrlKind = "video" | "short" | "live";

export interface ParsedYouTubeUrl {
  videoId: string;
  urlKind: UrlKind;
  canonicalUrl: string;
}

export type ParseResult =
  | { ok: true; value: ParsedYouTubeUrl }
  | { ok: false; error: string };

const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;
const MAX_URL_LENGTH = 2048;
const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
]);
const SHORT_HOSTS = new Set(["youtu.be", "www.youtu.be"]);
const PATH_PREFIXES: Array<[string, UrlKind]> = [
  ["/live/", "live"],
  ["/shorts/", "short"],
  ["/embed/", "video"],
  ["/v/", "video"],
  ["/e/", "video"],
];

export const isValidVideoId = (id: string) => VIDEO_ID_RE.test(id);
export const canonicalWatchUrl = (id: string) => `https://www.youtube.com/watch?v=${id}`;

function ok(videoId: string, urlKind: UrlKind): ParseResult {
  return { ok: true, value: { videoId, urlKind, canonicalUrl: canonicalWatchUrl(videoId) } };
}

function fail(error: string): ParseResult {
  return { ok: false, error };
}

export function parseYouTubeUrl(raw: unknown): ParseResult {
  if (typeof raw !== "string") return fail("URL must be a string.");
  let url = raw.trim();
  if (!url) return fail("Please paste a YouTube URL.");
  if (url.length > MAX_URL_LENGTH) return fail("URL is too long.");
  if (/[\s\u0000-\u001f]/.test(url)) return fail("URL contains invalid characters.");
  if (!url.includes("://")) url = `https://${url}`;

  // Reject credentials before URL() normalises them away.
  const authority = url.split("://")[1]?.split(/[/?#]/)[0] ?? "";
  if (authority.includes("@")) return fail("URLs with credentials are not allowed.");

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return fail("Malformed URL.");
  }
  const scheme = parsed.protocol.replace(":", "").toLowerCase();
  if (scheme !== "http" && scheme !== "https") return fail("Only http(s) YouTube links are supported.");
  if (parsed.port && parsed.port !== "80" && parsed.port !== "443") return fail("Custom ports are not allowed.");

  const host = parsed.hostname.toLowerCase().replace(/\.$/, "");
  const path = parsed.pathname || "/";

  if (SHORT_HOSTS.has(host)) {
    const id = path.replace(/^\/+/, "").split("/")[0];
    return isValidVideoId(id) ? ok(id, "video") : fail("Could not find a video ID in this youtu.be link.");
  }
  if (!YOUTUBE_HOSTS.has(host)) return fail("This is not a YouTube URL.");

  if (path.replace(/\/$/, "") === "/watch") {
    const v = parsed.searchParams.get("v") ?? "";
    return isValidVideoId(v) ? ok(v, "video") : fail("This YouTube link has no valid video ID.");
  }
  for (const [prefix, kind] of PATH_PREFIXES) {
    if (path.startsWith(prefix)) {
      const id = path.slice(prefix.length).split("/")[0];
      return isValidVideoId(id) ? ok(id, kind) : fail("This YouTube link has no valid video ID.");
    }
  }
  return fail(
    "Unsupported YouTube link. Use a video, Shorts or live URL (channel and playlist pages are not supported).",
  );
}
