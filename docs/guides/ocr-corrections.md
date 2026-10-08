# OCR, details and corrections

## Selective OCR {#selective}

Text recognition (OCR) runs locally with **PaddleOCR (PP-OCRv5)** by default, or **Tesseract (Legacy)** through OCRmyPDF; see [OCR engines](ocr-engines.md). It reads **only what you choose**, so a 40-page bank statement is not recognised just because one page matters. Born-digital PDFs that already contain text are always indexed without OCR.

The administrator sets a policy for each document type in **Settings → OCR & processing → OCR policy per document type**:

| Policy | What happens |
| --- | --- |
| **Disabled** | Never recognised. The file is stored, previewed and downloadable as usual. |
| **Manual** (default for new installations) | Nothing is recognised until someone with edit rights chooses **Run OCR**. |
| **Automatic** | Only the document's **primary OCR source** (the files and pages marked as primary) is recognised after upload. |

Each type also lists its expected fields (for example passport number and expiry date), its default languages and whether the local AI may read its text. The expected fields are the template fields marked **OCR / Local AI may suggest** in the type's template: OCR and the local AI only suggest those fields for a typed document (see [document types](document-types.md#ocr-ai)). For an untyped document, OCR may also suggest a type from the recognised text; it is never applied without a person accepting it. Administrators can add **custom types** and **archive** types no longer needed. Since Change Set N types and their fields are managed in **Settings → Documents & folders → Document types**; a type that documents use is never deleted (move its documents to another type first, or archive it). See [managing types](document-types.md#manage). Documents without a type follow *Untyped documents* in the same settings section.

Installations upgraded from earlier releases keep their previous behaviour: every type is set to *Automatic* with AI allowed, so nothing changes until the administrator chooses otherwise.

### Choosing what to recognise {#sources}

Open a document, then **Text (OCR)** (or **⋮ → Text recognition (OCR)…**) and **Run OCR…**:

