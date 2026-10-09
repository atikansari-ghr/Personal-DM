import { useEffect, useState } from "react";
import { api, formatBytes, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { Icon, Skeleton, useToast } from "../../components/ui";

interface Dev { id: string; label: string; platform: string; installed_app: boolean; last_sync_at: string | null; items: number; bytes: number; failures: number; wipe_pending: boolean }
interface Row { id: string; display_name: string; offline_allowed: boolean; devices: Dev[] }

/** Settings → Offline & PWA (main administrator): policy, per-person capability, devices, app identity. */
export default function OfflineAdminPanel() {
  const toast = useToast();
  const [rows, setRows] = useState<Row[] | null>(null);
  const load = () => api<{ users: Row[] }>("admin/offline").then((r) => setRows(r.users)).catch((e) => toast(e.message, "error"));
  useEffect(() => { load(); }, []);
  const setAllowed = (u: Row, allowed: boolean) =>
    api(`admin/offline/users/${u.id}`, { method: "PATCH", body: { offline_allowed: allowed } })
      .then(() => { toast(allowed ? `Offline copies allowed for ${u.display_name}` : `Offline copies turned off for ${u.display_name}; their devices remove copies at the next sync`); load(); })
      .catch((e) => toast(e.message, "error"));
  const wipe = (d: Dev) => api(`admin/offline/devices/${d.id}/wipe`, { method: "POST" }).then(() => { toast("Removal requested; the device deletes its copies at its next sync"); load(); });
  return (
    <div className="stack">
      <SettingsForm section="offline" title="Offline copies">
        <p className="small muted">People choose folders or documents to keep on a device from the <strong>⋮</strong> menu. Each choice applies to one account on one device. Downloads always re-check permissions; removed access, archived or quarantined documents and turned-off accounts are deleted from devices at their next sync. A device that stays offline cannot be reached until it reconnects (it locks its copies after the configured number of days).</p>
      </SettingsForm>
      <div className="card">
        <h2>People and devices</h2>
        {!rows ? <Skeleton lines={4} /> : (
          <table className="responsive">
            <thead><tr><th>Person</th><th>Offline copies</th><th>Devices</th></tr></thead>
            <tbody>{rows.map((u) => (
              <tr key={u.id}>
                <td data-label="Person"><strong>{u.display_name}</strong></td>
                <td data-label="Offline copies">
                  <label className="check"><input type="checkbox" checked={u.offline_allowed} onChange={(e) => setAllowed(u, e.target.checked)} aria-label={`Allow offline copies for ${u.display_name}`} /> {u.offline_allowed ? "Allowed" : "Turned off"}</label>
                </td>
                <td data-label="Devices">
                  {u.devices.length === 0 ? <span className="muted small">None</span> : u.devices.map((d) => (
                    <div key={d.id} className="row between small" style={{ marginBottom: ".3rem" }}>
                      <span><Icon name="monitor" size={14} /> {d.label}{d.installed_app ? " (installed app)" : ""} · {d.items} copies · {formatBytes(d.bytes)}{d.failures ? ` · ${d.failures} failed` : ""} · {d.last_sync_at ? `synced ${formatDateTime(d.last_sync_at)}` : "never synced"}</span>
                      {d.wipe_pending ? <span className="badge warn"><Icon name="clock" size={12} /> Removal pending</span> : <button className="btn small danger" onClick={() => wipe(d)}>Remove copies</button>}
                    </div>
                  ))}
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <PwaIdentityCard />
    </div>
  );
}

/** Installed-app identity: the icons and names devices use for the Home Screen / app launcher. */
function PwaIdentityCard() {
  const [manifest, setManifest] = useState<any>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  useEffect(() => {
    fetch("/manifest.webmanifest", { credentials: "omit" }).then((r) => r.json()).then(async (m) => {
      setManifest(m);
      const found: string[] = [];
      const urls = [...m.icons.map((i: any) => i.src), "/apple-touch-icon.png", "/favicon.ico", "/favicon-32.png"];
      for (const u of urls) {
        const r = await fetch(u, { credentials: "omit", cache: "no-store" }).catch(() => null);
        const type = r?.headers.get("Content-Type") || "";
        if (!r || !r.ok || !/^image\//.test(type)) found.push(`${u}: ${r ? `${r.status} ${type || "no type"}` : "not reachable"}`);
      }
      setProblems(found);
    }).catch(() => setProblems(["/manifest.webmanifest could not be loaded"]));
  }, []);
  return (
    <div className="card">
      <h2>Installed app (PWA)</h2>
      <div className="row" style={{ alignItems: "flex-end", gap: "1.2rem" }}>
        {[["/icon-512.png", 96, "512 × 512"], ["/icon-192.png", 64, "192 × 192"], ["/apple-touch-icon.png", 60, "180 × 180 (Apple)"], ["/icon-maskable-512.png", 64, "Maskable"], ["/favicon-32.png", 32, "32 × 32"], ["/favicon-16.png", 16, "16 × 16"]].map(([src, size, label]) => (
          <figure key={src as string} className="pwa-icon-preview"><img src={src as string} width={size as number} height={size as number} alt="" /><figcaption className="small muted">{label}</figcaption></figure>
        ))}
      </div>
      {manifest && <p className="small muted">Name “{manifest.name}”, short name “{manifest.short_name}”, opens {manifest.start_url} in {manifest.display} mode.</p>}
      {problems === null ? null : problems.length === 0
        ? <div className="alert ok"><Icon name="check" size={16} /> Manifest and icons load without signing in, with image types.</div>
        : <div className="alert error"><strong>Some app icons cannot be loaded without signing in.</strong> Phones fetch these without your session; a reverse proxy that requires sign-in for them makes iPhone show a letter instead of the icon. <ul>{problems.map((p) => <li key={p} className="mono small">{p}</li>)}</ul></div>}
      <p className="small muted">After changing icons, remove the old Home Screen shortcut and add it again: iOS keeps the icon it saw when the shortcut was created. See Help → Phone and tablet (PWA).</p>
    </div>
  );
}
