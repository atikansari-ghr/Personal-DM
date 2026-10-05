import { useState } from "react";
import { api, ApiError, formatDateTime } from "../api";
import { useSession } from "../session";
import { createPasskey, passkeyErrorMessage, passkeysSupported } from "../webauthn";
import { Reauth, withReauth } from "./Reauth";
import { CopyButton, HelpTip, Icon, Skeleton, useAsync, useToast } from "./ui";

/** Settings → My account → Security → Passkeys */
export default function PasskeysCard() {
  const { refresh } = useSession();
  const toast = useToast();
  const data = useAsync(() => api<any>("me/passkeys"), []);
  const [name, setName] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [reauth, setReauth] = useState<(() => void) | null>(null);
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);
  if (!data.data) return <div className="card"><Skeleton /></div>;
  const d = data.data;
  const supported = passkeysSupported();
  const add = withReauth(async () => {
    const options = await api("me/passkeys", { body: { step: "options" } });
    let credential;
    try { credential = await createPasskey(options); } catch (e: any) { throw new Error(passkeyErrorMessage(e)); }
    const r = await api("me/passkeys", { body: { credential, name: name || "Passkey" } });
    if (r.recovery_codes) setCodes(r.recovery_codes);
    setName("");
    toast("Passkey added");
    data.reload();
    refresh();
  }, setReauth, toast);
  const remove = (id: number) => withReauth(async () => { await api(`me/passkeys/${id}`, { method: "DELETE" }); toast("Passkey removed"); data.reload(); refresh(); }, setReauth, toast)();
  const passwordless = (enabled: boolean) => withReauth(async () => { await api("me/passwordless", { body: { enabled } }); toast(enabled ? "Passwordless sign-in turned on" : "Passwordless sign-in turned off"); data.reload(); refresh(); }, setReauth, toast)();
  return (
    <div className="card">
      <div className="row between"><div><h2>Passkeys <HelpTip text="A passkey is a key stored on your phone, computer, password manager or security key, unlocked with fingerprint, face or PIN. It is used after your password as a second step, or alone if you turn on passwordless sign-in." link="/help/passkeys" /></h2>
        <p className="small muted">Works with iPhone/iPad, Android, Windows Hello, macOS, password managers and security keys. Bound to {d.rp_id}.</p></div>
        <span className={`badge ${d.passkeys.length ? "ok" : "soon"}`}>{d.passkeys.length ? `${d.passkeys.length} registered` : "None"}</span></div>
      {d.passkeys.length > 0 && (
        <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
          {d.passkeys.map((p: any) => (
            <li key={p.id} className="list-item">
              <Icon name="lock" />
              <div className="grow">
                {renaming && renaming.id === p.id ? (
                  <form className="row" onSubmit={(e) => { e.preventDefault(); api(`me/passkeys/${p.id}`, { method: "PATCH", body: { name: renaming.name } }).then(() => { setRenaming(null); data.reload(); }).catch((x) => toast(x.message, "error")); }}>
                    <input aria-label="Passkey name" type="text" value={renaming.name} onChange={(e) => setRenaming({ id: p.id, name: e.target.value })} style={{ maxWidth: 220 }} autoFocus /><button className="btn small">Save</button>
                  </form>
                ) : <strong>{p.name}</strong>}
                <div className="small muted">Added {formatDateTime(p.created_at)} · {p.last_used_at ? `last used ${formatDateTime(p.last_used_at)}` : "not used yet"}{p.synced ? " · synced" : ""}{p.passwordless_capable ? " · passwordless capable" : ""}</div>
              </div>
              <button className="btn small ghost" onClick={() => setRenaming({ id: p.id, name: p.name })}>Rename</button>
              <button className="btn small danger" onClick={() => remove(p.id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {!d.allowed ? <p className="small muted">Passkey registration is turned off by the administrator.</p> : !supported ? (
        <p className="small muted">This browser or address cannot create passkeys. Open the app through its secure HTTPS address.</p>
      ) : (
        <form className="row" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <label htmlFor="pk-name" className="sr-only">Passkey name</label>
          <input id="pk-name" type="text" placeholder="Name, e.g. My iPhone" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} style={{ maxWidth: 240 }} />
          <button className="btn"><Icon name="plus" size={16} /> Add a passkey</button>
        </form>
      )}
      {d.passwordless_allowed && d.passkeys.length > 0 && (
        <label className="check" style={{ marginTop: ".6rem" }}>
          <input type="checkbox" checked={d.passwordless_enabled} onChange={(e) => passwordless(e.target.checked)} />
          Allow signing in with a passkey alone (passwordless). <span className="small muted">Your password keeps working.</span>
        </label>
      )}
      {codes && (
        <div className="alert warn"><strong>Recovery codes — shown once.</strong> Each works one time if you lose your passkeys. Store them safely.
          <pre className="mono">{codes.join("\n")}</pre><CopyButton label="Recovery codes" getValue={() => codes.join("\n")} /></div>
      )}
      {reauth && <Reauth onClose={() => setReauth(null)} onDone={reauth} />}
    </div>
  );
}

export function ApiErrorText({ e }: { e: unknown }) {
  return <span>{e instanceof ApiError ? e.message : String(e)}</span>;
}
