<!-- audience: admin -->
# Private GitHub access

The repository is private. The server needs **read-only** access to install and update.

## Option A: fine-grained personal access token (recommended) {#token}

GitHub → Settings → Developer settings → Fine-grained tokens → *Generate new token*:

- Resource owner: you; Repository access: **only this repository**.
- Permissions: *Contents: Read-only* (and *Metadata: Read-only*, added automatically).
- Set an expiry and renew it before it lapses.

Store it on the server only in `/etc/personaldocs/github-token` (mode 600, root). The `personaldocs` tool passes it to git through a credential helper, never in URLs, command-line arguments or logs.

## Option B: deploy key {#deploy-key}

```
ssh-keygen -t ed25519 -f /etc/personaldocs/deploy_key -N ""
```

Add `/etc/personaldocs/deploy_key.pub` as a **read-only deploy key** in the repository settings, and install with the SSH URL `git@github.com:OWNER/REPO.git`. Set `PD_GIT_SSH_KEY=/etc/personaldocs/deploy_key` in `/etc/personaldocs/personaldocs.env`.

## Updating the credential {#rotate}

Replace the file contents (or key) and run `personaldocs upgrade`. Revoke the old token on GitHub.

Do not publish the repository, and never commit tokens, documents, backups or databases.
