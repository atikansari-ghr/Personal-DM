import { describe, expect, it } from "vitest";
import { safeNext } from "./api";
import { clampZoom, fitZoom, MAX_ZOOM, MIN_ZOOM, stepZoom } from "./components/DocViewer";
import { kindFromMime } from "./components/FileTypeIcon";

const O = "https://docs.example.com";

describe("safeNext (no open redirects after sign-in)", () => {
  it("keeps in-app paths", () => {
    expect(safeNext("/folders/abc?x=1#y", O)).toBe("/folders/abc?x=1#y");
  });
  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/\\\\evil", "javascript:alert(1)", "", null, "folders", "/a\nb"])(
    "rejects %s", (v) => expect(safeNext(v as any, O)).toBe("/"));
});

describe("viewer zoom", () => {
  it("steps through fixed levels and clamps", () => {
    expect(stepZoom(100, 1)).toBe(110);
    expect(stepZoom(100, -1)).toBe(90);
    expect(stepZoom(97, 1)).toBe(100); // from a fitted value to the next step
    expect(stepZoom(MAX_ZOOM, 1)).toBe(MAX_ZOOM);
    expect(stepZoom(MIN_ZOOM, -1)).toBe(MIN_ZOOM);
    expect(clampZoom(1000)).toBe(MAX_ZOOM);
  });
  it("fits width and page", () => {
    const page = { w: 816, h: 1056 }; // US Letter at 96 dpi
    const box = { w: 840, h: 600 };
    expect(Math.round(fitZoom("width", page, box))).toBe(100);
    expect(fitZoom("page", page, box)).toBeLessThan(fitZoom("width", page, box));
    expect(fitZoom("page", { w: 10, h: 10 }, box)).toBe(MAX_ZOOM);
  });
});

describe("offline file types", () => {
  it("maps MIME types", () => {
    expect(kindFromMime("application/pdf")).toBe("pdf");
    expect(kindFromMime("image/jpeg")).toBe("jpeg");
    expect(kindFromMime("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).toBe("excel");
    expect(kindFromMime("application/zip")).toBe("archive");
    expect(kindFromMime("application/octet-stream")).toBe("other");
  });
});
