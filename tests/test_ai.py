"""Local AI (AT-31..AT-36, part of AT-48): profiles, privacy, suggestions with confirmation, authorization, outages."""
import logging

import pytest

from apps.ai.models import AIJob, AIProfile, AISuggestion, DocumentChunk
from apps.core import config
from apps.library.models import Document
from conftest import make_text_pdf, personal_root, run_jobs, upload
from fake_ai_server import FakeAI

pytestmark = pytest.mark.django_db

SON_SECRET = "ZEBRAQUARTZ"  # a marker that only appears in son1's private document


@pytest.fixture
def fake_ai():
    srv = FakeAI().start()
    yield srv
    srv.stop()


def enable_ai(**overrides):
    values = {"ai.enabled": True, "ai.ocr_assist": True, "ai.smart_organization": True, "ai.semantic_search": True,
              "ai.assistant": True, "ai.auto_analyze": True, **overrides}
    for k, v in values.items():
        config.set_value(k, v)


@pytest.fixture
def profile(fake_ai, family, clients):
    r = clients["dad"].post("/api/ai/profiles", {"name": "LAN box", "provider": "openai", "base_url": f"http://127.0.0.1:{fake_ai.port}/v1",
                                                 "text_model": "text-model", "embedding_model": "embed-model", "privacy": "local",
                                                 "api_key": "sk-local-SECRETKEY"}, format="json")
    assert r.status_code == 201, r.content
    return AIProfile.objects.get(pk=r.json()["id"])


def make_doc(client, user, text, name="doc.pdf"):
    r = upload(client, personal_root(user), name=name, content=make_text_pdf(text))
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


# ------------------------------------------------------------------ AT-31 configuration

def test_at31_profile_configuration_test_and_discovery(family, clients, fake_ai, profile):
    admin = clients["dad"]
    data = admin.get("/api/ai/profiles").json()["profiles"][0]
    assert data["api_key_configured"] and "SECRETKEY" not in str(data) and data["is_default"]
    assert "SECRETKEY" not in profile.api_key_enc  # encrypted at rest
    r = admin.post(f"/api/ai/profiles/{profile.pk}/test")
    assert r.status_code == 200, r.content
    t = r.json()
    assert t["privacy_actual"] == "local" and "text-model" in t["models"] and t["chat_ok"] and t["embedding_dimensions"] == 64
    assert admin.get(f"/api/ai/profiles/{profile.pk}/models").json()["models"] == ["embed-model", "text-model", "vision-model"]
    auth = [p for p, _b in fake_ai.requests]
    assert auth  # the server was really contacted
    assert clients["mom"].get("/api/ai/profiles").status_code == 403


def test_invalid_and_unreachable_endpoints_fail_safely(family, clients):
    admin = clients["dad"]
    assert admin.post("/api/ai/profiles", {"name": "x", "base_url": "ftp://nope", "privacy": "lan"}, format="json").status_code == 400
    r = admin.post("/api/ai/profiles", {"name": "down", "base_url": "http://127.0.0.1:9/v1", "text_model": "m", "privacy": "local"}, format="json")
    assert r.status_code == 201
    t = admin.post(f"/api/ai/profiles/{r.json()['id']}/test")
    assert t.status_code == 503 and t.json()["category"] == "unavailable" and "Cannot connect" in t.json()["error"]


def test_privacy_classification_enforced(family, clients, profile):
    admin = clients["dad"]
    r = admin.post("/api/ai/profiles", {"name": "cloud", "base_url": "http://8.8.8.8:1/v1", "privacy": "lan"}, format="json")
    assert r.status_code == 400 and "EXTERNAL" in r.json()["error"]
    r = admin.post("/api/ai/profiles", {"name": "cloud", "base_url": "http://8.8.8.8:1/v1", "privacy": "external"}, format="json")
    assert r.status_code == 400 and "Acknowledge" in r.json()["error"]
    r = admin.post("/api/ai/profiles", {"name": "cloud", "base_url": "http://8.8.8.8:1/v1", "privacy": "external",
                                       "external_acknowledged": True}, format="json")
    assert r.status_code == 201
    # A profile whose URL later points outside its class is refused at request time (no text sent).
    from apps.ai.providers import AIError, check_privacy

    profile.base_url = "http://8.8.8.8:1/v1"
    with pytest.raises(AIError) as e:
        check_privacy(profile)
    assert e.value.category == "privacy"


