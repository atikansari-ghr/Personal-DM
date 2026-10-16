// Change Set X: screens are separate files that load when first opened (code splitting), so the sign-in page and
// the first screen download only what they need. The rest is fetched in the background when the browser is idle.
import { lazy, type ComponentType } from "react";
import { reportClientError } from "./api";

const RELOADED = "pd-chunk-reload";

/** A lazily loaded screen. If its file cannot be loaded (typically: a new release replaced the files while this tab
 *  was open), retry once and then reload the page once so the current release is used. */
export function lazyPage<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) {
  return lazy(async () => {
    try {
      return await load();
    } catch {
      try {
        return await load();
      } catch (e) {
        reportClientError("chunk_error");
        let reloaded = false;
        try { reloaded = sessionStorage.getItem(RELOADED) === "1"; sessionStorage.setItem(RELOADED, "1"); } catch { /* ignore */ }
        if (!reloaded) window.location.reload();
        throw e;
      }
    }
  });
}

/** Start loading these screens when the browser has nothing else to do (they are then instant when opened). */
export function prefetchWhenIdle(loaders: (() => Promise<unknown>)[]) {
  const run = () => loaders.forEach((l) => l().catch(() => undefined));
  const w = window as any;
  if (typeof w.requestIdleCallback === "function") w.requestIdleCallback(run, { timeout: 4000 });
  else window.setTimeout(run, 1500);
}

export function clearChunkReloadFlag() {
  try { sessionStorage.removeItem(RELOADED); } catch { /* ignore */ }
}
