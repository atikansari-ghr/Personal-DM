import { useState } from "react";
import { api, ApiError } from "../api";
import { useSession } from "../session";
import { getPasskey, passkeyErrorMessage, passkeysSupported } from "../webauthn";
import { Modal } from "./ui";

/** Re-confirm identity before sensitive changes (password + code, or a passkey). */
export function Reauth({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const { session } = useSession();
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [need, setNeed] = useState(false);
  const [err, setErr] = useState("");
  const hasPasskey = (session?.user?.passkey_count || 0) > 0 && passkeysSupported();
  const withPasskey = async () => {
    setErr("");
    try {
      const options = await api("auth/reauth/passkey", { body: { step: "options" } });
      const credential = await getPasskey(options);
      await api("auth/reauth/passkey", { body: { credential } });
      onDone();
    } catch (x: any) { setErr(x instanceof ApiError ? x.message : passkeyErrorMessage(x)); }
  };
  return (
    <Modal title="Confirm it's you" onClose={onClose}>
      <form className="stack" onSubmit={async (e) => {
        e.preventDefault();
        try { await api("auth/reauth", { body: { password: pw, code: code.replace(/[\s-]/g, "") } }); onDone(); } catch (x: any) { if (x.data?.code === "totp_required") setNeed(true); setErr(x.message); }
      }}>
        {err && <div className="alert error" role="alert">{err}</div>}
        <p className="small muted">Security changes need a fresh confirmation.</p>
        {hasPasskey && <button type="button" className="btn primary" onClick={withPasskey}>Confirm with a passkey</button>}
        <div className="field"><label htmlFor="rp">Password</label><input id="rp" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
        {need && <div className="field"><label htmlFor="rc">Authenticator code</label><input id="rc" name="one-time-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></div>}
        <button className={`btn ${hasPasskey ? "" : "primary"}`} disabled={!pw}>Confirm with password</button>
      </form>
    </Modal>
  );
}

export function withReauth(action: () => Promise<any>, setReauth: (f: (() => void) | null) => void, toast: (m: string, k?: any) => void) {
  return async () => {
    try { await action(); } catch (e: any) {
      if (e.data?.code === "reauth_required") setReauth(() => async () => { setReauth(null); try { await action(); } catch (x: any) { toast(x.message, "error"); } });
      else toast(e.message, "error");
    }
  };
}
