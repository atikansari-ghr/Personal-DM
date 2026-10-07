import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatDate, formatDateTime } from "../../api";
import PasskeysCard from "../../components/Passkeys";
import PhotoEditor from "../../components/PhotoEditor";
import { Reauth, withReauth } from "../../components/Reauth";
import SettingsForm from "../../components/SettingsForm";
import { Avatar, CopyButton, Icon, Skeleton, useAsync, useToast } from "../../components/ui";
import { FolderSelect } from "../../components/UploadDialog";
import { useSession } from "../../session";
import type { FolderNode } from "../../types";
import { AuthentikLogo, ChangePassword } from "../Auth";

const SUB: [string, string][] = [["profile", "Profile"], ["security", "Password & security"], ["linked", "Linked accounts"], ["appearance", "Appearance"], ["notifications", "Notifications"], ["email", "Email imports"]];

function Profile() {
  const { session, refresh } = useSession();
  const toast = useToast();
  const u = session!.user!;
  const [form, setForm] = useState({ display_name: u.display_name, full_name: u.full_name || "", email: u.email || "" });
  return (
    <div className="grid two-col">
      <form className="card" onSubmit={async (e) => { e.preventDefault(); try { await api("me", { method: "PATCH", body: form }); toast("Profile saved"); refresh(); } catch (x: any) { toast(x.message, "error"); } }}>
        <h2>Profile information</h2>
        <p className="small muted">Used within your family account.</p>
        <div className="row" style={{ margin: "1rem 0" }}>
          <Avatar user={u} size="lg" />
          <div><h2 style={{ margin: 0 }}>{u.display_name}</h2><div className="row">{u.is_main_admin && <span className="badge" style={{ background: "var(--brand)", color: "var(--brand-ink)" }}>Main administrator</span>}{u.is_head && <span className="badge">Family head</span>}{u.role_label && <span className="badge neutral">{u.role_label}</span>}</div></div>
        </div>
        <div className="field"><label htmlFor="pf">Full name</label><input id="pf" type="text" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Enter your full name" /></div>
        <div className="field"><label htmlFor="pd">Display name</label><input id="pd" type="text" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
        <div className="field"><label htmlFor="pe">Email address</label><input id="pe" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="Add your email" /><div className="hint">Needed for email reminders and self-service password reset.</div></div>
        <div className="field"><label htmlFor="pu">Username</label><input id="pu" type="text" value={u.username} disabled /></div>
        <button className="btn primary">Save profile</button>
      </form>
      <div className="stack">
        <div className="card"><h2>Profile photo</h2><PhotoEditor user={u} endpoint="me/photo" onChanged={refresh} /></div>
        <div className="card row between"><div><h3>Offline documents</h3><p className="small muted">Access saved documents without a connection.</p></div><Link className="btn" to="/offline">Manage saved files</Link></div>
        <div className="card row between"><div><h3>My activity</h3><p className="small muted">Sign-ins and actions on your account.</p></div><Link className="btn" to="/settings/account?tab=security">View</Link></div>
      </div>
    </div>
  );
}

