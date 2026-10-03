<!-- audience: admin -->
# Installation on a Proxmox LXC (Debian 13)

## Target {#target}

- Proxmox LXC running **Debian 13 (trixie)**, unprivileged is fine. Recommended: 2 vCPU, 4 GB RAM, 50 GB disk.
- No Docker. Native services under systemd.
- HTTPS is provided by your existing **Nginx Proxy Manager** or **Pangolin** (see [Reverse proxy](reverse-proxy.md)).
- A NAS share mounted in the container for backups (see [Backup and restore](backup-restore.md)).

## What the installer does {#what}

`personaldocs install` is idempotent and resumable (rerun it after any failure; it continues safely and never wipes data or keys):

1. Checks OS, architecture, RAM, disk, systemd, DNS/network and port availability.
2. Installs packages: Python 3, PostgreSQL, Tesseract (English), OCRmyPDF, Ghostscript, qpdf, poppler-utils, LibreOffice (headless Writer/Calc/Impress), Node.js (only if the frontend must be built), git.
3. Creates the `personaldocs` system user, the PostgreSQL role/database (local socket only), and directories:

| Path | Contents |
|---|---|
| `/opt/personaldocs/releases/<version>` | Application code + Python virtualenv per release |
| `/opt/personaldocs/current` | Symlink to the active release |
| `/etc/personaldocs/` | `personaldocs.env`, `secret_key`, `encryption.key`, optional `github-token` (all private) |
| `/var/lib/personaldocs/` | Originals, previews, staging, temporary files, status files |
| `/var/log/personaldocs/install.log` | Redacted installer log |

4. Builds/installs the release, runs database migrations and collects static files.
5. Installs systemd units `personaldocs-web` (gunicorn), `personaldocs-worker` and `personaldocs-scheduler`, then starts them and runs a health check.
6. Prints a one-time setup code.

## Install {#install}

The repository is private, so the installer needs a read-only credential (see [Private GitHub access](private-github.md)). On the LXC as root:

```
apt-get update && apt-get install -y git ca-certificates curl
install -d -m 700 /etc/personaldocs
read -rsp "GitHub read-only token: " T && printf '%s' "$T" > /etc/personaldocs/github-token && chmod 600 /etc/personaldocs/github-token; unset T; echo
git -c credential.helper='!f(){ echo username=x-access-token; echo password=$(cat /etc/personaldocs/github-token); }; f' \
    clone https://github.com/OWNER/REPO.git /root/personaldocs-src
/root/personaldocs-src/scripts/personaldocs install --public-origin https://docs.example.com
```

Replace `OWNER/REPO` with your private repository and the origin with your public HTTPS address. The token is never put in the URL, process arguments or logs.

Useful options: `--bind 0.0.0.0:8000` (when the proxy runs on another host), `--ref v0.1.0` (install a tag), `--build-frontend` (force a local frontend build).

## After installing {#after}

1. Configure the reverse proxy and open the public address.
2. Enter the setup code (`personaldocs setup-token` prints a new one) and create the family accounts.
3. Configure the backup destination (Settings → Storage & backup) and run **Back up now**.
4. Optionally configure SMTP, Telegram, Google sign-in.
5. Run `personaldocs doctor`.

## Commands {#commands}

| Command | Purpose |
|---|---|
| `personaldocs status` | Service state, version, health |
| `personaldocs doctor` | Read-only diagnostics (redacted) |
| `personaldocs upgrade [--ref TAG]` | Back up, update, migrate, restart, verify |
| `personaldocs rollback` | Return to the previous release when the schema is compatible |
| `personaldocs repair` | Safe repairs (packages, permissions, services, migrations, stuck jobs) |
| `personaldocs backup` | Application backup now |
| `personaldocs restore PATH` | Verify and restore a backup (stops services) |
| `personaldocs integrity [--repair [--confirm]]` | Storage integrity check |
| `personaldocs recover-admin USER` | Console recovery for the main administrator |
| `personaldocs setup-token` | One-time code for the setup wizard |
| `personaldocs logs [web|worker|scheduler]` | Follow service logs |
| `personaldocs manage ...` | Run a Django management command as the service user |

## Resources {#resources}

The default is one OCR/conversion job at a time, which keeps a 2 vCPU / 4 GB container responsive. Each converter is limited in time and memory. The 10 GB of source documents will grow: previews, versions, thumbnails and the database add space. Watch **Activity & health → Disk** and plan for growth.
