// Kept in sync with backend/app/services/formatting.py so client-side TXT
// exports match the backend download endpoints.
import type { Segment, TranscriptResult } from "./types";

const SENTENCE_END_RE = /[.!?\u3002\uff01\uff1f\u0964\u061f\u2026]["')\]\u201d\u2019]*$/;
const PARAGRAPH_GAP_SECONDS = 2.0;
const PARAGRAPH_SOFT_CHARS = 400;

export function formatTimestamp(seconds: number | null | undefined): string {
  const s = seconds == null || !Number.isFinite(seconds) || seconds < 0 ? 0 : Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
}

export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null;
  const ts = formatTimestamp(seconds);
  return ts.startsWith("00:") ? ts.slice(3) : ts;
}

export function buildParagraphs(segments: Segment[]): string[] {
  const paragraphs: string[] = [];
  let current: string[] = [];
  let length = 0;
  let prev: Segment | null = null;
  for (const s of segments) {
    if (current.length && prev) {
      const untimed = s.start == null || prev.start == null;
      let gap: number | null = null;
      if (!untimed) {
        const prevEnd = prev.end ?? prev.start!;
        gap = s.start! - prevEnd;
      }
      const softBreak = length >= PARAGRAPH_SOFT_CHARS && SENTENCE_END_RE.test(current[current.length - 1]);
      if (untimed || (gap != null && gap >= PARAGRAPH_GAP_SECONDS) || softBreak) {
        paragraphs.push(current.join(" "));
        current = [];
        length = 0;
      }
    }
    current.push(s.text);
    length += s.text.length + 1;
    prev = s;
  }
  if (current.length) paragraphs.push(current.join(" "));
  return paragraphs;
}

export function buildTxt(segments: Segment[], includeTimestamps: boolean): string {
  if (!segments.length) return "";
  if (includeTimestamps) {
    return (
      segments.map((s) => (s.start != null ? `[${formatTimestamp(s.start)}] ` : "") + s.text).join("\n\n") + "\n"
    );
  }
  return buildParagraphs(segments).join("\n\n") + "\n";
}

export function buildFullText(segments: Segment[]): string {
  return segments
    .map((s) => s.text)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

export function resultToJson(result: TranscriptResult): string {
  return JSON.stringify(result, null, 2) + "\n";
}

export function isLiveResult(result: Pick<TranscriptResult, "video_type">, kind?: string): boolean {
  return kind === "live" || result.video_type === "live" || result.video_type === "live_replay";
}

export function safeFilename(videoId: string | null | undefined, isLive: boolean, ext: string): string {
  const id = (videoId ?? "").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64) || "transcript";
  const safeExt = ext.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 8) || "txt";
  return `${isLive ? "youtube_live_transcript" : "youtube_transcript"}_${id}.${safeExt}`;
}

export function exportFilename(result: TranscriptResult, ext: "txt" | "json", kind?: string): string {
  if (!result.video_id && result.title) {
    const base = result.title
      .normalize("NFKD")
      .replace(/[^A-Za-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 64);
    return `transcript_${base || "file"}.${ext}`;
  }
  return safeFilename(result.video_id, isLiveResult(result, kind), ext);
}

export function countWords(text: string): number {
  // Intl.Segmenter counts words correctly for CJK/Thai etc. that lack spaces.
  const Seg = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (Seg) {
    let n = 0;
    for (const part of new Seg(undefined, { granularity: "word" }).segment(text)) {
      if ((part as { isWordLike?: boolean }).isWordLike) n++;
    }
    return n;
  }
  const m = text.trim().match(/\S+/g);
  return m ? m.length : 0;
}

export function countChars(text: string): number {
  return Array.from(text).length;
}

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
