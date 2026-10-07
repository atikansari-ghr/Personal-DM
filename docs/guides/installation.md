<!-- audience: admin -->
# Installation on a Proxmox LXC (Debian 13)

## Target {#target}

- Proxmox LXC running **Debian 13 (trixie)**. Recommended: 2 vCPU, 4 GB RAM, 50 GB disk, and **Options → Features → Nesting** enabled (lets systemd isolate the services; without it the installer detects this and runs them without that extra isolation). To let the app mount the NAS itself (Settings → Storage & backup) the container must be **privileged with the `mount=nfs;cifs` feature**; an unprivileged container works too when the Proxmox host bind-mounts the share (see [Container requirements](backup-restore.md#lxc-requirements)).
- No Docker. Native services under systemd.
- HTTPS is provided by your existing **Nginx Proxy Manager** or **Pangolin** (see [Reverse proxy](reverse-proxy.md)).
- A NAS share (NFS or SMB) for backups — connected from Settings, or bind-mounted by the host (see [Backup and restore](backup-restore.md#nas)).

## What the installer does {#what}

`personaldocs install` is idempotent and resumable (rerun it after any failure; it continues safely and never wipes data or keys):

1. Checks OS, architecture, RAM, disk, systemd, DNS/network and port availability.
2. Installs packages: Python 3, PostgreSQL, Tesseract (English, Arabic, Hindi and orientation detection; packs for any other offered OCR language are installed too), OCRmyPDF, Ghostscript, qpdf, poppler-utils, LibreOffice (headless Writer/Calc/Impress), Node.js (only if the frontend must be built), git, and the **ClamAV antivirus** (`clamav`, `clamav-daemon`, `clamav-freshclam`; see [Antivirus](#antivirus)).
3. Creates the `personaldocs` system user, the PostgreSQL role/database (local socket only), and directories:

| Path | Contents |
|---|---|
| `/opt/personaldocs/releases/<version>` | Application code + Python virtualenv per release |
| `/opt/personaldocs/current` | Symlink to the active release |
| `/etc/personaldocs/` | `personaldocs.env`, `secret_key`, `encryption.key`, optional `github-token` (all private) |
| `/var/lib/personaldocs/` | Originals, previews, staging, temporary files, status files |
| `/var/log/personaldocs/install.log` | Redacted installer log |

4. Builds/installs the release, runs database migrations and collects static files.
5. Installs systemd units `personaldocs-web` (gunicorn), `personaldocs-worker` and `personaldocs-scheduler`, plus the root **host helper** `personaldocs-host.path` / `personaldocs-host.service` (see [Host helper](#host-helper)), then starts them and runs a health check.
6. Prints a one-time setup code.

## One-line install (recommended) {#one-line}

On a fresh Debian 13 machine or container, as root:

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)"
```

`personal-DM.sh` checks that the system is Debian 13 with systemd and that you are root, and refuses to continue
otherwise. It installs `git`, `curl` and `ca-certificates` if missing and downloads the source to
`/root/personaldocs-src`. It then starts the guided installer described below. On an installed system the same
command opens a menu:

| Menu / command | What it does |
|---|---|
| `install` | Fresh install, or re-run the guided installer (safe: answers remembered, finished steps skipped) |
| `upgrade` | `personaldocs upgrade` (verified backup first, automatic rollback on failure), then `personaldocs doctor` |
| `repair` | Reinstall services, permissions and installer steps; data and keys are kept |
| `doctor` / `status` | Health checks / services and version |
| `backup` | Application backup to the configured destination now |
| `restore DIR` | Verify the backup, then restore it after you type RESTORE |
| `recover-admin USER` | One-time password (and optional 2FA reset) for an administrator, shown on the console only |

For unattended use, add the command after `--`, for example:

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/atikansari-ghr/Personal-DM/main/personal-DM.sh)" -- upgrade --yes
```

Options: `--ref TAG` installs or upgrades to a specific tag or branch, `--dry-run` shows what would happen without
changing anything, and `--yes` avoids questions where possible. The script's own log is
`/var/log/personaldocs/personal-DM.log`. Secrets are never written to it. If a step fails, the script stops,
names the log and changes nothing further.

If the repository is private, the raw URL needs authentication and the one-liner does not work. Clone the repository
with a token instead (below) and run `bash personal-DM.sh` from the checkout; it asks for a read-only token if it
needs one and stores it in `/etc/personaldocs/github-token` (root only).

## Guided installation {#guided}

Run everything **inside the Debian 13 container**, as root (Proxmox: `pct enter <id>` or the container console).

**1. Copy the repository into the container**

```
apt-get update && apt-get install -y git
git clone https://github.com/OWNER/REPO.git /root/personaldocs-src
```

The repository is private, so git asks for a username and password: enter your GitHub username and, as the password, a
fine-grained token with read-only *Contents* access (see [Private GitHub access](private-github.md)). Typing it at the prompt keeps
it out of the URL, shell history and process list. Add `-b <branch>` to install a branch other than `main`.

**2. Run the installation script**

```
cd /root/personaldocs-src
bash scripts/easy-install.sh            # add --dry-run first to only see what it would do
```

The script then:

1. **Checks the system** and shows the result: operating system, CPU cores (2+ recommended), memory (4 GB recommended,
   2 GB minimum), free disk (40 GB+ recommended, 10 GB minimum), systemd, internet/DNS and whether the container can mount
   NFS/SMB. Missing requirements stop the script before anything is changed; warnings ask whether to continue.
2. **Asks the parameters**: the GitHub token again (stored root-only in `/etc/personaldocs/github-token` for later upgrades; it is
   tested immediately), public domain, reverse proxy (Nginx Proxy Manager, Pangolin or local) and the IP it connects from, port,
   an optional firewall rule that only lets the proxy reach the port, timezone, NAS (NFS server + export, SMB server + share + user +
   password, an already-mounted folder, or later), daily backup time and optional veraPDF. It shows a summary and asks for confirmation.
3. **Installs the dependencies**: Python, PostgreSQL, Tesseract OCR, OCRmyPDF, Ghostscript, LibreOffice, NFS/SMB client tools and more.
4. **Completes the installation**: database, application release built from this checkout, systemd services, trusted proxy,
   firewall, app settings (`manage.py apply_settings`, validated like the Settings screen), NAS connection
   (`personaldocs nas-apply --from-settings`), a first backup, `status` and `doctor`.
5. **Prints what to do next**: the exact settings to enter in Nginx Proxy Manager or Pangolin and the one-time setup code.

Answers (never passwords or tokens) are remembered in `/etc/personaldocs/install-answers.env`, so re-running the script offers the
previous values; every step is safe to repeat after an error. Progress is logged to `/var/log/personaldocs/easy-install.log`.
For an unattended install put the same `PD_…` variables in a file and run `PD_ANSWERS=/root/answers.env bash scripts/easy-install.sh --yes`
(an SMB password cannot be given this way — enter it later in Settings).

**Optional: create the container from the Proxmox host.** `scripts/proxmox-create-lxc.sh` (run as root on the host, `--dry-run`
supported) asks for the container ID, hostname, storage, disk/CPU/RAM, network and how backups reach the NAS, creates a matching
container (privileged with `mount=nfs;cifs`, or unprivileged with a host bind mount), and starts the installer inside it.

## Manual install {#install}

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

Useful options: `--bind 0.0.0.0:8000` (when the proxy runs on another host), `--ref v0.1.0` (install a tag), `--build-frontend` (force a local frontend build), `--without-antivirus` (skip ClamAV, for machines with less memory), `--with-security-tools` (also install `pip-audit` for the dependency check of the [security test](security-center.md#test); `repair` accepts it too).

## Antivirus (ClamAV) {#antivirus}

Install, upgrade and repair install `clamav`, `clamav-daemon` and `clamav-freshclam` and adjust `/etc/clamav/clamd.conf`:

- `LocalSocket /run/clamav/clamd.ctl` and **no** `TCPSocket` (clamd never listens on the network);
- `StreamMaxLength 1100M` (the app's own *Maximum scan size*, default 50 MB, decides what is scanned);
- `ConcurrentDatabaseReload no` (avoids holding two signature sets in memory during a reload);
- `EnableVersionCommand true` (Debian ships it off; the app reads the engine and signature version with it).

The first signature download can take a few minutes; `clamav-freshclam` then checks for updates automatically. ClamAV 1.5 also downloads `.cvd.sign` files, which it needs to load the signatures (FIPS mode); let freshclam fetch them rather than copying `.cvd` files by hand.

**Memory:** ClamAV needs about **1.2 GB of RAM** for its signatures. The recommended 4 GB container has room for it; the installer warns below about 3.5 GB. On smaller machines install with `--without-antivirus` and turn scanning off in Settings → Security → Antivirus, otherwise new files show *Not scanned*. See [antivirus](antivirus.md#install).

## Host helper {#host-helper}

`personaldocs-host.path` watches `/var/lib/personaldocs/host/request.json` and runs `personaldocs host-apply` as root. It accepts only fixed actions: inspect (firewall and listening services), check updates, install Debian security updates, update ClamAV signatures and reboot. The web app itself never runs `sudo`. Without the helper, Settings → Security → OS updates shows the commands to run by hand. See [OS updates](security-center.md#updates).

## After installing {#after}

1. Configure the reverse proxy and open the public address.
2. Enter the setup code (`personaldocs setup-token` prints a new one) and create the **Main Administrator** (your name, username and password). Only this one account is created. In the next step, **Add family members (optional)**, add members now or choose **Skip for now** and add them later in Settings → Family & access. See [setup](setup.md#main-admin).
3. Connect the NAS and check the backup destination (Settings → Storage & backup → **Connect NAS**), then run **Back up now** (the guided installer already did this if you answered the NAS questions).
4. Optionally configure SMTP, Telegram, Google or authentik sign-in.
5. In Settings → Security, set **Deployment exposure** (LAN only or Published on the Internet) and run **Scan entire existing library** if you imported files before ClamAV had its signatures.
6. Run `personaldocs doctor`.

## Commands {#commands}

| Command | Purpose |
|---|---|
| `personaldocs status` | Service state (also `clamav-daemon`, `clamav-freshclam`, `personaldocs-host.path`), version, health, "Reboot required" |
| `personaldocs doctor` | Read-only diagnostics (redacted), including missing OCR language packs, ClamAV and signature age, files pending scan, host helper, HTTPS for Internet deployments, storage thresholds and a pending reboot |
| `personaldocs upgrade [--ref TAG]` | Back up, update, migrate, restart, verify |
| `personaldocs rollback` | Return to the previous release when the schema is compatible |
| `personaldocs repair` | Safe repairs (packages, permissions, services, migrations, stuck jobs) |
| `personaldocs backup` | Application backup now |
| `personaldocs restore PATH` | Verify and restore a backup (stops services) |
| `personaldocs integrity [--repair [--confirm]]` | Storage integrity check |
| `personaldocs recover-admin USER` | Console recovery for the main administrator |
| `personaldocs setup-token` | One-time code for the setup wizard |
| `personaldocs host-apply` | Run the host action requested in Settings → Security (normally started by `personaldocs-host.path`) |
| `personaldocs logs [web|worker|scheduler]` | Follow service logs |
| `personaldocs manage ...` | Run a Django management command as the service user |

## Resources {#resources}

The default is one OCR/conversion job at a time, which keeps a 2 vCPU / 4 GB container responsive. ClamAV uses about 1.2 GB of that memory. Each converter is limited in time and memory. The 10 GB of source documents will grow: previews, versions, thumbnails and the database add space. Watch **Activity & health → Disk** and plan for growth.
