# Office files, DICOM and other formats

## Supported formats {#formats}

| Format | What happens |
|---|---|
| PDF | Preview, text extraction, OCR when needed, thumbnail, searchable PDF/A copy |
| Images (JPEG, PNG, TIFF, WebP, GIF, BMP) | Preview, OCR, thumbnail |
| Plain text | Safe text preview and search |
| Word, Excel, PowerPoint, OpenDocument, RTF, CSV | Local PDF preview made with LibreOffice; original kept for download. Edit outside the app and upload a new version |
| DICOM and study folders | Stored intact for download and use in your own viewer. No medical viewer or interpretation is provided |
| Anything else | Stored safely for download; no preview |

Uploaded programs, scripts and macros are never executed. Conversion runs with time and memory limits and without macros.

The administrator can block extensions entirely under **Documents & folders → Blocked extensions**.

## DICOM studies {#dicom}

Keep a study's folder structure together (import the whole folder). To give it to a doctor or viewer, open the folder and choose **Download folder (ZIP)**: the ZIP keeps the paths and includes SHA-256 checksums.