def test_ollama_adapter(family, clients, fake_ai):
    admin = clients["dad"]
    r = admin.post("/api/ai/profiles", {"name": "ollama", "provider": "ollama", "base_url": f"http://127.0.0.1:{fake_ai.port}",
                                       "text_model": "llama3", "embedding_model": "nomic-embed-text", "privacy": "local"}, format="json")
    t = admin.post(f"/api/ai/profiles/{r.json()['id']}/test").json()
    assert t["models"] == ["llama3", "nomic-embed-text"] and t["chat_ok"] and t["embedding_dimensions"] == 64
    assert any(p.endswith("/api/chat") for p, _ in fake_ai.requests) and any(p.endswith("/api/embed") for p, _ in fake_ai.requests)


# ------------------------------------------------------------------ AT-32 / AT-33 suggestions need confirmation

def test_at32_at33_ocr_assist_suggests_without_changing_metadata(family, clients, fake_ai, profile):
    enable_ai()
    son = family["son1"]
    doc = make_doc(clients["son1"], son, "REPUBLIC OF SAMPLES PASSPORT\nSurname SAMPLE\nDate of expiry 20 May 2031")
    run_jobs()
    doc.refresh_from_db()
    assert doc.state in ("ready", "needs_review") and doc.content_text  # baseline OCR/text extraction completed first
    title_before, type_before = doc.title, doc.doc_type_id
    job = AIJob.objects.get(document=doc, kind="analyze")
    assert job.status == "done" and job.model == "text-model"
    sugg = {s["field"]: s for s in clients["son1"].get(f"/api/documents/{doc.id}/ai/suggestions").json()["suggestions"]}
    assert {"title", "expiry_date", "doc_type", "correspondent", "tags"} <= set(sugg)
    doc.refresh_from_db()
    assert (doc.title, doc.doc_type_id, doc.expiry_date) == (title_before, type_before, doc.expiry_date)  # nothing applied
    assert not doc.tags.exists() and doc.correspondent is None
    # a person who can only view cannot accept
    clients["dad"].put(f"/api/documents/{doc.id}/permissions", {"user": str(family["mom"].pk), "caps": ["view"]}, format="json")
    r = clients["mom"].post(f"/api/documents/{doc.id}/ai/suggestions/{sugg['expiry_date']['id']}", {"action": "accept"}, format="json")
    assert r.status_code == 403
    # the owner accepts the expiry date and dismisses the title
    r = clients["son1"].post(f"/api/documents/{doc.id}/ai/suggestions/{sugg['expiry_date']['id']}", {"action": "accept"}, format="json")
    assert r.status_code == 200
    clients["son1"].post(f"/api/documents/{doc.id}/ai/suggestions/{sugg['title']['id']}", {"action": "dismiss"}, format="json")
    doc.refresh_from_db()
    assert str(doc.expiry_date) == "2031-05-20" and doc.title != "Passport - Sample"
    field = doc.fields.get(key="expiry_date")
    assert field.status == "confirmed" and field.confirmed_by == son
    # accept all remaining: type, issuer, tags applied through the normal services
    clients["son1"].post(f"/api/documents/{doc.id}/ai/suggestions/0", {"action": "accept"}, format="json")
    doc.refresh_from_db()
    assert doc.doc_type.name == "Passport" and doc.correspondent.name == "Ministry of Samples"
    assert list(doc.tags.values_list("name", flat=True)) == ["travel"]
    assert doc.history.filter(action="ai_suggestion_accepted").count() >= 4


