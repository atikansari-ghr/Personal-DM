// Browser side of passkeys (WebAuthn). Converts the server's JSON options to the binary form the browser API
// expects and the resulting credential back to JSON. Works with platform authenticators (phone, Windows Hello,
// macOS/iOS), password managers and security keys; nothing vendor-specific.

const toBuf = (s: string): ArrayBuffer => {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
};
const toB64u = (buf: ArrayBuffer | null): string | null => {
  if (!buf) return null;
  let s = "";
  new Uint8Array(buf).forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && window.isSecureContext;
}

export async function createPasskey(options: any): Promise<any> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: toBuf(options.challenge),
    user: { ...options.user, id: toBuf(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c: any) => ({ ...c, id: toBuf(c.id) })),
    extensions: { ...(options.extensions || {}), credProps: true } as any,
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
    response: { clientDataJSON: toB64u(r.clientDataJSON), attestationObject: toB64u(r.attestationObject), transports: r.getTransports?.() || [] },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}

/** Browser offers passkeys in the username field's autofill list (WebAuthn conditional mediation). */
export async function conditionalMediationAvailable(): Promise<boolean> {
  try {
    const PKC: any = window.PublicKeyCredential;
    return !!PKC?.isConditionalMediationAvailable && (await PKC.isConditionalMediationAvailable());
  } catch {
    return false;
  }
}

export async function getPasskey(options: any, extra: { mediation?: "conditional"; signal?: AbortSignal } = {}): Promise<any> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: toBuf(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c: any) => ({ ...c, id: toBuf(c.id) })),
  };
  const cred = (await navigator.credentials.get({ publicKey, ...(extra as any) })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
    response: { clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData), signature: toB64u(r.signature), userHandle: toB64u(r.userHandle) },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}

export function passkeyErrorMessage(e: any): string {
  if (e?.name === "NotAllowedError") return "The passkey request was cancelled or timed out.";
  if (e?.name === "InvalidStateError") return "This passkey is already registered.";
  if (e?.name === "SecurityError") return "Passkeys need the secure HTTPS address of this app.";
  return e?.message || "The passkey could not be used.";
}
