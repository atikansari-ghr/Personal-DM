"""Document types, metadata templates, field provenance and type assignment (Change Set N, AT-161..AT-174).

Synthetic documents only. AT-175 (responsive Details workflow) is covered by tests/e2e/parity.mjs.
"""
from datetime import timedelta

import pytest
from conftest import personal_root, run_jobs, upload
from django.utils import timezone
from fixtures import make_text_pdf

from apps.core.models import AuditEvent
from apps.library import doctypes
from apps.library.models import Document, DocumentField, DocumentType, DocumentTypeField, Folder

pytestmark = pytest.mark.django_db

PASSPORT_TEXT = ("PASSPORT\nName: SAMPLE PERSON\nNationality: Testland\nSex: F\nDate of birth: 01 Jan 2000\n"
                 "Date of issue: 19 Oct 2016\nDate of expiry: 18 Oct 2030\nPlace of issue: Sample City")


def _doc(client, folder, name="doc.pdf", text="synthetic text only", **data):
    r = upload(client, folder, name=name, content=make_text_pdf(text), **data)
    assert r.status_code == 201, r.content
    return Document.objects.get(pk=r.json()["documents"][0]["id"])


def _detail(client, doc):
    r = client.get(f"/api/documents/{doc.id}")
    assert r.status_code == 200
    return r.json()


def _grant_view(clients, family, folder, user):
    r = clients["dad"].put(f"/api/folders/{folder.id}/permissions", {"user": str(family[user].pk), "caps": ["view"]},
                           format="json")
    assert r.status_code in (200, 201), r.content


def _passport():
    return DocumentType.objects.get(name="Passport")


def test_at161_untyped_document_with_details_can_be_typed_and_survives_reload(family, clients):
    """Reproduces the defect: OCR details exist while Type is blank; the type can now be set from Details."""
    son = clients["son1"]
    doc = _doc(son, personal_root(family["son1"]), text=PASSPORT_TEXT)
    run_jobs()
    data = _detail(son, doc)
    assert data["type"] is None and len(data["fields"]) >= 3  # the reported state: metadata, no type
    assert data["type_info"]["suggestions"][0]["name"] == "Passport"  # recognised text suggests it, not applied
    assert data["type_info"]["suggestions"][0]["source"] == "ocr"
    r = son.post(f"/api/documents/{doc.id}/type", {"type": _passport().id}, format="json")
    assert r.status_code == 200, r.content
    again = _detail(son, doc)  # reload
    assert again["type"]["name"] == "Passport" and again["type"]["confirmed"] is True
    assert again["type_info"]["source"] == "manual"
    assert [t["key"] for t in again["template"]][:3] == ["document_number", "full_name", "nationality"]
    assert {f["group"] for f in again["fields"]} <= {"template"}  # every extracted value maps onto the passport
    hist = Document.objects.get(pk=doc.pk).history.filter(action="type_changed").first()
    assert hist.changes["new"] == "Passport" and hist.changes["old"] is None
    assert AuditEvent.objects.filter(action="document.type_change", target_id=str(doc.id)).exists()


def test_at162_folder_and_type_are_independent(family, clients):
    son = clients["son1"]
    root = personal_root(family["son1"])
    old = Folder.objects.create(parent=root, name="Old passports", owner=family["son1"])
    doc = _doc(son, root, doc_type=_passport().id)
    r = son.patch(f"/api/documents/{doc.id}", {"folder": str(old.id)}, format="json")
    assert r.status_code == 200
    doc.refresh_from_db()
    assert doc.folder_id == old.id and doc.doc_type == _passport()  # moving keeps the type
    visa = DocumentType.objects.get(name="Visa")
    son.post(f"/api/documents/{doc.id}/type", {"type": visa.id}, format="json")
    doc.refresh_from_db()
    assert doc.doc_type == visa and doc.folder_id == old.id  # changing the type does not move the file


