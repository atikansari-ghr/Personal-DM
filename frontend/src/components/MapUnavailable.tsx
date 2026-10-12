import { Link } from "react-router-dom";

// Sign-in map availability (Change Set U): kept apart from SigninMap so pages can show the state without loading Leaflet.

export type MapConfig = { enabled: boolean; tile_url: string; attribution: string; referrer_policy?: string; provider_label?: string;
  unavailable?: string; admin?: boolean };
export type Probe = { state: "checking" | "ok" | "unknown" | "failed"; status?: number | null; error?: string };

export const PROBE_MESSAGES: Record<string, string> = {
  401: "The map provider refused its API key.",
  403: "The map provider blocked the tiles (its usage policy or the key's allowed sites).",
  429: "The map provider is limiting requests right now.",
  network: "The map provider could not be reached from this browser.",
};

/** Fetch one tile the way the map will (same referrer policy) and report the provider's answer. */
export async function probeTiles(cfg: MapConfig, force = false): Promise<Probe> {
  const url = cfg.tile_url.replace("{s}", "a").replace("{z}", "2").replace("{x}", "2").replace("{y}", "1").replace("{r}", "");
  const key = `pd-map-probe:${cfg.tile_url}`;
  if (!force) {
    try { const c = JSON.parse(sessionStorage.getItem(key) || "null"); if (c && Date.now() - c.at < 600_000) return c.probe; } catch { /* storage unavailable */ }
  }
  let probe: Probe;
  try {
    const r = await fetch(url, { mode: "cors", credentials: "omit", cache: "no-store", referrerPolicy: (cfg.referrer_policy || "strict-origin-when-cross-origin") as ReferrerPolicy });
    probe = r.ok ? { state: "ok", status: r.status } : { state: "failed", status: r.status };
  } catch (e: any) {
    // no CORS headers (some self-hosted servers) or offline: let the tiles try; failed images are counted below
    probe = { state: "unknown", status: null, error: String(e?.message || e).slice(0, 80) };
  }
  try { sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), probe })); } catch { /* storage unavailable */ }
  return probe;
}

export function MapUnavailable({ reason, admin, height = 360 }: { reason: string; admin?: boolean; height?: number }) {
  return (
    <div className="map-unavailable" style={{ minHeight: Math.min(height, 260) }} role="status">
      <div className="map-unavailable-icon" aria-hidden="true">🗺️</div>
      <div><strong>Map unavailable</strong>
        <p>{reason} Sign-in records, Trusted Zones and risk levels are not affected: the list below shows every sign-in.</p>
        {admin && <p><Link to="/settings/security?view=access#map-provider">Map provider settings and Test Map Provider</Link></p>}</div>
    </div>
  );
}

