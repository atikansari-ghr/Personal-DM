import { describe, expect, it } from "vitest";
import { safeNext } from "./api";
import { clampZoom, fitZoom, MAX_ZOOM, MIN_ZOOM, stepZoom } from "./components/DocViewer";
import { kindFromMime } from "./components/FileTypeIcon";
import { normaliseView, SORT_LABELS } from "./docview";
import { collectDropped } from "./dropUpload";

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

describe("folder view preference", () => {
  it("maps old and unknown values to a supported view", () => {
    expect(normaliseView("grid")).toBe("thumbnails"); // stored by earlier versions
    expect(normaliseView("details")).toBe("details");
    expect(normaliseView(null)).toBe("list");
    expect(normaliseView("carousel")).toBe("list");
  });
  it("labels every server sort key", () => {
    for (const k of ["-added", "added", "name", "-name", "size", "-size", "expiry", "-expiry", "type", "-type"]) expect(SORT_LABELS[k]).toBeTruthy();
  });
});

describe("desktop folder drop", () => {
  // Minimal stand-ins for the File and Directory Entries API objects a browser hands over on drop.
  const file = (name: string) => ({ isFile: true, isDirectory: false, name, file: (ok: (f: File) => void) => ok(new File(["x"], name, { type: "application/pdf" })) });
  const dir = (name: string, children: any[]) => ({
    isFile: false, isDirectory: true, name,
    createReader: () => { let done = false; return { readEntries: (ok: (e: any[]) => void) => { const batch = done ? [] : children; done = true; setTimeout(() => ok(batch)); } }; },
  });
  const dt = (entries: any[]) => ({ items: entries.map((e) => ({ kind: "file", webkitGetAsEntry: () => e })), files: [] }) as unknown as DataTransfer;

  it("walks dropped folders and keeps relative paths, including empty folders", async () => {
    const tree = dir("House Documents", [dir("Lease", [file("2025.pdf"), file("2026.pdf")]), dir("Insurance", []), file("readme.pdf")]);
    const got = await collectDropped(dt([tree, file("loose.pdf")]));
    expect(got.files.map((f) => f.path).sort()).toEqual(["House Documents/Lease/2025.pdf", "House Documents/Lease/2026.pdf", "House Documents/readme.pdf", "loose.pdf"]);
    expect(got.dirs).toEqual(["House Documents/Insurance"]);
    expect(got.unsupported).toEqual([]);
  });

  it("falls back to plain files when the browser gives no folder entries", async () => {
    const f = new File(["x"], "scan.pdf", { type: "application/pdf" });
    const got = await collectDropped({ items: [{ kind: "file" }], files: [f] } as unknown as DataTransfer);
    expect(got.files.map((x) => x.path)).toEqual(["scan.pdf"]);
  });
});