def test_at163_type_administration_and_no_destructive_delete(family, clients):
    admin = clients["dad"]
    r = admin.post("/api/document-types/admin", {"name": "Club membership", "template": "generic", "has_expiry": True,
                                                  "description": "Sports and social clubs", "emoji": "🏅"}, format="json")
    assert r.status_code == 201, r.content
    t = DocumentType.objects.get(name="Club membership")
    assert t.description == "Sports and social clubs" and t.template_fields.filter(key="expiry_date").exists()
    r = admin.patch(f"/api/document-types/{t.id}", {"name": "Club card", "reminder_days": "30, 7"}, format="json")
    assert r.status_code == 200 and r.json()["name"] == "Club card" and r.json()["reminder_days"] == [30, 7]
    doc = _doc(clients["son1"], personal_root(family["son1"]), doc_type=t.id)
    r = admin.delete(f"/api/document-types/{t.id}")
    assert r.status_code == 409 and r.json()["code"] == "in_use"
    r = admin.delete(f"/api/metadata/type/{t.id}")  # the older endpoint no longer untypes documents either
    assert r.status_code == 409
    doc.refresh_from_db()
    assert doc.doc_type_id == t.id
    r = admin.patch(f"/api/document-types/{t.id}", {"archived": True}, format="json")
    assert r.status_code == 200
    assert t.id not in [x["id"] for x in clients["son1"].get("/api/document-types").json()["types"]]
    doc.refresh_from_db()
    assert doc.doc_type_id == t.id  # archived: existing documents keep it
    other = DocumentType.objects.get(name="Other")
    r = admin.delete(f"/api/document-types/{t.id}", {"reassign_to": other.id}, format="json")
    assert r.status_code == 204
    doc.refresh_from_db()
    assert doc.doc_type == other  # safe migration before the delete
    # members cannot manage types
    assert clients["son1"].get("/api/document-types/admin").status_code == 403


def test_at164_template_fields_configure_details(family, clients):
    admin, son = clients["dad"], clients["son1"]
    t = _passport()
    r = admin.post(f"/api/document-types/{t.id}/fields",
                   {"label": "Blood group", "field_type": "select", "choices": "A, B, AB, O", "required": True,
                    "searchable": False, "help_text": "As printed"}, format="json")
    assert r.status_code == 201, r.content
    f = t.template_fields.get(key="blood_group")
    assert f.choices == ["A", "B", "AB", "O"] and f.required and not f.searchable and not f.extract
    # reorder: put the new field first
    ids = [f.id] + list(t.template_fields.exclude(pk=f.id).values_list("id", flat=True))
    assert admin.post(f"/api/document-types/{t.id}/fields", {"reorder": ids}, format="json").status_code == 200
    r = admin.patch(f"/api/document-types/{t.id}/fields/{t.template_fields.get(key='place_of_issue').id}",
                    {"enabled": False, "label": "Issued at"}, format="json")
    assert r.status_code == 200
    # invalid definitions are refused server-side
    bad = admin.post(f"/api/document-types/{t.id}/fields", {"label": "X", "field_type": "text", "role": "expiry"}, format="json")
    assert bad.status_code == 400 and "date" in bad.json()["error"]
    bad = admin.post(f"/api/document-types/{t.id}/fields", {"label": "Y", "field_type": "text",
                                                            "validation": {"pattern": "("}}, format="json")
    assert bad.status_code == 400
    doc = _doc(son, personal_root(family["son1"]), doc_type=t.id)
    data = _detail(son, doc)
    keys = [x["key"] for x in data["template"]]
    assert keys[0] == "blood_group" and "place_of_issue" not in keys
    assert data["details_status"]["missing_required"][:1] == ["Blood group"]
    r = son.post(f"/api/documents/{doc.id}/fields", {"key": "blood_group", "value": "Q"}, format="json")
    assert r.status_code == 400 and "one of" in r.json()["error"]
    assert son.post(f"/api/documents/{doc.id}/fields", {"key": "blood_group", "value": "AB"}, format="json").status_code == 200


