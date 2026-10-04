# Importing folders

The import wizard brings an existing folder structure into the library while keeping every sub-folder.

## From this computer {#browser}

Settings is not needed: open **Folders → Import folder**, then choose or drag a folder. Desktop Chrome, Edge and Firefox can select whole folders. Browsers without folder selection (many phones) cannot keep paths; use a desktop browser or the server import instead.

## How mapping works {#mapping}

Each top-level folder is a mapping unit. For each one you decide:

- **A person's folder** — documents become that person's and land in their personal folder, sub-folders preserved. Several source folders may map to the same person.
- **Another folder** — for shared material (trips, house papers). Choose the destination and the owning account. The top folder's name is kept.
- **Skip**.

Suggestions appear only when a folder name exactly matches an account's name or username, and still need confirmation. An old name such as `user3` is never guessed — you choose who it belongs to. You can only map into folders where you may upload.

System and sync folders (for example `.sync`, `Thumbs.db`, `@eaDir`) are shown as excluded with a reason; tick *include excluded items* if you really want them.

## Running the import {#running}

The preview shows destinations and size. Start the import; progress is tracked per file. If the browser is closed, open the import again, select the same folder, and continue — files already imported are never imported twice. Failed files can be retried. Download the CSV report for a per-file record.

## From the server or NAS {#server}

The main administrator can import from folders listed under **Settings → Documents & folders → Approved server import folders** (one absolute path per line, e.g. `/mnt/nas/old-documents`).

- Files are **copied**; the source is opened read-only and never changed, moved, renamed or deleted.
- Paths outside the approved folders, `..` traversal and symbolic links pointing outside are refused.
- The import runs in the background and resumes safely after interruptions.

## Duplicates {#duplicates}

Uploading the same file twice on purpose creates two separate documents with their own permissions. Retrying the same import item never creates a second copy.

## Limits {#limits}

The maximum upload size per file is set in **Documents & folders → Maximum upload size**. Before importing, the preview warns if the server may not have enough free space (originals plus previews).

## Folder emoji {#emoji}

New folders get an emoji suggested from their name (Travel ✈️, Passport 🛂, Visa 🛃, House 🏠, Education 🎓, Medical 🩺, Banking 🏦, Insurance 🛡️, Vehicle 🚗, Certificates 📜, others 📁). Change it with **Rename / emoji**. Emoji are labels only; they never affect access and are not added to stored filenames.
