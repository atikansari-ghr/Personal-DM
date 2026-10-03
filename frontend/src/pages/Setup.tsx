import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { AuthFrame } from "./Auth";

interface Member { slot: string; role_label: string; display_name: string; full_name: string; username: string; email: string; password: string; generate_password: boolean }

export default function Setup() {
  const [step, setStep] = useState(1);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [groupName, setGroupName] = useState("My family");
  const [timezone, setTimezone] = useState("Asia/Riyadh");
  const [shareView, setShareView] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [result, setResult] = useState<{ issued_passwords: Record<string, string> } | null>(null);
  const [busy, setBusy] = useState(false);

  const verify = async () => {
    setError("");
    try {
      const r = await api<{ slots: { slot: string; role_label: string }[]; timezone: string }>("setup/verify", { body: { token } });
      setMembers(r.slots.map((s) => ({ ...s, display_name: "", full_name: "", username: s.slot, email: "", password: "", generate_password: s.slot !== "dad" })));
      setTimezone(r.timezone || "Asia/Riyadh");
      setStep(2);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const update = (i: number, patch: Partial<Member>) => setMembers((m) => m.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const included = members.filter((m) => m.slot === "dad" || m.display_name.trim());
      const r = await api("setup/complete", { body: { token, group_name: groupName, timezone, share_family_folder_view: shareView, members: included } });
      setResult(r);
      setStep(4);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      <div className="panel" style={{ maxWidth: 720 }}>
        <p className="muted small">First-run setup · step {step} of 4</p>
        {error && <div className="alert error" role="alert">{error}</div>}
        {step === 1 && (
          <form onSubmit={(e) => { e.preventDefault(); verify(); }}>
            <h1>Set up your family library</h1>
            <p className="muted">Run <code>personaldocs setup-token</code> on the server console and enter the one-time code it prints. Nobody else can claim this installation.</p>
            <div className="field"><label htmlFor="token">One-time setup code</label><input id="token" type="text" value={token} onChange={(e) => setToken(e.target.value.trim())} autoComplete="off" /></div>
            <button className="btn primary" disabled={!token}>Continue</button>
          </form>
        )}
        {step === 2 && (
          <div>
            <h1>Family accounts</h1>
            <p className="muted">Enter each person's real name. Role labels (Dad, Mom…) describe relationships only and can be changed later. Leave a row's name empty to skip that slot for now. Dad becomes the main administrator and family head.</p>
            {members.map((m, i) => (
              <fieldset key={m.slot} className="card" style={{ margin: "0.8rem 0" }}>
                <legend style={{ fontWeight: 700, padding: "0 .3rem" }}>{m.role_label}{m.slot === "dad" ? " — main administrator" : ""}</legend>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.6rem" }}>
                  <div className="field"><label htmlFor={`n-${i}`}>Display name</label><input id={`n-${i}`} type="text" value={m.display_name} onChange={(e) => update(i, { display_name: e.target.value })} /></div>
                  <div className="field"><label htmlFor={`f-${i}`}>Full name (optional)</label><input id={`f-${i}`} type="text" value={m.full_name} onChange={(e) => update(i, { full_name: e.target.value })} /></div>
                  <div className="field"><label htmlFor={`u-${i}`}>Username</label><input id={`u-${i}`} type="text" autoCapitalize="none" value={m.username} onChange={(e) => update(i, { username: e.target.value.toLowerCase() })} /></div>
                  <div className="field"><label htmlFor={`e-${i}`}>Email (optional)</label><input id={`e-${i}`} type="email" value={m.email} onChange={(e) => update(i, { email: e.target.value })} /></div>
                </div>
                {m.slot === "dad" ? (
                  <div className="field"><label htmlFor={`p-${i}`}>Your password</label><input id={`p-${i}`} type="password" autoComplete="new-password" value={m.password} onChange={(e) => update(i, { password: e.target.value })} /><div className="hint">At least 10 characters.</div></div>
                ) : (
                  <div className="row">
                    <label className="check"><input type="checkbox" checked={m.generate_password} onChange={(e) => update(i, { generate_password: e.target.checked, password: "" })} /> Generate a temporary password</label>
                    {!m.generate_password && <input aria-label={`Temporary password for ${m.role_label}`} type="password" autoComplete="new-password" placeholder="Temporary password" value={m.password} onChange={(e) => update(i, { password: e.target.value })} style={{ maxWidth: 260 }} />}
                  </div>
                )}
              </fieldset>
            ))}
            <div className="row"><button className="btn" onClick={() => setStep(1)}>Back</button><button className="btn primary" onClick={() => setStep(3)} disabled={!members[0]?.display_name || !members[0]?.password}>Continue</button></div>
          </div>
        )}
        {step === 3 && (
          <div>
            <h1>Family group & settings</h1>
            <div className="field"><label htmlFor="g">Family group name</label><input id="g" type="text" value={groupName} onChange={(e) => setGroupName(e.target.value)} /></div>
            <div className="field"><label htmlFor="tz">Timezone</label><input id="tz" type="text" value={timezone} onChange={(e) => setTimezone(e.target.value)} /><div className="hint">Used for expiry reminders, e.g. Asia/Riyadh or Asia/Kolkata.</div></div>
            <label className="check field"><input type="checkbox" checked={shareView} onChange={(e) => setShareView(e.target.checked)} /> Let everyone in the family group view the "Shared family" folder</label>
            <p className="muted small">Each person can see only their own folder until you grant more access. You can change all of this later in Settings → Family & access.</p>
            <div className="row"><button className="btn" onClick={() => setStep(2)}>Back</button><button className="btn primary" onClick={submit} disabled={busy}>Create accounts</button></div>
          </div>
        )}
        {step === 4 && result && (
          <div>
            <h1>All set</h1>
            <p>The family accounts were created.</p>
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