function Security() {
  const { session, refresh } = useSession();
  const toast = useToast();
  const u = session!.user!;
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [reauth, setReauth] = useState<(() => void) | null>(null);
  const audit = useAsync(() => api<{ events: any[] }>("audit", { query: { action: "auth" } }), []);
  return (
    <div className="grid two-col">
      <div className="card"><h2>Change password</h2><ChangePassword /></div>
      <div className="stack">
        <div className="card">
          <div className="row between"><div><h2>Authenticator app</h2><p className="small muted">Adds a 6-digit code at sign-in, including Google sign-in. Works with authenticator apps and password managers that support one-time codes (e.g. Bitwarden, 1Password, Apple Passwords).</p></div>
            <span className={`badge ${u.totp_enabled ? "ok" : "soon"}`}>{u.totp_enabled ? "Enabled" : "Not enabled"}</span></div>
          {!u.totp_enabled && !setup && session?.totp_allowed === false && <p className="small muted">New authenticator set-ups are turned off by the administrator.</p>}
          {!u.totp_enabled && !setup && session?.totp_allowed !== false && <button className="btn" onClick={withReauth(async () => setSetup(await api("me/totp/setup", { method: "POST" })), setReauth, toast)}>Set up</button>}
          {setup && (
            <div className="stack">
              <p className="small">Scan this QR code with your authenticator app, or enter the key manually.</p>
              <div style={{ width: 200, background: "#fff" }} dangerouslySetInnerHTML={{ __html: setup.qr_svg.replace(/<\?xml[^>]*>/, "") }} />
              <div className="row"><code>{setup.secret}</code><CopyButton label="Key" getValue={() => setup.secret} /></div>
              <form className="row" onSubmit={async (e) => { e.preventDefault(); try { const r = await api("me/totp/enable", { body: { code } }); setCodes(r.recovery_codes); setSetup(null); refresh(); } catch (x: any) { toast(x.message, "error"); } }}>
                <input aria-label="Code from app" name="one-time-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/[\s-]/g, ""))} style={{ maxWidth: 160 }} /><button className="btn primary">Verify & enable</button>
              </form>
            </div>
          )}
          {(u.totp_enabled || (u.passkey_count || 0) > 0) && (
            <div className="row">
              <button className="btn" onClick={withReauth(async () => setCodes((await api("me/recovery-codes", { method: "POST" })).recovery_codes), setReauth, toast)}>New recovery codes</button>
              {u.totp_enabled && <button className="btn danger" onClick={withReauth(async () => { await api("me/totp/disable", { method: "POST" }); toast("Authenticator removed"); refresh(); }, setReauth, toast)}>Turn off</button>}
            </div>
          )}
          {codes && (
            <div className="alert warn"><strong>Recovery codes — shown once.</strong> Each works one time if you lose your phone. Store them safely.
              <pre className="mono">{codes.join("\n")}</pre><CopyButton label="Recovery codes" getValue={() => codes.join("\n")} /></div>
          )}
        </div>
        <PasskeysCard />
        <Sessions />
        <div className="card">
          <h2>Recent sign-in activity</h2>
          {audit.loading ? <Skeleton /> : <ul className="small">{audit.data?.events.slice(0, 10).map((e) => <li key={e.id}>{formatDateTime(e.at)} — {e.action} ({e.outcome}){e.context?.method ? ` via ${e.context.method}` : ""}</li>)}</ul>}
        </div>
      </div>
      {reauth && <Reauth onClose={() => setReauth(null)} onDone={reauth} />}
    </div>
  );
}

function Sessions() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<{ sessions: any[] }>("me/sessions"), []);
  return (
    <div className="card">
      <h2>Active sessions</h2>
      <p className="small muted">Devices where you are signed in. Sign out any device you do not recognise and change your password.</p>
      {!data ? <Skeleton /> : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Signed-in devices">
          {data.sessions.map((s) => (
            <li key={s.id} className="list-item">
              <Icon name="eye" />
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{s.device} {s.current && <span className="badge ok">This device</span>}</div>
                <div className="small muted">Last active {formatDateTime(s.last_seen_at)} · signed in {formatDateTime(s.created_at)}{s.ip ? ` · ${s.ip}` : ""}{s.method ? ` · ${s.method}` : ""}</div>
              </div>
              {!s.current && <button className="btn small danger" aria-label={`Sign out ${s.device}`} onClick={() => api(`me/sessions/${s.id}`, { method: "DELETE" }).then(() => { toast(`${s.device} signed out`); reload(); }).catch((e) => toast(e.message, "error"))}>Sign out</button>}
            </li>
          ))}
        </ul>
      )}
      <button className="btn" style={{ marginTop: ".6rem" }} onClick={() => api("me/sessions/revoke", { method: "POST" }).then(() => { toast("Other devices were signed out"); reload(); })}>Sign out all other devices</button>
    </div>
  );
}