def test_at165_passport_template_editing_and_validation(family, clients):
    son = clients["son1"]
    doc = _doc(son, personal_root(family["son1"]), doc_type=_passport().id)
    data = _detail(son, doc)
    labels = [x["label"] for x in data["template"]]
    for label in ("Passport number", "Full name", "Nationality", "Date of birth", "Sex", "Issue date", "Expiry date",
                  "Issuing authority", "Place of issue"):
        assert label in labels
    r = son.post(f"/api/documents/{doc.id}/fields", {"key": "date_of_birth", "value": "not a date"}, format="json")
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["error"]
    r = son.post(f"/api/documents/{doc.id}/fields", {"key": "sex", "value": "Z"}, format="json")
    assert r.status_code == 400
    assert son.post(f"/api/documents/{doc.id}/fields", {"key": "expiry_date", "value": "2031-05-02"}, format="json").status_code == 200
    doc.refresh_from_db()
    assert doc.expiry_date.isoformat() == "2031-05-02"
    status = _detail(son, doc)["details_status"]
    assert status["status"] == "confirmed"  # the only required passport field is filled and confirmed


def test_at166_folder_suggested_type_is_a_suggestion_only(family, clients):
    son = clients["son1"]
    root = personal_root(family["son1"])
    folder = Folder.objects.create(parent=root, name="Passport", owner=family["son1"])
    r = son.patch(f"/api/folders/{folder.id}", {"suggested_type": _passport().id}, format="json")
    assert r.status_code == 200 and r.json()["suggested_type"]["name"] == "Passport"
    # upload dialog kept the suggestion: assigned, recorded as coming from the folder
    kept = _doc(son, folder, name="a.pdf", doc_type=_passport().id, type_source="folder")
    assert kept.doc_type == _passport() and kept.type_source == "folder" and kept.type_confirmed
    # dropped without the dialog: not assigned, only suggested
    dropped = _doc(son, folder, name="b.pdf")
    assert dropped.doc_type is None and dropped.type_suggestions[0]["source"] == "folder"
    # the person may choose another type
    visa = DocumentType.objects.get(name="Visa")
    other = _doc(son, folder, name="c.pdf", doc_type=visa.id)
    assert other.doc_type == visa
    # the folder relation is not permanent: clearing the suggestion changes no document
    son.patch(f"/api/folders/{folder.id}", {"suggested_type": None}, format="json")
    kept.refresh_from_db()
    assert kept.doc_type == _passport()
    # subfolders inherit the suggestion
    son.patch(f"/api/folders/{folder.id}", {"suggested_type": _passport().id}, format="json")
    sub = Folder.objects.create(parent=folder, name="2016", owner=family["son1"])
    assert doctypes.folder_suggestion(Folder.objects.get(pk=sub.pk)) == _passport()


