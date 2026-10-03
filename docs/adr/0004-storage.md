# ADR-0004: Immutable originals on the filesystem with versioned managed paths

- Status: accepted

## Decision
Uploads stream to a staging file while hashing (SHA-256), then are atomically moved (`os.replace`) into `originals/<template path>` where the template must contain `{version_id}`; files are set 0440. Paths are sanitised per component and verified to stay within the storage root. Stored paths are never changed after upload (renames/metadata edits do not move files). Derivatives live in `derivatives/<vid[:2]>/<vid>/`.

## Consequences
Collisions are impossible; identical deliberate uploads remain independent. Backups can hard-link unchanged originals. Files are readable by the server administrator (not end-to-end encrypted) — documented.
