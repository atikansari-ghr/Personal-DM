import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/ui";
import { useSession } from "../session";

const GOOGLE_ERRORS: Record<string, string> = {
  google_disabled: "Google sign-in is not enabled.",
  google_unlinked: "This Google account is not linked to a family account. Sign in with your password, then link Google in Settings → My account.",
  google_denied: "Google sign-in was cancelled.",
  google_state: "The Google sign-in attempt expired or was tampered with. Please try again.",
  google_invalid: "Google's response could not be verified. Please try again or contact your administrator.",
  account_disabled: "This account is disabled. Ask your family administrator.",
  sign_in_first: "Please sign in first.",
};

export function AuthFrame({ children }: { children: ReactNode }) {
  const { session } = useSession();
  return (
    <div className="auth">
      <section className="auth-art" aria-hidden="true">
        <div className="brand" style={{ fontSize: "1.5rem" }}><Icon name="shield" size={34} /> {session?.app_name || "Personal Documents"}</div>
        <h1>Your family documents.<br />Together.</h1>
        <p className="muted" style={{ fontSize: "1.2rem" }}>A private space for the things that matter.</p>
        <div className="folders-art">
          <div><span>🪪</span>Identity</div>
          <div><span>🎓</span>Education</div>
          <div><span>✈️</span>Travel</div>
        </div>
        <p className="muted small" style={{ marginTop: "auto" }}>Hosted on your own server.</p>
      </section>
      <section className="auth-form">{children}</section>
    </div>
  );
}

