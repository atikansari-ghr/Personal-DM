import { useState } from "react";
import { api, formatDateTime } from "../../api";
import { Avatar, HelpTip, Modal, Skeleton, useAsync, useToast } from "../../components/ui";
import { useSession } from "../../session";
import type { Group, User } from "../../types";

const SCOPE_LABELS: Record<string, string> = {
  documents: "Manage documents of group members",
  membership: "Add/remove group members",
  folder_permissions: "Manage folder permissions (within what they hold)",
  reminders: "Manage reminders for the group",
  notifications: "Receive the group's expiry reminders",
};

function MemberDialog({ member, groups, onClose, onDone }: { member?: User; groups: Group[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<any>(member ? { display_name: member.display_name, full_name: member.full_name, email: member.email, role_label: member.role_label, username: member.username, reminder_group: member.reminder_group || "" }
    : { display_name: "", full_name: "", email: "", role_label: "", username: "", group: groups[0]?.id || "" });
  const [temp, setTemp] = useState("");
  return (
    <Modal title={member ? `Edit ${member.display_name}` : "Add family member"} onClose={onClose}>
      {temp ? (
        <div className="stack"><div className="alert warn"><strong>Temporary password (shown once):</strong> <code>{temp}</code><br />Give it to the person privately; they must change it at first sign-in.</div><button className="btn primary" onClick={onDone}>Done</button></div>
      ) : (
        <form className="stack" onSubmit={async (e) => {
          e.preventDefault();
          try {
            if (member) { await api(`family/members/${member.id}`, { method: "PATCH", body: f }); onDone(); }
            else { const r = await api("family/members", { body: f }); setTemp(r.temporary_password); }
          } catch (x: any) { toast(x.message, "error"); }
        }}>
          {[["display_name", "Display name"], ["full_name", "Full name"], ["role_label", "Relationship label (e.g. Grandfather)"], ["username", "Username"], ["email", "Email (optional)"]].map(([k, l]) => (
            <div className="field" key={k}><label htmlFor={`m-${k}`}>{l}</label><input id={`m-${k}`} type={k === "email" ? "email" : "text"} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
          ))}
          <div className="field"><label htmlFor="m-g">{member ? "Reminder group (whose head gets their expiry reminders)" : "Family group"}</label>
            <select id="m-g" value={member ? f.reminder_group : f.group} onChange={(e) => setF({ ...f, [member ? "reminder_group" : "group"]: e.target.value })}><option value="">None</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></div>
          <p className="small muted">Every person whose documents are managed gets their own account, even if they never sign in. A personal folder is created for them, visible only to them and the main administrator.</p>
          <button className="btn primary">{member ? "Save" : "Add member"}</button>
        </form>
      )}
    </Modal>
  );
}

export default function FamilyPanel() {
  const { session } = useSession();
  const toast = useToast();
  const admin = !!session?.user?.is_main_admin;
  const members = useAsync(() => api<{ members: User[] }>("family/members"), []);
  const groups = useAsync(() => api<{ groups: Group[]; scopes: string[] }>("family/groups"), []);
  const [dialog, setDialog] = useState<any>(null);
  const [newGroup, setNewGroup] = useState("");
  const [deleg, setDeleg] = useState<{ group: string; delegate: string; scopes: string[] }>({ group: "", delegate: "", scopes: [] });
  if (!members.data || !groups.data) return <Skeleton lines={6} />;
  const byId = new Map(members.data.members.map((m) => [m.id, m]));
  const reload = () => { members.reload(); groups.reload(); };
  const patchGroup = async (id: string, body: any) => { try { await api(`family/groups/${id}`, { method: "PATCH", body }); reload(); } catch (e: any) { toast(e.message, "error"); } };
  return (
    <div className="stack">
      <div className="card">
        <h2>Members {admin && <button className="btn small primary" onClick={() => setDialog({ kind: "member" })}>Add member</button>}</h2>
        <table className="responsive"><thead><tr><th>Person</th><th className="hide-mobile">Username</th><th className="hide-mobile">Last sign-in</th><th>Status</th>{admin && <th />}</tr></thead><tbody>
          {members.data.members.map((m) => (
            <tr key={m.id}>
              <td><div className="row"><Avatar user={m} size="sm" /><div><strong>{m.display_name}</strong><div className="small muted">{m.role_label}{m.is_main_admin ? " · Main administrator" : ""}{m.is_head ? " · Family head" : ""}</div></div></div></td>
              <td className="hide-mobile">{m.username}</td>
              <td className="hide-mobile small">{m.last_login ? formatDateTime(m.last_login) : "Never"}</td>
              <td>{m.is_active ? <span className="badge ok">Active</span> : <span className="badge neutral">Disabled</span>}{m.totp_enabled && <span className="badge neutral">2FA</span>}{m.must_change_password && <span className="badge soon">Temp password</span>}</td>
              {admin && (
                <td className="row">
                  <button className="btn small" onClick={() => setDialog({ kind: "member", member: m })}>Edit</button>
                  <button className="btn small" onClick={async () => { const r = await api(`family/members/${m.id}/reset-password`, { body: {} }); setDialog({ kind: "temp", value: r.temporary_password, name: m.display_name }); }}>Reset password</button>
                  {m.totp_enabled && <button className="btn small" onClick={() => api(`family/members/${m.id}/reset-totp`, { body: {} }).then(() => { toast("Authenticator reset"); reload(); })}>Reset 2FA</button>}
                  {m.id !== session?.user?.id && <button className="btn small" onClick={() => api(`family/members/${m.id}`, { method: "PATCH", body: { is_active: !m.is_active } }).then(reload).catch((e) => toast(e.message, "error"))}>{m.is_active ? "Disable" : "Enable"}</button>}
                </td>
              )}
            </tr>
          ))}
        </tbody></table>
      </div>
      <div className="card">
        <h2>Family groups <HelpTip text="Groups organise people (e.g. Grandparents, Uncle's family). A head receives the group's reminders. Groups grant access only where you add a rule for them." link="/help/extended-family#groups" /></h2>
        {groups.data.groups.map((g) => (
          <div key={g.id} className="card" style={{ margin: ".6rem 0" }}>
            <div className="row between">
              <h3>{g.name}</h3>
              {admin && <div className="row"><label className="small" htmlFor={`head-${g.id}`}>Head</label>
                <select id={`head-${g.id}`} value={g.head || ""} onChange={(e) => patchGroup(g.id, { head: e.target.value || null })} style={{ maxWidth: 200 }}><option value="">No head</option>{g.members.map((id) => <option key={id} value={id}>{byId.get(id)?.display_name}</option>)}</select></div>}
            </div>
            <div className="row">{g.members.map((id) => (
              <span key={id} className="badge neutral">{byId.get(id)?.display_name || "Member"}{(admin || session?.delegations?.some((d) => d.group_id === g.id && d.scopes.includes("membership"))) && <button className="icon-btn" style={{ minWidth: 20, minHeight: 20, padding: 0 }} aria-label={`Remove ${byId.get(id)?.display_name}`} onClick={() => patchGroup(g.id, { remove_member: id })}>×</button>}</span>
            ))}</div>
            <div className="row" style={{ marginTop: ".5rem" }}>
              <select aria-label={`Add member to ${g.name}`} defaultValue="" onChange={(e) => { if (e.target.value) patchGroup(g.id, { add_member: e.target.value }); e.target.value = ""; }} style={{ maxWidth: 240 }}>
                <option value="">Add member…</option>{members.data!.members.filter((m) => !g.members.includes(m.id)).map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
              </select>
            </div>
            {g.delegations.length > 0 && <ul className="small">{g.delegations.map((d) => <li key={d.delegate}>Delegate {byId.get(d.delegate)?.display_name}: {d.scopes.map((s) => SCOPE_LABELS[s] || s).join("; ")}</li>)}</ul>}
          </div>
        ))}
        {admin && <form className="row" onSubmit={(e) => { e.preventDefault(); api("family/groups", { body: { name: newGroup } }).then(() => { setNewGroup(""); reload(); }).catch((x) => toast(x.message, "error")); }}>
          <input aria-label="New group name" type="text" placeholder="New group, e.g. Grandparents" value={newGroup} onChange={(e) => setNewGroup(e.target.value)} style={{ maxWidth: 300 }} /><button className="btn" disabled={!newGroup}>Create group</button></form>}
      </div>
      {admin && (
        <div className="card">
          <h2>Delegation <HelpTip text="Give a person scoped administration over one group. Delegates can never grant more than they hold and cannot create delegations." link="/help/extended-family#delegation" /></h2>
          <div className="row">
            <select aria-label="Group" value={deleg.group} onChange={(e) => { const g = groups.data!.groups.find((x) => x.id === e.target.value); setDeleg({ ...deleg, group: e.target.value, scopes: g?.delegations.find((d) => d.delegate === deleg.delegate)?.scopes || [] }); }} style={{ maxWidth: 220 }}>
              <option value="">Group…</option>{groups.data.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
            <select aria-label="Delegate" value={deleg.delegate} onChange={(e) => { const g = groups.data!.groups.find((x) => x.id === deleg.group); setDeleg({ ...deleg, delegate: e.target.value, scopes: g?.delegations.find((d) => d.delegate === e.target.value)?.scopes || [] }); }} style={{ maxWidth: 220 }}>
              <option value="">Person…</option>{members.data.members.filter((m) => !m.is_main_admin).map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select>
          </div>
          <div className="stack" style={{ marginTop: ".6rem" }}>{groups.data.scopes.map((s) => <label key={s} className="check"><input type="checkbox" checked={deleg.scopes.includes(s)} onChange={(e) => setDeleg({ ...deleg, scopes: e.target.checked ? [...deleg.scopes, s] : deleg.scopes.filter((x) => x !== s) })} /> {SCOPE_LABELS[s]}</label>)}</div>
          <button className="btn primary" style={{ marginTop: ".6rem" }} disabled={!deleg.group || !deleg.delegate} onClick={() => api("family/delegations", { body: deleg }).then(() => { toast(deleg.scopes.length ? "Delegation saved" : "Delegation removed"); reload(); }).catch((e) => toast(e.message, "error"))}>Save delegation</button>
          <p className="small muted">Folder access itself is managed per folder: open a folder and choose “Who has access”.</p>
        </div>
      )}
      {dialog?.kind === "member" && <MemberDialog member={dialog.member} groups={groups.data.groups} onClose={() => setDialog(null)} onDone={() => { setDialog(null); reload(); }} />}
      {dialog?.kind === "temp" && <Modal title="Temporary password" onClose={() => setDialog(null)}><div className="alert warn">New temporary password for {dialog.name}: <code>{dialog.value}</code>. Shown once. Their other sessions were signed out.</div></Modal>}
    </div>
  );
}
