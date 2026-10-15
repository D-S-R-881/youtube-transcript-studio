import { describe, expect, it } from "vitest";

import {
  buildFullText,
  buildTxt,
  countChars,
  countWords,
  exportFilename,
  formatDuration,
  formatTimestamp,
  resultToJson,
  safeFilename,
} from "./transcript-format";
import type { Segment, TranscriptResult } from "./types";

const seg = (id: number, start: number | null, end: number | null, text: string): Segment => ({
  id,
  start,
  end,
  duration: start != null && end != null ? end - start : null,
  text,
});

const sample = [
  seg(1, 0, 4.5, "Hello everyone, welcome to today's video."),
  seg(2, 5, 11, "Today we are going to discuss artificial intelligence."),
  seg(3, 12, 15, "Let's get started."),
];

function result(overrides: Partial<TranscriptResult> = {}): TranscriptResult {
  return {
    video_id: "VIDEO_ID",
    video_url: "https://www.youtube.com/watch?v=VIDEO_ID",
    title: "t",
    channel: null,
    video_type: "regular",
    language: "en",
    transcript_source: "youtube_captions",
    is_live: false,
    duration_seconds: 120,
    transcript: sample,
    full_text: buildFullText(sample),
    total_segments: 3,
    language_name: "English",
    caption_type: "manual",
    translated_from: null,
    has_timestamps: true,
    timestamp_reference: "video_start",
    generated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("timestamps", () => {
  it.each([
    [0, "00:00:00"],
    [5.9, "00:00:05"],
    [65, "00:01:05"],
    [3600, "01:00:00"],
    [36061, "10:01:01"],
    [null, "00:00:00"],
    [-1, "00:00:00"],
    [NaN, "00:00:00"],
  ])("formats %s as %s", (s, out) => expect(formatTimestamp(s as number | null)).toBe(out));

  it("formats durations", () => {
    expect(formatDuration(213)).toBe("03:33");
    expect(formatDuration(3723)).toBe("01:02:03");
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(0)).toBeNull();
  });
});

describe("buildTxt (matches backend formatting)", () => {
  it("renders timestamped lines", () => {
    expect(buildTxt(sample, true)).toBe(
      "[00:00:00] Hello everyone, welcome to today's video.\n\n" +
        "[00:00:05] Today we are going to discuss artificial intelligence.\n\n" +
        "[00:00:12] Let's get started.\n",
    );
  });

  it("groups untimestamped text into paragraphs on pauses", () => {
    const segs = [seg(1, 0, 2, "One."), seg(2, 2.2, 3, "Two."), seg(3, 10, 11, "Three.")];
    expect(buildTxt(segs, false)).toBe("One. Two.\n\nThree.\n");
  });

  it("keeps untimed segments as separate paragraphs", () => {
    expect(buildTxt([seg(1, null, null, "A"), seg(2, null, null, "B")], true)).toBe("A\n\nB\n");
  });

  it("handles empty transcripts", () => {
    expect(buildTxt([], true)).toBe("");
  });

  it("preserves multilingual unicode", () => {
    const segs = [seg(1, 0, 1, "こんにちは世界"), seg(2, 1, 2, "مرحبا"), seg(3, 2, 3, "नमस्ते 🌍")];
    const txt = buildTxt(segs, true);
    expect(txt).toContain("こんにちは世界");
    expect(txt).toContain("🌍");
  });
});

describe("JSON export", () => {
  it("is valid JSON with numeric timestamps", () => {
    const parsed = JSON.parse(resultToJson(result()));
    expect(parsed.transcript[1]).toEqual({ id: 2, start: 5, end: 11, duration: 6, text: "Today we are going to discuss artificial intelligence." });
    expect(typeof parsed.transcript[0].start).toBe("number");
    expect(parsed.total_segments).toBe(parsed.transcript.length);
    expect(parsed.channel).toBeNull();
  });

  it("does not escape unicode", () => {
    const json = resultToJson(result({ transcript: [seg(1, 0, 1, "日本語")], full_text: "日本語" }));
    expect(json).toContain("日本語");
  });
});

describe("filenames", () => {
  it("uses the required patterns", () => {
    expect(safeFilename("abc_DEF-123", false, "txt")).toBe("youtube_transcript_abc_DEF-123.txt");
    expect(safeFilename("abc", true, "json")).toBe("youtube_live_transcript_abc.json");
    expect(safeFilename("../../etc", false, "txt")).toBe("youtube_transcript_etc.txt");
  });

  it("picks live names for live sessions and replays", () => {
    expect(exportFilename(result(), "txt")).toBe("youtube_transcript_VIDEO_ID.txt");
    expect(exportFilename(result({ video_type: "live" }), "json")).toBe("youtube_live_transcript_VIDEO_ID.json");
    expect(exportFilename(result(), "json", "live")).toBe("youtube_live_transcript_VIDEO_ID.json");
  });

  it("uses a sanitized title for uploads", () => {
    expect(exportFilename(result({ video_id: null, title: "My Talk (final).mp3" }), "txt")).toBe("transcript_My_Talk_final_mp3.txt");
  });
});

describe("counts", () => {
  it("counts words and characters", () => {
    expect(countWords("Hello world, again")).toBe(3);
    expect(countChars("héllo 🌍")).toBe(7);
    expect(countWords("")).toBe(0);
  });
});
