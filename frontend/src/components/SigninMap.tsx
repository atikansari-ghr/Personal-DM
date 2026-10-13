import { useEffect, useRef, useState } from "react";
import { MapUnavailable, PROBE_MESSAGES, probeTiles, type MapConfig, type Probe } from "./MapUnavailable";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Sign-in map (Change Set V). Leaflet is bundled with the app (no CDN) and draws markers, clusters and Trusted Zone
// pins. The base map is either
//  * vector (default, OpenFreeMap): MapLibre draws OpenStreetMap vector tiles in the browser and EVERY label uses the
//    English name (name:en, then the Latin transliteration, then the local name) whatever the browser language;
//  * raster tiles (OpenStreetMap standard, MapTiler, Stadia, custom): labels as rendered by the provider.
// Sign-in addresses are never sent to a map provider. A refused or unreachable provider shows "Map unavailable"; the
// list of sign-ins below never depends on the map. Without WebGL the vector map falls back to raster tiles.

export type MapEvent = { id: number; lat: number | null; lon: number | null; coord_source: string; coord_label: string; location: string; at: string;
  user: string; risk: string; result: string; device: string; zone: string; ip?: string; network?: string };

const RISK_COLOUR: Record<string, string> = { normal: "#1e6b3a", low: "#175cd3", warning: "#b54708", high: "#b42318", "": "#667085" };
const RISK_ORDER = ["normal", "low", "warning", "high"];
export const EN_LABEL = ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name:latin"], ["get", "name"]];

/** Every label of a MapLibre style in English: text fields that show a name read name:en first. */
export function englishStyle(style: any): any {
  const out = { ...style, layers: (style.layers || []).map((l: any) => {
    const tf = l.layout?.["text-field"];
    if (tf === undefined || !JSON.stringify(tf).includes("name")) return l;
    return { ...l, layout: { ...l.layout, "text-field": EN_LABEL } };
  }) };
  return out;
}

const hasWebGL = () => { try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; } };
const esc = (s: string) => s.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]!));
const worstRisk = (list: MapEvent[]) => list.reduce((acc, x) => (RISK_ORDER.indexOf(x.risk) > RISK_ORDER.indexOf(acc) ? x.risk : acc), "normal");

