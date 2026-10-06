# OCR benchmark

This page records how the OCR preprocessing pipeline (`backend/apps/library/ocr.py`) was chosen. Every step was
measured. None was added just because it is commonly recommended.

## Method

- **Samples:** `tests/ocr_samples.py` generates 12 deterministic **synthetic** images. They are fictional ID
  cards, a resident card stating "No Expiry Date" and an insurance page, with distortions families actually
  upload:
  - phone photos on a textured table
  - security-print backgrounds
  - pictures stored sideways with an EXIF orientation tag
  - upside-down and 90°-rotated scans
  - skew
  - dim/low-contrast photos
  - glare
  - tiny crops
  - sensor noise and JPEG compression

  No real document, name or number is used.
- **Metric:** word-level F1 between the recognised text and the ground truth (words of two or more characters,
  case-insensitive). 1.00 means every word was read and nothing extra was produced.
- **Engine:** Tesseract 5.3 (`eng` + `osd`), the same binary the server uses, run locally. No cloud OCR.
- **Reproduce:** `PD_DEBUG=1 .venv/bin/python scripts/ocr_benchmark.py --markdown /tmp/ocr.md`

## Results

Each row adds one step to the row above it. The rows marked "rejected" are alternatives that were measured and
not adopted.

| Variant | clean card scan | clean text page | phone photo, patterned card, skewed 4° | phone photo stored sideways (EXIF 6) | upside-down scan | rotated 90° without EXIF | dim low-contrast photo | photo with glare | small crop (420 px) | noisy photo | skewed text page 3° | sparse one-line scan | Mean F1 | Time |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (before) | 1.00 | 1.00 | 0.60 | 0.00 | 0.00 | 0.00 | 0.94 | 0.00 | 1.00 | 0.82 | 0.99 | 1.00 | **0.61** | 10s |
| + EXIF orientation | 1.00 | 1.00 | 0.60 | 0.73 | 0.00 | 0.00 | 0.94 | 0.00 | 1.00 | 0.82 | 0.99 | 1.00 | **0.67** | 10s |
| + grayscale/contrast | 1.00 | 1.00 | 0.92 | 1.00 | 0.00 | 0.00 | 0.94 | 0.38 | 1.00 | 1.00 | 0.99 | 1.00 | **0.77** | 6s |
| + orientation (0/90/180/270) | 1.00 | 1.00 | 0.92 | 1.00 | 1.00 | 1.00 | 0.94 | 0.35 | 1.00 | 1.00 | 0.99 | 1.00 | **0.93** | 27s |
| + deskew | 1.00 | 1.00 | 0.92 | 0.96 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 0.91 | 1.00 | 1.00 | **0.96** | 30s |
| + denoise | 1.00 | 1.00 | 0.92 | 0.96 | 1.00 | 1.00 | 0.94 | 0.40 | 1.00 | 1.00 | 1.00 | 1.00 | **0.94** | 34s |
| + upscale < 2400 px (chosen) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | 0.69 | 1.00 | 1.00 | 1.00 | 1.00 | **0.97** | 41s |
| chosen + threshold (rejected) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.59 | 1.00 | 0.97 | 0.99 | 1.00 | **0.96** | 37s |
| chosen, psm 6 (rejected) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.97 | 0.94 | 0.00 | 1.00 | 0.97 | 1.00 | 1.00 | **0.91** | 40s |
| chosen, psm 11 (rejected) | 0.91 | 1.00 | 1.00 | 1.00 | 0.91 | 0.97 | 0.94 | 0.30 | 0.91 | 0.95 | 1.00 | 1.00 | **0.91** | 38s |

Timing is the wall-clock time for all 12 samples on the development container (single CPU core per Tesseract
call). The orientation check adds a fast `--psm 0` pass, plus a reduced-size four-way trial when the orientation
model is unsure.

## Findings

- **Mean F1 rose from 0.61 to 0.97.** The clean samples stayed at 1.00, so clean scans are not degraded.
- **Contrast stretching clips only the bright end.** Clipping the darkest 1 % as well erased the ink of sparse pages
  (one line of text on a full page is far below 1 % of the pixels) and produced empty or truncated text. The
  "sparse one-line scan" sample guards against this.
- **Orientation matters most.** Pictures stored sideways or upside down produced pure junk (F1 0.00) before.
  EXIF orientation fixes phone photos. Tesseract's orientation model, with a confidence-based fallback, fixes
  scans that carry no EXIF tag.
- **Grayscale plus a contrast stretch** removes most of the junk produced by coloured security backgrounds.
- **Deskew alone made photos worse** because the noise confused the projection profile. Denoise and upscaling
  recovered them. The median filter runs *after* resizing; running it before measured worse (0.95 vs 0.97).
- **Global thresholding (Otsu) was rejected.** It erases faint text on patterned or glared cards.
- **`--psm 6` (single block) was rejected.** It is marginally better on glare, but the automatic layout mode
  (`--psm 3`) is more robust on multi-column documents.
- **Glare is still the weakest case (0.70).** A strong reflection really does remove ink. Users are told to
  re-take such photos (see the OCR corrections guide).

## How the results are used

- Every processed version stores an `ocr_quality` record: engine, mean confidence, rotation applied, skew,
  steps, and the per-line confidence. The document's **Text** tab shows the confidence and greys out
  low-confidence lines (below 60).
- Field extraction (`extraction.py`) reads only the reliable lines, so junk never becomes a suggested
  value. Suggested values stay *suggestions* until a person confirms them, and confirmed values are never
  overwritten by a later OCR run.
- **Re-run OCR** lets a person force a rotation (90°, 180°, 270°) when automatic detection fails.

Automated checks: `tests/test_ocr_quality.py` (AT-93, AT-94, AT-95) asserts the improvement on the hard samples,
no regression on clean samples, the reported confidence and rotation, the column-layout and "No Expiry"
extraction, and that corrections survive re-runs.