def test_at167_ocr_suggestion_accept_change_ignore_and_confirmed_type_kept(family, clients):
    son = clients["son1"]
    root = personal_root(family["son1"])
    doc = _doc(son, root, text=PASSPORT_TEXT)
    run_jobs()
    sug = _detail(son, doc)["type_info"]["suggestions"]
    assert sug and sug[0]["source"] == "ocr" and "passport" in sug[0]["reason"].lower()
    # Ignore
    r = son.post(f"/api/documents/{doc.id}/type", {"ignore": True}, format="json")
    assert r.status_code == 200 and r.json()["type_info"]["suggestions"] == []
    # Accept (source kept for provenance)
    doc2 = _doc(son, root, name="p2.pdf", text=PASSPORT_TEXT)
    run_jobs()
    son.post(f"/api/documents/{doc2.id}/type", {"type": _passport().id, "source": "ocr"}, format="json")
    doc2.refresh_from_db()
    assert doc2.doc_type == _passport() and doc2.type_source == "ocr" and doc2.type_confirmed
    # a confirmed type is never silently overwritten by a later scan that suggests something else
    visa = DocumentType.objects.get(name="Visa")
    doc3 = _doc(son, root, name="v.pdf", text="ENTRY VISA\nDate of expiry: 01 Jan 2031", doc_type=visa.id)
    run_jobs()
    doc3.refresh_from_db()
    assert doc3.doc_type == visa
    doctypes.suggest_from_text(doc3, PASSPORT_TEXT)
    doc3.refresh_from_db()
    assert doc3.doc_type == visa and doc3.type_suggestions[0]["name"] == "Passport"
    assert "confirmed type was kept" in doc3.type_suggestions[0]["reason"]
    # folder and OCR suggestions disagreeing are shown as a conflict, not decided
    folder = Folder.objects.create(parent=root, name="Visas", owner=family["son1"])
    son.patch(f"/api/folders/{folder.id}", {"suggested_type": visa.id}, format="json")
    doc4 = _doc(son, folder, name="p4.pdf", text=PASSPORT_TEXT)
    run_jobs()
    s4 = _detail(son, doc4)["type_info"]["suggestions"]
    assert {s["source"] for s in s4} == {"folder", "ocr"} and all(s.get("conflict") for s in s4)
    assert Document.objects.get(pk=doc4.pk).doc_type is None


def test_at168_value_provenance_and_protection(family, clients):
    son = clients["son1"]
    doc = _doc(son, personal_root(family["son1"]), text=PASSPORT_TEXT, doc_type=_passport().id)
    run_jobs()
    fields = {f["key"]: f for f in _detail(son, doc)["fields"]}
    assert fields["expiry_date"]["status"] == "proposed" and fields["expiry_date"]["source_label"] == "OCR"
    # a person corrects an OCR value: manual + overridden + confirmed by them
    son.post(f"/api/documents/{doc.id}/fields", {"key": "expiry_date", "value": "2030-10-19"}, format="json")
    f = DocumentField.objects.get(document=doc, key="expiry_date")
    assert f.source == "manual" and f.overridden and f.status == "confirmed" and f.confirmed_by == family["son1"]
    # a later scan never replaces the confirmed value; it is shown next to it
    from apps.library.extraction import Proposal

    doctypes.store_proposals(doc, [Proposal("expiry_date", "2032-01-01", "ocr", 0.9, [], "")])
    f.refresh_from_db()
    assert f.value == "2030-10-19" and f.proposed_value == "2032-01-01"
    # accepted Local AI value keeps its source
    from apps.library import services as S

    S.set_field(actor=family["son1"], doc=doc, key="issuer", value="Sample Authority", source="ai")
    assert DocumentField.objects.get(document=doc, key="issuer").source == "ai"
    out = {x["key"]: x for x in _detail(son, doc)["fields"]}
    assert out["issuer"]["source_label"] == "Local AI" and out["expiry_date"]["confirmed_by"]


