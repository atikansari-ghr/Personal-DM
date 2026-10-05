import { useEffect, useState } from "react";
import { api } from "../api";
import type { Group, User } from "../types";
import { Avatar, Modal, Skeleton, useToast } from "./ui";

const ORDER = ["view", "download", "upload", "edit", "version", "organize", "archive", "share", "manage"];

export default function PermissionsDialog({ target, onClose }: { target: { kind: "folders" | "documents"; id: string; name: string }; onClose: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<any>(null);
  const [members, setMembers] = useState<User[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [subject, setSubject] = useState("");
  const [caps, setCaps] = useState<string[]>(["view"]);
  const [inspect, setInspect] = useState("");
  const load = () => api(`${target.kind}/${target.id}/permissions`, { query: { user: inspect || undefined } }).then(setData).catch((e) => toast(e.message, "error"));
  useEffect(() => { load(); }, [inspect]);
  useEffect(() => {
    api<{ members: User[] }>("family/members").then((r) => setMembers(r.members));
    api<{ groups: Group[] }>("family/groups").then((r) => setGroups(r.groups)).catch(() => undefined);
  }, []);
  if (!data) return <Modal title="Access" onClose={onClose}><Skeleton /></Modal>;
  const save = async (subj: string, c: string[]) => {
    const [kind, id] = subj.split(":");
    try {
      await api(`${target.kind}/${target.id}/permissions`, { method: "PUT", body: { [kind]: id, caps: c } });
      toast(c.length ? "Access updated" : "Access removed");
      load();
    } catch (e: any) { toast(e.message, "error"); }
  };
  return (
    <Modal title={`Access — ${target.name}`} onClose={onClose} wide>
      <div className="stack">
        <p className="small">Your access: {data.my_caps.map((c: string) => data.cap_labels[c] || c).join(", ") || "none"}</p>
        <details>
          <summary>Why do I have this access?</summary>
          <ul className="small">{data.why.map((w: any, i: number) => <li key={i}>{w.source}{w.at ? ` at “${w.at}”` : ""}{w.inherited ? " (inherited)" : ""}: {w.caps.join(", ") || "—"}</li>)}</ul>
        </details>
        {data.can_manage && (
          <>
            <label className="check">
              <input type="checkbox" checked={data.inherit_permissions} onChange={async (e) => {
                try { await api(`${target.kind}/${target.id}`, { method: "PATCH", body: { inherit_permissions: e.target.checked } }); load(); } catch (x: any) { toast(x.message, "error"); }
              }} />
              Inherit access from the parent folder
            </label>
            <p className="small muted">Turning inheritance off makes this {target.kind === "folders" ? "folder (and its contents)" : "document"} an exception: only the rules below apply.</p>
            <h3>Explicit rules</h3>
            {data.rules.length === 0 ? <p className="muted small">No explicit rules here.</p> : (
              <table className="responsive"><thead><tr><th>Who</th><th>Capabilities</th><th /></tr></thead><tbody>
                {data.rules.map((r: any) => (
                  <tr key={r.id}><td>{r.user ? <span className="row" style={{ gap: ".4rem" }}><Avatar user={r.user} size="sm" /> {r.user.display_name}</span> : `Group: ${r.group.name}`}</td><td className="small">{r.caps.join(", ")}</td>
                    <td><button className="btn small danger" onClick={() => save(r.user ? `user:${r.user.id}` : `group:${r.group.id}`, [])}>Remove</button></td></tr>
                ))}
              </tbody></table>
            )}
            <h3>Grant access</h3>
            <div className="row">
              <select aria-label="Person or group" value={subject} onChange={(e) => setSubject(e.target.value)} style={{ maxWidth: 280 }}>
                <option value="">Choose a person or group…</option>
                {members.map((m) => <option key={m.id} value={`user:${m.id}`}>{m.display_name}</option>)}
                {groups.map((g) => <option key={g.id} value={`group:${g.id}`}>Group: {g.name}</option>)}
              </select>
            </div>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: ".4rem" }}>
              {ORDER.map((c) => (
                <label key={c} className="check small"><input type="checkbox" checked={caps.includes(c)} disabled={c === "view"} onChange={(e) => setCaps(e.target.checked ? [...caps, c] : caps.filter((x) => x !== c))} /> {data.cap_labels[c]}</label>
              ))}
            </div>
            <div><button className="btn primary" disabled={!subject} onClick={() => save(subject, caps)}>Save access</button></div>
            <h3>Check someone's effective access</h3>
            <select aria-label="Inspect person" value={inspect} onChange={(e) => setInspect(e.target.value)} style={{ maxWidth: 280 }}>
              <option value="">Choose a person…</option>
              {members.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
            </select>
            {data.effective_for && (
              <div className="card small">
                <strong>{data.effective_for.user.display_name}:</strong> {data.effective_for.caps.join(", ") || "no access"}
                <ul>{data.effective_for.why.map((w: any, i: number) => <li key={i}>{w.source}{w.at ? ` at “${w.at}”` : ""}{w.inherited ? " (inherited)" : ""}: {w.caps.join(", ") || "—"}</li>)}</ul>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
