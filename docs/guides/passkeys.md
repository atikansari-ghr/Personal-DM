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

There are two ways to use a passkey. The administrator chooses one for the whole installation with **Passkey sign-in
mode** (see [policy](#policy)):
- **Passwordless** (the default): the sign-in page offers **Sign in with Passkey** before any password. The passkey alone
  signs you in after your device checks your fingerprint, face or PIN. Your password keeps working.
- **Password + Passkey:** sign in with your password, then confirm with your passkey (instead of a 6-digit code).

## The sign-in screen {#sign-in-screen}

![Sign-in page with Sign in with Passkey (synthetic data)](../images/screenshots/login-passkey.png)

The sign-in page shows, from top to bottom:

1. **Email or username** and **Password**, with the normal **Sign in** button.
2. An "or" line, then **Sign in with Passkey**.
3. **Sign in with authentik** and **Sign in with Google**, only when the administrator has turned them on.

**Sign in with Passkey** does not need your username: the browser lists the passkeys it has for this site and you
pick yours. Where the browser supports it, your saved passkeys are also offered in the autofill list of the username
field (the field is marked `autocomplete="username webauthn"`), so one tap signs you in.

On a plain `http://` address the button is greyed out with the note *Passkeys need the secure HTTPS address of this
app*. Open the app through its `https://` address instead.

You can type your **email address instead of your username** in the first field, as long as that address belongs to
exactly one active account.

## Turning passkeys on (administrator) {#enable}

**Settings → Authentication → Allow passkeys** (on by default). Passkeys only work on the app's **HTTPS address**
(`PD_PUBLIC_ORIGIN`), not on `http://<lan-ip>:8000`. See [relying party and domain](#rp-id).

## Adding, renaming and removing passkeys {#manage}

**My account → Password & security → Passkeys**:

1. Type a name (for example "Office Laptop", "Personal iPhone", "Home PC" or "Security Key") and click **Add a passkey**.
   If you have not confirmed it's you in the last few minutes, the **Confirm it's you** dialog asks for your password
   (or an existing passkey). Then your device asks for your fingerprint, face or PIN.
2. The first time you add a second step (passkey or authenticator app) you get **recovery codes**. Store them safely.
3. **Rename** and **Remove** also need a recent confirmation; a removed passkey stops working immediately.

Adding, renaming and removing a passkey are recorded in the audit log (`account.passkey_register`,
`account.passkey_rename`, `account.passkey_revoke`), and you get a security notification for added and removed
passkeys.

In passwordless mode, adding a passkey that can sign you in on its own (a *discoverable* passkey, which most phones,
computers and password managers create) **turns on passwordless sign-in for your account automatically**. The message
"Passkey added — you can now use Sign in with Passkey on the sign-in page" confirms it.

### Several passkeys {#multiple}

Add one per device you use (phone, laptop, security key). Synced passkeys (iCloud, Google, password managers) are marked
"synced". Keeping at least two is the easiest protection against losing a device.

## Password + passkey {#second-factor}

In **Password + Passkey** mode (and for people who turned passwordless off), the sign-in page shows **Use a passkey**
after your password. If you also have an authenticator app, you can use either. The login audit
records the method as `password+passkey`.

## Passwordless sign-in {#passwordless}

Passwordless is the default **Passkey sign-in mode**. Click **Sign in with Passkey** (or pick your passkey from the
username autofill list) and confirm with your fingerprint, face or PIN. That is all.

How it is protected:
- It uses a *discoverable* passkey and always **requires user verification** (fingerprint, face or PIN); a passkey
  that only proves "someone touched the key" is refused.
- Each sign-in uses a new single-use challenge; a replayed answer is refused.
- The browser's origin and the relying party ID must match the app's HTTPS address (see [below](#rp-id)).
- Your password keeps working, and so do recovery codes.

**Opting out:** under **My account → Password & security → Passkeys**, untick **Use Sign in with Passkey without a
password**. Your passkeys are then only used as the second step after your password. Turning it on again needs a
recent confirmation. Both are audited and notified.

If the administrator switches the mode to **Password + Passkey**, passwordless sign-in stops immediately for everyone.

### After upgrading {#upgrade}

The upgrade to Change Set P replaces the older on/off setting *Allow passwordless passkey sign-in*
(`auth.allow_passwordless`, off by default) with **Passkey sign-in mode** (`auth.passkey_mode`). The migration
(`accounts.0007_passkey_mode`) keeps an explicit earlier choice:

| Before the upgrade | After the upgrade |
|---|---|
| Passwordless was explicitly turned **off** (saved) | **Password + Passkey** |
| Passwordless was explicitly turned **on** (saved) | **Passwordless** |
| Never changed (default) | **Passwordless** |

In passwordless mode the migration also turns passwordless sign-in on for every account that already has a
discoverable passkey, so those people see **Sign in with Passkey** work straight away. Everyone else keeps signing in
as before. Before this change passkeys were only offered after the password because passwordless was off by default
and also needed a per-person opt-in.

## Authentication policy (administrator) {#policy}

**Settings → Authentication**:

| Setting | Effect |
|---|---|
| Allow authenticator apps (TOTP) | Off = no *new* set-ups; existing users keep theirs so nobody is locked out. |
| Allow passkeys | Off = no *new* passkeys; existing passkeys keep working until removed. |
| Passkey sign-in mode | **Passwordless** (default): Sign in with Passkey on the first screen, passkey alone signs in. **Password + Passkey**: passkeys only after the password. Replaces *Allow passwordless passkey sign-in*. |
| Require two-step verification | None / administrators / everyone. People without one sign in with their password and are then guided to set up a passkey or authenticator app. They are not locked out. The last second step cannot be removed while required. |
| Re-confirmation window | Minutes after confirming it's you during which sensitive changes are allowed (default 10). |

Existing accounts keep their current sign-in requirements after an upgrade until you change these settings (see
[after upgrading](#upgrade) for the passkey mode).

**Main administrator recovery works in both modes:** the main administrator's password, recovery codes and the console
command `sudo personaldocs recover-admin USERNAME` keep working whichever mode is chosen.

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

## Troubleshooting {#troubleshooting}

| Problem | What to do |
|---|---|
| **Sign in with Passkey** is greyed out ("Passkeys need the secure HTTPS address of this app") | You opened `http://<ip>:8000` or another plain-http address. Open the `https://` address in `PD_PUBLIC_ORIGIN` |
| The browser says no passkey is available | The passkey was created for another address (relying party ID), or it is not discoverable. Sign in with your password, add a new passkey on this address |
| "The passkey could not be verified" | The address in the browser differs from `PD_PUBLIC_ORIGIN` (origin check), or the proxy changes the Host header. Run `sudo personaldocs doctor` |
| Passkey works only after the password | The mode is **Password + Passkey**, or you turned off *Use Sign in with Passkey without a password*, or your passkey is not discoverable (add a new one) |
| Passkeys not offered in the username autofill list | Not every browser supports passkey autofill; use the **Sign in with Passkey** button |

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
