import { describe, expect, it } from "vitest";

import { parseYouTubeUrl } from "./youtube";

const VID = "dQw4w9WgXcQ";

describe("parseYouTubeUrl", () => {
  it.each([
    [`https://www.youtube.com/watch?v=${VID}`, "video"],
    [`https://youtu.be/${VID}`, "video"],
    [`https://youtu.be/${VID}?si=abc&t=10`, "video"],
    [`https://www.youtube.com/live/${VID}`, "live"],
    [`https://www.youtube.com/live/${VID}?feature=share`, "live"],
    [`https://www.youtube.com/watch?v=${VID}&feature=share`, "video"],
    [`https://www.youtube.com/watch?v=${VID}&list=PL123&index=2`, "video"],
    [`https://m.youtube.com/watch?v=${VID}`, "video"],
    [`https://www.youtube.com/shorts/${VID}`, "short"],
    [`https://www.youtube.com/embed/${VID}`, "video"],
    [`youtube.com/watch?v=${VID}`, "video"],
    [`  https://WWW.YOUTUBE.COM/watch?v=${VID} `, "video"],
  ])("accepts %s", (url, kind) => {
    const r = parseYouTubeUrl(url);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value.videoId).toBe(VID);
      expect(r.value.urlKind).toBe(kind);
      expect(r.value.canonicalUrl).toBe(`https://www.youtube.com/watch?v=${VID}`);
    }
  });

  it.each([
    "",
    "hello",
    "https://vimeo.com/1",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/playlist?list=PL1",
    "https://www.youtube.com/channel/UC123",
    "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com@evil.com/watch?v=dQw4w9WgXcQ",
    "https://user:pw@www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ\nx",
    "https://www.youtube.com/" + "a".repeat(3000),
  ])("rejects %s", (url) => {
    expect(parseYouTubeUrl(url).ok).toBe(false);
  });

  it("rejects non-strings", () => {
    expect(parseYouTubeUrl(42).ok).toBe(false);
  });
});
