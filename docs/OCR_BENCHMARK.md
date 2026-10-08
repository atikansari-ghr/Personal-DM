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

## PaddleOCR PP-OCRv5 vs Tesseract (Change Set Q) {#engines}

Measured on 2026-10-08 in the development container (x86-64 with AVX, CPU only) with
`scripts/ocr_engine_benchmark.py`. The worker starts once per run (as in production), so each time includes model
loading.

**Samples.** All samples are **synthetic**; no real document, name or number is used:

- the 12 images above;
- a 2-page scanned PDF stand-in, rendered at 300 dpi;
- for each of Arabic + English, Hindi (Devanagari) + English, Telugu + English and Tamil + English, a fictional card
  rendered with Noto fonts, both clean and as a skewed, noisy phone photo.

**Metrics.**

- Word F1 for the English samples, as above.
- Character accuracy (1 − CER) for every sample.
- Seconds per page.
- The engines' own confidences are listed but **not comparable** between engines.

**Settings.** PaddleOCR mobile models, 2 CPU threads, document orientation on, text-line orientation **off**,
unwarping off. Tesseract (Legacy) uses the preprocessing described above, with the profile's languages
(`eng`, `ara+eng`, `hin+eng`, `tel+eng`, `tam+eng`).

PaddleOCR 3.7.0 / PaddlePaddle 3.2.2 (model mobile, 2 CPU threads); Tesseract tesseract 5.3.4.

| Sample | Profile | Engine | Word F1 | Char accuracy | s/page | Engine confidence |
|---|---|---|---|---|---|---|
| clean card scan | en | Tesseract (Legacy) | 1.00 | 100.0% | 2.18 | 92 |
| clean text page | en | Tesseract (Legacy) | 1.00 | 100.0% | 1.49 | 96 |
| phone photo, patterned card, skewed 4° | en | Tesseract (Legacy) | 1.00 | 100.0% | 3.62 | 94 |
| phone photo stored sideways (EXIF 6) | en | Tesseract (Legacy) | 1.00 | 100.0% | 3.77 | 95 |
| upside-down scan | en | Tesseract (Legacy) | 1.00 | 100.0% | 2.37 | 92 |
| rotated 90° without EXIF | en | Tesseract (Legacy) | 1.00 | 97.3% | 1.18 | 96 |
| dim low-contrast photo | en | Tesseract (Legacy) | 0.94 | 96.4% | 3.83 | 94 |
| photo with glare | en | Tesseract (Legacy) | 0.69 | 51.2% | 3.38 | 88 |
| small crop (420 px) | en | Tesseract (Legacy) | 1.00 | 100.0% | 2.78 | 92 |
| noisy photo | en | Tesseract (Legacy) | 1.00 | 97.3% | 3.47 | 96 |
| skewed text page 3° | en | Tesseract (Legacy) | 1.00 | 100.0% | 1.59 | 95 |
| sparse one-line scan | en | Tesseract (Legacy) | 1.00 | 100.0% | 2.09 | 96 |
| scanned 2-page PDF (300 dpi render) | en | Tesseract (Legacy) | 1.00 | 95.9% | 1.46 | 96 |
| Arabic + English clean card | ar_en | Tesseract (Legacy) | — | 67.3% | 1.15 | 91 |
| Arabic + English phone photo, skewed 3° | ar_en | Tesseract (Legacy) | — | 85.6% | 4.43 | 89 |
| Hindi (Devanagari) + English clean card | hi_en | Tesseract (Legacy) | — | 96.8% | 0.89 | 89 |
| Hindi (Devanagari) + English phone photo, skewed 3° | hi_en | Tesseract (Legacy) | — | 81.7% | 4.42 | 77 |
| Telugu + English clean card | te_en | Tesseract (Legacy) | — | 100.0% | 0.87 | 95 |
| Telugu + English phone photo, skewed 3° | te_en | Tesseract (Legacy) | — | 100.0% | 4.27 | 96 |
| Tamil + English clean card | ta_en | Tesseract (Legacy) | — | 98.6% | 0.96 | 96 |
| Tamil + English phone photo, skewed 3° | ta_en | Tesseract (Legacy) | — | 98.6% | 4.26 | 96 |
| clean card scan | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 3.92 | 100 |
| clean text page | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 7.27 | 99 |
| phone photo, patterned card, skewed 4° | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 5.14 | 100 |
| phone photo stored sideways (EXIF 6) | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 5.92 | 99 |
| upside-down scan | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 4.07 | 99 |
| rotated 90° without EXIF | en | PaddleOCR PP-OCRv5 | 1.00 | 97.3% | 3.91 | 99 |
| dim low-contrast photo | en | PaddleOCR PP-OCRv5 | 1.00 | 97.3% | 5.09 | 99 |
| photo with glare | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 4.89 | 100 |
| small crop (420 px) | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 3.60 | 100 |
| noisy photo | en | PaddleOCR PP-OCRv5 | 0.94 | 96.4% | 5.13 | 99 |
| skewed text page 3° | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 7.03 | 99 |
| sparse one-line scan | en | PaddleOCR PP-OCRv5 | 1.00 | 100.0% | 11.91 | 100 |
| scanned 2-page PDF (300 dpi render) | en | PaddleOCR PP-OCRv5 | 1.00 | 95.9% | 4.86 | 99 |
| Arabic + English clean card | ar_en | PaddleOCR PP-OCRv5 | — | 95.2% | 5.50 | 94 |
| Arabic + English phone photo, skewed 3° | ar_en | PaddleOCR PP-OCRv5 | — | 96.2% | 7.06 | 93 |
| Hindi (Devanagari) + English clean card | hi_en | PaddleOCR PP-OCRv5 | — | 100.0% | 5.10 | 98 |
| Hindi (Devanagari) + English phone photo, skewed 3° | hi_en | PaddleOCR PP-OCRv5 | — | 100.0% | 6.99 | 98 |
| Telugu + English clean card | te_en | PaddleOCR PP-OCRv5 | — | 97.2% | 4.60 | 99 |
| Telugu + English phone photo, skewed 3° | te_en | PaddleOCR PP-OCRv5 | — | 100.0% | 6.74 | 98 |
| Tamil + English clean card | ta_en | PaddleOCR PP-OCRv5 | — | 100.0% | 4.62 | 97 |
| Tamil + English phone photo, skewed 3° | ta_en | PaddleOCR PP-OCRv5 | — | 98.6% | 7.03 | 98 |

