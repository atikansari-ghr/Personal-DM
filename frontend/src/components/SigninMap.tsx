import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Sign-in map. Leaflet is bundled with the app (no CDN). The browser only downloads picture tiles from the configured
// tile server; sign-in addresses are never sent to it. Markers are drawn as SVG circles (no marker images needed).

export type MapEvent = { id: number; lat: number | null; lon: number | null; coord_source: string; coord_label: string; location: string; at: string;
  user: string; risk: string; result: string; device: string; zone: string };

const RISK_COLOUR: Record<string, string> = { normal: "#1e6b3a", low: "#175cd3", warning: "#b54708", high: "#b42318", "": "#667085" };

export default function SigninMap({ events, zones, tileUrl, attribution, height = 360 }: { events: MapEvent[]; zones: any[]; tileUrl: string; attribution: string; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { worldCopyJump: true, zoomControl: true, attributionControl: true, scrollWheelZoom: false });
    map.current = m;
    L.tileLayer(tileUrl, { attribution, maxZoom: 18, crossOrigin: true, referrerPolicy: "no-referrer" } as any).addTo(m);
    m.setView([20, 10], 2);
    return () => { m.remove(); map.current = null; };
  }, [tileUrl, attribution]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const layer = L.layerGroup().addTo(m);
    const pts: L.LatLngExpression[] = [];
    for (const z of zones) {
      if (!z.pin) continue;
      const ll: L.LatLngExpression = [z.pin.lat, z.pin.lon];
      pts.push(ll);
      L.circleMarker(ll, { radius: 11, color: "#1e6b3a", weight: 2, fillColor: "#e7f5ec", fillOpacity: 0.9 })
        .bindTooltip(`${z.pin.label || z.name} — configured Trusted Zone location`).addTo(layer);
    }
    const groups = new Map<string, MapEvent[]>();
    for (const e of events) {
      if (e.lat == null || e.lon == null) continue;
      const k = `${e.lat.toFixed(2)},${e.lon.toFixed(2)}`;
      groups.set(k, [...(groups.get(k) || []), e]);
    }
    groups.forEach((list) => {
      const e = list[0];
      const worst = list.reduce((acc, x) => (["normal", "low", "warning", "high"].indexOf(x.risk) > ["normal", "low", "warning", "high"].indexOf(acc) ? x.risk : acc), "normal");
      const ll: L.LatLngExpression = [e.lat!, e.lon!];
      pts.push(ll);
      const text = `${e.location} · ${list.length} sign-in${list.length > 1 ? "s" : ""} · ${e.coord_label}${worst !== "normal" ? ` · highest risk: ${worst}` : ""}`;
      L.circleMarker(ll, { radius: 6 + Math.min(list.length, 8), color: RISK_COLOUR[worst] || "#667085", weight: 2, fillOpacity: 0.35,
        dashArray: e.coord_source === "geoip_country" ? "4 3" : undefined }).bindTooltip(text).addTo(layer);
    });
    if (pts.length) m.fitBounds(L.latLngBounds(pts as any).pad(0.4), { maxZoom: 9 });
    return () => { layer.remove(); };
  }, [events, zones]);
  return <div ref={el} className="signin-map" style={{ height }} role="img" aria-label="Map of sign-in locations. The same information is listed in the table below." />;
}
