"""Change Set Y — OCR → AI document analysis pipeline (AT-426..AT-440; the prompt numbered them AT-401..AT-415).

The fake AI server (tests/fake_ai_server.py) records every request, so these tests prove what was (not) sent: only
recognised text reaches the text model, never an image; the AI server is not called without usable text; HTTP errors
are classified and sanitized; the optional structured-output feature gets exactly one fallback; transient errors retry
a bounded number of times; and every job ends in a truthful state with its failing stage."""
import json
import logging
import shutil
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai import jobs as ai_jobs
from apps.ai import service
from apps.ai.models import AIJob, AIProfile, AISuggestion
from apps.ai.providers import AIError, parse_json_object, sanitize_server_message
from apps.core import config
from apps.core.models import Job
from apps.library.models import Document, DocumentField, DocumentVersion
from conftest import make_text_pdf, personal_root, run_jobs, upload
from test_ai import enable_ai, fake_ai, make_doc, profile  # noqa: F401 - fixtures
from test_ocr_engines_lifecycle import _png, _upload, paddle  # noqa: F401 - fixture

pytestmark = pytest.mark.django_db
HAS_TESSERACT = shutil.which("tesseract") is not None
SECRET = "QUOKKAPASSPORT"  # a marker that appears only in a document's text


def _setup(engine="tesseract"):
    enable_ai(**{"ai.auto_analyze": False})
    config.set_value("processing.ocr_engine_order", [engine] if engine == "tesseract" else [engine, "tesseract"])
    config.set_value("processing.ocr_untyped_ai_allowed", True)
    config.set_value("processing.ocr_untyped_mode", "manual")


def _analyze(client, doc):
    r = client.post(f"/api/documents/{doc.id}/ai/analyze", {}, format="json")
    assert r.status_code == 202, r.content
    return AIJob.objects.get(pk=r.json()["job"])


def _image_doc(client, family, lines, name="scan.png"):
    return _upload(client, personal_root(family["dad"]), name, _png(lines))


def _no_images(fake) -> bool:
    body = json.dumps(fake.chats())
    return "image_url" not in body and '"images"' not in body and "base64" not in body


def _due_now():
    Job.objects.filter(kind="ai_task", status=Job.QUEUED).update(run_after=timezone.now())


# ------------------------------------------------------------------ AT-426 / AT-427 / AT-428 OCR engine → text model

@pytest.mark.tools
@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
def test_at426_tesseract_ocr_feeds_text_model(family, clients, fake_ai, profile):
    _setup("tesseract")
    c = clients["dad"]
    doc = _image_doc(c, family, ["SAMPLE RESIDENCE PERMIT", "VALID UNTIL 2031-05-20"])
    run_jobs()
    assert not fake_ai.analysis_chats()
    job = _analyze(c, doc)
    run_jobs()  # analysis -> OCR queued -> OCR (Tesseract) -> analysis resumes -> AI
    job.refresh_from_db()
    assert job.status == AIJob.DONE and job.stage == "done", (job.status, job.stage, job.error)
    assert job.detail["ocr_requested"] and job.detail["ocr_engine"] == "tesseract" and job.detail["ocr_chars"] > 10
    v = DocumentVersion.objects.get(pk=doc.current_version_id)
    assert v.ocr_engine == "tesseract" and "RESIDENCE" in v.text.upper()
    sent = fake_ai.analysis_chats()
    assert len(sent) == 1 and sent[0]["model"] == "text-model"  # the TEXT model, not embedding/vision
    assert "RESIDENCE" in json.dumps(sent).upper() and _no_images(fake_ai)
    assert AISuggestion.objects.filter(document=doc).exists()


