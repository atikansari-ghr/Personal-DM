# User guide

For everyone in the family. The same help is built into the app under **Help**; the linked topic guides go deeper.
Examples use the demo labels A. Ansari (administrator), Mom, Son1, Son2, Son3 and Daughter. These are demonstration
accounts added in the optional setup step for the screenshots; the app never creates them
([names in screenshots](guides/setup.md#demo-names)).

## 1. Signing in {#sign-in}

1. Open your family's address, for example `https://docs.example.com`.
2. Enter your username (or your email address) and password, then **Sign in**.
3. If you set up two-step verification, the app asks for the 6-digit code from your authenticator app, a passkey, or
   a recovery code.
4. **Or** click **Sign in with Passkey** below the password: your phone or computer asks for your fingerprint, face or
   PIN and signs you in without a username or password. Your browser may also offer your passkey right in the
   username field. The button is greyed out on a plain `http://` address; use the `https://` address. If your
   administrator chose *Password + Passkey*, the passkey is asked after the password instead.
5. If your family uses authentik, a **Sign in with authentik** button (the label may differ) is shown. It works only
   after you linked your account (see [your account](#account)). Signing in with your username and password always
   stays available, also when authentik is down. Two-step verification you turned on is still asked afterwards.

![Sign-in page with Sign in with Passkey (synthetic data)](images/screenshots/login-passkey.png)

**First sign-in, or a temporary password from your administrator:** sign in with the temporary password the
administrator gave you (in person or another safe channel; it is never emailed). You are asked to choose your own
straight away. When an administrator issues a temporary password you are signed out on every device and get the
notice **Temporary password issued**, which never contains the password.

**Forgot your password?** Click **Forgot password?** on the sign-in page. If your account has an email address, you
get an email **Reset your password** with a button that works once, for 30 minutes by default. Your administrator can
also send you this email. See [password reset](guides/password-reset.md).

**Sign-in page design:** the administrator may choose a wallpaper, title and logo for the sign-in page. The design
only changes the look; the sign-in methods (password, code, passkey, Google, authentik) are the same with every design. See
[sign-in page designs](guides/login-designs.md).

**Password managers:** the username, password and one-time-code fields are standard, so Bitwarden, 1Password, Apple
Passwords and browser password managers can fill them. You can paste the code, and typing it always works.
More: [authenticator app and recovery codes](guides/totp-recovery.md), [passkeys](guides/passkeys.md),
[password reset](guides/password-reset.md).

## 2. Your account {#account}

**Settings → My account**:

| Tab | What you can do |
|---|---|
| Profile | Name, email (needed for email notifications), [profile photo](guides/getting-started.md#profile-photo) |
| Password & security | Change password, authenticator app, recovery codes, passkeys, passwordless sign-in, signed-in devices, **Link authentik account** (when the administrator turned authentik on) |
| Linked accounts | Link Google sign-in (optional) |
| Appearance | Theme (Green, Blue, Black & White), layout, Overview widgets |
| Notifications | Critical notifications (read-only), your optional notifications per channel, Telegram link, push notifications on this device and their lock-screen detail |
| Email imports | Import attachments from your own mailbox by rule |

Your theme, Overview, layout and notification choices are saved to your account, so they are the same on every
device.

**Security changes** need a fresh confirmation (password or passkey within the last few minutes). This covers:
- adding or removing passkeys
- turning the authenticator app on or off
- new recovery codes
- passwordless sign-in on or off

Each of these sends you a security notification.

**Adding a passkey:** under **Passkeys**, type a name (for example "Personal iPhone" or "Office Laptop") and click
**Add a passkey**. In passwordless mode this turns on **Use Sign in with Passkey without a password** for you
automatically; untick it if you want the passkey only after your password. Rename or remove passkeys there too.

**Linking authentik:** open **My account → Password & security → authentik → Link authentik account**, confirm your
password, then sign in at authentik. Only you can link your account; it is never linked because an email address
matches. **Unlink** removes the link again (you need a local password for that). The administrator can also revoke a
link; your account, password and documents stay as they are. See [authentik](guides/authentik.md#linking).

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

**Antivirus check:** if the administrator turned on the antivirus, every new file is checked on your family's own
server a few seconds after the upload. You can use the file straight away. A small shield shows the result in the
folder list and in the document's **Versions** tab:

| Badge | Meaning |
|---|---|
| Scan pending | Waiting for its check; the file is usable. |
| Clean | Nothing was found. |
| Not scanned | The check was not possible (for example the antivirus was not running), or the file was stored before the antivirus existed. The file stays available. |
| Not scanned — size limit exceeded | The file is larger than the scan limit. It is stored normally, but not reported as clean. |
| Scan failed | The antivirus reported an error for this file. The file stays available. |
| Threat detected / Quarantined | Malware was found. The file is blocked (see below). |
| Released from quarantine | The main administrator checked the file and released it. |

When a file is quarantined, the document shows **"Quarantined by the antivirus"**: preview, download, sharing,
export, OCR and Local AI are blocked for that file. Its name and details stay visible. Only the main administrator can
review it, release it or delete it. See [antivirus](guides/antivirus.md#quarantine).

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
  **⋮ → Add another side or copy…**), the pages (`1-2, 5`, empty for all), the engine (**PaddleOCR (PP-OCRv5)** by
  default, or **Tesseract (Legacy)**), the language profile (English, Arabic + English, Hindi + English and any
  others offered) and, if needed, a forced rotation. Each result shows which engine produced it. See
  [OCR engines](guides/ocr-engines.md). The status shows *Not processed*, *Queued*,
  *Processing*, *Needs review*, *Confirmed*, *Failed* or *OCR removed*; a queued job can be cancelled. See
  [selective OCR](guides/ocr-corrections.md#selective).
- **OCR quality:** the **Text** tab shows the recognised text and the **OCR confidence**, and greys out unreliable
  lines. If the text is junk, use **Re-run OCR…** with other pages, languages or a rotation. Your confirmed values
  are never overwritten by a re-run. A card that says "No Expiry Date" is suggested as **Does not expire** instead of
  an invented date. See [OCR quality](guides/ocr-corrections.md#quality).
- **OCR review:** the **OCR review** page in the sidebar lists the documents you may edit whose text waits for
  review or failed. Accept, correct or reject the suggested details, or **Mark reviewed**. See
  [review queue](guides/ocr-corrections.md#review).
- **Remove OCR data…** (also in **⋮ More actions**) deletes the recognised text, its positions and confidences, the
  searchable copy, its search entries, unconfirmed suggestions and Local AI data built from it. Optionally it also
  hides the text layer embedded in the file. The original file stays unchanged and details you confirmed are kept.
  See [removing OCR data](guides/ocr-engines.md#remove).
- **Disable OCR for this document…** stops every future recognition of that document (also by an *Automatic* type or
  *Regenerate preview*) until you choose **Enable OCR for this document**. You decide whether the existing text is
  kept or removed. See [disabling OCR](guides/ocr-engines.md#disable).
- **Details:** suggested details (issue/expiry date, number, name) only count after you **Confirm** them. Confirmed
  dates drive the document name and reminders. See [OCR and corrections](guides/ocr-corrections.md).
- **Versions and renewals:** a better scan is a new version; a renewed passport is a new linked document. See
  [originals and versions](guides/originals-versions.md).

### Document type and details {#document-types}

The **folder** is where a document is kept; the **document type** (Passport, Visa, Insurance…) is what it is.
Moving a document never changes its type, and changing the type never moves it.

- **Set or change the type:** in **Details** use **Set type** (shown as *Not assigned* when empty) or **Change…**;
  or **⋮ → Set document type…** in Folders and **More actions** on the document page; or choose it in the upload
  dialog, where a folder's suggested type is preselected (*Suggested by this folder*). Viewers see the type
  read-only.
- **Details:** the type decides the fields shown under **… details** heading (for example *Passport details*), in order. Empty fields show **+**. The
  status badge says *Details confirmed*, *Incomplete: …* (naming the empty required fields) or *Needs review*; **Confirm as incomplete** accepts
  empty required fields on purpose.
- **Where a value came from:** *Suggested* (not yet confirmed) or *Edited* (you replaced an OCR/AI value), and a
  source chip: Manual, OCR, OCR (MRZ), Local AI, Imported, System or Migrated. Only confirmed values count for the
  name and reminders, and confirmed values are never overwritten.
- **Suggested types:** a folder, OCR or the local AI can suggest a type with **Accept…**, **Change…** or **Ignore**;
  nothing is applied by itself.
- **Changing the type** shows a preview first. Values the new type has no field for are kept under **Previous
  details — needs review**: **Map to a template field**, **Keep as detail** or **Remove**. If the expiry field no
  longer applies, reminders stop until you map it. **Re-map existing OCR data** fills the new fields from the text
  already recognised, without a new scan.
- **Additional details:** **Add a detail… → New detail for this document…** adds a one-off detail (name and value)
  to this document only.
- **Several documents:** tick them and choose **Set type…**. Documents with another confirmed type are skipped unless
  you tick *Also change documents with a confirmed type*.

See [document types and details](guides/document-types.md).

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

**Security notices you may get:** New sign-in, Unusual sign-in (new country), New passkey registered, Passkey removed,
Authenticator app turned on or off, Password reset requested, Administrator reset your password, Temporary password
issued, Password reset completed, Account locked, and Google or authentik account linked or removed. Each has a
highlighted warning such as *"If this was not you, change your password and sign out other devices…"*, shown in red
in the app and in email and in bold in Telegram. These warnings are always included.

**Optional notifications** are yours to choose per event and channel (in-app, email, Telegram, push) under
**My account → Notifications**. Examples:
- documents added to your folders
- documents archived or deleted
- access given to you
- import finished
- OCR finished or failed
- sign-ins
- your documents moved, restored, re-typed or confirmed by someone else

If a required channel cannot reach you (no email address, Telegram not linked), a red message tells you what to fix.

**Expiry reminders** go to the owner and the family head at 90/60/30/7/0 days, by default.

Messages show what happened, when, the account, and, for sign-ins, the IP, country, method and device. Large
imports arrive as one summary. Messages never contain passwords or codes; document numbers are hidden unless the
administrator allows a masked number, and never appear in push notifications.

**Notification Center.** Open **Notifications** (the bell) to see your notifications as cards with an icon, the
severity (Critical, Warning, Success, Information) and category as text, a summary and buttons such as **Open
Document**, **Go to Folder** or **Review Activity**. **Show details** lists the details and what to do. Filter by
unread, category or severity, and use **Mark read** / **Mark all read**. New warning, critical and success
notifications also appear briefly as a banner at the top of the app. Expiry reminders offer **Snooze 7 days**.

**Email and Telegram** messages have the same content with icons and buttons. Links open the app and still need
you to sign in.

**Push notifications** on your phone or computer: open the app through its HTTPS address (on iPhone and iPad, from
the Home Screen), go to **My account → Notifications → Push notifications on this device**, choose **Turn on for this
device** and **Send test push**, then tick **Push** for the events you want. **Lock-screen detail** decides what the
lock screen shows (Minimal, Standard or Detailed). Repeat on each device.

See [notifications](guides/notifications.md), [push](guides/notifications.md#push) and
[critical and optional notifications](guides/expiry-rules.md#critical).

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
| Forgot password | Use **Forgot password?** if your account has an email address, or ask the administrator for a temporary password or a reset email. See [password reset](guides/password-reset.md) |
| **Sign in with Passkey** is greyed out | Open the `https://` address of the app, not `http://…` |
| Reset email did not arrive | Check spam; only the newest link works, for 30 minutes; ask the administrator |
| Lost phone with authenticator / passkey | Sign in with a recovery code or another passkey; otherwise ask the administrator to **Reset 2FA** |
| "Access not allowed" page | You are outside the allowed countries; ask the administrator for temporary travel access |
| A move was refused | Read the message; you may lack permission at the destination |
| Document stuck in Processing or Queued | Wait a few minutes (the administrator may have paused the OCR queue); cancel a queued job or use **Re-run OCR…** in the Text (OCR) tab |
| Not receiving email/Telegram | My account → Notifications shows what is missing |
| No push notifications offered | Use the HTTPS address; on iPhone/iPad add the app to the Home Screen first; allow notifications in the browser. See [push troubleshooting](guides/notifications.md#troubleshooting) |
| "Quarantined by the antivirus" on a document | The file is blocked for safety; ask the main administrator to review it |
| "This authentik account is not linked" | Sign in with your password, then use **Link authentik account** in My account → Password & security |
| "authentik cannot be reached" | Sign in with your password instead; authentik is optional |

More: [troubleshooting](guides/troubleshooting.md).