def test_ai_never_invents_document_numbers(family, clients, fake_ai, profile):
    enable_ai()
    fake_ai.analyze_reply = {"document_number": "X9999999"}
    doc = make_doc(clients["son1"], family["son1"], "Sample letter without any number")
    run_jobs()
    assert not AISuggestion.objects.filter(document=doc, field="document_number").exists()


# ------------------------------------------------------------------ AT-34 / AT-35 authorization

def test_at34_assistant_and_semantic_respect_permissions(family, clients, fake_ai, profile):
    enable_ai()
    son_doc = make_doc(clients["son1"], family["son1"], f"Private diary {SON_SECRET} passport travel plans")
    mom_doc = make_doc(clients["mom"], family["mom"], "Passport of mom travel booking")
    run_jobs()
    assert DocumentChunk.objects.filter(document=son_doc).exists()
    fake_ai.requests.clear()
    r = clients["mom"].post("/api/ai/assistant", {"question": "Find the passport travel plans diary"}, format="json")
    assert r.status_code == 200, r.content
    ids = {s["id"] for s in r.json()["sources"]}
    assert str(son_doc.id) not in ids and str(mom_doc.id) in ids
    assert SON_SECRET not in fake_ai.prompts()  # the private text never reached the model
    assert str(son_doc.id) not in fake_ai.prompts()
    hits = clients["mom"].get("/api/ai/semantic", {"q": f"diary {SON_SECRET} travel"}).json()["results"]
    assert str(son_doc.id) not in {h["id"] for h in hits}
    assert clients["mom"].get(f"/api/documents/{son_doc.id}/ai/suggestions").status_code == 404  # no existence leak
    assert clients["mom"].post(f"/api/documents/{son_doc.id}/ai/analyze").status_code == 404
    assert clients["mom"].post("/api/ai/assistant", {"question": "summarize", "document": str(son_doc.id)}, format="json").status_code == 404


def test_at35_revoking_access_revokes_ai_retrieval(family, clients, fake_ai, profile):
    enable_ai()
    son_doc = make_doc(clients["son1"], family["son1"], f"Insurance policy {SON_SECRET} coverage")
    run_jobs()
    mom = family["mom"]
    clients["dad"].put(f"/api/documents/{son_doc.id}/permissions", {"user": str(mom.pk), "caps": ["view"]}, format="json")
    hits = clients["mom"].get("/api/ai/semantic", {"q": "insurance coverage policy"}).json()["results"]
    assert str(son_doc.id) in {h["id"] for h in hits}
    clients["dad"].put(f"/api/documents/{son_doc.id}/permissions", {"user": str(mom.pk), "caps": []}, format="json")
    hits = clients["mom"].get("/api/ai/semantic", {"q": "insurance coverage policy"}).json()["results"]
    assert str(son_doc.id) not in {h["id"] for h in hits}
    fake_ai.requests.clear()
    r = clients["mom"].post("/api/ai/assistant", {"question": "insurance coverage policy"}, format="json")
    assert str(son_doc.id) not in {s["id"] for s in r.json()["sources"]} and SON_SECRET not in fake_ai.prompts()


def test_assistant_drops_citations_outside_context(family, clients, fake_ai, profile):
    enable_ai()
    son_doc = make_doc(clients["son1"], family["son1"], "Son private record")
    make_doc(clients["mom"], family["mom"], "Mom vaccination record")
    run_jobs()
    fake_ai.extra_citation = f" Also see [doc:{son_doc.id}]"
    answer = clients["mom"].post("/api/ai/assistant", {"question": "vaccination record"}, format="json").json()["answer"]
    assert str(son_doc.id) not in answer


def test_expiry_intent_uses_permitted_documents(family, clients, fake_ai, profile):
    from datetime import timedelta

    from django.utils import timezone

    enable_ai()
    doc = make_doc(clients["mom"], family["mom"], "Residence permit")
    son_doc = make_doc(clients["son1"], family["son1"], "Son permit")
    run_jobs()
    soon = timezone.localdate() + timedelta(days=60)
    Document.objects.filter(pk__in=[doc.pk, son_doc.pk]).update(expiry_date=soon)
    fake_ai.requests.clear()
    r = clients["mom"].post("/api/ai/assistant", {"question": "Which of my documents expire within six months?"}, format="json")
    ids = {s["id"] for s in r.json()["sources"]}
    assert str(doc.id) in ids and str(son_doc.id) not in ids


