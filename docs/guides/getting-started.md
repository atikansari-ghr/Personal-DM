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
| Settings | Your account and, for administrators, the whole workspace |

## Dashboard {#dashboard}

The dashboard only counts documents you can see. Administrators additionally see backup and processing health. Choose which statistics appear under Settings → My account → Appearance → Dashboard widgets (comma-separated: `documents,members,expiring,storage`).

## What the app does and does not do {#scope}

- OCR, previews and search run locally on your server. No cloud AI is used.
- External connections happen only for features you configure: Google sign-in, SMTP email, Telegram, your own IMAP mailboxes, package downloads during installation, and public share links you create.
- Viewing a document shows its content: turning off download cannot prevent screenshots or copying.
