# ADR 0010: Portal menus, folder-drop uploads, measured OCR and a one-line installer

Status: accepted (2026-10-05, change set J)

## Context

- Row and folder menus were absolutely positioned inside scrolling panels and got clipped.
- Families drag whole folders from Windows Explorer or Finder and expect the same structure in the app.
- OCR of phone photos produced junk: sideways and upside-down pictures and card layouts with labels above values.
- The public repository needs a single, memorable install command.

## Decisions

1. **One menu component rendered in a portal** (`components/Menu.tsx`). It is positioned from the trigger's
   bounding box and clamped to the viewport, opening upwards or leftwards when needed. Only one menu is open at a
   time (module-level close callback). The browser's own `<dialog>`/popover APIs were not used because the
   behaviour has to stay identical in every supported browser.
2. **Folder drops reuse the upload endpoint** with a parallel `paths` list (and `dirs` for empty folders) instead of
   the import pipeline. Paths go through the same `normalize_rel` validation as imports. Folders are created only
   with organise rights, and every refused file is reported. Uploads go in batches (20 files / 64 MB) so one
   failure never loses the rest.
3. **OCR preprocessing only where measured.** A synthetic benchmark (`scripts/ocr_benchmark.py`) decided the steps.
   Thresholding and `--psm 6/11` were rejected because they hurt patterned or glared cards. Field extraction
   reads only lines above the confidence threshold. "No Expiry Date" becomes a boolean, never an invented date.
   Confirmed values always win over a new reading. Pillow only: no new native dependency except the
   `tesseract-ocr-osd` data package.
4. **Sub-folder icons default to 📁.** Name-based suggestions apply only directly inside a person's or the family
   area. Icons come from an approved list (no free-form emoji), so the stored value is predictable.
5. **`personal-DM.sh` delegates.** The root script only checks the platform, obtains the source (token via the
   existing credential-helper pattern, never in a URL) and calls the already-tested `easy-install.sh` and
   `personaldocs` commands. There is no second installer to maintain.

## Consequences

- A synthetic DataTransfer cannot carry folder entries, so browser tests cover file drops. The folder walk is
  unit-tested with fake entries, and the server hierarchy logic with API tests. Real OS drags remain a manual check.
- The raw-URL one-liner works only while the repository is public; private installations use a checkout.