def test_at169_type_change_keeps_values_and_unmapped_are_reviewable(family, clients):
    son = clients["son1"]
    doc = _doc(son, personal_root(family["son1"]), doc_type=_passport().id)
    for k, v in (("full_name", "Sample Person"), ("nationality", "Testland"), ("sex", "F"),
                 ("expiry_date", "2031-01-01"), ("place_of_issue", "Sample City")):
        assert son.post(f"/api/documents/{doc.id}/fields", {"key": k, "value": v}, format="json").status_code == 200
    ins = DocumentType.objects.get(name="Insurance policy")
    plan = son.post(f"/api/documents/{doc.id}/type", {"type": ins.id, "preview": True}, format="json").json()["plan"]
    assert {u["key"] for u in plan["unmapped"]} == {"nationality", "sex", "place_of_issue"}
    assert {k["key"] for k in plan["keep"]} == {"full_name", "expiry_date"}
    assert DocumentField.objects.filter(document=doc).count() == 5  # preview changed nothing
    son.post(f"/api/documents/{doc.id}/type", {"type": ins.id}, format="json")
    data = _detail(son, doc)
    groups = {f["key"]: f["group"] for f in data["fields"]}
    assert groups["nationality"] == groups["sex"] == groups["place_of_issue"] == "unmapped"
    assert DocumentField.objects.filter(document=doc).count() == 5  # nothing deleted
    assert data["details_status"]["status"] == "needs_review" and data["details_status"]["unmapped"] == 3
    doc.refresh_from_db()
    assert doc.expiry_date.isoformat() == "2031-01-01"  # compatible expiry kept, reminders unchanged
    # review: keep / map / remove
    assert son.post(f"/api/documents/{doc.id}/fields", {"key": "nationality", "action": "keep"}, format="json").status_code == 200
    r = son.post(f"/api/documents/{doc.id}/fields", {"key": "place_of_issue", "action": "map", "to": "issuer"}, format="json")
    assert r.status_code == 200
    assert son.post(f"/api/documents/{doc.id}/fields", {"key": "sex", "action": "remove"}, format="json").status_code == 200
    f = {x.key: x for x in DocumentField.objects.filter(document=doc)}
    assert f["nationality"].scope == "custom" and f["issuer"].value == "Sample City" and "sex" not in f
    assert doc.versions.count() == 1  # original binary and versions untouched
    hist = [h.action for h in doc.history.all()]
    assert "type_changed" in hist and "previous_value_mapped" in hist and "previous_value_removed" in hist


def test_at169_expiry_role_lost_stops_reminders_only_after_review(family, clients):
    son = clients["son1"]
    doc = _doc(son, personal_root(family["son1"]), doc_type=_passport().id)
    son.post(f"/api/documents/{doc.id}/fields", {"key": "expiry_date", "value": "2031-01-01"}, format="json")
    cert = DocumentType.objects.get(name="Birth certificate")
    plan = son.post(f"/api/documents/{doc.id}/type", {"type": cert.id, "preview": True}, format="json").json()["plan"]
    assert plan["reminder_effect"] and "reminders" in plan["reminder_effect"]
    son.post(f"/api/documents/{doc.id}/type", {"type": cert.id}, format="json")
    doc.refresh_from_db()
    assert doc.expiry_date is None  # the warned effect
    assert DocumentField.objects.get(document=doc, key="expiry_date").scope == "unmapped"  # value kept for review


def test_at170_remap_existing_ocr_without_rescanning(family, clients):
    son = clients["son1"]
    text = PASSPORT_TEXT + "\nPolicy No: POL-12345\nInsurer: Sample Insurance"
    doc = _doc(son, personal_root(family["son1"]), text=text, doc_type=DocumentType.objects.get(name="Visa").id)
    run_jobs()
    versions_before = list(doc.versions.values_list("id", "sha256", "ocr_applied"))
    passport = _passport()
    son.post(f"/api/documents/{doc.id}/type", {"type": passport.id}, format="json")
    from apps.core.models import Job

    jobs_before = Job.objects.count()
    r = son.post(f"/api/documents/{doc.id}/remap-ocr")
    assert r.status_code == 200, r.content
    assert Job.objects.count() == jobs_before  # no OCR job: the existing text was used
    keys = {f.key for f in DocumentField.objects.filter(document=doc)}
    assert "date_of_birth" in keys  # a passport-only field (not in the visa template) proposed from the same text
    assert list(doc.versions.values_list("id", "sha256", "ocr_applied")) == versions_before


