import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeSegmentBatch } from "@/hooks/use-transcript-job";

import { copyToClipboard } from "./clipboard";
import { downloadJson, downloadTxt } from "./download";
import type { Segment } from "./types";

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob, "utf-8");
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("copyToClipboard", () => {
  it("writes the complete text with the async clipboard API", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    vi.stubGlobal("isSecureContext", true);
    const big = "x".repeat(2_000_000) + "末尾";
    await copyToClipboard(big);
    expect(writeText).toHaveBeenCalledWith(big);
  });

  it("falls back to execCommand when the clipboard API is unavailable", async () => {
    vi.stubGlobal("navigator", {});
    let copied = "";
    const exec = vi.fn(() => {
      copied = (document.activeElement as HTMLTextAreaElement | null)?.value ?? (document.querySelector("textarea")?.value ?? "");
      return true;
    });
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
    await copyToClipboard("hello");
    expect(exec).toHaveBeenCalledWith("copy");
    expect(copied).toBe("hello");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("throws when copying is impossible", async () => {
    vi.stubGlobal("navigator", {});
    Object.defineProperty(document, "execCommand", { value: () => false, configurable: true });
    await expect(copyToClipboard("x")).rejects.toThrow(/denied/);
  });
});

describe("downloads", () => {
  it("creates a UTF-8 blob with the right filename and full content", async () => {
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn((b: Blob) => {
        blobs.push(b);
        return "blob:test";
      }),
      revokeObjectURL: vi.fn(),
    });
    const clicks: Array<{ href: string; download: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({ href: this.href, download: this.download });
    });

    downloadTxt("[00:00:00] héllo 🌍\n", "youtube_transcript_abc.txt");
    downloadJson('{"a":1}', "youtube_transcript_abc.json");

    expect(clicks.map((c) => c.download)).toEqual(["youtube_transcript_abc.txt", "youtube_transcript_abc.json"]);
    expect(blobs[0].type).toBe("text/plain;charset=utf-8");
    expect(blobs[1].type).toBe("application/json;charset=utf-8");
    expect(await readBlob(blobs[0])).toBe("[00:00:00] héllo 🌍\n");
    expect(JSON.parse(await readBlob(blobs[1]))).toEqual({ a: 1 });
    expect(document.querySelectorAll("a").length).toBe(0);
  });
});

describe("mergeSegmentBatch (live SSE)", () => {
  const s = (id: number): Segment => ({ id, start: id, end: id + 1, duration: 1, text: `t${id}` });

  it("appends in order", () => {
    expect(mergeSegmentBatch([s(1)], 1, [s(2), s(3)]).map((x) => x.id)).toEqual([1, 2, 3]);
  });

  it("does not duplicate when a reconnect replays segments", () => {
    const merged = mergeSegmentBatch([s(1), s(2), s(3)], 1, [s(2), s(3), s(4)]);
    expect(merged.map((x) => x.id)).toEqual([1, 2, 3, 4]);
  });

  it("ignores batches that would leave a gap", () => {
    const before = [s(1)];
    expect(mergeSegmentBatch(before, 5, [s(6)])).toBe(before);
  });
});