function AuthentikLink() {
  const toast = useToast();
  const [params] = useSearchParams();
  const [reauth, setReauth] = useState<(() => void) | null>(null);
  const { data, reload } = useAsync(() => api<any>("me/authentik"), []);
  const err = params.get("error");
  if (!data || !data.enabled) return null;
  return (
    <div className="card" style={{ maxWidth: 720, marginTop: "1rem" }}>
      <h2><AuthentikLogo /> authentik</h2>
      {params.get("linked") === "authentik" && <div className="alert ok">authentik account linked.</div>}
      {err === "authentik_already_linked" && <div className="alert error">That authentik account is already linked to another family account.</div>}
      {err === "reauth_required" && <div className="alert warn">Please confirm your password, then link again.</div>}
      <p className="small muted">Link your family identity-provider account so you can use <strong>{data.label}</strong>. Accounts are only linked here, by you — never because an email address matches. Your password and two-step verification keep working.</p>
      {data.linked ? (
        <div className="stack">
          <p>Linked to <strong>{data.username || data.email}</strong> since {formatDate(data.linked_at)}{data.last_login_at ? `; last used ${formatDateTime(data.last_login_at)}` : ""}.</p>
          <button className="btn danger" disabled={!data.has_password} title={data.has_password ? "" : "Ask the administrator to set a local password first."}
            onClick={withReauth(async () => { await api("me/authentik", { method: "DELETE" }); toast("authentik unlinked"); reload(); }, setReauth, toast)}>Unlink</button>
        </div>
      ) : (
        <button className="btn primary" onClick={() => setReauth(() => () => { window.location.href = "/api/auth/authentik/start?mode=link"; })}>Link authentik account</button>
      )}
      {reauth && <Reauth onClose={() => setReauth(null)} onDone={reauth} />}
    </div>
  );
}

function Linked() {
  const toast = useToast();
  const [params] = useSearchParams();
  const [reauth, setReauth] = useState<(() => void) | null>(null);
  const { data, reload } = useAsync(() => api<{ enabled: boolean; linked: boolean; email: string | null; linked_at: string | null }>("me/google"), []);
  const err = params.get("error");
  if (!data) return <Skeleton />;
  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <h2>Google account</h2>
      {params.get("linked") && <div className="alert ok">Google account linked.</div>}
      {err === "google_already_linked" && <div className="alert error">That Google account is already linked to another family account.</div>}
      {err === "reauth_required" && <div className="alert warn">Please confirm your password, then connect again.</div>}
      <p className="small muted">Google is only an extra way to sign in to this account. Documents stay on your server; Google sees the sign-in itself. No Gmail or Drive access is requested.</p>
      {!data.enabled ? <div className="alert">Google sign-in is not enabled by the administrator.</div> : data.linked ? (
        <div className="stack">
          <p>Linked to <strong>{data.email}</strong> since {formatDate(data.linked_at)}.</p>
          <button className="btn danger" onClick={withReauth(async () => { await api("me/google", { method: "DELETE" }); toast("Google disconnected"); reload(); }, setReauth, toast)}>Disconnect</button>
        </div>
      ) : (
        <button className="btn primary" onClick={() => setReauth(() => () => { window.location.href = "/api/auth/google/start?mode=link"; })}>Connect Google account</button>
      )}
      {reauth && <Reauth onClose={() => setReauth(null)} onDone={reauth} />}
    </div>
  );
}

const CH_LABEL: Record<string, string> = { in_app: "In-app", email: "Email", telegram: "Telegram" };
const GROUPS: [string, string][] = [["documents", "Documents"], ["security", "Account & security"], ["system", "System (administrators)"]];