- **Source files** — tick one or more files of the document. A front and back side added with **⋮ → Add another side or copy…** can be recognised together as one job.
- **Pages** — for PDFs, leave empty for all pages or enter pages and ranges such as `1-2, 5`. Invalid ranges are rejected with a clear message.
- **OCR engine** and **Language profile** — PaddleOCR (PP-OCRv5) with a profile such as Arabic + English, or Tesseract (Legacy) with languages; see [OCR engines](ocr-engines.md#profiles).
- **Languages** (Tesseract only) — see below.
- **Orientation of photos** — detect automatically or force 90°, 180° or 270°.
- **Use these files as the primary OCR source** — marks the selection as the document's primary source, which is what *Automatic* processes for new versions.

Status: *Not processed*, *Queued*, *Processing*, *Needs review*, *Confirmed*, *Failed* and *OCR removed*. A queued job can be cancelled. The original files are never changed.

### Languages {#languages}

*This section is about Tesseract (Legacy). PaddleOCR uses [language profiles](ocr-engines.md#profiles).*

English, Arabic and Hindi (Devanagari) are offered by default; the administrator can offer more in **Settings → OCR & processing → OCR languages**. Choose the languages printed on the document. Combining several is slower. A language whose Tesseract pack is missing on the server is shown as *not installed* and cannot be chosen; `sudo personaldocs repair` installs the packs for every offered language and `sudo personaldocs doctor` reports any that are missing.

### Review queue {#review}

**OCR review** in the sidebar lists the documents you may edit whose recognised text waits for review or failed. Accept, correct or reject each suggested detail, or open the document. Filter the queue by **Document type** (All, Not assigned, or one type). Nobody sees documents or text they could not already open. **Mark reviewed** on a document moves it to *Confirmed*; remaining suggestions stay available.

### Removing OCR data {#remove}

**Remove OCR data…** deletes the recognised text, its positions, search entries, confidence values, every searchable PDF copy, the details that were only *suggested* from it, raw OCR excerpts and Local AI data built from it. The **original file stays unchanged**, details you confirmed are kept, and the document no longer appears in full-text search results for words that came only from OCR. You can run OCR again later. Text embedded in the PDF itself can be hidden too, and OCR can be disabled for the document; see [removing](ocr-engines.md#remove) and [disabling](ocr-engines.md#disable) OCR.

### Local AI and OCR text {#ai}

The local AI never receives every upload. It may read a document's text only when the document type allows AI (*AI may read text* in the type policy, or the *Untyped documents* setting) and AI features are enabled. Types that do not allow it are skipped by re-indexing and refused by **Analyse**. There is no external or cloud fallback.

## OCR quality and re-running OCR {#quality}

Before reading a photo or scan, the app prepares a working copy. It applies the phone's orientation tag, converts to grayscale, stretches the contrast, enlarges small images, removes speckle, turns sideways or upside-down pages upright and straightens small skews. Each step was chosen by measurement ([OCR benchmark](../OCR_BENCHMARK.md)). Only the working copy is changed.

The **Text (OCR)** tab shows the **OCR confidence**, the engine's average certainty for the words it read, and any rotation that was applied:

- **85 % or more** (green): usually reliable.
- **60–85 %** (amber): check important values.
- **Below 60 %** (red): much of the text is probably wrong.

Lines read with low confidence are **greyed out**. They stay searchable, but they are never used to suggest details.

If the text looks like junk, choose **Re-run OCR…** with other pages, languages or a forced rotation. Re-running OCR never overwrites values you have confirmed. If the new reading differs, it appears next to the confirmed value as "New scan suggests …", and you decide. When a photo has strong glare or blur, retake it in even light; no software can recover ink that is not in the picture.

## Documents without an expiry date {#no-expiry}

Some cards state **"No Expiry Date"**, for example a permanent residence card. The app suggests a **Does not expire = Yes** detail instead of inventing a date. It does not mistake a column heading such as "Badge No | Expiry Date" for that statement. Once you confirm it, the document shows a **No expiry** badge, never appears in "expiring soon" lists and is not reported as missing an expiry date. If a document has both a confirmed expiry date and "Does not expire", it is flagged for review.

## PDF/A validation {#pdfa}

Every searchable copy is checked against PDF/A-2b, the long-term archiving standard:

- If the optional **veraPDF** validator is installed (`personaldocs install --with-verapdf`, about 250 MB including Java), the copy gets a full conformance validation by the PDF Association's reference tool.
- Otherwise a built-in structural check verifies the most important requirements: PDF/A identification, colour profile, embedded fonts, no encryption and no scripts. It is not a full validation, so its badge is marked with \*.

The result appears as a **PDF/A ✓** or **PDF/A issues** badge in the document's *Versions* tab (hover for details). Administrators can re-check every copy with `personaldocs manage pdfa_check`. The original file is never changed either way.

## Suggested details {#suggestions}

The app suggests details such as name, document number, issue and expiry dates using deterministic rules. These rules include passport machine-readable zones (with check-digit validation) and card layouts where the labels sit on one line and the values on the next, e.g. "Badge No  Expiry Date" above "145070  12-31-2030". Dates are read day-first (31/12/2030) and, when that is impossible, month-first (12-31-2030). Dates that could be either way (05/06/2020) are flagged for checking. Suggestions:

- are marked **Suggested** and never rename the document or schedule reminders until confirmed;
- are flagged when something looks wrong — check-digit mismatches, ambiguous characters (O/0, I/1), impossible date order, or a name that does not match the owner. Not every error can be detected; always compare with the document.

Use **Confirm all**, confirm one value with ✓, or edit it. If nothing was recognised, add details manually with **Add a detail**. Each value shows its source (Manual, OCR, OCR (MRZ), Local AI…) and **Edited** when a person replaced a suggested value; see [provenance](document-types.md#provenance). After a type change, **Re-map existing OCR data** proposes the new type's fields from the existing text without a new scan ([re-mapping](document-types.md#remap)). Corrections are recorded in the document's history and reschedule reminders automatically.

## Copying details {#copy}

Each detail has a copy button for filling forms. Document numbers are masked on screen; copying fetches the full value and records an audit entry (without the value).

## Limits {#limits}

To protect a small server, the administrator can set in **Settings → OCR & processing**: concurrent OCR/conversion jobs (default 1 for 2 vCPU / 4 GB), a timeout per step, the maximum file size for OCR (default 50 MB), the maximum pages per OCR job, the queue size (default 50 waiting jobs), the number of attempts (default 2) and a maximum image size in megapixels (decompression-bomb protection). **Pause OCR queue** keeps queued jobs waiting until it is turned off again; nothing is lost. Files above the limits are still stored and downloadable.
