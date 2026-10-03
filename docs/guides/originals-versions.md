# Originals, versions and renewals

## Originals are kept exactly {#originals}

Every uploaded file is stored byte-for-byte as an ordinary file on the server, made read-only, with a SHA-256 checksum. OCR and previews create separate copies; the original is never altered.

## Better scan or renewal? {#version-or-renewal}

| Situation | Use | Result |
|---|---|---|
| Clearer scan, corrected copy of the *same* document | **Upload new version** | Same record and details; the old file stays in version history |
| A *new* credential (renewed passport, new Iqama, new visa) | **Add renewed document** | A separate record linked to the old one; both keep their own dates and history |

Renewed records stop reminders for the old record.

## Generated names {#generated-names}

When a document has a type, its name is generated from **confirmed** details: `Name Passport (2016–2026)` using the confirmed issue and expiry years. Years are never guessed (validity periods differ). Without dates the name says "(dates needed)". You can always type your own title, or switch back to the generated one.

## Stored filenames {#naming}

The administrator sets the storage path template in **Settings → Documents & folders → Stored filename template**. Placeholders: `{owner}`, `{type}`, `{title}`, `{year}`, `{month}`, `{original_name}`, `{document_id}`, `{version_id}` (required, so files never collide). The template applies to new uploads only; existing files keep their paths, and renaming a document never renames files on disk. Unsafe characters are replaced and paths cannot leave the storage folder.

## Server administrator access {#server-access}

Files are not end-to-end encrypted: anyone with root access to the server (or the backup share) can read them. Protect the server and the NAS accordingly.
