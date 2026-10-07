import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, safeNext } from "../api";
import { Icon } from "../components/ui";
import { useSession } from "../session";
import { getPasskey, passkeyErrorMessage, passkeysSupported } from "../webauthn";
import PasskeysCard from "../components/Passkeys";
import LoginArt from "../components/LoginArt";
import { Reauth } from "../components/Reauth";

const GOOGLE_ERRORS: Record<string, string> = {
  google_disabled: "Google sign-in is not enabled.",
  google_unlinked: "This Google account is not linked to a family account. Sign in with your password, then link Google in Settings → My account.",
  google_denied: "Google sign-in was cancelled.",
  google_state: "The Google sign-in attempt expired or was tampered with. Please try again.",
  google_invalid: "Google's response could not be verified. Please try again or contact your administrator.",
  authentik_disabled: "Sign-in with authentik is not enabled.",
  authentik_unavailable: "authentik cannot be reached right now. Sign in with your password instead.",
  authentik_unlinked: "This authentik account is not linked to a family account. Sign in with your password, then link authentik in Settings → My account → Password & security.",
  authentik_denied: "Sign-in with authentik was cancelled.",
  authentik_state: "The authentik sign-in attempt expired or was tampered with. Please try again.",
  authentik_invalid: "authentik's response could not be verified. Please try again or contact your administrator.",
  account_disabled: "This account is disabled. Ask your family administrator.",
  sign_in_first: "Please sign in first.",
};

export interface LoginBranding { design: string; title: string; tagline: string; overlay: number; position: string; wallpaper: string | null; logo: string | null; has_wallpaper?: boolean }

/** Sign-in layout: light wallpaper on the left, the sign-in panel on the right. On phones the wallpaper becomes a
 *  short banner so the form comes first. Sign-in behaves identically with every design. */
export function AuthWallpaper({ b, preview }: { b: LoginBranding; preview?: boolean }) {
  return (
    <section className={`auth-art design-${b.design}${preview ? " preview" : ""}`} aria-hidden={preview ? undefined : true} aria-label={preview ? "Sign-in page preview" : undefined}>
      {b.wallpaper ? <div className="auth-wallpaper" style={{ backgroundImage: `url(${b.wallpaper})`, backgroundPosition: b.position || "center" }} /> : <LoginArt design={b.design} />}
      {b.overlay > 0 && <div className="auth-overlay" style={{ opacity: b.overlay / 100 }} />}
      <div className="auth-brand">
        <div className="brand">{b.logo ? <img src={b.logo} alt="" className="auth-logo" /> : <Icon name="shield" size={34} />}</div>
        <h1>{b.title}</h1>
        {b.tagline && <p className="auth-tagline">{b.tagline}</p>}
      </div>
      <p className="small auth-foot">Hosted on your own server.</p>
    </section>
  );
}

export const DEFAULT_BRANDING: LoginBranding = { design: "minimal", title: "Personal Documents Management System", tagline: "Your family documents, safely in one place.", overlay: 0, position: "center", wallpaper: null, logo: null };

