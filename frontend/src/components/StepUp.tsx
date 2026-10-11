import { useState } from "react";
import { api, ApiError } from "../api";
import { useSession } from "../session";
import { getPasskey, passkeyErrorMessage, passkeysSupported } from "../webauthn";
import { Modal } from "./ui";

/** Step-up authentication for high-impact backup actions: the main administrator's password plus the
 * authenticator code or a passkey when the account has one. Valid for 5 minutes, one sensitive action. */
export function StepUp({ action, onDone, onClose }: { action: string; onDone: () => void; onClose: () => void }) {
  const { session } = useSession();
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [need, setNeed] = useState<{ totp: boolean; passkey: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const hasPasskey = (session?.user?.passkey_count || 0) > 0 && passkeysSupported();
  const submit = async (credential?: any) => {
    setErr(""); setBusy(true);
    try {
      await api("backup/stepup", { body: { password: pw, code: code.replace(/[\s-]/g, ""), credential } });
      onDone();
    } catch (x: any) {
      if (x.data?.code === "second_factor_required") setNeed({ totp: !!x.data.totp, passkey: !!x.data.passkey });
      setErr(x instanceof ApiError ? x.message : passkeyErrorMessage(x));
    } finally { setBusy(false); }
  };
  const withPasskey = async () => {
    try {
      const options = await api("backup/stepup/options", { method: "POST" });
      await submit(await getPasskey(options));
    } catch (x: any) { setErr(x instanceof ApiError ? x.message : passkeyErrorMessage(x)); }
  };
  return (
    <Modal title="Confirm it's you" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="callout warning" role="note"><strong>High-impact action:</strong> {action}. Enter your password{need || hasPasskey ? " and confirm with your authenticator code or passkey" : ""}. The confirmation is valid for 5 minutes and one action.</div>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="field"><label htmlFor="su-pw">Password</label><input id="su-pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
        {need?.totp && <div className="field"><label htmlFor="su-code">Authenticator code</label><input id="su-code" name="one-time-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></div>}
        <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          {(need?.passkey || hasPasskey) && <button type="button" className="btn" disabled={!pw || busy} onClick={withPasskey}>Confirm with passkey</button>}
          <button className="btn primary" disabled={!pw || busy}>Confirm</button>
        </div>
      </form>
    </Modal>
  );
}

/** Run an action; when the server asks for step-up, show the dialog and retry once confirmed. */
export function useStepUp(toast: (m: string, k?: any) => void) {
  const [pending, setPending] = useState<{ label: string; run: () => Promise<any> } | null>(null);
  const run = async (label: string, fn: () => Promise<any>) => {
    try { return await fn(); } catch (e: any) {
      if (e?.data?.code === "stepup_required") setPending({ label, run: fn });
      else toast(e.message, "error");
    }
  };
  const dialog = pending ? (
    <StepUp action={pending.label} onClose={() => setPending(null)} onDone={async () => {
      const p = pending; setPending(null);
      try { await p.run(); } catch (e: any) { toast(e.message, "error"); }
    }} />
  ) : null;
  return { run, dialog };
}
