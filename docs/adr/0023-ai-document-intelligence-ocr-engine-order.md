# ADR 0023: Optional AI Document Intelligence above a configurable OCR engine order

Status: accepted (2026-10-17, change set Z. The change prompt numbered its tests AT-416…AT-435; those numbers were
already used, so they are AT-441…AT-460, where prompt AT-n = AT-(n+25).)

## Context

- OCR had one default engine (PaddleOCR) with an on/off Tesseract fallback. A third, much lighter engine became
  available ([light-ocr](https://github.com/arcships/light-ocr): PP-OCRv6 Small on ONNX Runtime, a Node.js package),
  and administrators need to choose the order themselves.
- AI could only suggest metadata after OCR (OCR assist / smart organisation) and answer questions, always with the
  default profile, and only with Local or explicitly acknowledged external servers. Families asked for cloud models,
  per-document actions, and a clear record of what was sent where.
- AI must stay optional, must never become an OCR engine, and must not weaken privacy, permissions or integrity.

## Decision

1. **Two independent priorities.** The OCR engine order (`processing.ocr_engine_order`, a new ordered setting type,
   and `processing.ocr_mode`) decides which engine recognises a document. AI profiles decide which model interprets
   the text. Neither setting can change the other, and AI cannot change either.
2. **Fallback at selection time.** In Auto mode, engines that cannot run (not installed, failed self-test, missing
   model, language profile not supported) are skipped with a recorded reason. An engine that crashes on a document
   fails the run safely and keeps the previous result (AT-214/AT-224), instead of silently trying the next engine.
3. **light-ocr as a pinned subprocess.** `backend/light-ocr/package-lock.json` pins 0.5.9; the installer runs
   `npm ci --ignore-scripts` into `/opt/personaldocs/light-ocr`; each page is one sandboxed `node cli.cjs --format
   json` process (memory/CPU limits, private temp dir, no inherited secrets). Health is a real recognition.
4. **Four provenance layers.** Original document, original OCR, AI interpretation (`AISuggestion`, new `AIOutput`)
   and confirmed metadata are separate tables/fields. AI output is never applied without a person.
5. **AI modes.** `ai.mode` (on demand by default, OCR only, OCR + AI, Smart Auto). Migration maps the old automatic
   switch; nothing existing is queued.
6. **Local / Cloud with one policy function.** Every profile is Local or Cloud. `service.plan_payload` is the single
   place that decides which data categories (OCR text, metadata, image, file) an action sends, enforces capabilities,
   and requires a confirmation (`ConsentRequired` → 409 with the disclosure) before an original goes to a Cloud
   profile. `providers.guard_payload` repeats the image/file check below it. Automatic AI never uses Cloud unless
   allowed.
7. **Untrusted documents.** Every request is system policy + task + the document inside a per-request random marker.
   The model has no tools; its output is parsed, validated and stored only as suggestions or labelled outputs.
   Dates, numbers and names are only proposed when they appear in the OCR text.
8. **Provenance in the job row.** `AIJob` keeps trigger, profile name (snapshot), provider, Local/Cloud, data
   categories sent and usage — never content or keys — and is kept when outputs are deleted.

## Consequences

- Upgraded installations behave as before; light-ocr must be added to the order by the administrator.
- Cloud providers are tested against a local emulation (`tests/fake_ai_server.py`); real accounts are part of the
  release checklist, not the automated suite.
- Rolling back `ai` to 0002 removes AI outputs and provenance fields; documents, OCR and suggestions stay.