export function AuthFrame({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const b: LoginBranding = session?.login || { ...DEFAULT_BRANDING, title: session?.app_name || DEFAULT_BRANDING.title };
  return (
    <div className="auth">
      <AuthWallpaper b={b} />
      <section className="auth-form">{children}</section>
    </div>
  );
}

/** Simple authentik-style mark (local SVG, no external image). */
export function AuthentikLogo() {
  return (
    <svg className="authentik-logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#fd4b2d" />
      <path d="M7 16.5 11.2 6.5h1.6L17 16.5h-2.2l-.9-2.3H10l-.9 2.3H7zm3.7-4.1h2.6L12 9.1l-1.3 3.3z" fill="#fff" />
    </svg>
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
  const [methods, setMethods] = useState<string[]>(session?.pending_methods || ["totp", "recovery"]);
  const canPasskey = passkeysSupported();

  const passkey = async (purpose: "2fa" | "passwordless") => {
    setBusy(true);
    setError("");
    try {
      const options = await api("auth/passkey/options", { body: { purpose } });
      const credential = await getPasskey(options);
      await api("auth/passkey/verify", { body: { purpose, credential } });
      await done();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : passkeyErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const done = async () => {
    await refresh();
    nav(safeNext(params.get("next")), { replace: true });
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (step === "password") {
        const r = await api<{ status: string; methods?: string[] }>("auth/login", { body: { username, password, remember } });
        if (r.status === "totp_required" || r.status === "second_factor_required") {
          const m = r.methods || ["totp"];
          setMethods(m);
          setUseRecovery(!m.includes("totp") && !m.includes("passkey") && m.includes("recovery"));
          setStep("totp");
        } else await done();
      } else {
        // Codes may be pasted with spaces or dashes (password managers, authenticator apps).
        await api("auth/totp", { body: useRecovery ? { recovery_code: code.trim() } : { code: code.replace(/[\s-]/g, "") } });
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
          {step === "password" ? "Sign in to your family document library" : useRecovery ? "Enter one of your recovery codes." : methods.includes("totp") ? "Enter the 6-digit code from your authenticator app or password manager." : "Confirm with your passkey."}
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
            {session?.authentik?.enabled && (
              <a className="btn authentik-btn" style={{ width: "100%", marginTop: "0.7rem" }} href="/api/auth/authentik/start?mode=login">
                {session.authentik.show_logo && <AuthentikLogo />}{session.authentik.label}
              </a>
            )}
            {session?.google_enabled && (
              <a className="btn" style={{ width: "100%", marginTop: "0.7rem" }} href="/api/auth/google/start?mode=login">Sign in with Google</a>
            )}
            {session?.passwordless_enabled && canPasskey && (
              <button type="button" className="btn" style={{ width: "100%", marginTop: "0.7rem" }} disabled={busy} onClick={() => passkey("passwordless")}><Icon name="lock" /> Sign in with a passkey</button>
            )}
            <p className="muted small" style={{ textAlign: "center", marginTop: "1rem" }}>Two-factor verification follows if enabled.</p>
          </>
        ) : (
          <>
            {methods.includes("passkey") && !useRecovery && (
              <button type="button" className="btn primary" style={{ width: "100%", marginBottom: "0.8rem" }} disabled={busy || !canPasskey} onClick={() => passkey("2fa")}><Icon name="lock" /> Use a passkey</button>
            )}
            {methods.includes("passkey") && !canPasskey && <p className="small muted">Passkeys need the secure HTTPS address of this app.</p>}
            {(methods.includes("totp") || useRecovery) && (
              <>
                <div className="field">
                  <label htmlFor="code">{useRecovery ? "Recovery code" : "Authentication code"}</label>
                  <input id="code" name={useRecovery ? "recovery-code" : "one-time-code"} type="text" inputMode={useRecovery ? "text" : "numeric"}
                    autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} autoFocus={!methods.includes("passkey")} />
                </div>
                <button className="btn primary" style={{ width: "100%" }} disabled={busy || !code}>Verify</button>
              </>
            )}
            <div className="row between" style={{ marginTop: "0.8rem" }}>
              {(methods.includes("recovery") || methods.includes("totp")) && <button type="button" className="btn ghost small" onClick={() => { setUseRecovery(!useRecovery); setCode(""); }}>{useRecovery ? (methods.includes("totp") ? "Use authenticator code" : "Use a passkey") : "Use a recovery code"}</button>}
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


/** Shown when the administrator requires two-step verification and this account has none yet. */
export function ForcedTwoFactor() {
  const { session, refresh } = useSession();
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [err, setErr] = useState("");
  const [reauth, setReauth] = useState<(() => void) | null>(null);
  const startTotp = async () => {
    setErr("");
    try { setSetup(await api("me/totp/setup", { method: "POST" })); }
    catch (e: any) { if (e.data?.code === "reauth_required") setReauth(() => async () => { setReauth(null); startTotp(); }); else setErr(e.message); }
  };
  return (
    <AuthFrame>
      <div className="stack">
        <h1>Set up two-step verification</h1>
        <p className="muted">Your family administrator requires a second step at sign-in. Choose a passkey (fingerprint, face or PIN on your device) or an authenticator app. Your password stays the same.</p>
        {err && <div className="alert error" role="alert">{err}</div>}
        {codes ? (
          <div className="alert warn"><strong>Recovery codes — shown once.</strong> Store them safely; each works one time.<pre className="mono">{codes.join("\n")}</pre>
            <button className="btn primary" onClick={() => refresh()}>Continue</button></div>
        ) : (
          <>
            <PasskeysCard />
            {session?.totp_allowed !== false && (
              <div className="card">
                <h2>Authenticator app</h2>
                {!setup ? <button className="btn" onClick={startTotp}>Set up an authenticator app</button> : (
                  <form className="stack" onSubmit={async (e) => { e.preventDefault(); try { const r = await api("me/totp/enable", { body: { code: code.replace(/[\s-]/g, "") } }); setCodes(r.recovery_codes); } catch (x: any) { setErr(x.message); } }}>
                    <div style={{ width: 200, background: "#fff" }} dangerouslySetInnerHTML={{ __html: setup.qr_svg.replace(/<\?xml[^>]*>/, "") }} />
                    <code>{setup.secret}</code>
                    <label htmlFor="ft-code">Code from the app</label>
                    <input id="ft-code" name="one-time-code" type="text" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} style={{ maxWidth: 180 }} />
                    <button className="btn primary" disabled={!code}>Verify & enable</button>
                  </form>
                )}
              </div>
            )}
            <button className="btn primary" onClick={() => refresh()}>I have set it up — continue</button>
          </>
        )}
        <button className="btn ghost" onClick={() => api("auth/logout", { method: "POST" }).then(() => refresh())}>Sign out</button>
      </div>
      {reauth && <Reauth onClose={() => setReauth(null)} onDone={reauth} />}
    </AuthFrame>
  );
}
