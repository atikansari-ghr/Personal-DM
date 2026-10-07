# Passwords, authenticator app and recovery

## Passwords {#passwords}

Passwords need at least 10 characters and cannot be common or similar to your username. Change yours in **My account → Password & security**; other devices are signed out and you receive the notice **Password reset completed**. You can sign in with your email address instead of your username when that address belongs to exactly one active account.

## Authenticator app (optional) {#totp}

**My account → Password & security → Authenticator app → Set up**: confirm your password, scan the QR code with an authenticator app, enter the 6-digit code. You receive 10 one-time **recovery codes** — store them safely. The code is also required after Google sign-in. Instead of (or as well as) an authenticator app you can use a [passkey](passkeys.md).

### Password managers and autofill {#password-managers}

The codes are standard TOTP (RFC 6238, SHA-1, 6 digits, 30 seconds), so any authenticator app or password manager with
one-time-code support works: Google/Microsoft Authenticator, Aegis, Bitwarden, 1Password, Apple Passwords / iCloud Keychain and
others. Scan the QR code or paste the setup key shown under it.

The code field is a normal text field marked `autocomplete="one-time-code"` with a numeric keyboard, so browsers and password
managers can offer to fill it. Pasting is allowed (spaces and dashes are removed), and typing the code by hand always works too.
The secret is stored encrypted and is never shown again after setup; to move to another app, turn the authenticator off and set it up again.
Compatibility with specific third-party password managers is tested manually (see the test report), not by automated tests.

## Sessions {#sessions}

"Remember me" keeps you signed in for the number of days set by the administrator (default 14). **My account → Password & security → Active sessions** lists every device where you are signed in (browser, system, last activity, address). Sign out any single device, or **Sign out all other devices**. Changing your password signs out your other devices but keeps the one you are using. Repeated failed sign-ins are slowed down; error messages never reveal whether a username exists.

## Forgotten password {#reset}

- With an email address on your profile and SMTP configured: **Forgot password?** sends a branded email with a single-use link valid for 30 minutes (configurable). A newer request or any password change makes older links stop working.
- Otherwise an administrator uses **Reset password…** (Settings → Family & access, or Settings → Users for the Administrator role): either a **temporary password** shown to them once, which you must change at sign-in (all your sessions end), or a **password reset email**. A main administrator's password can only be reset by another main administrator or from the console.
- Lost authenticator or passkeys: use a recovery code (or another passkey), or ask the administrator to reset two-step verification ([details](passkeys.md#recovery)).

Full details for members and administrators: [password reset](password-reset.md).

## Main administrator lockout {#console-recovery}

On the server console (requires root on the LXC):

```
sudo personaldocs recover-admin <username> --generate            # temporary password
sudo personaldocs recover-admin <username> --generate --reset-totp
sudo personaldocs recover-admin <username> --generate --reset-2fa   # also removes all passkeys (lost devices)
```

It works only for main administrator accounts, signs out all their sessions and is recorded in the audit log. There is no web-based backdoor.
