import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/ui";
import { AuthFrame } from "./Auth";

interface Person { display_name: string; full_name: string; username: string; email: string; role_label: string; password: string; generate_password: boolean }

const blank = (role = ""): Person => ({ display_name: "", full_name: "", username: "", email: "", role_label: role, password: "", generate_password: true });
const suggestUsername = (name: string) => name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "").slice(0, 30);

/**
 * First-run setup. Only the main administrator is required; family members are optional, can be added here
 * (any number, or none) or later in Settings -> Family & access. Nothing is created from placeholder slots.
 */
export default function Setup() {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [groupName, setGroupName] = useState("My family");
  const [timezone, setTimezone] = useState("Asia/Riyadh");
  const [shareView, setShareView] = useState(false);
  const [applyTemplate, setApplyTemplate] = useState(false);
  const [admin, setAdmin] = useState<Person>({ ...blank("Main administrator"), generate_password: false });
  const [members, setMembers] = useState<Person[]>([]);
  const [relationships, setRelationships] = useState<string[]>([]);
  const [result, setResult] = useState<{ issued_passwords: Record<string, string> } | null>(null);
  const [busy, setBusy] = useState(false);

  const verify = async () => {
    setError("");
    try {
      const r = await api<{ relationships: string[]; timezone: string }>("setup/verify", { body: { token } });
      setRelationships(r.relationships || []);
      setTimezone(r.timezone || "Asia/Riyadh");
      setStep(2);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const update = (i: number, patch: Partial<Person>) => setMembers((m) => m.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const named = (p: Person) => p.display_name.trim() !== "";
  const membersValid = members.every((m) => named(m) && m.username.trim() && (m.generate_password || m.password));
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api("setup/complete", { body: { token, group_name: groupName, timezone, share_family_folder_view: shareView, apply_template: applyTemplate, admin, members } });
      setResult(r);
      setStep(5);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const personFields = (p: Person, set: (patch: Partial<Person>) => void, prefix: string) => (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.6rem" }}>
      <div className="field"><label htmlFor={`${prefix}-n`}>Display name</label>
        <input id={`${prefix}-n`} type="text" value={p.display_name} maxLength={80}
          onChange={(e) => set({ display_name: e.target.value, ...(p.username === suggestUsername(p.display_name) || !p.username ? { username: suggestUsername(e.target.value) } : {}) })} /></div>
      <div className="field"><label htmlFor={`${prefix}-u`}>Username</label><input id={`${prefix}-u`} type="text" autoCapitalize="none" value={p.username} onChange={(e) => set({ username: e.target.value.toLowerCase() })} /></div>
      <div className="field"><label htmlFor={`${prefix}-r`}>Relationship (optional)</label><input id={`${prefix}-r`} type="text" list="relationships" value={p.role_label} maxLength={40} onChange={(e) => set({ role_label: e.target.value })} /></div>
      <div className="field"><label htmlFor={`${prefix}-f`}>Full name (optional)</label><input id={`${prefix}-f`} type="text" value={p.full_name} onChange={(e) => set({ full_name: e.target.value })} /></div>
      <div className="field"><label htmlFor={`${prefix}-e`}>Email (optional)</label><input id={`${prefix}-e`} type="email" value={p.email} onChange={(e) => set({ email: e.target.value })} /></div>
    </div>
  );

  return (
    <AuthFrame>
      <div className="panel" style={{ maxWidth: 720 }}>
        <p className="muted small">First-run setup · step {Math.min(step, 4)} of 4</p>
        {error && <div className="alert error" role="alert">{error}</div>}
        <datalist id="relationships">{relationships.map((r) => <option key={r} value={r} />)}</datalist>
        {step === 1 && (
          <form onSubmit={(e) => { e.preventDefault(); verify(); }}>
            <h1>Set up your family library</h1>
            <p className="muted">Run <code>personaldocs setup-token</code> on the server console and enter the one-time code it prints. Nobody else can claim this installation.</p>
            <div className="field"><label htmlFor="token">One-time setup code</label><input id="token" type="text" value={token} onChange={(e) => setToken(e.target.value.trim())} autoComplete="off" /></div>
            <button className="btn primary" disabled={!token}>Continue</button>
          </form>
        )}
        {step === 2 && (
          <form onSubmit={(e) => { e.preventDefault(); setStep(3); }}>
            <h1>Main administrator</h1>
            <p className="muted">This is your own account. It owns the installation, manages family members and settings, and is the family head.</p>
            {personFields(admin, (patch) => setAdmin((a) => ({ ...a, ...patch })), "admin")}
            <div className="field"><label htmlFor="admin-p">Your password</label><input id="admin-p" type="password" autoComplete="new-password" value={admin.password} onChange={(e) => setAdmin((a) => ({ ...a, password: e.target.value }))} /><div className="hint">At least 10 characters.</div></div>
            <div className="row"><button type="button" className="btn" onClick={() => setStep(1)}>Back</button><button className="btn primary" disabled={!named(admin) || !admin.username || !admin.password}>Continue</button></div>
          </form>
        )}
        {step === 3 && (
          <div>
            <h1>Add family members <span className="muted" style={{ fontWeight: 500 }}>(optional)</span></h1>
            <p className="muted">Add as many people as you like now, or skip this step and add them later in <strong>Settings → Family &amp; access</strong>. No accounts are created for people you do not add.</p>
            {members.length === 0 && <div className="empty small" style={{ padding: "1rem" }}>No family members added yet.</div>}
            {members.map((m, i) => (
              <fieldset key={i} className="card" style={{ margin: "0.8rem 0" }}>
                <legend style={{ fontWeight: 700, padding: "0 .3rem" }}>Family member {i + 1}</legend>
                {personFields(m, (patch) => update(i, patch), `m${i}`)}
                <div className="row between">
                  <span className="row">
                    <label className="check"><input type="checkbox" checked={m.generate_password} onChange={(e) => update(i, { generate_password: e.target.checked, password: "" })} /> Generate a temporary password</label>
                    {!m.generate_password && <input aria-label={`Temporary password for family member ${i + 1}`} type="password" autoComplete="new-password" placeholder="Temporary password" value={m.password} onChange={(e) => update(i, { password: e.target.value })} style={{ maxWidth: 240 }} />}
                  </span>
                  <button type="button" className="btn small ghost" onClick={() => setMembers((ms) => ms.filter((_, j) => j !== i))}>Remove</button>
                </div>
              </fieldset>
            ))}
            <button type="button" className="btn" onClick={() => setMembers((ms) => [...ms, blank()])}><Icon name="plus" size={16} /> Add a family member</button>
            <div className="row" style={{ marginTop: "1rem" }}>
              <button className="btn" onClick={() => setStep(2)}>Back</button>
              {members.length === 0
                ? <button className="btn primary" onClick={() => setStep(4)}>Skip for now</button>
                : <button className="btn primary" onClick={() => setStep(4)} disabled={!membersValid}>Continue</button>}
            </div>
          </div>
        )}
        {step === 4 && (
          <div>
            <h1>Family group & settings</h1>
            <div className="field"><label htmlFor="g">Family group name</label><input id="g" type="text" value={groupName} onChange={(e) => setGroupName(e.target.value)} /></div>
            <div className="field"><label htmlFor="tz">Timezone</label><input id="tz" type="text" value={timezone} onChange={(e) => setTimezone(e.target.value)} /><div className="hint">Used for expiry reminders and the Overview date, e.g. Asia/Riyadh or Asia/Kolkata.</div></div>
            <label className="check field"><input type="checkbox" checked={shareView} onChange={(e) => setShareView(e.target.checked)} /> Let everyone in the family group view the "Shared family" folder</label>
            <label className="check field"><input type="checkbox" checked={applyTemplate} onChange={(e) => setApplyTemplate(e.target.checked)} /> Create the suggested folders for each person (Identity, Education, Medical, Travel…)</label>
            <p className="muted small">Each person can see only their own folder until you grant more access. You can change all of this later in Settings → Family & access.</p>
            <div className="row"><button className="btn" onClick={() => setStep(3)}>Back</button><button className="btn primary" onClick={submit} disabled={busy}>{members.length ? `Create ${members.length + 1} accounts` : "Create my account"}</button></div>
          </div>
        )}
        {step === 5 && result && (
          <div>
            <h1>All set</h1>
            <p>{members.length ? "Your account and the family accounts were created." : "Your administrator account was created. Add family members any time in Settings → Family & access."}</p>
            {Object.keys(result.issued_passwords).length > 0 && (
              <div className="alert warn">
                <strong>Temporary passwords — shown only once.</strong> Hand them over privately; each person must change theirs at first sign-in.
                <table style={{ marginTop: ".5rem" }}><tbody>{Object.entries(result.issued_passwords).map(([u, p]) => <tr key={u}><td>{u}</td><td className="mono">{p}</td></tr>)}</tbody></table>
              </div>
            )}
            <Link className="btn primary" to="/login">Go to sign in</Link>
          </div>
        )}
      </div>
    </AuthFrame>
  );
}