**PaddleOCR PP-OCRv5:** mean char accuracy 98.8% over 21 samples; mean word F1 (English) 1.00; mean 5.73 s/page; peak child RSS 1880 MB (includes the Tesseract pass if that was higher).

**Tesseract (Legacy):** mean char accuracy 93.7% over 21 samples; mean word F1 (English) 0.97; mean 2.59 s/page; peak child RSS 509 MB.

**Why text-line orientation is off by default.** The first run used text-line orientation **on**. PP-OCRv5 then
read the Hindi + English card at **20.4 %** (clean) and **19.4 %** (photo) character accuracy, because the
text-line orientation model classified every line as upside down. Its mean over all 21 samples was 91.1 %. With it
off, the same cards read at 100 %, and no other sample got worse. The default was changed to off
(`processing.paddle_textline`), and `test_live_at216_hindi_english_profile_reads_upright` guards it.

**Reading the results.**

- On these samples PP-OCRv5 is clearly better on glare (100 % vs 51 %) and on Arabic (95–96 % vs 67–86 %), and
  better on the Hindi photo (100 % vs 82 %).
- Both engines read clean English, Telugu and Tamil cards almost perfectly.
- PP-OCRv5 is about **2.2× slower** per page on CPU (5.7 s vs 2.6 s on average, including model loading) and needs
  more memory: the largest OCR child process reached **1.9 GB** (Tesseract 0.5 GB). Hence one OCR job at a time and
  the 3000 MB per-job limit.

**Not Run (no sanitised real samples available).** Real passports and their MRZ, real iqamas and resident cards,
national ID cards, certificates, real phone photos (motion blur, perspective, curved pages, low light), real
multi-page scanned PDFs, and real handwriting. These categories must be measured with sanitised samples before
claiming accuracy on real family documents. Use **Settings → OCR & processing → Test OCR / Compare engines** with
sanitised copies; the file is never added to the library.

Reproduce:
`PD_PADDLE_PYTHON=/opt/personaldocs/paddle-venv/bin/python PD_PADDLE_HOME=/var/lib/personaldocs/paddle PD_DEBUG=1 .venv/bin/python scripts/ocr_engine_benchmark.py --markdown /tmp/engines.md`
