# OCR, details and corrections

## Local OCR {#ocr}

Scans and photos are read locally with Tesseract (English) through OCRmyPDF. The result is a searchable PDF/A copy next to the untouched original. Born-digital PDFs that already contain text are indexed without OCR. Turn OCR off in **Settings → OCR & processing** if needed.

Processing states: *Queued*, *Processing*, *Needs review*, *Ready*, *Failed* (retry from the document's menu) and *No preview* (stored safely, but no preview for this format).

## Suggested details {#suggestions}

The app suggests details such as name, document number, issue and expiry dates using deterministic rules, including passport machine-readable zones (with check-digit validation). Suggestions:

- are marked **Suggested** and never rename the document or schedule reminders until confirmed;
- are flagged when something looks wrong — check-digit mismatches, ambiguous characters (O/0, I/1), impossible date order, or a name that does not match the owner. Not every error can be detected; always compare with the document.

Use **Confirm all**, confirm one value with ✓, or edit it. If nothing was recognised, add details manually with **Add a detail**. Corrections are recorded in the document's history and reschedule reminders automatically.

## Copying details {#copy}

Each detail has a copy button for filling forms. Document numbers are masked on screen; copying fetches the full value and records an audit entry (without the value).

## Limits {#limits}

To protect a small server, the administrator can set: concurrent OCR/conversion jobs (default 1 for 2 vCPU / 4 GB), a timeout per step, a maximum page count for OCR, and a maximum image size in megapixels (decompression-bomb protection). Larger files are still stored and downloadable.