def test_ai_access_policy_and_switches(family, clients, fake_ai, profile):
    enable_ai(**{"ai.allowed_users": "admins"})
    assert clients["mom"].post("/api/ai/assistant", {"question": "x"}, format="json").status_code == 403
    assert clients["mom"].get("/api/ai/status").json()["assistant"] is False
    assert clients["dad"].get("/api/ai/status").json()["assistant"] is True
    enable_ai(**{"ai.assistant": False})
    assert clients["dad"].post("/api/ai/assistant", {"question": "x"}, format="json").status_code == 403


# ------------------------------------------------------------------ AT-36 outage resilience

def test_at36_ai_outage_does_not_break_document_management(family, clients, profile, caplog):
    enable_ai()
    profile.base_url = "http://127.0.0.1:9/v1"  # nothing listens here
    profile.save()
    son = family["son1"]
    c = clients["son1"]
    doc = make_doc(c, son, "Driving licence SAMPLE renewal")
    run_jobs()
    doc.refresh_from_db()
    assert doc.state in ("ready", "needs_review") and "licence" in doc.content_text.lower()
    jobs = AIJob.objects.filter(document=doc)
    assert jobs.exists() and all(j.status in ("failed", "queued") for j in jobs)
    assert c.get("/api/documents", {"q": "licence"}).json()["total"] >= 1
    assert c.get(f"/api/documents/{doc.id}/file").status_code == 200
    assert c.patch(f"/api/documents/{doc.id}", {"title": "My licence"}, format="json").status_code == 200
    r = c.post("/api/ai/assistant", {"question": "licence"}, format="json")
    assert r.status_code == 503 and r.json()["sources"]  # AI down, but matching documents are still listed
    assert config.get("ai.enabled")  # no silent fallback or reconfiguration


def test_ai_disabled_queues_nothing(family, clients, profile):
    config.set_value("ai.enabled", False)
    doc = make_doc(clients["son1"], family["son1"], "Plain document")
    run_jobs()
    assert not AIJob.objects.filter(document=doc).exists()
    assert clients["son1"].post("/api/ai/assistant", {"question": "x"}, format="json").status_code == 403


def test_ai_logs_and_jobs_contain_no_document_content(family, clients, fake_ai, profile, caplog):
    enable_ai(**{"ai.debug_logging": True})
    caplog.set_level(logging.DEBUG)
    doc = make_doc(clients["son1"], family["son1"], f"Bank statement {SON_SECRET} balance")
    run_jobs()
    clients["son1"].post("/api/ai/assistant", {"question": f"balance {SON_SECRET}?"}, format="json")
    assert SON_SECRET not in caplog.text
    jobs = clients["dad"].get("/api/ai/jobs").json()["jobs"]
    assert jobs and SON_SECRET not in str(jobs) and "SECRETKEY" not in caplog.text
    from apps.core.models import AuditEvent

    assert SON_SECRET not in str(list(AuditEvent.objects.values("context")))


def test_reindex_and_job_visibility(family, clients, fake_ai, profile):
    enable_ai(**{"ai.auto_analyze": False})
    make_doc(clients["son1"], family["son1"], "Utility bill electricity")
    run_jobs()
    assert not DocumentChunk.objects.exists()
    assert clients["mom"].post("/api/ai/reindex").status_code == 403
    assert clients["dad"].post("/api/ai/reindex").json()["queued"] == 1
    run_jobs()
    assert DocumentChunk.objects.count() >= 1
    jobs = clients["dad"].get("/api/ai/jobs").json()
    assert jobs["jobs"][0]["kind"] == "embed" and jobs["jobs"][0]["profile"] == "LAN box"
