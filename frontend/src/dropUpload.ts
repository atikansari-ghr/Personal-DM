/**
 * Files and folders dragged from the desktop (Windows Explorer, macOS Finder, Linux file managers).
 *
 * Folders are walked with the File and Directory Entries API (``webkitGetAsEntry``, supported by Chromium,
 * Firefox and Safari) so the server can recreate the same hierarchy below the drop target. When the browser
 * cannot provide folder contents, the drop is reported as such instead of silently losing the folder.
 */
import { ApiError, upload } from "./api";

export interface DroppedFile { file: File; path: string }
export interface Dropped { files: DroppedFile[]; dirs: string[]; unsupported: string[] }

export function isExternalFileDrag(e: React.DragEvent | DragEvent): boolean {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
}

function readAll(dir: any): Promise<any[]> {
  const reader = dir.createReader();
  const out: any[] = [];
  return new Promise((resolve, reject) => {
    const next = () => reader.readEntries((batch: any[]) => {
      if (!batch.length) resolve(out);
      else { out.push(...batch); next(); } // readEntries returns at most ~100 entries per call
    }, reject);
    next();
  });
}

function fileOf(entry: any): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

/** Must be called synchronously inside the drop event: DataTransfer items are cleared afterwards. */
export function collectDropped(dt: DataTransfer): Promise<Dropped> {
  const items = Array.from(dt.items || []).filter((i) => i.kind === "file");
  const entries = items.map((i) => (typeof (i as any).webkitGetAsEntry === "function" ? (i as any).webkitGetAsEntry() : null));
  const plain = Array.from(dt.files || []);
  return (async () => {
    const result: Dropped = { files: [], dirs: [], unsupported: [] };
    if (!entries.length || entries.every((e) => !e)) {
      // No entries API: plain files work; a folder shows up as an empty, type-less "file" we cannot read.
      for (const f of plain) {
        if (!f.type && f.size % 4096 === 0 && !/\.[a-z0-9]{1,8}$/i.test(f.name)) result.unsupported.push(f.name);
        else result.files.push({ file: f, path: f.name });
      }
      return result;
    }
    const walk = async (entry: any, prefix: string): Promise<void> => {
      const path = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isFile) {
        try { result.files.push({ file: await fileOf(entry), path }); } catch { result.unsupported.push(path); }
      } else if (entry.isDirectory) {
        let children: any[] = [];
        try { children = await readAll(entry); } catch { result.unsupported.push(path); return; }
        if (!children.length) result.dirs.push(path);
        for (const c of children) await walk(c, path);
      }
    };
    for (let i = 0; i < entries.length; i++) {
      if (entries[i]) await walk(entries[i], "");
      else if (plain[i]) result.files.push({ file: plain[i], path: plain[i].name });
    }
    return result;
  })();
}

export interface DropProgress {
  total: number; done: number; failed: { file: string; error: string }[]; foldersCreated: number; running: boolean; bytes: number; sent: number;
}

const BATCH_FILES = 20;
const BATCH_BYTES = 64 * 1024 * 1024;

/** Upload in batches so one failure never loses the rest and progress is visible. */
export async function uploadDropped(folderId: string, dropped: Dropped, onProgress: (p: DropProgress) => void): Promise<DropProgress> {
  const p: DropProgress = {
    total: dropped.files.length, done: 0, foldersCreated: 0, running: true, sent: 0,
    bytes: dropped.files.reduce((n, f) => n + f.file.size, 0),
    failed: dropped.unsupported.map((n) => ({ file: n, error: "Your browser did not give access to this folder's contents. Use Import folder instead." })),
  };
  onProgress({ ...p });
  const batches: DroppedFile[][] = [];
  let cur: DroppedFile[] = [], size = 0;
  for (const f of dropped.files) {
    if (cur.length && (cur.length >= BATCH_FILES || size + f.file.size > BATCH_BYTES)) { batches.push(cur); cur = []; size = 0; }
    cur.push(f); size += f.file.size;
  }
  if (cur.length) batches.push(cur);
  const send = async (batch: DroppedFile[], dirs: string[]) => {
    const form = new FormData();
    form.set("folder", folderId);
    batch.forEach((f) => { form.append("files", f.file, f.file.name); form.append("paths", f.path); });
    dirs.forEach((d) => form.append("dirs", d));
    const base = p.sent;
    const batchBytes = batch.reduce((n, f) => n + f.file.size, 0);
    try {
      const r = await upload<any>("documents", form, (fr) => { p.sent = base + fr * batchBytes; onProgress({ ...p }); });
      p.done += (r.documents || []).length;
      p.failed.push(...(r.errors || []));
      p.foldersCreated += r.folders_created || 0;
    } catch (e: any) {
      const errs = e instanceof ApiError && e.data?.errors?.length ? e.data.errors : batch.map((f) => ({ file: f.path, error: e.message }));
      p.failed.push(...errs);
      if (e instanceof ApiError) p.foldersCreated += e.data?.folders_created || 0;
    }
    p.sent = base + batchBytes;
    onProgress({ ...p });
  };
  if (!batches.length && dropped.dirs.length) await send([], dropped.dirs);
  for (let i = 0; i < batches.length; i++) await send(batches[i], i === 0 ? dropped.dirs : []);
  p.running = false;
  onProgress({ ...p });
  return p;
}
