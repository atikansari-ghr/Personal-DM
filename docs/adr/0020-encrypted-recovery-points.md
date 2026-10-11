# ADR 0020: Encrypted recovery points, chains and the Recovery Key hierarchy

Status: accepted (2026-10-11, change set T).

## Context

Before this change, a backup was a plain folder: a database dump, the document store and settings, written to one share
on a schedule. It had several gaps:

- It was not encrypted. Anyone with the share could read every document.
- Every run was a full copy, with only one destination.
- Nothing proved the copy could actually be restored.
- A lost server needed a manual rebuild before anything could be restored.

The change prompt asks for:

- encrypted full-system backups with incrementals and several destinations;
- deep verification;
- granular and full disaster recovery onto a clean server;
- key rotation and an offline emergency copy of the key.

## Decision

1. **Key hierarchy.**
   - The **Backup Recovery Key** is 32 random bytes, shown as `PDRK1-XXXX-…` (base32 in groups of four). It is stored on
     the installation only encrypted with the installation key, and is shown only after main-administrator step-up
     authentication.
   - KEK = HKDF-SHA256(Recovery Key, `personaldocs-backup-kek-v1`).
   - Each **recovery point** gets its own random DEK, wrapped with AES-256-GCM under the KEK. The point id is the
     associated data, so a wrapped key cannot be moved to another point.
   - Each file gets its own key: HKDF(DEK, `pdbk-file:<name>`).
2. **File format.**
   - Files use the STREAM construction over AES-256-GCM, in 1 MiB chunks.
   - The nonce is a 7-byte random prefix, a 4-byte counter and a last-chunk flag. A required empty final chunk detects
     truncation.
   - The magic is `PDBK2\n`.
   - There is **no compression**: documents are mostly already-compressed PDFs and images, and compressing before
     encrypting adds a length side channel. `pg_dump` runs with `--compress=0` and is streamed straight into
     encryption.
3. **Package layout:** `<destination>/<point id>/g<key generation>/` contains:
   - `header.json`, which is plain and holds no secrets: the wrapped DEK, the version and the file list;
   - `manifest.enc`, `database.enc`, `catalog.enc`, `settings.enc` and `secrets.enc`;
   - `objects/`, `derived/`, `photos/` and `branding/`.
4. **Chains.** A Full point stores everything. An incremental point stores only objects that are new since its parent,
   and references the rest through its chain (`RecoveryPoint.stored`). Retention deletes whole chains only. A Full point
   is never deleted while a kept incremental needs it.
5. **Staging and replication.**
   - A point is built once in `DATA_DIR/backup-staging`, then copied to each destination through a small provider
     interface (local, NAS, S3 with SigV4, Google Drive, OneDrive).
   - Each copy has its own state. Failures are retried for 24 hours.
   - A PostgreSQL advisory lock allows only one backup or rotation at a time.
6. **Verification is deep.** Every copy is re-read from its destination:
   - checksums;
   - authenticated decryption of every chunk;
   - manifest and chain completeness;
   - `pg_restore --list` of the dump.

   Health is derived from verified copies, never from "the scheduler ran".
7. **Rotation** creates a new key generation and re-encrypts every reachable copy. Any good copy is a valid source. A
   generation is retired, and its key material erased, only when no retained copy references it.
8. **Emergency Recovery Package** (`.pdrp`): the Recovery Key sealed with scrypt (N=2^15) and AES-GCM under a
   passphrase of at least 12 characters, plus printed instructions. Readiness records only that one was exported, and
   for which generation; it never records where the package is kept.
9. **Disaster recovery** (`manage.py recover`, `personaldocs recover`, installer option 2) is resumable:
   - The state is kept in a marker file, with the DEKs stripped.
   - A wrong key or an incompatible version stops the recovery before anything changes.
   - Compromise mode ends sessions and untrusts devices but keeps MFA.
   - Restored integrations stay on hold until verified.

## Consequences

- Losing both the Recovery Key and the Emergency Recovery Package makes every backup unreadable. This is deliberate, and
  the UI, the guide and the package say so.
- Backups are not immutable or "ransomware-proof". An attacker with destination credentials can delete copies. The
  guides recommend at least one offline or separately credentialed destination.
- Backups made by earlier releases are still listed, verified and restorable through the legacy code path.
