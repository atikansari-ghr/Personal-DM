# User guide

For everyone in the family. The same help is built into the app under **Help**; the linked topic guides go deeper.
Examples use the demo labels A. Ansari (administrator), Mom, Son1, Son2, Son3 and Daughter. These are demonstration
accounts added in the optional setup step for the screenshots; the app never creates them
([names in screenshots](guides/setup.md#demo-names)).

## 1. Signing in {#sign-in}

1. Open your family's address, for example `https://docs.example.com`.
2. Enter your username and password, then **Sign in**.
3. If you set up two-step verification, the app asks for the 6-digit code from your authenticator app, a passkey, or
   a recovery code.
4. If the administrator allows it and you turned it on, **Sign in with a passkey** signs you in with your phone's or
   computer's fingerprint, face or PIN, without a password.

**First sign-in:** use the temporary password the administrator gave you. You are asked to choose your own straight
away.

**Sign-in page design:** the administrator may choose a wallpaper, title and logo for the sign-in page. The design
only changes the look; the sign-in methods (password, code, passkey, Google) are the same with every design. See
[sign-in page designs](guides/login-designs.md).

**Password managers:** the username, password and one-time-code fields are standard, so Bitwarden, 1Password, Apple
Passwords and browser password managers can fill them. You can paste the code, and typing it always works.
More: [authenticator app and recovery codes](guides/totp-recovery.md), [passkeys](guides/passkeys.md).

## 2. Your account {#account}

**Settings → My account**:

| Tab | What you can do |
|---|---|
| Profile | Name, email (needed for email notifications), [profile photo](guides/getting-started.md#profile-photo) |
| Password & security | Change password, authenticator app, recovery codes, passkeys, passwordless sign-in, signed-in devices |
| Linked accounts | Link Google sign-in (optional) |
| Appearance | Theme (Green, Blue, Black & White), layout, Overview widgets |
| Notifications | Critical notifications (read-only), your optional notifications per channel, Telegram link |
| Email imports | Import attachments from your own mailbox by rule |

Your theme, Overview, layout and notification choices are saved to your account, so they are the same on every
device.

**Security changes** need a fresh confirmation (password or passkey within the last few minutes). This covers:
- adding or removing passkeys
- turning the authenticator app on or off
- new recovery codes
- passwordless sign-in on or off

Each of these sends you a security notification.

## 3. Overview {#dashboard}

The **Overview** is your start page (it replaces the former dashboard). It shows only documents you can open.

- **Widgets:** Today (Gregorian and Hijri date), Weather, Documents summary, Month calendar with holidays, Upcoming
  holidays, Expiring soon, Shared with me, Recent documents, Recent activity, Review queue and more.
- **Customize Overview:** add (**Add widget…**) or remove (**×**) widgets, reorder by dragging or with **‹ / ›**,
  resize with **− / +**, choose a style (rectangular, compact, circular for single-value widgets) and open **⚙** for
  widget settings. **Save layout** stores it for your account on every device; **Cancel** and **Reset to default**
  are always available. The selection and order can also be changed in My account → Appearance → Overview widgets.
- **Hijri date:** Umm al-Qura calendar, following the installation timezone. The administrator may shift it by up to
  two days to match the local moon sighting.
- **Holidays:** public holidays of the countries chosen by the administrator (Saudi Arabia and India by default).
  Moon-dependent holidays are marked *Provisional* until confirmed.
- **Weather** (only if the administrator enabled it): choose your own city in the widget. Only the city's
  coordinates are sent to the weather provider.

If you had chosen your widgets before an upgrade, your choice is kept; add the new widgets with **Customize
Overview**. See [Overview](guides/overview.md).

## 4. Folders and file types {#folders}

- **My Documents** at the top of the tree is your own area, opened when you go to **Folders**. Other members'
  areas show their name and photo, only if you have access, and stay closed until you open them.
- Each document has a labelled icon (PDF, JPG, PNG, WEBP, TXT, DOC, XLS, PPT, ZIP, DCM, FILE) based on the real file
  content.
- On a computer the browser has three panels: folders, documents, preview. Drag the dividers to resize them. On
  phones you go Folders → Documents → Preview, with **☰** for the tree and **← Back to folder**.
- Folders directly in your area get a suggested icon (✈️ Travel, 🛂 Passport…); sub-folders get 📁. Change it with
  **⋮ → Change icon…** or **Reset to default**. Icons never change access.
- **Views:** List, Thumbnails or Details (a sortable table), plus **Sort by**. Your choice follows you to every device.
- **⋮ menus** on documents (Open, Rename, Move to, Download, Share, Archive) and folders (Open, New subfolder, Rename,
  Change icon, Move to, Share / who has access, Download ZIP, Archive) list only what you may do.

More: [getting started](guides/getting-started.md#my-documents), [actions](guides/getting-started.md#actions),
[views](guides/getting-started.md#views), [icons](guides/getting-started.md#icons), [file types](guides/getting-started.md#file-types).

## 5. Uploading and importing {#upload}

- **Upload:** choose files (or take a photo on a phone), pick the folder and optionally the document type.
- **Drag and drop from your computer:** drop files or whole folders on the document list or on a folder in the tree.
  Folders keep their structure below the drop target; a progress card lists anything that could not be uploaded
  and why. See [drag and drop](guides/getting-started.md#drop).
- **Import folder:** bring a whole folder structure in. For each top folder choose:
  - a person (optionally a sub-folder inside their area)
  - another folder
  - or skip

  Then **Check & preview** shows the exact final folders (*new* or *existing*) before anything is imported. Nested
  folders are kept as they are.
- Duplicate uploads become separate documents; nothing is overwritten.

More: [folder imports](guides/folder-imports.md), [phone uploads](guides/mobile-pwa.md#upload).

## 6. Moving documents and folders {#moving}

- **Drag and drop** (computer): drag documents (or several ticked ones) onto a folder in the tree or a sub-folder
  button; drag folders in the tree.
- **Move to…** (all devices): ⋮ → **Move to…** → choose the folder → **Next** → **Move**.

If a move is not allowed, the reason is shown and nothing changes. Moving can change who can see a document,
because it inherits the new folder's access. See [moving](guides/getting-started.md#moving).

## 7. Viewing, OCR and details {#viewing}

- **Viewer:** zoom − / +, the current %, **Fit page**, **Fit width**, **100%**, page arrows, **Full screen** and
  **Download**. Keys: `+` `−` `0` `W` `P`. See [viewer](guides/getting-started.md#viewer).
- **OCR (text recognition):** runs on your server, and only on what is chosen. Depending on the document type, the
  administrator sets OCR to *Disabled*, *Manual* (the default for new installations) or *Automatic*. To recognise a
  document, open **Text (OCR)** and choose **Run OCR…**: tick the source files (for example front and back, added with
  **⋮ → Add another side or copy…**), the pages (`1-2, 5`, empty for all), the languages (English, Arabic, Hindi
  and any others offered) and, if needed, a forced rotation. The status shows *Not processed*, *Queued*,
  *Processing*, *Needs review*, *Confirmed*, *Failed* or *OCR removed*; a queued job can be cancelled. See
  [selective OCR](guides/ocr-corrections.md#selective).
- **OCR quality:** the **Text** tab shows the recognised text and the **OCR confidence**, and greys out unreliable
  lines. If the text is junk, use **Re-run OCR…** with other pages, languages or a rotation. Your confirmed values
  are never overwritten by a re-run. A card that says "No Expiry Date" is suggested as **Does not expire** instead of
  an invented date. See [OCR quality](guides/ocr-corrections.md#quality).
- **OCR review:** the **OCR review** page in the sidebar lists the documents you may edit whose text waits for
  review or failed. Accept, correct or reject the suggested details, or **Mark reviewed**. See
  [review queue](guides/ocr-corrections.md#review).
- **Remove OCR data…** deletes the recognised text and its search entries. The original file stays unchanged and
  details you confirmed are kept. See [removing OCR data](guides/ocr-corrections.md#remove).
- **Details:** suggested details (issue/expiry date, number, name) only count after you **Confirm** them. Confirmed
  dates drive the document name and reminders. See [OCR and corrections](guides/ocr-corrections.md).
- **Versions and renewals:** a better scan is a new version; a renewed passport is a new linked document. See
  [originals and versions](guides/originals-versions.md).

## 8. Local AI (if your administrator turned it on) {#ai}

- **AI suggestions** on a document propose a title, type, dates, tags and folder. Nothing changes until you click
  **Accept**.
- **Ask AI** answers questions such as "When does my passport expire?" using only documents you can open, and links
  to its sources.
- **Match meaning** in search finds documents with similar meaning.

AI runs on your family's own server, and normal search, OCR and uploads work without it. It reads a document's text
only when the administrator allows AI for that document type.
See [Local AI](guides/local-ai.md).

## 9. Search {#search}

Type in the search box at the top. Results show highlighted snippets. You can filter by person, type, tag and
expiry, and save searches as views. See [search](guides/search.md).

## 10. Sharing {#sharing}

- **Share → Create link** makes an expiring, optionally password-protected link to one version.
- **Share file…** uses your device's share menu.
- Links can be revoked at any time.

See [sharing](guides/sharing.md).

## 11. Notifications and reminders {#notifications}

**Critical notifications** are set by the administrator and always reach you. Examples: a new passkey on your
account, two-step verification turned off, a sign-in from a new country.

**Optional notifications** are yours to choose per event and channel (in-app, email, Telegram) under
**My account → Notifications**. Examples:
- documents added to your folders
- documents archived or deleted
- access given to you
- import finished
- OCR finished or failed
- sign-ins

If a required channel cannot reach you (no email address, Telegram not linked), a red message tells you what to fix.

**Expiry reminders** go to the owner and the family head at 90/60/30/7/0 days, by default.

Messages show what happened, when, the account, and, for sign-ins, the IP, country, method and device. Large
imports arrive as one summary. Messages never contain passwords, codes or document numbers.
See [notifications](guides/expiry-rules.md#critical).

## 12. Archive {#archive}

**Archive** hides a document or folder, and its public links stop working. Only the main administrator can restore
or permanently delete it. You are told when someone else archives or deletes your documents.
See [archive](guides/archive.md).

## 13. Offline, phone and tablet {#offline}

- Install the app on your phone's home screen. Every feature is available on phones and tablets.
- **Save for offline use** keeps a document on that device for your account only; **Offline files** lists them.
- **Export** downloads a ZIP of folders you may download.

See [phone and tablet](guides/mobile-pwa.md) and [offline and export](guides/offline-export.md).

## 14. Appearance {#appearance}

Pick Green & White, Blue & White or Black & White, and the three-panel or full-page layout. Your choice applies on
all your devices. See [themes](guides/themes.md).

## 15. Troubleshooting {#troubleshooting}

| Problem | Try |
|---|---|
| Forgot password | Ask the administrator to reset it (or use "Forgot password" if email is configured) |
| Lost phone with authenticator / passkey | Sign in with a recovery code or another passkey; otherwise ask the administrator to **Reset 2FA** |
| "Access not allowed" page | You are outside the allowed countries; ask the administrator for temporary travel access |
| A move was refused | Read the message; you may lack permission at the destination |
| Document stuck in Processing or Queued | Wait a few minutes (the administrator may have paused the OCR queue); cancel a queued job or use **Re-run OCR…** in the Text (OCR) tab |
| Not receiving email/Telegram | My account → Notifications shows what is missing |

More: [troubleshooting](guides/troubleshooting.md).
