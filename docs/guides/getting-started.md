# Getting started

Personal Documents is a private, self-hosted library for your family's documents: passports, visas, residence permits, ID cards, certificates, property papers, bills and more. Everything is stored on your own server.

## First steps {#first-steps}

1. The administrator runs the installer on the server and opens the web address (see [Installation](installation.md)).
2. The first-run wizard creates the six initial family accounts (see [Family accounts and setup](setup.md)).
3. Each person signs in with the temporary password they were given and chooses their own.
4. Upload documents, or import an existing folder structure with the [folder import wizard](folder-imports.md).

## Navigation {#navigation}

| Section | What it is for |
|---|---|
| Overview | Your dashboard: statistics, family members, recent documents, upcoming expiries, review queue |
| Folders | The three-panel browser: folder tree, documents, preview and details |
| Shared with me | Documents owned by others that you are allowed to view |
| Offline files | Files you saved on this device, and full-library export |
| Notifications | Expiry reminders and other messages |
| Archive | Archived documents (main administrator only) |
| Ask AI | The document assistant, when the administrator enabled [Local AI](local-ai.md) |
| Settings | Your account and, for administrators, the whole workspace |

## Dashboard {#dashboard}

The dashboard only counts documents you can see. Administrators additionally see backup and processing health.

Choose what it shows with **Customise** on the dashboard (or Settings → My account → Appearance → Dashboard widgets):
- **Tick** the widgets you want: the counters (documents, family members, expiring in 90 days, storage, needs
  review), the family member cards, saved views, recent documents, upcoming expiries, the review queue and (for
  administrators) backup status.
- **Order** the ticked widgets by dragging them, or with the ↑ / ↓ buttons (keyboard and touch).
- **Save settings.** The choice belongs to your account, so your phone, tablet and computer show the same dashboard.

## Your own folders {#my-documents}

At the top of the folder tree, **My Documents** with your photo (or initials) takes you straight to your own area.
In the tree it is labelled "My Documents — <your name>"; other people's areas show their name and photo.

## File types {#file-types}

Each document shows a small labelled icon — PDF, JPG, PNG, WEBP, IMG, TXT, DOC, XLS, PPT, ZIP, DCM or FILE. The type
is taken from the file's actual content, not just its name: a photo renamed to `.pdf` shows as JPG/PNG, and a file
called `.docx` that is not really a Word document shows as FILE.

## Moving documents and folders {#moving}

- **Drag and drop** (computer): drag a document (or several ticked ones) onto a folder in the tree or onto a
  sub-folder button above the list. Drag a folder in the tree onto another folder to move it with everything inside.
- **Move to…** (every device, keyboard and touch): the ⋮ menu of a document or folder → **Move to…** → pick the
  folder → **Next** → **Move**. Folders you cannot use are greyed out with the reason.
- Both use the same server checks. A move that is not allowed (no permission, a folder into its own sub-folder, a
  folder name that already exists there, an archived destination) is refused and nothing changes — nothing is lost,
  copied or left behind.
- Moving within an area that has the same access is always allowed with organise rights. A move that would let
  *more* people see the item needs the "manage permissions" right (or the main administrator), because it changes
  who has access.

## Viewing documents {#viewer}

PDFs, scans and images open in the built-in viewer (in the preview panel and in **Open full page**):

| Control | Keys (when the viewer has focus) |
|---|---|
| Zoom out / in (− / +), 25 % to 400 %, current zoom shown | `−` / `+` (also Ctrl/⌘ + mouse wheel) |
| Fit page — the whole page is visible | `P` |
| Fit width — page as wide as the viewer; scroll down | `W` |
| 100 % — actual size | `0` |
| Page ‹ › and "Page 2 / 5" for multi-page PDFs | Page Up / Page Down in Fit page |
| Full screen, Download | — |

Fit page and Fit width adjust automatically when you resize the window, rotate a phone or open/close panels.
Images keep their proportions. On phones the toolbar is one row you can swipe sideways. Viewing never changes the
stored file, and documents are never sent to an outside viewer. If a file cannot be displayed (damaged or
unusual), the viewer says so and offers **Download**; for PDFs you can also switch to the browser's own viewer.


## Profile photo {#profile-photo}

**Settings → My account → Profile → Profile photo**:
- Upload a JPEG, PNG or WebP (up to 5 MB).
- Move the zoom and position sliders to crop it to a square, then **Save photo**. **Replace photo** and **Remove photo** work the same way.
- Without a photo, your initials are shown.

The main administrator can manage anyone's photo in **Family & access** (edit a member).

Photos are private:
- **Visibility:** they are only shown to signed-in family members who can see you. They are never available at a public web address.
- **Metadata:** location and camera details are removed when the photo is saved.
- **Identity:** a photo never decides who you are or what you can access.

## What the app does and does not do {#scope}

- OCR, previews and search run locally on your server. Optional [Local AI](local-ai.md) uses only an AI server the
  administrator configures (normally on your home network) and never falls back to a cloud service.
- External connections happen only for features you configure: Google sign-in, SMTP email, Telegram, your own IMAP mailboxes, package downloads during installation, and public share links you create.
- Viewing a document shows its content: turning off download cannot prevent screenshots or copying.