export function Login() {
  const { session, refresh } = useSession();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [step, setStep] = useState<"password" | "totp">(params.get("step") === "totp" || session?.pending_2fa ? "totp" : "password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [remember, setRemember] = useState(true);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState(GOOGLE_ERRORS[params.get("error") || ""] || "");
  const [busy, setBusy] = useState(false);

  const done = async () => {
    await refresh();
    nav(params.get("next") || "/", { replace: true });
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (step === "password") {
        const r = await api<{ status: string }>("auth/login", { body: { username, password, remember } });
        if (r.status === "totp_required") setStep("totp");
        else await done();
      } else {
        await api("auth/totp", { body: useRecovery ? { recovery_code: code } : { code } });
        await done();
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthFrame>
      <form onSubmit={submit} noValidate>
        <h1 style={{ fontSize: "2.3rem" }}>{step === "password" ? "Welcome back" : "Verification"}</h1>
        <p className="muted" style={{ marginBottom: "1.5rem" }}>
          {step === "password" ? "Sign in to your family document library" : useRecovery ? "Enter one of your recovery codes." : "Enter the 6-digit code from your authenticator app."}
        </p>
        {error && <div className="alert error" role="alert">{error}</div>}
        {step === "password" ? (
          <>
            <div className="field">
              <label htmlFor="username">Username</label>
              <input id="username" type="text" autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <div style={{ position: "relative" }}>
                <input id="password" type={show ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
                <button type="button" className="icon-btn" style={{ position: "absolute", right: 4, top: 3 }} aria-label={show ? "Hide password" : "Show password"} onClick={() => setShow(!show)}>
                  <Icon name="eye" />
                </button>
              </div>
            </div>
            <div className="row between field">
              <label className="check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember me</label>
              <Link to="/forgot-password">Forgot password?</Link>
            </div>
            <button className="btn primary" style={{ width: "100%" }} disabled={busy || !username || !password}>Sign in <Icon name="arrow" /></button>
            {session?.google_enabled && (
              <a className="btn" style={{ width: "100%", marginTop: "0.7rem" }} href="/api/auth/google/start?mode=login">Sign in with Google</a>
            )}
            <p className="muted small" style={{ textAlign: "center", marginTop: "1rem" }}>Two-factor verification follows if enabled.</p>
          </>
        ) : (
          <>
            <div className="field">
              <label htmlFor="code">{useRecovery ? "Recovery code" : "Authentication code"}</label>
              <input id="code" type="text" inputMode={useRecovery ? "text" : "numeric"} autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
            </div>
            <button className="btn primary" style={{ width: "100%" }} disabled={busy || !code}>Verify</button>
            <div className="row between" style={{ marginTop: "0.8rem" }}>
              <button type="button" className="btn ghost small" onClick={() => setUseRecovery(!useRecovery)}>{useRecovery ? "Use authenticator code" : "Use a recovery code"}</button>
              <button type="button" className="btn ghost small" onClick={() => { setStep("password"); setCode(""); }}>Start over</button>
            </div>
          </>
        )}
      </form>
    </AuthFrame>
  );
}

export function ForgotPassword() {
  const [ident, setIdent] = useState("");
  const [msg, setMsg] = useState("");
  return (
    <AuthFrame>
      <form onSubmit={async (e) => { e.preventDefault(); const r = await api<{ message: string }>("auth/password/forgot", { body: { username: ident } }).catch((x) => ({ message: x.message })); setMsg(r.message); }}>
        <h1>Reset password</h1>
        <p className="muted">Enter your username or registered email address.</p>
        {msg && <div className="alert ok" role="status">{msg}</div>}
        <div className="field"><label htmlFor="ident">Username or email</label><input id="ident" type="text" value={ident} onChange={(e) => setIdent(e.target.value)} /></div>
        <button className="btn primary" disabled={!ident}>Send reset link</button>
        <p className="small muted" style={{ marginTop: "1rem" }}>No email on your account? Your family administrator can set a temporary password for you.</p>
        <p><Link to="/login">Back to sign in</Link></p>
      </form>
    </AuthFrame>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  return (
    <AuthFrame>
      <form onSubmit={async (e) => {
        e.preventDefault();
        if (pw !== pw2) return setError("The passwords do not match.");
        try { await api("auth/password/reset", { body: { token: params.get("token"), password: pw } }); setDone(true); } catch (x: any) { setError(x.message); }
      }}>
        <h1>Choose a new password</h1>
        {error && <div className="alert error" role="alert">{error}</div>}
        {done ? <div className="alert ok">Password changed. <Link to="/login">Sign in</Link></div> : (
          <>
            <div className="field"><label htmlFor="pw">New password</label><input id="pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /><div className="hint">At least 10 characters; avoid common passwords.</div></div>
            <div className="field"><label htmlFor="pw2">Repeat password</label><input id="pw2" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></div>
            <button className="btn primary" disabled={!pw}>Save password</button>
          </>
        )}
      </form>
    </AuthFrame>
  );
}

export function ChangePassword({ forced }: { forced?: boolean }) {
  const { refresh } = useSession();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState(false);
  const body = (
    <form onSubmit={async (e) => {
      e.preventDefault();
      setError("");
      if (pw !== pw2) return setError("The new passwords do not match.");
      try { await api("auth/password/change", { body: { current_password: cur, new_password: pw } }); setOk(true); setCur(""); setPw(""); setPw2(""); await refresh(); } catch (x: any) { setError(x.message); }
    }}>
      {forced && <><h1>Set your own password</h1><p className="muted">Your administrator gave you a temporary password. Choose a new one to continue.</p></>}
      {error && <div className="alert error" role="alert">{error}</div>}
      {ok && <div className="alert ok" role="status">Password changed. Other devices were signed out.</div>}
      <div className="field"><label htmlFor="cur">Current password</label><input id="cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></div>
      <div className="field"><label htmlFor="npw">New password</label><input id="npw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /><div className="hint">At least 10 characters; not similar to your username.</div></div>
      <div className="field"><label htmlFor="npw2">Repeat new password</label><input id="npw2" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></div>
      <button className="btn primary" disabled={!cur || !pw}>Change password</button>
    </form>
  );
  return forced ? <AuthFrame>{body}</AuthFrame> : body;
}