def test_at427_paddleocr_feeds_the_same_ai_layer(family, clients, fake_ai, profile, paddle):
    _setup("paddleocr")
    c = clients["dad"]
    doc = _image_doc(c, family, ["SAMPLE DRIVING LICENCE", "EXPIRY 2030-01-31"])
    run_jobs()
    job = _analyze(c, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.DONE, (job.stage, job.error)
    assert job.detail["ocr_engine"] == "paddleocr" and job.detail["ocr_chars"] > 10
    sent = fake_ai.analysis_chats()
    assert len(sent) == 1 and sent[0]["model"] == "text-model" and _no_images(fake_ai)
    assert "LICENCE" in json.dumps(sent).upper()


@pytest.mark.tools
@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
def test_at428_switching_ocr_engines_needs_no_ai_profile_change(family, clients, fake_ai, profile, paddle):
    c = clients["dad"]
    before = AIProfile.objects.get(pk=profile.pk).updated_at
    for engine, words in (("paddleocr", "SAMPLE INSURANCE CARD"), ("tesseract", "SAMPLE BIRTH CERTIFICATE"), ("paddleocr", "SAMPLE TAX NOTICE")):
        _setup(engine)
        doc = _image_doc(c, family, [words, "ISSUED 2024-02-01"], name=f"{engine}-{len(words)}.png")
        run_jobs()
        job = _analyze(c, doc)
        run_jobs()
        job.refresh_from_db()
        assert job.status == AIJob.DONE and job.detail["ocr_engine"] == engine, (engine, job.error)
    assert AIProfile.objects.get(pk=profile.pk).updated_at == before  # the AI profile was never touched
    assert len(fake_ai.analysis_chats()) == 3 and _no_images(fake_ai)


# ------------------------------------------------------------------ AT-429 OCR reuse

def test_at429_existing_text_is_reused_and_new_versions_invalidate(family, clients, fake_ai, profile):
    _setup()
    c = clients["son1"]
    doc = make_doc(c, family["son1"], "Utility bill SAMPLE ENERGY account 4711")
    run_jobs()
    job = _analyze(c, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.DONE and job.detail["ocr_reused"] and not job.detail.get("ocr_requested")
    assert not Job.objects.filter(kind="ocr_run").exists()  # no unnecessary OCR run
    # a new file version: its text is analysed, not the old one
    r = c.post(f"/api/documents/{doc.id}/versions", {"file": _pdf_file("Utility bill SAMPLE ENERGY NEWVERSIONMARK")}, format="multipart")
    assert r.status_code in (200, 201), r.content
    run_jobs()
    _analyze(c, Document.objects.get(pk=doc.pk))
    run_jobs()
    assert "NEWVERSIONMARK" in json.dumps(fake_ai.analysis_chats()[-1])


def _pdf_file(text):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("v2.pdf", make_text_pdf(text), content_type="application/pdf")


# ------------------------------------------------------------------ AT-430 / AT-431 empty OCR and OCR failures

@pytest.mark.tools
@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
def test_at430_empty_ocr_never_calls_ai(family, clients, fake_ai, profile):
    _setup("tesseract")
    c = clients["dad"]
    doc = _image_doc(c, family, [], name="blank.png")  # a blank page: OCR succeeds but finds nothing
    run_jobs()
    job = _analyze(c, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.FAILED and job.error_category == "ocr_empty" and job.stage == "validating_ocr"
    assert job.error == service.EMPTY_OCR and job.detail["ocr_engine"] and job.detail["ocr_chars"] < service.MIN_USABLE_CHARS
    assert not fake_ai.analysis_chats()  # the AI server was not called
    row = clients["dad"].get("/api/ai/jobs").json()["jobs"][0]
    assert row["stage_label"] == "Checking OCR text" and "AI" not in row["error"]


def test_at431_ocr_engine_failures_fail_at_the_ocr_stage(family, clients, fake_ai, profile, paddle, monkeypatch):
    from apps.library import ocr_engines, ocr_runs

    _setup("paddleocr")
    config.set_value("processing.ocr_max_attempts", 1)
    c = clients["dad"]

    def broken_paddle(*a, **k):
        raise ocr_engines.EngineError("PaddleOCR worker stopped (synthetic failure)")

    monkeypatch.setattr(ocr_runs, "_run_paddle", broken_paddle)
    doc = _image_doc(c, family, ["SAMPLE CARD"], name="p.png")
    run_jobs()
    job = _analyze(c, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.FAILED and job.error_category == "ocr_failed" and "PaddleOCR worker stopped" in job.error

    _setup("tesseract")

    def broken_tesseract(*a, **k):
        raise RuntimeError("tesseract crashed (synthetic failure)")

    monkeypatch.setattr(ocr_runs, "_run_tesseract", broken_tesseract)
    doc2 = _image_doc(c, family, ["SAMPLE CARD TWO"], name="t.png")
    run_jobs()
    job2 = _analyze(c, doc2)
    run_jobs()
    job2.refresh_from_db()
    assert job2.status == AIJob.FAILED and job2.error_category == "ocr_failed" and "tesseract crashed" in job2.error
    assert not fake_ai.analysis_chats()  # no AI request after an OCR failure


def test_ocr_disabled_document_fails_without_ai(family, clients, fake_ai, profile):
    _setup()
    c = clients["dad"]
    doc = _image_doc(c, family, ["SAMPLE"], name="d.png")
    run_jobs()
    Document.objects.filter(pk=doc.pk).update(ocr_override="disabled")
    job = _analyze(c, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.FAILED and job.error_category == "ocr_unavailable" and not fake_ai.analysis_chats()


def test_automatic_analysis_never_starts_ocr_on_manual_types(family, clients, fake_ai, profile):
    _setup()
    config.set_value("ai.mode", "auto")
    doc = _image_doc(clients["dad"], family, ["SAMPLE"], name="auto.png")
    run_jobs()
    assert not AIJob.objects.filter(document=doc, kind=AIJob.ANALYZE).exists()  # no text: nothing automatic queued
    job = ai_jobs.queue(AIJob.ANALYZE, document=doc, user=family["dad"])  # an automatic job (not asked for by a person)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.SKIPPED and "no recognised text" in job.error
    assert not Job.objects.filter(kind="ocr_run").exists() and not fake_ai.analysis_chats()


# ------------------------------------------------------------------ AT-432 LM Studio

def test_at432_lm_studio_profile_test_analysis_and_document(family, clients, fake_ai, profile):
    _setup()
    fake_ai.lmstudio = True  # rejects response_format json_object exactly like LM Studio (the reported HTTP 400)
    fake_ai.analyze_reply = {**fake_ai.analyze_reply, "issue_date": "2024-01-15", "expiry_date": "2029-01-14"}
    dad = clients["dad"]
    r = dad.post(f"/api/ai/profiles/{profile.id}/test-analysis")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["ok"] and body["structured_output"] == "schema" and not body["fallback"]
    assert set(body["dates_correct"]) == {"issue_date", "expiry_date"}
    sent = fake_ai.analysis_chats()[-1]
    assert sent["model"] == "text-model" and sent["response_format"]["type"] == "json_schema"
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE passport text for LM Studio")
    run_jobs()
    job = _analyze(dad, doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.DONE, job.error
    assert all(b.get("response_format", {}).get("type") != "json_object" for b in fake_ai.chats())
    t = dad.post(f"/api/ai/profiles/{profile.id}/test").json()
    assert t["ok"] and any(s["step"] == "Text model" and s["ok"] for s in t["steps"])


def test_reasoning_blocks_are_ignored(family, clients, fake_ai, profile):
    _setup()
    fake_ai.think = True
    fake_ai.reject_schema = True  # prompt-only path, where a <think> block reaches us
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE reasoning model document")
    run_jobs()
    job = _analyze(clients["dad"], doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.DONE, job.error
    assert parse_json_object('<think>{"a": 1} maybe</think>\n{"title": "X"}') == {"title": "X"}


# ------------------------------------------------------------------ AT-433 HTTP 400 diagnostics

def test_at433_http_400_is_diagnosed_sanitized_and_not_requeued(family, clients, fake_ai, profile, caplog):
    _setup()
    fake_ai.echo_400 = True
    caplog.set_level(logging.DEBUG)
    doc = make_doc(clients["son1"], family["son1"], f"Passport {SECRET} holder SAMPLE PERSON number 778899")
    run_jobs()
    job = _analyze(clients["dad"], doc)
    run_jobs()
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.FAILED and job.error_category == "bad_request" and job.stage == "ai_running"
    assert "HTTP 400" in job.error and "Invalid request near" in job.error
    assert SECRET not in job.error and SECRET not in json.dumps(job.detail) and "SECRETKEY" not in job.error
    assert job.detail["http_status"] == 400
    assert len(fake_ai.analysis_chats()) == 1  # deterministic: no retry, no fallback, no requeue
    assert not AIJob.objects.filter(status=AIJob.QUEUED).exists()
    assert SECRET not in caplog.text
    row = clients["dad"].get("/api/ai/jobs").json()["jobs"][0]
    assert row["status"] == "failed" and row["detail"]["http_status"] == 400 and SECRET not in json.dumps(row)
    # pressing Analyze again while nothing runs creates one new job, never a pile of queued ones
    _analyze(clients["dad"], doc)
    _analyze(clients["dad"], doc)
    assert AIJob.objects.filter(document=doc, status=AIJob.QUEUED).count() == 1


def test_sanitizer_removes_keys_and_echoed_text():
    sent = "OCR TEXT: Holder SAMPLE PERSON passport number 778899 issued in Sampletown"
    raw = json.dumps({"error": {"message": "bad token near 'Holder SAMPLE PERSON passport number 778899' Bearer sk-abcdefghijk"}})
    out = sanitize_server_message(raw, sent)
    assert "778899" not in out and "sk-abcdefghijk" not in out and "[document text removed]" in out and len(out) <= 200


# ------------------------------------------------------------------ AT-434 structured-output fallback

def test_at434_one_structured_output_fallback_then_remembered(family, clients, fake_ai, profile):
    _setup()
    fake_ai.reject_schema = True
    c = clients["son1"]
    doc = make_doc(c, family["son1"], "SAMPLE insurance policy renewal")
    run_jobs()
    job = _analyze(clients["dad"], doc)
    run_jobs()
    job.refresh_from_db()
    chats = fake_ai.analysis_chats()
    assert job.status == AIJob.DONE and job.detail["fallback"] and job.detail["structured_output"] == "prompt"
    assert len(chats) == 2 and "response_format" in chats[0] and "response_format" not in chats[1]  # exactly one fallback
    assert AIProfile.objects.get(pk=profile.pk).capabilities["structured_output"] == "unsupported"
    doc2 = make_doc(c, family["son1"], "SAMPLE second policy")
    run_jobs()
    _analyze(clients["dad"], doc2)
    run_jobs()
    assert len(fake_ai.analysis_chats()) == 3 and "response_format" not in fake_ai.analysis_chats()[-1]
    # malformed JSON from the model: validated, failed once, never looped
    fake_ai.raw_reply = "Sure! title: something, no JSON here"
    doc3 = make_doc(c, family["son1"], "SAMPLE third policy")
    run_jobs()
    job3 = _analyze(clients["dad"], doc3)
    run_jobs()
    job3.refresh_from_db()
    assert job3.status == AIJob.FAILED and job3.error_category == "bad_response" and job3.stage == "validating_ai"
    assert len(fake_ai.analysis_chats()) == 4
    # a changed server URL or model resets what was learnt
    clients["dad"].patch(f"/api/ai/profiles/{profile.id}", {"base_url": profile.base_url.replace("127.0.0.1", "localhost")}, format="json")
    assert AIProfile.objects.get(pk=profile.pk).capabilities == {}


# ------------------------------------------------------------------ AT-435 model roles

def test_at435_model_roles(family, clients, fake_ai, profile):
    dad = clients["dad"]
    r = dad.patch(f"/api/ai/profiles/{profile.id}", {"text_model": "embed-model"}, format="json")
    assert r.status_code == 400 and "different" in r.json()["error"]
    r = dad.patch(f"/api/ai/profiles/{profile.id}", {"text_model": "nomic-embed-text-v1.5"}, format="json")
    assert r.status_code == 400 and "embedding model" in r.json()["error"]
    fake_ai.lmstudio = True
    t = dad.post(f"/api/ai/profiles/{profile.id}/test").json()
    steps = {s["step"]: s for s in t["steps"]}
    assert steps["Text model"]["ok"] and steps["Embedding model"]["ok"] and "vision" not in json.dumps(steps).lower()
    AIProfile.objects.filter(pk=profile.pk).update(embedding_model="text-model")  # a misconfigured legacy profile
    t = dad.post(f"/api/ai/profiles/{profile.id}/test").json()
    assert not t["ok"] and not {s["step"]: s for s in t["steps"]}["Embedding model"]["ok"]
    AIProfile.objects.filter(pk=profile.pk).update(text_model="embed-model", embedding_model="embed-model")
    with pytest.raises(AIError) as exc:
        service.run_analysis(AIProfile.objects.get(pk=profile.pk), "SAMPLE text for role check", keys=["title"], vocab={},
                             folders={}, title="t")
    assert exc.value.category == "model_role" and not fake_ai.analysis_chats()  # refused before any request


# ------------------------------------------------------------------ AT-436 transient retry

def test_at436_transient_errors_retry_with_backoff_then_succeed_or_fail(family, clients, fake_ai, profile):
    _setup()
    c = clients["son1"]
    fake_ai.fail_queue = [503, 429]
    doc = make_doc(c, family["son1"], "SAMPLE retry document")
    run_jobs()
    job = _analyze(clients["dad"], doc)
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.QUEUED and job.attempts == 1 and job.next_retry_at and job.error_category == "unavailable"
    assert timedelta(seconds=50) < job.next_retry_at - timezone.now() <= timedelta(seconds=61)
    row = clients["dad"].get("/api/ai/jobs").json()["jobs"][0]
    assert row["status"] == "queued" and row["next_retry_at"] and row["max_attempts"] == 3
    _due_now()
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.QUEUED and job.attempts == 2 and job.detail["http_status"] == 429
    _due_now()
    run_jobs()
    job.refresh_from_db()
    assert job.status == AIJob.DONE and job.attempts == 3 and job.next_retry_at is None and not job.error
    # always unavailable: three attempts, then failed truthfully
    fake_ai.fail_queue = [502, 503, 504]
    doc2 = make_doc(c, family["son1"], "SAMPLE retry document two")
    run_jobs()
    job2 = _analyze(clients["dad"], doc2)
    for _ in range(4):
        _due_now()
        run_jobs()
    job2.refresh_from_db()
    assert job2.status == AIJob.FAILED and job2.attempts == 3 and job2.retryable and job2.detail["http_status"] == 504
    # connection refused is transient too
    AIProfile.objects.filter(pk=profile.pk).update(base_url="http://127.0.0.1:9/v1")
    doc3 = make_doc(c, family["son1"], "SAMPLE offline server")
    run_jobs()
    job3 = _analyze(clients["dad"], doc3)
    run_jobs()
    job3.refresh_from_db()
    assert job3.status == AIJob.QUEUED and job3.error_category == "unavailable"


# ------------------------------------------------------------------ AT-437 stages; retry after a fix

def test_at437_stages_and_retry_after_fix(family, clients, fake_ai, profile):
    _setup()
    doc = make_doc(clients["son1"], family["son1"], "SAMPLE stage document")
    run_jobs()
    seen = []
    orig = service.set_stage

    def spy(job, stage, **kw):
        seen.append(stage)
        return orig(job, stage, **kw)

    service.set_stage = spy
    try:
        job = _analyze(clients["dad"], doc)
        run_jobs()
    finally:
        service.set_stage = orig
    job.refresh_from_db()
    assert seen == ["preparing", "validating_ocr", "ai_running", "validating_ai", "saving"] and job.stage == "done"
    # a failure, then Retry once the cause is fixed: a new job; the failed one stays failed
    fake_ai.echo_400 = True
    job2 = _analyze(clients["dad"], doc)
    run_jobs()
    job2.refresh_from_db()
    assert job2.status == AIJob.FAILED and job2.retryable
    fake_ai.echo_400 = False
    r = clients["dad"].post(f"/api/ai/jobs/{job2.id}/retry")
    assert r.status_code == 202
    run_jobs()
    job2.refresh_from_db()
    assert job2.status == AIJob.FAILED and AIJob.objects.get(pk=r.json()["job"]).status == AIJob.DONE
    assert clients["mom"].post(f"/api/ai/jobs/{job2.id}/retry").status_code in (403, 404)  # needs edit rights on the document


# ------------------------------------------------------------------ AT-438 metadata integrity

def test_at438_validation_and_manual_details_protected(family, clients, fake_ai, profile):
    _setup()
    assert service.validate_ai_data({"title": 5, "issue_date": "31/12/2020", "expiry_date": "2031-02-30", "tags": "a, b",
                                     "folder": {"x": 1}, "summary": "ok\x00"}) == {"title": "5", "tags": ["a", "b"], "summary": "ok"}
    with pytest.raises(AIError):
        service.validate_ai_data({"unexpected": "x"})
    with pytest.raises(AIError):
        service.validate_ai_data(["not", "an", "object"])
    c = clients["son1"]
    doc = make_doc(c, family["son1"], "Passport SAMPLE expiry 2031-05-20 issued 2021-05-21")
    run_jobs()
    DocumentField.objects.update_or_create(document=doc, key="expiry_date",
                                           defaults={"value": "2032-01-01", "status": DocumentField.CONFIRMED, "source": "manual"})
    _analyze(clients["dad"], doc)
    run_jobs()
    fields = set(AISuggestion.objects.filter(document=doc).values_list("field", flat=True))
    assert "expiry_date" not in fields and "issue_date" in fields  # the person's value is never proposed for replacement
    doc.refresh_from_db()
    assert doc.title != "Passport - Sample"  # suggestions are never applied without a person


def test_long_text_is_split_in_order_and_truncation_recorded(family, clients, fake_ai, profile):
    _setup()
    AIProfile.objects.filter(pk=profile.pk).update(max_input_chars=1000)
    pages = [f"PAGE {i} " + ("sample words " * 60) for i in range(5)]
    parts = service.split_for_model("\f".join(pages), 1000)
    assert len(parts) >= 4 and all(len(p) <= 1000 for p in parts) and parts[0].startswith("PAGE 0")
    data, info = service.run_analysis(AIProfile.objects.get(pk=profile.pk), "\f".join(pages), keys=["title", "tags"],
                                      vocab={}, folders={}, title="t")
    assert info["parts"] == service.ANALYSIS_PARTS and info["truncated"] and info["analyzed_chars"] < info["total_chars"]
    assert len(fake_ai.analysis_chats()) == service.ANALYSIS_PARTS and data["title"] == "Passport - Sample"


# ------------------------------------------------------------------ AT-439 privacy / performance

def test_at439_no_content_in_logs_or_job_data_and_throttling_applies(family, clients, fake_ai, profile, caplog):
    from apps.core import throttle

    _setup()
    config.set_value("ai.debug_logging", True)
    caplog.set_level(logging.DEBUG)
    doc = make_doc(clients["son1"], family["son1"], f"Statement {SECRET} balance SAMPLE")
    run_jobs()
    _analyze(clients["dad"], doc)
    run_jobs()
    assert SECRET not in caplog.text and "SECRETKEY" not in caplog.text
    jobs = clients["dad"].get("/api/ai/jobs").json()
    assert SECRET not in json.dumps(jobs)
    sug = clients["son1"].get(f"/api/documents/{doc.id}/ai/suggestions").json()["last_job"]
    assert sug["stage"] == "done" and SECRET not in json.dumps(sug["detail"])
    assert "ai_task" in throttle.DEFERRABLE  # background analysis waits while the server is under sustained load


def test_test_ocr_endpoints_use_a_synthetic_sample(family, clients, paddle):
    r = clients["dad"].post("/api/ai/test-ocr", {"engine": "paddleocr"}, format="json")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["chars"] > 5, r.content
    assert clients["mom"].post("/api/ai/test-ocr", {"engine": "paddleocr"}, format="json").status_code == 403
    assert clients["dad"].post("/api/ai/test-ocr", {"engine": "cloud"}, format="json").status_code == 400
    if HAS_TESSERACT:
        t = clients["dad"].post("/api/ai/test-ocr", {"engine": "tesseract"}, format="json").json()
        assert t["ok"] and "SAMPLE" in t["text"].upper()


def test_reported_http_400_reproduced_and_explained(family, clients, fake_ai, profile):
    """The reported failure: Analyze Document used response_format {"type": "json_object"}, which LM Studio rejects
    with HTTP 400, while the assistant (plain chat) worked. The old request shape still fails, but now says why and is
    classified as deterministic (no requeue); the new request shape succeeds on the same server."""
    from apps.ai.providers import provider_for

    fake_ai.lmstudio = True
    prov = provider_for(profile)
    assert prov.chat([{"role": "user", "content": "Reply with the single word OK."}], "text-model") == "OK"  # assistant path
    with pytest.raises(AIError) as exc:
        prov.chat([{"role": "user", "content": "OCR TEXT:\nSAMPLE"}], "text-model", json_mode=True)  # the old analyze path
    e = exc.value
    assert e.status == 400 and e.category == "bad_request" and not e.transient
    assert "'response_format.type' must be 'json_schema' or 'text'" in str(e) and e.capability == "response_format"
    reply, info = prov.structured([{"role": "user", "content": "OCR TEXT:\nSAMPLE"}], "text-model",
                                  {"type": "object", "properties": {"title": {"type": "string"}}})
    assert info == {"structured_output": "schema", "fallback": False} and parse_json_object(reply)["title"]