function Channels() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<any>("me/notification-preferences"), []);
  const [link, setLink] = useState<any>(null);
  const [busy, setBusy] = useState("");
  if (!data) return <Skeleton />;
  const channels: any[] = data.channels;
  const critical = data.events.filter((e: any) => e.critical);
  const optional = data.events.filter((e: any) => !e.critical);
  const toggle = async (ev: any, ch: string, on: boolean) => {
    const next = on ? [...new Set([...ev.chosen, ch])] : ev.chosen.filter((c: string) => c !== ch);
    setBusy(`${ev.key}:${ch}`);
    try { await api("me/notification-preferences", { method: "PUT", body: { preferences: { [ev.key]: next } } }); await reload(); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(""); }
  };
  return (
    <div className="stack">
      {data.problems.length > 0 && (
        <div className="alert error" role="alert">
          <strong>Some required notifications cannot reach you.</strong>
          <ul style={{ margin: ".3rem 0 0" }}>{data.problems.map((p: any) => <li key={p.channel}>{CH_LABEL[p.channel]}: {p.issue} (needed for {p.events.slice(0, 3).join(", ")}{p.events.length > 3 ? ` and ${p.events.length - 3} more` : ""})</li>)}</ul>
          <p className="small" style={{ margin: ".3rem 0 0" }}>Add an email address under Profile, link Telegram below, or ask the administrator to configure the channel.</p>
        </div>
      )}
      <div className="card">
        <h2>Critical notifications</h2>
        <p className="small muted">Chosen by the family administrator. They cannot be turned off and always arrive on the channels shown.</p>
        <ul className="crit-list">
          {critical.map((e: any) => (
            <li key={e.key}><Icon name="lock" size={14} /> <strong>{e.label}</strong> <span className="small muted">— {e.description}</span>
              <div className="small">{e.channels.map((c: string) => <span key={c} className="badge neutral" style={{ marginRight: ".25rem" }}>{CH_LABEL[c]}</span>)}</div></li>
          ))}
        </ul>
      </div>
      <div className="card">
        <h2>Optional notifications</h2>
        <p className="small muted">Pick the events you want and where each one should reach you. Large actions (imports, many uploads) arrive as one summary with a report link.</p>
        <div className="table-scroll">
          <table className="matrix">
            <thead><tr><th scope="col">Event</th>{channels.map((c) => <th scope="col" key={c.channel}>{c.label}</th>)}</tr></thead>
            {GROUPS.map(([g, gl]) => {
              const rows = optional.filter((e: any) => e.group === g);
              if (!rows.length) return null;
              return (
                <tbody key={g}>
                  <tr className="matrix-group"><th colSpan={channels.length + 1} scope="rowgroup">{gl}</th></tr>
                  {rows.map((e: any) => (
                    <tr key={e.key}>
                      <th scope="row"><div>{e.label}</div><div className="small muted" style={{ fontWeight: 400 }}>{e.description}</div></th>
                      {channels.map((c) => {
                        const locked = e.locked.includes(c.channel);
                        const checked = e.channels.includes(c.channel);
                        const unavailable = !c.configured && !checked;
                        return (
                          <td key={c.channel} data-label={c.label}>
                            <input type="checkbox" aria-label={`${e.label} by ${c.label}`} checked={checked} disabled={locked || unavailable || busy === `${e.key}:${c.channel}`}
                              title={locked ? "Required by the administrator" : unavailable ? `${c.label} is not configured by the administrator` : ""}
                              onChange={(ev) => toggle(e, c.channel, ev.target.checked)} />
                            {locked && <span className="sr-only"> (required)</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              );
            })}
          </table>
        </div>
        <p className="small muted">{channels.filter((c) => c.channel !== "in_app" && c.issue).map((c) => `${c.label}: ${c.issue}`).join(" · ")}</p>
      </div>
      <div className="card">
        <h2>Telegram</h2>
        {data.telegram.linked ? (
          <><p>Linked{data.telegram.username ? ` to @${data.telegram.username}` : ""}.</p><button className="btn danger" onClick={() => api("me/telegram", { method: "DELETE" }).then(reload)}>Unlink</button></>
        ) : (
          <div className="stack">
            <p className="small">Link your own Telegram so notifications reach you there. You must send the code to the bot from your Telegram account.</p>
            {!link ? <button className="btn" onClick={() => api("me/telegram", { method: "POST" }).then(setLink).catch((e) => toast(e.message, "error"))}>Get link code</button> : (
              <div className="stack">
                <p>Send <code>/start {link.code}</code> to the bot{data.telegram.bot ? ` @${data.telegram.bot}` : ""} within {link.expires_minutes} minutes.</p>
                {link.deep_link && <a className="btn primary" href={link.deep_link} target="_blank" rel="noopener noreferrer">Open Telegram</a>}
                <button className="btn" onClick={() => api("me/telegram/check", { method: "POST" }).then((r) => { if (r.linked) { toast("Telegram linked"); setLink(null); reload(); } else toast("Not linked yet — send the code, then check again.", "error"); }).catch((e) => toast(e.message, "error"))}>I've sent it — check</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EmailImports() {
  const toast = useToast();
  const { data, reload } = useAsync(() => api<{ accounts: any[] }>("me/email-accounts"), []);
  const [folders, setFolders] = useState<FolderNode[]>([]);
  const [form, setForm] = useState<any>({ label: "", host: "", port: 993, security: "ssl", username: "", password: "", mailbox: "INBOX", poll_minutes: 30 });
  const [rule, setRule] = useState<any>({ name: "", sender_contains: "", subject_contains: "", extensions: "pdf,jpg,jpeg,png", max_mb: 25, destination: "" });
  useEffect(() => { api<{ folders: FolderNode[] }>("folders").then((r) => setFolders(r.folders)); }, []);
  if (!data) return <Skeleton />;
  return (
    <div className="stack">
      <div className="alert">Connect your own mailbox over IMAP to import attachments that match your rules. Messages are only read, never moved or deleted. Signing in with Google does not give access to Gmail; for Gmail use an app password with IMAP. Your mailbox password is stored encrypted and is never shown to anyone.</div>
      {data.accounts.map((a) => (
        <div key={a.id} className="card stack">
          <div className="row between"><div><h3>{a.label}</h3><p className="small muted">{a.username} @ {a.host} · {a.mailbox} · every {a.poll_minutes} min · last checked {formatDateTime(a.last_poll_at)}</p>
            {a.last_error && <div className="small error-text">{a.last_error}</div>}{a.disabled_by_admin && <span className="badge danger">Disabled by administrator</span>}</div>
            <div className="row"><button className="btn small" onClick={() => api(`me/email-accounts/${a.id}/test`, { method: "POST" }).then((r) => toast(`Connected. ${r.mailboxes.length} folders found.`)).catch((e) => toast(e.message, "error"))}>Test connection</button>
              <button className="btn small" onClick={() => api(`me/email-accounts/${a.id}/poll`, { method: "POST" }).then(() => toast("Check queued"))}>Check now</button>
              <button className="btn small danger" onClick={() => api(`me/email-accounts/${a.id}`, { method: "DELETE" }).then(reload)}>Remove</button></div></div>
          <h4>Rules</h4>
          {a.rules.length === 0 && <p className="small muted">No rules yet — nothing will be imported.</p>}
          {a.rules.map((r: any) => <div key={r.id} className="row between small"><span><strong>{r.name}</strong>: from “{r.sender_contains || "anyone"}”, subject “{r.subject_contains || "any"}”, {r.extensions} → {r.destination_name}</span><button className="btn small" onClick={() => api(`me/email-accounts/${a.id}/rules/${r.id}`, { method: "DELETE" }).then(reload)}>Delete</button></div>)}
          <form className="row" onSubmit={(e) => { e.preventDefault(); api(`me/email-accounts/${a.id}/rules`, { body: rule }).then(() => { reload(); setRule({ ...rule, name: "" }); }).catch((x) => toast(x.message, "error")); }}>
            <input aria-label="Rule name" type="text" placeholder="Rule name" value={rule.name} onChange={(e) => setRule({ ...rule, name: e.target.value })} style={{ maxWidth: 160 }} />
            <input aria-label="Sender contains" type="text" placeholder="Sender contains" value={rule.sender_contains} onChange={(e) => setRule({ ...rule, sender_contains: e.target.value })} style={{ maxWidth: 180 }} />
            <input aria-label="Subject contains" type="text" placeholder="Subject contains" value={rule.subject_contains} onChange={(e) => setRule({ ...rule, subject_contains: e.target.value })} style={{ maxWidth: 180 }} />
            <input aria-label="File types" type="text" value={rule.extensions} onChange={(e) => setRule({ ...rule, extensions: e.target.value })} style={{ maxWidth: 160 }} />
            <div style={{ minWidth: 220 }}><FolderSelect id={`dest-${a.id}`} folders={folders} value={rule.destination} onChange={(v) => setRule({ ...rule, destination: v })} /></div>
            <button className="btn" disabled={!rule.destination}>Add rule</button>
          </form>
          {a.history.length > 0 && <details><summary>Import history</summary><ul className="small">{a.history.map((h: any, i: number) => <li key={i}>{formatDateTime(h.at)} {h.filename} — {h.status}{h.error ? `: ${h.error}` : ""}{h.document && <> · <Link to={`/documents/${h.document}`}>open</Link></>}</li>)}</ul></details>}
        </div>
      ))}
      <form className="card" onSubmit={async (e) => { e.preventDefault(); try { await api("me/email-accounts", { body: form }); toast("Mailbox added"); setForm({ ...form, password: "", label: "" }); reload(); } catch (x: any) { toast(x.message, "error"); } }}>
        <h3>Add a mailbox</h3>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: ".6rem" }}>
          {[["label", "Label", "text"], ["host", "IMAP server", "text"], ["port", "Port", "number"], ["username", "Username", "text"], ["password", "Password / app password", "password"], ["mailbox", "Folder", "text"], ["poll_minutes", "Check every (minutes)", "number"]].map(([k, l, t]) => (
            <div className="field" key={k}><label htmlFor={`em-${k}`}>{l}</label><input id={`em-${k}`} type={t} autoComplete={t === "password" ? "new-password" : "off"} value={form[k]} onChange={(e) => setForm({ ...form, [k]: t === "number" ? Number(e.target.value) : e.target.value })} /></div>
          ))}
          <div className="field"><label htmlFor="em-sec">Security</label><select id="em-sec" value={form.security} onChange={(e) => setForm({ ...form, security: e.target.value })}><option value="ssl">SSL/TLS (993)</option><option value="starttls">STARTTLS (143)</option></select></div>
        </div>
        <button className="btn primary">Add mailbox</button>
      </form>
    </div>
  );
}

export default function AccountSettings() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "profile";
  return (
    <div>
      <nav className="tabs" aria-label="My account">{SUB.map(([k, l]) => <button key={k} className={tab === k ? "active" : ""} aria-current={tab === k} onClick={() => setParams({ tab: k })}>{l}</button>)}</nav>
      {tab === "profile" && <Profile />}
      {tab === "security" && <><Security /><AuthentikLink /></>}
      {tab === "linked" && <Linked />}
      {tab === "appearance" && <SettingsForm section="appearance" title="Appearance"><p className="small muted">Your theme applies to your account on every device. Other family members choose their own. Black & White is a monochrome light theme.</p></SettingsForm>}
      {tab === "notifications" && <Channels />}
      {tab === "email" && <EmailImports />}
    </div>
  );
}
