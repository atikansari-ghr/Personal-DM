# OCR, details and corrections

## Local OCR {#ocr}

Scans and photos are read locally with Tesseract (English) through OCRmyPDF. The result is a searchable PDF/A copy next to the untouched original. Born-digital PDFs that already contain text are indexed without OCR. Turn OCR off in **Settings → OCR & processing** if needed.

Before reading a photo or scan, the app prepares a working copy. It applies the phone's orientation tag, converts to grayscale, stretches the contrast, enlarges small images, removes speckle, turns sideways or upside-down pages upright and straightens small skews. Each step was chosen by measurement ([OCR benchmark](../OCR_BENCHMARK.md)). Only the working copy is changed; your original file is never modified.

Processing states: *Queued*, *Processing*, *Needs review*, *Ready*, *Failed* (retry from the document's menu) and *No preview* (stored safely, but no preview for this format).

## OCR quality and re-running OCR {#quality}

The document's **Text** tab shows the **OCR confidence**, the engine's average certainty for the words it read, and any rotation that was applied:

- **85 % or more** (green): usually reliable.
- **60–85 %** (amber): check important values.
- **Below 60 %** (red): much of the text is probably wrong.

Lines read with low confidence are **greyed out**. They stay searchable, but they are never used to suggest details, so junk characters do not end up in your document's metadata.

If the text looks like junk, open **⋮ → Re-run OCR…**. For photos and image scans you can let the app detect the orientation again or force a rotation (90°, 180° or 270°). Re-running OCR never overwrites values you have confirmed. If the new reading differs, it appears next to the confirmed value as "New scan suggests …", and you decide. When a photo has strong glare or blur, retake it in even light; no software can recover ink that is not in the picture.

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

Use **Confirm all**, confirm one value with ✓, or edit it. If nothing was recognised, add details manually with **Add a detail**. Corrections are recorded in the document's history and reschedule reminders automatically.

## Copying details {#copy}

Each detail has a copy button for filling forms. Document numbers are masked on screen; copying fetches the full value and records an audit entry (without the value).

## Limits {#limits}

To protect a small server, the administrator can set: concurrent OCR/conversion jobs (default 1 for 2 vCPU / 4 GB), a timeout per step, a maximum page count for OCR, and a maximum image size in megapixels (decompression-bomb protection). Larger files are still stored and downloadable.
