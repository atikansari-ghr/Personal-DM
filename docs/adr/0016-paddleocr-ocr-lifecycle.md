# ADR 0016: PaddleOCR (PP-OCRv5) as the preferred engine and a complete OCR lifecycle

Status: accepted (2026-10-08, change set Q. The change prompt called it "Change Set P" with AT-191…AT-210; those
numbers were already used, so it was renumbered to AT-211…AT-230, where prompt AT-n = AT-(n+20).)

## Context

- **Tesseract struggled with real family uploads.** Phone photos, skewed or curved pages, security-print
  backgrounds, and mixed Arabic/Devanagari/Telugu/Tamil + English documents all read poorly. PP-OCRv5 models are
  much stronger on those inputs, and they run on CPU.
- **Removed OCR text came back.** The pipeline map of Change Set Q found nine causes:
  1. *Remove* fell back to the PDF's embedded text layer (from a scanner or earlier OCR), so the text stayed
     searchable.
  2. The *Remove* button was hidden when no version was marked `ocr_applied`.
  3. *Regenerate preview* (`/reprocess` → `process_version`) and the integrity repair re-ran automatic OCR.
     Migration 0007 had made every type *Automatic* on upgraded installs.
  4. Queued or running Local AI jobs recreated suggestions and semantic chunks after removal.
  5. Confirmed details kept raw OCR snippets in `source_excerpt`.
  6. A page-range re-run left the previous full `searchable.pdf`, which the preview and share links still served.
  7. Stale searchable copies inside known version directories were never detected.
  8. Policy switches never deleted data, and nothing said so.
  9. `set_current_version` rebuilt the search text without `document_text()`, and removal left `ocr_sources` and
     `ocr_languages` set.
- **The administrator could not see existing OCR data**: which engine produced it, how much storage it uses,
  orphans, or how to act on many documents at once.

## Decision

1. **Engine abstraction** (`apps/library/ocr_engines.py`):
   - PaddleOCR is the default (`processing.ocr_engine`). Tesseract is kept as *Legacy / Fallback*, with optional
     fallback when PaddleOCR is unavailable and the run did not request an engine explicitly.
   - Every result stores `ocr_engine`, `ocr_model`, `ocr_profile`, `ocr_at`, and (for PaddleOCR) `ocr_blocks` with
     line boxes and scores.
   - Upgrades label history as `tesseract` or `unknown` and never relabel it. Changing the engine never triggers
     library-wide OCR.
2. **Isolated runtime.** PaddlePaddle 3.2.2, PaddleOCR 3.7.0 and PaddleX 3.7.2 live in `/opt/personaldocs/paddle-venv`,
   pinned in `backend/requirements-paddle.txt`. 3.3.x crashes in oneDNN on CPU, and PaddleOCR 3.2 lacks the ar/hi/te/ta
   PP-OCRv5 models.
   - `apps/library/paddle_worker.py` runs there through the existing sandbox: RLIMIT_AS = `paddle_memory_mb`, a CPU
     limit and a timeout, no inherited secrets, and one heavy job at a time.
   - It never imports Django and never downloads models at OCR time. Models are installed by the installer into
     `/var/lib/personaldocs/paddle`.
   - The worker systemd unit is capped at `MemoryMax=4000M` with `CPUWeight=50`.
3. **Health means real inference.** The self-test recognises a generated image. Installed packages or a successful
   import alone never count as *Healthy*. Doctor, `personaldocs ocr status` and the Settings card all use it.
4. **Language profiles** (English, Arabic+English, Hindi+English, Telugu+English, Tamil+English):
   - Each profile maps to PP-OCRv5 recognition models whose lines are merged (IoU de-duplication, highest score).
   - It also maps to the equivalent Tesseract language set.
5. **Staged runs.** Every source is recognised into a private work directory first. The result is applied in one
   transaction only if every source succeeded and the document's **OCR epoch** is unchanged.
   - A failure leaves the previous result, the search index and the searchable copy untouched.
   - Engine crashes, timeouts and memory-limit stops fail once (no triple retry of a heavy job).
   - Every run is recorded in `OcrRun`: metadata only, never text.
6. **Exact removal.** *Remove OCR data* deletes all OCR-derived data:
   - the text and blocks;
   - all searchable copies;
   - proposals and OCR excerpts;
   - pending AI suggestions, queued AI jobs and semantic chunks;
   - the search entries.

   Removal also bumps the epoch, so running OCR or AI jobs discard their results. Optionally the embedded text layer
   is hidden too (`ignore_embedded_text`). Originals, versions, manual and confirmed details, and audit history stay.
   The audit records counts, never text.
7. **Per-document Disable** (`ocr_override = "disabled"`) beats the type policy, *Regenerate preview*, repairs and bulk
   re-processing. `process_version` jobs from reprocess/integrity carry `auto_ocr: False`.
8. **Administration** (main administrator only, enforced server-side):
   - Existing OCR data: inventory, filters, storage, and bulk actions with a mandatory preview, run in throttled
     background batches.
   - Orphan analysis as a dry run, then a confirmed clean.
   - Storage Health categories.
   - Test OCR / Compare engines on a sanitised file in a temporary directory that is always deleted.

## Consequences

- About 1.3 GB of disk for the runtime and 60–160 MB of models. Up to about 1.9 GB RAM per OCR job (measured peak); it fits a 6 GB / 4 vCPU
  server with the defaults.
- PaddleOCR needs a CPU with AVX. Without it (or with `--without-paddleocr`) the app keeps working with Tesseract.
- Re-processing older results is a deliberate administrator action (bulk *Re-process with PP-OCRv5*), never automatic.
- CI cannot install the 1.3 GB runtime, so it exercises the worker protocol with `tests/fake_paddle_worker.py`. The
  `test_live_*` tests run the real PP-OCRv5 models when `PD_TEST_PADDLE_PYTHON` is set, and are reported as skipped
  otherwise.