def test_at171_custom_detail_is_one_off_and_promotion_is_admin_only(family, clients):
    son, admin = clients["son1"], clients["dad"]
    root = personal_root(family["son1"])
    doc = _doc(son, root, doc_type=_passport().id)
    other = _doc(son, root, name="other.pdf", doc_type=_passport().id)
    r = son.post(f"/api/documents/{doc.id}/fields", {"label": "Old passport number", "value": "X1234567"}, format="json")
    assert r.status_code == 200, r.content
    f = DocumentField.objects.get(document=doc, key="custom:old_passport_number")
    assert f.scope == "custom" and f.label == "Old passport number"
    assert not DocumentField.objects.filter(document=other, key__startswith="custom:").exists()
    assert not _passport().template_fields.filter(key="old_passport_number").exists()  # the template did not change
    # promotion: separate administrator action
    r = son.post(f"/api/document-types/{_passport().id}/fields",
                 {"promote": True, "document": str(doc.id), "key": "custom:old_passport_number"}, format="json")
    assert r.status_code == 403
    r = admin.post(f"/api/document-types/{_passport().id}/fields",
                   {"promote": True, "document": str(doc.id), "key": "custom:old_passport_number"}, format="json")
    assert r.status_code == 201, r.content
    assert _passport().template_fields.filter(key="old_passport_number", label="Old passport number").exists()
    moved = DocumentField.objects.get(document=doc, key="old_passport_number")
    assert moved.scope == "type" and moved.value == "X1234567"
    assert not DocumentField.objects.filter(document=other, key="old_passport_number").exists()  # others unchanged
    assert "old_passport_number" in [t["key"] for t in _detail(son, other)["template"]]  # empty row there


def test_at172_permissions(family, clients):
    son, mom, admin = clients["son1"], clients["mom"], clients["dad"]
    root = personal_root(family["son1"])
    folder = Folder.objects.create(parent=root, name="Shared ID", owner=family["son1"])
    doc = _doc(son, folder, doc_type=_passport().id)
    _grant_view(clients, family, folder, "mom")
    assert mom.get(f"/api/documents/{doc.id}").json()["type"]["name"] == "Passport"  # read-only users see the type
    assert mom.post(f"/api/documents/{doc.id}/type", {"type": DocumentType.objects.get(name='Visa').id},
                    format="json").status_code == 403
    assert mom.post(f"/api/documents/{doc.id}/fields", {"key": "full_name", "value": "X"}, format="json").status_code == 403
    assert mom.post(f"/api/documents/{doc.id}/fields", {"label": "Note", "value": "x"}, format="json").status_code == 403
    assert mom.post(f"/api/documents/{doc.id}/remap-ocr").status_code == 403
    r = mom.post("/api/documents/bulk-type", {"ids": [str(doc.id)], "type": DocumentType.objects.get(name='Visa').id},
                 format="json")
    assert r.json()["changed"] == 0 and r.json()["not_allowed"] == 1
    # editors may classify their documents, never manage templates
    assert son.post(f"/api/documents/{doc.id}/type", {"type": DocumentType.objects.get(name='Visa').id},
                    format="json").status_code == 200
    t = _passport()
    assert son.post(f"/api/document-types/{t.id}/fields", {"label": "Z"}, format="json").status_code == 403
    assert son.patch(f"/api/document-types/{t.id}", {"name": "P"}, format="json").status_code == 403
    assert son.get("/api/document-types/review").status_code == 403
    assert admin.post(f"/api/document-types/{t.id}/fields", {"label": "Z"}, format="json").status_code == 201
    # no access at all: indistinguishable from a missing document
    assert clients["son2"].post(f"/api/documents/{doc.id}/type", {"type": t.id}, format="json").status_code == 404


