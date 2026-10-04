<!-- audience: admin -->
# Google sign-in

Google sign-in is an optional extra way for **existing** accounts to sign in. It never creates accounts, never links by email address, and does not give the app access to Gmail or Drive. Documents stay on your server; Google sees only the sign-in.

## Requirements {#requirements}

- A public **HTTPS** address for the app (through Nginx Proxy Manager or Pangolin), set as `PD_PUBLIC_ORIGIN`.
- A Google account to own the Google Cloud project.

## Create credentials {#credentials}

1. Open Google Cloud Console → create (or choose) a project.
2. **Google Auth Platform / OAuth consent screen**: choose *External* (or *Internal* for Workspace), enter the app name and support email. Scopes: `openid`, `email`, `profile` only. While in *Testing*, add each family member's Google address as a test user; publishing may require verification depending on Google's current policy — check before relying on it.
3. **Clients → Create client → Web application**.
   - *Authorised JavaScript origins*: your public origin, e.g. `https://docs.example.com`.
   - *Authorised redirect URIs*: copy the exact URL shown in **Settings → Authentication → Google** (e.g. `https://docs.example.com/api/auth/google/callback`).
4. Copy the client ID and secret into Settings → Authentication → Google. The secret is stored encrypted and never shown again.

## Enable and test {#enable}

Turn on **Google sign-in enabled** and save. The diagnostics list checks HTTPS, credentials and reachability; they cannot confirm the redirect URI is registered, so complete a real test link and sign-in.

Disabling Google blocks new Google sign-ins immediately. Existing sessions continue until they expire or the person signs out (use *Sign out other devices* or disable the account to end them).

## Linking (each person) {#linking}

Settings → My account → Linked accounts → **Connect Google account** → confirm your password → choose your Google account. One Google account can be linked to only one family account. **Disconnect** also requires confirmation; your password keeps working.

## Security {#security}

The server uses the authorization-code flow with PKCE, validates state, nonce, issuer, audience, signature and expiry, and binds to Google's stable account ID. If the local account has an authenticator app, its code is still required. Disabled accounts cannot sign in by any method.

## Troubleshooting {#troubleshooting}

| Symptom | Cause / fix |
|---|---|
| `redirect_uri_mismatch` from Google | Register exactly the redirect URI shown in Settings; check `PD_PUBLIC_ORIGIN` |
| "not linked to a family account" | Sign in with password and link Google first |
| "already linked to another family account" | That Google account is linked elsewhere; disconnect it there |
| `access_denied` | Consent cancelled, or the user is not a test user while the app is in Testing |
| "could not be verified" | Wrong client ID/secret, or server clock wrong — check NTP |
| Outer auth gate blocks callback | Allow `/api/auth/google/callback` through the proxy's authentication (see [Reverse proxy](reverse-proxy.md)) |
