# Passkeys and two-step verification

## What a passkey is {#about}

A passkey is a sign-in key stored on your phone, computer, password manager or security key. It is unlocked with your fingerprint,
face or device PIN. The private key never leaves the device. Personal Documents Management System only stores the public key, a counter, the name you gave
it and when it was used. Passkeys are standard (WebAuthn) and work with:
- iPhone/iPad and macOS (iCloud Keychain / Apple Passwords)
- Android (Google Password Manager)
- Windows Hello
- password managers such as Bitwarden or 1Password
- FIDO2 security keys

There are two ways to use a passkey:
- **Second step:** sign in with your password, then confirm with your passkey (instead of a 6-digit code).
- **Passwordless:** sign in with the passkey alone, if the administrator allows it and you turned it on for your account.

## Turning passkeys on (administrator) {#enable}

**Settings → Authentication → Allow passkeys** (on by default). Passkeys only work on the app's **HTTPS address**
(`PD_PUBLIC_ORIGIN`), not on `http://<lan-ip>:8000`. See [relying party and domain](#rp-id).

## Adding, renaming and removing passkeys {#manage}

**My account → Password & security → Passkeys**:

1. Type a name (for example "My iPhone") and click **Add a passkey**. You confirm it's you (password or an existing passkey),
   then your device asks for your fingerprint, face or PIN.
2. The first time you add a second step (passkey or authenticator app) you get **recovery codes**. Store them safely.
3. **Rename** at any time. **Remove** needs a fresh confirmation; a removed passkey stops working immediately.

### Several passkeys {#multiple}

Add one per device you use (phone, laptop, security key). Synced passkeys (iCloud, Google, password managers) are marked
"synced". Keeping at least two is the easiest protection against losing a device.

## Password + passkey {#second-factor}

After your password, the sign-in page shows **Use a passkey**. If you also have an authenticator app, you can use either. The login audit
records the method as `password+passkey`.

## Passwordless sign-in {#passwordless}

The administrator turns on **Allow passwordless passkey sign-in** (Authentication). Then each person who wants it ticks
**Allow signing in with a passkey alone** under Passkeys (this needs a passkey that supports it, which most phones and computers
do). The sign-in page then shows **Sign in with a passkey**. Your device must verify you (fingerprint, face or PIN), and your
password keeps working. Turning the setting off stops passwordless sign-in immediately.

## Authentication policy (administrator) {#policy}

**Settings → Authentication**:

| Setting | Effect |
|---|---|
| Allow authenticator apps (TOTP) | Off = no *new* set-ups; existing users keep theirs so nobody is locked out. |
| Allow passkeys | Off = no *new* passkeys; existing passkeys keep working until removed. |
| Allow passwordless passkey sign-in | Off by default; people must also opt in. |
| Require two-step verification | None / administrators / everyone. People without one sign in with their password and are then guided to set up a passkey or authenticator app. They are not locked out. The last second step cannot be removed while required. |
| Re-confirmation window | Minutes after confirming it's you during which sensitive changes are allowed (default 10). |

Existing accounts keep their current sign-in requirements after an upgrade until you change these settings.

## Re-confirming for sensitive changes {#recent-auth}

These changes need a confirmation within the re-confirmation window, using your password (plus code) or a passkey:
- adding or removing passkeys
- setting up or turning off the authenticator app
- new recovery codes
- passwordless on/off

Changing your password requires the current password. All of these changes are recorded in the audit log and can trigger an
[account security alert](security-access.md#alerts).

## Relying party, domain and reverse proxy {#rp-id}

- **Relying party ID** = the host name of `PD_PUBLIC_ORIGIN` (for example `docs.example.com`).
- **Expected origin** = `PD_PUBLIC_ORIGIN` exactly, for example `https://docs.example.com`.
- NPM or Pangolin must serve that address over HTTPS and pass the original Host header (both do by default). Set
  `PD_BEHIND_PROXY=1`. `sudo personaldocs doctor` checks HTTPS, the relying party ID and proxy mode.
- Development/testing: `http://localhost:8000` is accepted when `PD_DEBUG=1`.
- **Changing the domain later makes existing passkeys unusable** (they are bound to the old domain). People then sign in with
  password + authenticator code or a recovery code and register new passkeys; the administrator can also reset them (below).

## Lost passkey and recovery {#recovery}

- Lost one device: sign in with another passkey, your authenticator app or a **recovery code**, then remove the lost passkey.
- Lost everything: the main administrator uses **Family & access → Reset 2FA** for that person. This removes the authenticator app, all
  passkeys and recovery codes and signs them out everywhere. The action is audited and the person is notified. Their documents
  are untouched.
- Main administrator locked out (server shell required):

```
sudo personaldocs recover-admin <username> --generate --reset-2fa
```

No secret is ever shown: neither TOTP seeds nor passkey material can be read back. There is no web-based bypass of two-step
verification.

## Security events {#events}

The login audit distinguishes:
- `password`, `password+totp`, `password+passkey`, `passkey` (passwordless) and `google`
- recovery-code sign-ins

The audit log records:
- passkey registered, renamed and revoked
- authenticator app on/off
- recovery codes regenerated
- passwordless on/off
- administrator and console resets
- authentication-policy changes

Records contain safe metadata only: never passwords, codes, seeds, recovery codes, challenges, passkey material, cookies or tokens.
