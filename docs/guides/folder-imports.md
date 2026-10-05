# Importing folders

The import wizard brings an existing folder structure into the library while keeping every sub-folder.

## From this computer {#browser}

Settings is not needed: open **Folders → Import folder**, then choose or drag a folder. Desktop Chrome, Edge and Firefox can select whole folders. Browsers without folder selection (many phones) cannot keep paths; use a desktop browser or the server import instead.

## How mapping works {#mapping}

Each top-level folder is a mapping unit. For each one you decide:

- **A person's folder** — documents become that person's. By default they land at the top of the person's area;
  click the folder button (**Top of their folder**) to pick an existing **sub-folder inside that person's area**
  instead, for example *Sam Sample / Education*. Several source folders may map to the same person.
- **Another folder** — for shared material (trips, house papers). Pick the destination folder in the folder picker
  and choose the owning account.
- **Skip**.

**keep “<name>” as a folder** decides whether the source folder itself is recreated (for *Old*: `… / Education /
Old / …`) or only its contents (`… / Education / …`). It is on by default for "Another folder" and off for "A
person's folder" when the source folder is named after the person.

### The destination only replaces the top {#destination}

Choosing a destination changes **where the import starts**, nothing else. Every nested source folder is recreated
beneath it exactly as it is — nothing is flattened. Example: `Old/Address Update 22July2026/letter.pdf` mapped to
*Sam Sample / Parity* with *keep "Old"* ticked becomes `Family library / Sam Sample / Parity / Old / Address Update
22July2026 / letter`.

**Check & preview** shows the **final folder structure**: every folder the import will use, with the number of files
and a badge:
- **existing** — a folder with that name is already there; files are added next to what it contains (nothing is
  overwritten, same-named files become separate documents)
- **new** — the folder will be created

Only folders you may upload to can be chosen, and a sub-folder must really be inside the chosen person's area; the
server checks this again when you save and when each file is imported. If a destination is archived or your access
is removed after the preview, the affected files fail with a clear reason and nothing is put anywhere else.

Suggestions appear only when a folder name exactly matches an account's name or username, and still need confirmation. An old name such as `user3` is never guessed — you choose who it belongs to. You can only map into folders where you may upload.

System and sync folders (for example `.sync`, `Thumbs.db`, `@eaDir`) are shown as excluded with a reason; tick *include excluded items* if you really want them.

## Running the import {#running}

The preview shows destinations, sizes and the final folder structure. Start the import; progress is tracked per file. If the browser is closed, open the import again, select the same folder, and continue — files already imported are never imported twice. Failed files can be retried. Download the CSV report for a per-file record.

## From the server or NAS {#server}

The main administrator can import from folders listed under **Settings → Documents & folders → Approved server import folders** (one absolute path per line, e.g. `/mnt/nas/old-documents`).

- Files are **copied**; the source is opened read-only and never changed, moved, renamed or deleted.
- Paths outside the approved folders, `..` traversal and symbolic links pointing outside are refused.
- The import runs in the background and resumes safely after interruptions.

## Duplicates {#duplicates}

Uploading the same file twice on purpose creates two separate documents with their own permissions. Retrying the same import item never creates a second copy.

## Limits {#limits}

The maximum upload size per file is set in **Documents & folders → Maximum upload size**. Before importing, the preview warns if the server may not have enough free space (originals plus previews).

## Folder templates {#templates}

A template is an optional list of folders to create for a person, for example `Identity/Passport`, `Education`, `Medical` and `Travel`. The main administrator edits it in **Settings → Documents & folders → Folder template for new members** (one path per line, `/` for sub-folders).

Nothing is created automatically. You choose to apply the template:

- when adding a family member (tick *Create template folders*);
- in the setup wizard (tick *Create the suggested folders for each person*);
- on any folder you may organise: open it and choose **Apply folder template**.

Applying a template again only adds missing folders. It never removes, renames or moves existing ones, and the folders get normal emoji suggestions and inherited access.

## Folder emoji {#emoji}

New folders get an emoji suggested from their name (Travel ✈️, Passport 🛂, Visa 🛃, House 🏠, Education 🎓, Medical 🩺, Banking 🏦, Insurance 🛡️, Vehicle 🚗, Certificates 📜, others 📁). Change it with **Rename / emoji**. Emoji are labels only; they never affect access and are not added to stored filenames.