def test_at173_search_and_expiry_integration(family, clients):
    son = clients["son1"]
    root = personal_root(family["son1"])
    p = _doc(son, root, name="p.pdf", doc_type=_passport().id)
    son.post(f"/api/documents/{p.id}/fields", {"key": "place_of_issue", "value": "Zanzibarville"}, format="json")
    son.post(f"/api/documents/{p.id}/fields", {"key": "document_number", "value": "ZX998877"}, format="json")
    _doc(son, root, name="v.pdf", doc_type=DocumentType.objects.get(name="Visa").id)
    rows = son.get(f"/api/documents?type={_passport().id}").json()["documents"]
    assert [r["id"] for r in rows] == [str(p.id)]
    assert str(p.id) in [r["id"] for r in son.get("/api/documents?q=Zanzibarville").json()["documents"]]
    assert str(p.id) not in [r["id"] for r in son.get("/api/documents?q=ZX998877").json()["documents"]]  # not searchable
    # the configured expiry field drives reminders; unconfirmed suggestions do not
    clients["dad"].post("/api/document-types/admin", {"name": "Club", "template": "generic"}, format="json")
    club = DocumentType.objects.get(name="Club")
    r = clients["dad"].post(f"/api/document-types/{club.id}/fields",
                            {"label": "Valid until", "field_type": "date", "role": "expiry"}, format="json")
    assert r.status_code == 201
    c = _doc(son, root, name="c.pdf", doc_type=club.id)
    soon = (timezone.localdate() + timedelta(days=20)).isoformat()
    son.post(f"/api/documents/{c.id}/fields", {"key": "valid_until", "value": soon, "confirm": False}, format="json")
    c.refresh_from_db()
    assert c.expiry_date is None  # a suggestion is not authoritative
    son.post(f"/api/documents/{c.id}/fields", {"key": "valid_until", "value": soon}, format="json")
    c.refresh_from_db()
    assert c.expiry_date.isoformat() == soon
    # per-type reminder days
    clients["dad"].patch(f"/api/document-types/{club.id}", {"reminder_days": [30]}, format="json")
    from apps.notify.expiry import run_expiry_scan

    out = run_expiry_scan()
    assert out["reminders"] >= 1
    # OCR review queue filter by type
    assert son.get(f"/api/ocr/review?type={club.id}").status_code == 200


def test_at174_migration_keeps_data_and_does_not_guess_types(family, clients):
    """The data step of library.0009 on documents created like earlier releases did."""
    import importlib

    from django.apps import apps as django_apps

    son = clients["son1"]
    root = personal_root(family["son1"])
    typed = _doc(son, root, name="t.pdf", doc_type=_passport().id)
    untyped = _doc(son, root, name="u.pdf")
    # simulate pre-upgrade rows: no template, no provenance, fields outside the template
    _passport().template_fields.all().delete()
    Document.objects.filter(pk=typed.pk).update(type_confirmed=False, type_source="", type_suggestions=[])
    Document.objects.filter(pk=untyped.pk).update(type_suggestions=[])
    DocumentField.objects.create(document=typed, key="full_name", value="Sample", status="confirmed")
    DocumentField.objects.create(document=typed, key="country_code", value="TST", status="confirmed")
    DocumentField.objects.create(document=untyped, key="full_name", value="Sample", status="confirmed", source="ocr")
    DocumentField.objects.create(document=untyped, key="expiry_date", value="2031-02-03", status="confirmed")
    from apps.library import services as S

    S.apply_confirmed_fields(Document.objects.get(pk=untyped.pk))
    before = {(f.document_id, f.key, f.value, f.status) for f in DocumentField.objects.all()}
    mig = importlib.import_module("apps.library.migrations.0009_document_type_templates")
    mig.forwards(django_apps, None)
    after = {(f.document_id, f.key, f.value, f.status) for f in DocumentField.objects.all()}
    assert before == after  # nothing lost or changed
    typed.refresh_from_db()
    untyped.refresh_from_db()
    assert typed.type_confirmed and typed.type_source == "migrated"
    assert untyped.doc_type is None and untyped.type_suggestions == []  # not guessed from field names
    assert untyped.expiry_date.isoformat() == "2031-02-03"  # untyped dates keep working
    assert DocumentField.objects.get(document=typed, key="country_code").scope == "custom"  # outside the template
    assert _passport().template_fields.filter(key="expiry_date").exists()
    r = son.get("/api/document-types").json()
    assert any(t["name"] == "Passport" for t in r["types"])
    report = doctypes.report()
    assert report["typed"] >= 1 and report["untyped"] >= 1
