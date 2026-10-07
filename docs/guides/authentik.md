# Sign in with authentik

[authentik](https://goauthentik.io) is an open-source identity provider. Personal DM can use it as an **additional** way to sign in through standard OpenID Connect. Personal DM stays the authority for documents and folders: authentik only proves who someone is.

## Setting it up {#setup}

1. In authentik, create an **OAuth2/OpenID Provider** (confidential client, signing key set) and an **Application** for it.
2. In Personal DM open **Settings → Authentication → External identity providers — authentik** and press **Test connection**. Copy the **Redirect URI** it shows (`https://<your address>/api/auth/authentik/callback`) into the provider's *Redirect URIs*.
3. Enter the provider's **Issuer** (for example `https://auth.example.com/application/o/personal-dm/`), the **Client ID** and **Client secret** (stored encrypted, never shown again), keep the scopes `openid profile email`, turn on **Sign in with authentik** and save.
4. Press **Test connection** again: the discovery document, issuer, signing keys and PKCE support are checked.

The sign-in uses the authorization-code flow with **PKCE, state and nonce**; tokens are verified against the provider's published keys, issuer and client ID. Only HTTPS provider addresses are accepted.

## Sign-in button {#button}

The button label (default **Sign in with authentik**) and the authentik logo can be changed. **Local sign-in always stays available** — password, authenticator app and passkeys keep working exactly as configured, so nobody is locked out when authentik is down. Two-step verification enabled on an account is still asked after authentik.

## Linking accounts {#linking}

Accounts are **never** linked because an email address matches. A person links their own account:

1. Sign in to Personal DM as usual.
2. Open **My account → Password & security → authentik → Link authentik account** (your password is confirmed first).
3. Sign in at authentik.

The main administrator sees all links in the authentik card and can **Revoke** one; the local account, its password and its documents stay unchanged.

## Provisioning {#provisioning}

**Account provisioning** defaults to **Existing Personal DM accounts only**: an unlinked authentik user is refused. With **Create accounts automatically**, an unknown authentik user gets a new **member** account with a personal folder (no local password) on first sign-in. Automatic provisioning never creates or assigns the main administrator.

## Claims {#claims}

The username, display name, email and groups are read from the claims `preferred_username`, `name`, `email` and `groups` (changeable). They are used for new accounts and shown on the link; they are never used to match existing accounts.

## Groups and roles {#groups}

**Map authentik groups to roles** is off by default. When on, each listed authentik group maps to **Member** or **Administrator** (the security and operations role). Rules:

- The main administrator is never assigned, promoted or demoted by a group.
- Groups never grant access to any document or folder — Personal DM's ownership, sharing and permissions stay authoritative.
- If none of a person's groups is mapped, their role is left as the administrator set it.
- Every role change from a mapping is recorded in the audit log.
