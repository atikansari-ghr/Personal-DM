# ADR 0024: Processing Source for Local AI, personal Overview groups, archived Document Type fields

Status: accepted (2026-10-25, change set AA. The change prompt numbered its tests AT-436…AT-455 and called itself
"Change Set X"; both were taken, so the tests are AT-461…AT-480, where prompt AT-n = AT-(n+25).)

## Context

- AI Actions always read OCR text (or, for Cloud profiles, an original after confirmation). Families running a capable
  Local vision model want it to read the scan itself — OCR on phone photos is the weakest step — while keeping OCR as
  a safety net and never sending originals to the cloud.
- The Overview had a fixed four-column width scale, no height and no grouping.
- Document Type fields could only be switched off ("Shown"), not archived, restored or deleted, and were reordered
  with ↑/↓ buttons.

## Decision

1. **Processing Source** per AI Action: OCR Text, Original Document — Local AI, Original Document — Local AI + OCR
   Fallback (default). One resolver (`apps/ai/direct.py`) decides it: Local profiles only; an explicit original mode
   with a Cloud profile is refused before anything is sent; the default with a Cloud profile reads OCR text.
2. **Images, rendered locally.** Local servers accept images, so PDFs and TIFFs are rendered/converted to PNG pages on
   the server (sandboxed pdftoppm, Pillow), bounded in pages, bytes and pixels, in a private temporary directory that
   is always removed. The format is detected from the content.
3. **Fallback by outcome, not confidence.** Not eligible, provider error, time-out, conversion failure, malformed or
   unusable answer → the Main Admin's OCR engine order → the same Local AI on OCR text. The original-only mode never
   reaches OCR. Every step is recorded on the AIJob (selected/final source, fallback and reason, file type, pages,
   OCR engine and order) and audited.
4. **Schema-aware, evidence-based.** The active Document Type fields (stable keys, archived ones excluded) are the
   schema; for originals each value needs its printed words and page; values without evidence are not proposed.
5. **Overview layout** stays in per-user settings (server-side): a 12-column grid with `cols` and `h` per tile,
   groups with a protected General group, and a server-side guarantee that tiles of a removed group move to General.
6. **Archive is the standard field removal** (it is what "Shown off" already did, now explicit and reversible);
   permanent deletion is Main Admin only, for archived fields, with count, typed confirmation and step-up.

## Consequences

- With no vision-capable Local profile, the default behaves like before (OCR text), and says why in AI History.
- A Local model that reads one image per request only gets the first page; Test Profile records that.
- Existing layouts keep working (General group with the saved order); older clients still read `w`.
- Permanent field deletion changes the live application only; backups keep what they contained.
