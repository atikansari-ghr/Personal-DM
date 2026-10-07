import { useState } from "react";
import { api, formatDateTime } from "../../api";
import SettingsForm from "../../components/SettingsForm";
import { Avatar, Confirm, CopyButton, Icon, Skeleton, useAsync, useToast } from "../../components/ui";

/** Settings → Authentication → External identity providers (authentik). */

function GroupMapping() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<{ settings: any[] }>("settings"), []);
  const [rows, setRows] = useState<[string, string][] | null>(null);
  if (!data) return <Skeleton />;
  const current: Record<string, string> = data.settings.find((s) => s.key === "authentik.group_mapping")?.value || {};
  const list = rows ?? Object.entries(current);
  const save = async () => {
    const value = Object.fromEntries(list.filter(([g]) => g.trim()).map(([g, r]) => [g.trim(), r]));
    try { await api("settings", { method: "PUT", body: { values: { "authentik.group_mapping": value } } }); toast("Group mapping saved"); setRows(null); reload(); }
    catch (e: any) { toast(e.data?.fields?.["authentik.group_mapping"] || e.message, "error"); }
  };
  return (
    <div className="stack">
      <h3>Group-to-role mapping</h3>
      <p className="small muted">Used only when <em>Map authentik groups to roles</em> is on. A group can make someone a <strong>Member</strong> or an <strong>Administrator</strong> (security area). The main administrator is never assigned or removed by a group, and groups never give access to documents or folders.</p>
      <table className="responsive"><thead><tr><th>authentik group</th><th>Role</th><th /></tr></thead><tbody>
        {list.map(([g, r], i) => (
          <tr key={i}>
            <td><input aria-label="authentik group" value={g} onChange={(e) => setRows(list.map((x, j) => j === i ? [e.target.value, x[1]] : x))} /></td>
            <td><select aria-label={`Role for ${g || "group"}`} value={r} onChange={(e) => setRows(list.map((x, j) => j === i ? [x[0], e.target.value] : x))}><option value="member">Member</option><option value="administrator">Administrator</option></select></td>
            <td><button className="btn small ghost" aria-label={`Remove mapping ${g}`} onClick={() => setRows(list.filter((_, j) => j !== i))}><Icon name="x" size={14} /></button></td>
          </tr>
        ))}
      </tbody></table>
      <div className="row"><button className="btn small" onClick={() => setRows([...list, ["", "member"]])}><Icon name="plus" size={14} /> Add group</button>
        <button className="btn small primary" disabled={rows === null} onClick={save}>Save mapping</button></div>
    </div>
  );
}

function Links() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("auth/authentik/links"), []);
  const [revoke, setRevoke] = useState<any>(null);
  if (!data) return <Skeleton />;
  return (
    <div className="stack">
      <h3>Linked accounts</h3>
      {data.links.length === 0 ? <p className="small muted">No account is linked yet. People link authentik themselves in My account → Password &amp; security.</p> : (
        <table className="responsive"><thead><tr><th>Person</th><th>authentik user</th><th className="hide-mobile">Groups</th><th className="hide-mobile">Last sign-in</th><th /></tr></thead><tbody>
          {data.links.map((l: any) => (
            <tr key={l.id}><td><div className="row"><Avatar user={l.user} size="sm" /> {l.user.display_name}</div>{l.provisioned && <span className="badge neutral">Created automatically</span>}</td>
              <td>{l.username || l.email}</td><td className="hide-mobile small">{(l.groups || []).join(", ")}</td>
              <td className="hide-mobile small">{l.last_login_at ? formatDateTime(l.last_login_at) : "Never"}</td>
              <td><button className="btn small danger" onClick={() => setRevoke(l)}>Revoke</button></td></tr>
          ))}
        </tbody></table>
      )}
      {revoke && <Confirm title="Revoke authentik link" danger confirmLabel="Revoke" message={<p>{revoke.user.display_name} can no longer sign in with authentik. Their account, password and documents stay as they are, and they are signed out of open sessions.</p>}
        onClose={() => setRevoke(null)} onConfirm={async () => { await api(`auth/authentik/links/${revoke.id}`, { method: "DELETE" }); setRevoke(null); toast("Link revoked"); reload(); }} />}
    </div>
  );
}

export default function AuthentikAdmin() {
  const [test, setTest] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  return (
    <SettingsForm section="identity" title="External identity providers — authentik">
      <div className="stack" style={{ marginTop: ".8rem" }}>
        <p className="small muted">Local sign-in (password, authenticator app, passkeys) always stays available, so nobody is locked out when authentik is down. Accounts are linked only by their owner; a matching email address never links accounts. <a href="/help/authentik">authentik setup guide</a></p>
        <div className="row">
          <button className="btn small" disabled={busy} onClick={async () => { setBusy(true); try { setTest(await api("auth/authentik/test", { method: "POST" })); } finally { setBusy(false); } }}><Icon name="refresh" size={16} /> Test connection</button>
        </div>
        {test && (
          <div className="card" style={{ background: "var(--brand-softer)" }}>
            <div><strong>Redirect URI</strong> (add exactly this to the authentik provider):<div className="row"><code>{test.callback_url}</code><CopyButton label="Redirect URI" getValue={() => test.callback_url} /></div></div>
            <ul className="small">{test.checks.map((c: any) => <li key={c.name}>{c.ok ? "✅" : "❌"} {c.name}{c.detail ? ` — ${c.detail}` : ""}</li>)}</ul>
            <p className="small muted">{test.note}</p>
          </div>
        )}
        <GroupMapping />
        <Links />
      </div>
    </SettingsForm>
  );
}
