# Passwords, authenticator app and recovery

## Passwords {#passwords}

Passwords need at least 10 characters and cannot be common or similar to your username. Change yours in **My account → Password & security**; other devices are signed out.

## Authenticator app (optional) {#totp}

**My account → Password & security → Authenticator app → Set up**: confirm your password, scan the QR code with an authenticator app, enter the 6-digit code. You receive 10 one-time **recovery codes** — store them safely. The code is also required after Google sign-in.

## Sessions {#sessions}

"Remember me" keeps you signed in for the number of days set by the administrator (default 14). **My account → Password & security → Active sessions** lists every device where you are signed in (browser, system, last activity, address). Sign out any single device, or **Sign out all other devices**. Changing your password signs out your other devices but keeps the one you are using. Repeated failed sign-ins are slowed down; error messages never reveal whether a username exists.

## Forgotten password {#reset}

- With an email address on your profile and SMTP configured: **Forgot password?** sends a single-use link valid for 30 minutes (configurable).
- Otherwise the main administrator sets a temporary password (Settings → Family & access → Reset password), which you must change at sign-in.
- Lost authenticator: use a recovery code, or ask the administrator to reset 2FA.

## Main administrator lockout {#console-recovery}

On the server console (requires root on the LXC):

```
sudo personaldocs recover-admin dad --generate            # temporary password
sudo personaldocs recover-admin dad --generate --reset-totp
```

It works only for main administrator accounts, signs out all their sessions and is recorded in the audit log. There is no web-based backdoor.