export default function SigninMap({ events, zones, config, height = 360, selected = [], onSelect }:
  { events: MapEvent[]; zones: any[]; config: MapConfig; height?: number; selected?: number[]; onSelect?: (ids: number[]) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const markers = useRef<Map<number, L.CircleMarker>>(new Map());
  const [probe, setProbe] = useState<Probe>({ state: "checking" });
  const [failed, setFailed] = useState("");
  const [mode, setMode] = useState<"vector" | "raster" | "">("");
  const [zoom, setZoom] = useState(2);
  const vector = config.kind === "vector" && hasWebGL();
  const source = (vector ? config.style_url : (config.kind === "vector" ? config.fallback_tile_url : config.tile_url)) || "";
  useEffect(() => {
    let live = true;
    setFailed("");
    setProbe({ state: "checking" });
    if (source) probeTiles(vector ? { ...config, tile_url: "", style_url: source } as MapConfig : { ...config, tile_url: source }).then((p) => live && setProbe(p));
    return () => { live = false; };
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!el.current || (probe.state !== "ok" && probe.state !== "unknown")) return;
    const m = L.map(el.current, { worldCopyJump: true, zoomControl: true, attributionControl: true, scrollWheelZoom: false });
    map.current = m;
    m.setView([20, 10], 2);
    m.on("zoomend", () => setZoom(m.getZoom()));
    let cancelled = false;
    const referrer = (config.referrer_policy || "strict-origin-when-cross-origin") as ReferrerPolicy;
    if (vector) {
      (async () => {
        try {
          const [{ default: maplibregl }, { default: workerUrl }] = await Promise.all([
            import("maplibre-gl"), import("maplibre-gl/dist/maplibre-gl-csp-worker.js?url"), import("@maplibre/maplibre-gl-leaflet")]);
          (maplibregl as any).setWorkerUrl(workerUrl);
          const res = await fetch(source, { referrerPolicy: referrer, credentials: "omit" });
          if (!res.ok) throw new Error(String(res.status));
          const style = englishStyle(await res.json());
          if (cancelled) return;
          (L as any).maplibreGL({ style, attribution: config.attribution, interactive: false }).addTo(m);
          el.current?.setAttribute("data-labels", "en");
          setMode("vector");
        } catch (e: any) {
          console.error("sign-in map: vector map failed", e);
          if (!cancelled) setFailed(PROBE_MESSAGES[String(e?.message)] || PROBE_MESSAGES.network);
        }
      })();
    } else {
      const layer = L.tileLayer(source, { attribution: config.kind === "vector" ? config.fallback_attribution : config.attribution, maxZoom: 18,
        referrerPolicy: referrer as L.TileLayerOptions["referrerPolicy"] });
      // no endless retries: after repeated failures without a single tile, stop and say so
      let loaded = 0, errors = 0;
      layer.on("tileload", () => { loaded++; });
      layer.on("tileerror", () => { errors++; if (errors >= 4 && loaded === 0) { layer.remove(); setFailed(PROBE_MESSAGES.network); } });
      layer.addTo(m);
      el.current.setAttribute("data-labels", "provider");
      setMode("raster");
    }
    return () => { cancelled = true; m.remove(); map.current = null; };
  }, [probe.state, source, config.attribution, config.referrer_policy]); // eslint-disable-line react-hooks/exhaustive-deps
  // markers: same-place sign-ins and markers closer than ~34 px at the current zoom are clustered (count shown)
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const layer = L.layerGroup().addTo(m);
    markers.current = new Map();
    const pts: L.LatLngExpression[] = [];
    for (const z of zones) {
      if (!z.pin) continue;
      const ll: L.LatLngExpression = [z.pin.lat, z.pin.lon];
      pts.push(ll);
      L.circleMarker(ll, { radius: 11, color: "#1e6b3a", weight: 2, fillColor: "#e7f5ec", fillOpacity: 0.9 })
        .bindTooltip(`${esc(z.pin.label || z.name)} — configured Trusted Zone location`).addTo(layer);
    }
    const located = events.filter((e) => e.lat != null && e.lon != null);
    const clusters: { ll: L.LatLng; list: MapEvent[] }[] = [];
    for (const e of located) {
      const ll = L.latLng(e.lat!, e.lon!);
      const p = m.project(ll, zoom);
      const c = clusters.find((x) => m.project(x.ll, zoom).distanceTo(p) < 34);
      if (c) c.list.push(e); else clusters.push({ ll, list: [e] });
    }
    for (const c of clusters) {
      pts.push(c.ll);
      const worst = worstRisk(c.list);
      if (c.list.length === 1) {
        const e = c.list[0];
        const mk = L.circleMarker(c.ll, { radius: 8, color: RISK_COLOUR[worst] || "#667085", weight: 2, fillOpacity: 0.4,
          dashArray: e.coord_source === "geoip_country" ? "4 3" : undefined })
          .bindTooltip(`<strong>${esc(e.user)}</strong><br>${esc(e.ip || "")}<br>${esc(e.zone ? `${e.zone} (Trusted Zone)` : e.location || "")}`, { direction: "top" })
          .on("click", () => onSelect?.([e.id])).addTo(layer);
        (mk as any)._path?.setAttribute?.("data-event", String(e.id));
        markers.current.set(e.id, mk);
      } else {
        const icon = L.divIcon({ className: "map-cluster", html: `<span style="border-color:${RISK_COLOUR[worst]}">${c.list.length}</span>`, iconSize: [34, 34] });
        const people = [...new Set(c.list.map((x) => x.user))];
        L.marker(c.ll, { icon, keyboard: true, title: `${c.list.length} sign-ins` })
          .bindTooltip(`${c.list.length} sign-ins · ${esc(people.slice(0, 3).join(", "))}${people.length > 3 ? "…" : ""}<br>${esc(c.list[0].location || "")}`, { direction: "top" })
          .on("click", () => onSelect?.(c.list.map((x) => x.id))).addTo(layer);
        for (const x of c.list) markers.current.set(x.id, null as any);
      }
    }
    if (pts.length && !selected.length) m.fitBounds(L.latLngBounds(pts as any).pad(0.4), { maxZoom: 9 });
    return () => { layer.remove(); };
  }, [events, zones, probe.state, zoom, mode]); // eslint-disable-line react-hooks/exhaustive-deps
  // a record chosen in the list: emphasise its marker and bring it into view
  useEffect(() => {
    const m = map.current;
    if (!m || !selected.length) return;
    const e = events.find((x) => x.id === selected[0]);
    if (!e || e.lat == null || e.lon == null) return;
    m.setView([e.lat, e.lon], Math.max(m.getZoom(), 7), { animate: false });
    const mk = markers.current.get(e.id);
    mk?.setStyle({ weight: 5 });
    return () => { mk?.setStyle({ weight: 2 }); };
  }, [selected, events, mode]);
  if (probe.state === "failed" || failed) {
    const reason = failed || PROBE_MESSAGES[String(probe.status)] || `The map provider answered HTTP ${probe.status}.`;
    return <MapUnavailable reason={reason} admin={config.admin} height={height} />;
  }
  if (probe.state === "checking") return <div className="signin-map map-checking" style={{ height }} aria-busy="true" aria-label="Loading the map" />;
  return (
    <>
      <div ref={el} className="signin-map" style={{ height }} role="img" data-map-mode={mode} aria-label="Map of sign-in locations. The same information is listed in the table below." />
      {config.kind === "vector" && !vector && <p className="small muted">This browser has no WebGL, so the map uses standard tiles with local-language place names.</p>}
    </>
  );
}
