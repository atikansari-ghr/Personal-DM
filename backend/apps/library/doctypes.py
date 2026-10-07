"""Document types, metadata templates, field provenance and type assignment (Change Set N).

A folder says *where* a document is kept; a document type says *what* it is. They are independent: moving a document
never changes its type and changing the type never moves it. A folder may only *suggest* a type.

Each type has an administrator-managed template (DocumentTypeField rows, stable `key`). A document's values live in
DocumentField rows with provenance (`source`: manual, ocr, mrz, ai, import, system, migrated) and `status`
(proposed = suggestion, confirmed). `scope` separates template values (type), one-off details of this document
(custom) and values kept from a previous type that the person still has to review (unmapped).

Only confirmed values of the fields with the expiry / issue / no-expiry role drive dates, generated names and
reminders. OCR and Local AI only ever *propose* values and types; a confirmed value or type is never overwritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.core import audit

from .models import Document, DocumentField, DocumentType, DocumentTypeField, Folder
from .services import DomainError

KEY_RX = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
SOURCE_LABELS = {"manual": "Manual", "ocr": "OCR", "mrz": "OCR (MRZ)", "ai": "Local AI", "import": "Imported",
                 "system": "System", "migrated": "Migrated", "folder": "Folder suggestion"}

# key -> (label, field type, role, searchable, choices)
STANDARD = {
    "full_name": ("Full name", "person", "", True, []),
    "document_number": ("Document number", "identifier", "", False, []),
    "issue_date": ("Issue date", "date", "issue", True, []),
    "expiry_date": ("Expiry date", "date", "expiry", True, []),
    "no_expiry": ("Does not expire", "boolean", "no_expiry", False, []),
    "date_of_birth": ("Date of birth", "date", "", False, []),
    "nationality": ("Nationality", "country", "", True, []),
    "issuer": ("Issuer", "text", "", True, []),
    "country_code": ("Country code", "country", "", True, []),
    "sex": ("Sex", "select", "", False, ["F", "M", "X"]),
    "place_of_issue": ("Place of issue", "text", "", True, []),
}

# template -> [(key, label override, required)]
TEMPLATES = {
    "passport": [("document_number", "Passport number", False), ("full_name", "", False), ("nationality", "", False),
                 ("date_of_birth", "", False), ("sex", "", False), ("issue_date", "", False),
                 ("expiry_date", "", True), ("issuer", "Issuing authority", False), ("place_of_issue", "", False)],
    "visa": [("document_number", "Visa number", False), ("full_name", "", False), ("nationality", "", False),
             ("issue_date", "", False), ("expiry_date", "", True), ("issuer", "Issuing country / authority", False),
             ("place_of_issue", "", False)],
    "iqama": [("document_number", "ID number", False), ("full_name", "", False), ("nationality", "", False),
              ("date_of_birth", "", False), ("issue_date", "", False), ("expiry_date", "", True),
              ("no_expiry", "", False), ("issuer", "", False)],
    "national_id": [("document_number", "ID number", False), ("full_name", "", False), ("date_of_birth", "", False),
                    ("sex", "", False), ("nationality", "", False), ("issue_date", "", False),
                    ("expiry_date", "", False), ("no_expiry", "", False)],
    "driving_license": [("document_number", "Licence number", False), ("full_name", "", False),
                        ("date_of_birth", "", False), ("issue_date", "", False), ("expiry_date", "", True),
                        ("issuer", "", False)],
    "employee_id": [("document_number", "Employee ID", False), ("full_name", "", False), ("issuer", "Employer", False),
                    ("issue_date", "", False), ("expiry_date", "", False), ("no_expiry", "", False)],
    "insurance": [("document_number", "Policy number", False), ("issuer", "Insurer", False),
                  ("full_name", "Insured person", False), ("issue_date", "Start date", False),
                  ("expiry_date", "End date", True)],
    "certificate": [("full_name", "", False), ("document_number", "Certificate number", False),
                    ("issuer", "", False), ("issue_date", "", False), ("place_of_issue", "", False)],
    "generic": [("issuer", "", False), ("issue_date", "", False)],
}

# OCR text -> template guess. Only a suggestion with its reason; never applied without a person.
_TYPE_HINTS = [
    (re.compile(r"^P[<A-Z][A-Z<]{3}", re.M), "passport", "machine-readable passport zone", 0.9),
    (re.compile(r"\bpassport\b", re.I), "passport", "the word 'passport'", 0.6),
    (re.compile(r"^V[<A-Z][A-Z<]{3}", re.M), "visa", "machine-readable visa zone", 0.85),
    (re.compile(r"\b(?:entry\s+)?visa\b", re.I), "visa", "the word 'visa'", 0.55),
    (re.compile(r"\b(?:iqama|residen(?:ce|t)\s+(?:permit|identity))\b", re.I), "iqama", "residence permit wording", 0.6),
    (re.compile(r"\bdriv(?:ing|er'?s?)\s+licen[cs]e\b", re.I), "driving_license", "driving licence wording", 0.65),
    (re.compile(r"\b(?:national\s+id(?:entity)?(?:\s+card)?|identity\s+card)\b", re.I), "national_id", "identity card wording", 0.55),
    (re.compile(r"\b(?:insurance\s+policy|policy\s+(?:no|number)|insured)\b", re.I), "insurance", "insurance wording", 0.5),
    (re.compile(r"\b(?:birth|marriage|degree|graduation)\s+certificate\b|\bcertificate\s+of\b", re.I),
     "certificate", "certificate wording", 0.5),
]


class TypeError_(DomainError):  # noqa: N801 - "TypeError" would shadow the builtin
    """A refused classification / template change; a DomainError, so views answer 400 with the message."""


# ------------------------------------------------------------------ templates

def standard_label(key: str) -> str:
    return STANDARD.get(key, (key.replace("_", " ").capitalize(),))[0]


def template_defs(template: str, has_expiry: bool = False) -> list[dict]:
    rows = list(TEMPLATES.get(template) or TEMPLATES["generic"])
    keys = [k for k, _l, _r in rows]
    if has_expiry and "expiry_date" not in keys:
        rows.append(("expiry_date", "", False))
    out = []
    for i, (key, label, required) in enumerate(rows):
        std_label, ftype, role, searchable, choices = STANDARD[key]
        out.append({"key": key, "label": label or std_label, "field_type": ftype, "role": role, "required": required,
                    "searchable": searchable, "choices": list(choices), "order": (i + 1) * 10, "extract": True})
    return out


def ensure_template(t: DocumentType, extra_keys: list[str] | None = None) -> int:
    """Create the default template fields of a type that has none (idempotent). Returns the number created."""
    have = set(t.template_fields.values_list("key", flat=True))
    defs = template_defs(t.template, t.has_expiry)
    order = max([d["order"] for d in defs] or [0])
    for k in extra_keys or []:
        if k in STANDARD and k not in [d["key"] for d in defs]:
            order += 10
            label, ftype, role, searchable, choices = STANDARD[k]
            defs.append({"key": k, "label": label, "field_type": ftype, "role": role, "required": False,
                         "searchable": searchable, "choices": list(choices), "order": order, "extract": True})
    n = 0
    for d in defs:
        if d["key"] not in have:
            DocumentTypeField.objects.create(doc_type=t, **d)
            n += 1
    sync_ocr_fields(t)
    return n


def sync_ocr_fields(t: DocumentType) -> None:
    """Keep the Change Set K `ocr_fields` list equal to the template's enabled, extractable standard fields."""
    keys = list(t.template_fields.filter(enabled=True, extract=True).values_list("key", flat=True))
    if t.ocr_fields != keys:
        DocumentType.objects.filter(pk=t.pk).update(ocr_fields=keys)
        t.ocr_fields = keys


def active_fields(t: DocumentType | None) -> list[DocumentTypeField]:
    if t is None:
        return []
    return list(t.template_fields.filter(enabled=True))


def field_json(f: DocumentTypeField) -> dict:
    return {"id": f.id, "key": f.key, "label": f.label, "field_type": f.field_type, "enabled": f.enabled,
            "required": f.required, "order": f.order, "help_text": f.help_text, "extract": f.extract,
            "searchable": f.searchable, "role": f.role, "choices": f.choices, "validation": f.validation}


def type_json(t: DocumentType, *, admin: bool = False) -> dict:
    data = {"id": t.id, "name": t.name, "emoji": t.emoji, "description": t.description, "has_expiry": t.has_expiry,
            "archived": t.archived, "template": t.template}
    if admin:
        data.update({"fields": [field_json(f) for f in t.template_fields.all()], "sort_order": t.sort_order,
                     "reminder_days": t.reminder_days, "is_custom": t.is_custom, "ocr_mode": t.ocr_mode,
                     "ocr_languages": t.ocr_languages, "ocr_ai_allowed": t.ocr_ai_allowed,
                     "documents": t.documents.filter(archived_at__isnull=True).count()})
    return data


# ------------------------------------------------------------------ validation

def validate_value(value: str, ftype: str, *, label: str = "Value", choices=None, validation=None) -> str:
    """Normalise a value for a field type; raises TypeError_ with a readable message."""
    from .extraction import parse_date

    value = (value or "").strip()
    validation = validation or {}
    if not value:
        return ""
    if ftype == "date":
        parsed = parse_date(value)
        if parsed is None:
            raise TypeError_(f"{label}: enter a date as YYYY-MM-DD.")
        value = parsed.isoformat()
    elif ftype == "number":
        try:
            num = float(value)
        except ValueError:
            raise TypeError_(f"{label} must be a number.") from None
        if "min" in validation and num < float(validation["min"]):
            raise TypeError_(f"{label} must be at least {validation['min']}.")
        if "max" in validation and num > float(validation["max"]):
            raise TypeError_(f"{label} must be at most {validation['max']}.")
    elif ftype == "boolean":
        low = value.lower()
        if low not in ("yes", "no", "true", "false"):
            raise TypeError_(f"{label}: choose yes or no.")
        value = "yes" if low in ("yes", "true") else "no"
    elif ftype == "select":
        if choices and value not in choices:
            raise TypeError_(f"{label} must be one of: {', '.join(choices)}.")
    limit = int(validation.get("max_length") or (5000 if ftype == "long_text" else 300))
    if len(value) > limit:
        raise TypeError_(f"{label} is longer than {limit} characters.")
    pattern = validation.get("pattern")
    if pattern and ftype in ("text", "identifier", "person", "country"):
        try:
            if not re.fullmatch(pattern, value):
                raise TypeError_(f"{label} does not have the expected format.")
        except re.error:
            pass  # an invalid pattern is rejected when it is saved; never block a value because of it
    return value


def validate_template_field(d: dict, *, existing: DocumentTypeField | None = None) -> dict:
    """Server-side check of a template field definition coming from the settings screen."""
    out = {}
    if existing is None:
        key = (d.get("key") or "").strip().lower()
        if not key:
            key = re.sub(r"[^a-z0-9]+", "_", (d.get("label") or "").lower()).strip("_")[:60]
            if key and key[0].isdigit():
                key = "f_" + key
        if not KEY_RX.match(key or ""):
            raise TypeError_("The field key must start with a letter and use a-z, 0-9 and _.")
        out["key"] = key
    if "label" in d or existing is None:
        label = (d.get("label") or "").strip()[:80]
        if not label:
            raise TypeError_("Enter a label for the field.")
        out["label"] = label
    if "field_type" in d:
        if d["field_type"] not in DocumentTypeField.TYPES:
            raise TypeError_("Unknown field type.")
        out["field_type"] = d["field_type"]
    if "role" in d:
        if (d["role"] or "") not in DocumentTypeField.ROLES:
            raise TypeError_("Unknown role.")
        out["role"] = d["role"] or ""
    for b in ("enabled", "required", "extract", "searchable"):
        if b in d:
            out[b] = bool(d[b])
    if "help_text" in d:
        out["help_text"] = str(d["help_text"] or "")[:300]
    if "order" in d:
        try:
            out["order"] = int(d["order"])
        except (TypeError, ValueError):
            raise TypeError_("Order must be a number.") from None
    if "choices" in d:
        ch = d["choices"] if isinstance(d["choices"], list) else str(d["choices"] or "").split(",")
        out["choices"] = [str(c).strip()[:80] for c in ch if str(c).strip()][:50]
    if "validation" in d:
        v = d["validation"] if isinstance(d["validation"], dict) else {}
        clean = {}
        if v.get("pattern"):
            try:
                re.compile(str(v["pattern"]))
            except re.error:
                raise TypeError_("The validation pattern is not a valid regular expression.") from None
            clean["pattern"] = str(v["pattern"])[:200]
        for k in ("min", "max", "max_length"):
            if v.get(k) not in (None, ""):
                try:
                    clean[k] = float(v[k]) if k != "max_length" else int(v[k])
                except (TypeError, ValueError):
                    raise TypeError_(f"Validation '{k}' must be a number.") from None
        out["validation"] = clean
    ftype = out.get("field_type", existing.field_type if existing else "text")
    role = out.get("role", existing.role if existing else "")
    if role in ("expiry", "issue") and ftype != "date":
        raise TypeError_("Only a date field can be the expiry or issue date.")
    if role == "no_expiry" and ftype != "boolean":
        raise TypeError_("Only a yes/no field can say that a document does not expire.")
    if ftype == "select" and not out.get("choices", existing.choices if existing else []):
        raise TypeError_("A list field needs at least one choice.")
    return out


def template_field_for(doc: Document, key: str) -> DocumentTypeField | None:
    if not doc.doc_type_id:
        return None
    return DocumentTypeField.objects.filter(doc_type_id=doc.doc_type_id, key=key, enabled=True).first()


def check_value(doc: Document, key: str, value: str) -> str:
    """Normalise/validate a value for this document's template (or the standard definition)."""
    tf = template_field_for(doc, key)
    if tf is not None:
        return validate_value(value, tf.field_type, label=tf.label, choices=tf.choices, validation=tf.validation)
    if key in STANDARD:
        label, ftype, _r, _s, choices = STANDARD[key]
        return validate_value(value, ftype, label=label, choices=choices)
    return validate_value(value, "text", label="Value")


# ------------------------------------------------------------------ roles: dates and reminders

def role_keys(doc: Document) -> dict:
    """Which field keys carry the issue / expiry / no-expiry meaning for this document."""
    if doc.doc_type_id:
        fields = active_fields(doc.doc_type)
        if fields:
            out = {}
            for f in fields:
                if f.role and f.role not in out:
                    out[f.role] = f.key
            return out
    return {"issue": "issue_date", "expiry": "expiry_date", "no_expiry": "no_expiry"}


def details_status(doc: Document) -> dict:
    fields = list(doc.fields.all())
    proposed = sum(1 for f in fields if f.status == DocumentField.PROPOSED and f.scope != DocumentField.UNMAPPED)
    unmapped = sum(1 for f in fields if f.scope == DocumentField.UNMAPPED)
    flagged = sum(1 for f in fields if f.flags and f.status == DocumentField.CONFIRMED)
    confirmed = {f.key for f in fields if f.status == DocumentField.CONFIRMED and f.value}
    expiry_key = role_keys(doc).get("expiry")
    missing = [f.label for f in active_fields(doc.doc_type) if f.required and f.key not in confirmed
               and not (doc.no_expiry and f.key == expiry_key)]  # "does not expire" answers a required expiry date
    if not fields and not doc.doc_type_id:
        status = "empty"
    elif proposed or unmapped or flagged or (doc.type_suggestions and not doc.type_confirmed):
        status = "needs_review"
    elif missing and not doc.details_incomplete_ok:
        status = "incomplete"
    elif not fields:
        status = "empty"
    else:
        status = "confirmed"
    return {"status": status, "proposed": proposed, "unmapped": unmapped, "missing_required": missing,
            "incomplete_ok": doc.details_incomplete_ok}


# ------------------------------------------------------------------ OCR / AI proposals

def allowed_extract_keys(doc: Document) -> set[str] | None:
    """None = any key (untyped documents keep the earlier behaviour)."""
    fields = active_fields(doc.doc_type) if doc.doc_type_id else []
    if not fields:
        return None
    return {f.key for f in fields if f.extract}


def store_proposals(doc: Document, proposals, version=None, *, source: str | None = None) -> int:
    """Save OCR / AI proposals as suggestions. Confirmed values are never replaced: a different new value is shown
    next to them instead. Returns the number of suggestions written."""
    allowed = allowed_extract_keys(doc)
    existing = {f.key: f for f in doc.fields.all()}
    n = 0
    for p in proposals:
        if allowed is not None and p.key not in allowed:
            continue
        f = existing.get(p.key)
        if f and f.status == DocumentField.CONFIRMED:
            if f.value != p.value:
                f.proposed_value = p.value
                note = (f"New scan suggests '{p.value}'." if p.key not in DocumentField.SENSITIVE
                        else "New scan suggests a different value.")
                f.flags = list(set((f.flags or []) + [note]))
                f.save(update_fields=["proposed_value", "flags", "updated_at"])
            continue
        DocumentField.objects.update_or_create(
            document=doc, key=p.key,
            defaults={"value": p.value, "status": DocumentField.PROPOSED, "source": source or p.source,
                      "version": version, "confidence": p.confidence, "flags": p.flags, "scope": DocumentField.TYPE,
                      "overridden": False,
                      "source_excerpt": "" if p.key in DocumentField.SENSITIVE else (p.excerpt or "")[:300]})
        n += 1
    return n


@dataclass
class TypeGuess:
    type_id: int
    name: str
    reason: str
    confidence: float


def guess_type(text: str) -> TypeGuess | None:
    """Best keyword / MRZ guess for the document's type from its recognised text."""
    if not text:
        return None
    head = text[:20000]
    best = None
    for rx, template, reason, conf in _TYPE_HINTS:
        if rx.search(head) and (best is None or conf > best[2]):
            best = (template, reason, conf)
    if best is None:
        return None
    t = (DocumentType.objects.filter(archived=False, template=best[0]).order_by("is_custom", "sort_order", "name").first())
    if t is None:
        return None
    return TypeGuess(t.id, t.name, best[1], best[2])


def add_suggestion(doc: Document, type_id: int, source: str, reason: str, confidence: float | None = None) -> bool:
    """Record a pending type suggestion (deduplicated). A confirmed type is never replaced by one."""
    if doc.type_confirmed and doc.doc_type_id == type_id:
        return False
    if any(s.get("type") == type_id and s.get("source") == source for s in doc.type_suggestions or []):
        return False
    t = DocumentType.objects.filter(pk=type_id, archived=False).first()
    if t is None:
        return False
    sug = list(doc.type_suggestions or []) + [{"type": t.id, "name": t.name, "source": source, "reason": reason[:200],
                                               "confidence": confidence, "at": timezone.now().isoformat()}]
    Document.objects.filter(pk=doc.pk).update(type_suggestions=sug)
    doc.type_suggestions = sug
    return True


def suggest_from_text(doc: Document, text: str) -> None:
    g = guess_type(text)
    if g and not (doc.type_confirmed and doc.doc_type_id == g.type_id):
        if doc.type_confirmed and doc.doc_type_id:
            add_suggestion(doc, g.type_id, "ocr", f"Recognised text: {g.reason}. The confirmed type was kept.", g.confidence)
        else:
            add_suggestion(doc, g.type_id, "ocr", f"Recognised text: {g.reason}.", g.confidence)


def folder_suggestion(folder: Folder | None) -> DocumentType | None:
    """The nearest folder (itself or an ancestor) with a suggested type."""
    seen = 0
    while folder is not None and seen < 50:
        if folder.suggested_type_id:
            t = folder.suggested_type
            return t if t and not t.archived else None
        folder = folder.parent
        seen += 1
    return None


def suggestions_json(doc: Document) -> list[dict]:
    out = []
    names = dict(DocumentType.objects.filter(pk__in=[s.get("type") for s in doc.type_suggestions or []]).values_list("id", "name"))
    for i, s in enumerate(doc.type_suggestions or []):
        if s.get("type") not in names or s.get("type") == doc.doc_type_id:
            continue
        out.append({"index": i, "type": s["type"], "name": names[s["type"]], "source": s.get("source"),
                    "source_label": SOURCE_LABELS.get(s.get("source"), s.get("source")), "reason": s.get("reason", ""),
                    "confidence": s.get("confidence")})
    if len({s["type"] for s in out}) > 1:
        for s in out:
            s["conflict"] = True
    return out


# ------------------------------------------------------------------ changing the type

def plan_change(doc: Document, new_type: DocumentType | None) -> dict:
    """What happens to each value when the document becomes `new_type` (nothing is changed)."""
    from .services import mask

    tfields = {f.key: f for f in active_fields(new_type)} if new_type else {}
    keep, unmapped, custom = [], [], []
    for f in doc.fields.all().order_by("key"):
        label = f.label or (tfields[f.key].label if f.key in tfields else standard_label(f.key))
        item = {"key": f.key, "label": label, "value": mask(f.key, f.value), "status": f.status, "source": f.source}
        if f.scope == DocumentField.CUSTOM:
            custom.append(item)
            continue
        if new_type is None or not tfields:
            keep.append(item)
            continue
        tf = tfields.get(f.key)
        if tf is None:
            unmapped.append({**item, "reason": "not part of the new type"})
            continue
        try:
            validate_value(f.value, tf.field_type, label=tf.label, choices=tf.choices, validation=tf.validation)
        except TypeError_ as exc:
            unmapped.append({**item, "reason": str(exc)})
            continue
        keep.append({**item, "label": tf.label})
    have = {k["key"] for k in keep}
    empty = [{"key": f.key, "label": f.label, "required": f.required} for f in tfields.values() if f.key not in have]
    effect = None
    if doc.expiry_date:
        rk = _role_keys_for(new_type).get("expiry")
        if not rk or rk not in have:
            effect = "The expiry date no longer applies, so expiry reminders for this document stop until it is mapped again."
    return {"from": doc.doc_type.name if doc.doc_type_id else None, "to": new_type.name if new_type else None,
            "keep": keep, "unmapped": unmapped, "custom": custom, "new_fields": empty, "reminder_effect": effect,
            "ocr_available": bool((doc.content_text or "").strip())}


def _role_keys_for(t: DocumentType | None) -> dict:
    if t is None:
        return {"issue": "issue_date", "expiry": "expiry_date", "no_expiry": "no_expiry"}
    out = {}
    for f in active_fields(t):
        if f.role and f.role not in out:
            out[f.role] = f.key
    return out or {"issue": "issue_date", "expiry": "expiry_date", "no_expiry": "no_expiry"}


def change_type(*, actor, doc: Document, new_type: DocumentType | None, source: str = "manual", request=None) -> dict:
    """Assign or change the type, keeping every value: compatible values stay, the rest become reviewable
    'previous metadata'. The file, its versions and its folder are untouched."""
    from . import search as searchlib
    from . import services as S

    if new_type is not None and new_type.archived and new_type.pk != doc.doc_type_id:
        raise TypeError_("This document type is archived. Choose an active type.")
    if source not in Document.TYPE_SOURCES:
        source = "manual"
    plan = plan_change(doc, new_type)
    old_name = doc.doc_type.name if doc.doc_type_id else None
    unmapped_keys = {u["key"] for u in plan["unmapped"]}
    with transaction.atomic():
        doc = Document.objects.select_for_update().get(pk=doc.pk)
        for f in doc.fields.exclude(scope=DocumentField.CUSTOM):
            if f.key in unmapped_keys:
                if f.scope != DocumentField.UNMAPPED:
                    f.scope, f.previous_type = DocumentField.UNMAPPED, old_name or ""
                    f.label = f.label or standard_label(f.key)
                    f.save(update_fields=["scope", "previous_type", "label", "updated_at"])
            elif f.scope == DocumentField.UNMAPPED:  # maps cleanly onto the new template
                f.scope = DocumentField.TYPE
                f.save(update_fields=["scope", "updated_at"])
        doc.doc_type = new_type
        doc.type_source = source if new_type else ""
        doc.type_confirmed = new_type is not None
        doc.type_suggestions = [s for s in doc.type_suggestions or [] if new_type is None or s.get("type") != new_type.pk]
        if new_type is not None:
            doc.type_suggestions = []  # decided by a person
        doc.details_incomplete_ok = False
        doc.save(update_fields=["doc_type", "type_source", "type_confirmed", "type_suggestions",
                                "details_incomplete_ok", "updated_at"])
        S._history(doc, actor, "type_changed", old=old_name, new=new_type.name if new_type else None, source=source,
                   unmapped=len(unmapped_keys))
        S.apply_confirmed_fields(doc)
    audit.record("document.type_change", request=request, actor=actor, target=doc,
                 subject_user=doc.owner, old=old_name, new=new_type.name if new_type else None, source=source)
    searchlib.update_search_vector(doc)
    from apps.notify.events import documents_changed

    documents_changed(actor=actor, doc=doc, change=f"set the type ({new_type.name if new_type else 'not assigned'}) of")
    return plan


def resolve_unmapped(*, actor, doc: Document, key: str, action: str, to: str = "") -> None:
    """Map a previous value onto a template field, keep it as a detail of this document, or remove it."""
    from . import services as S

    f = doc.fields.filter(key=key, scope=DocumentField.UNMAPPED).first()
    if f is None:
        raise TypeError_("There is no previous value with this name.")
    if action == "keep":
        f.scope = DocumentField.CUSTOM
        f.label = f.label or standard_label(key)
        f.save(update_fields=["scope", "label", "updated_at"])
        S._history(doc, actor, "previous_value_kept", key=key)
    elif action == "remove":
        f.delete()
        S._history(doc, actor, "previous_value_removed", key=key)
    elif action == "map":
        tf = template_field_for(doc, to)
        if tf is None:
            raise TypeError_("Choose a field of this document's type.")
        target = doc.fields.filter(key=to).exclude(pk=f.pk).first()
        if target is not None and target.value and target.scope != DocumentField.UNMAPPED:
            raise TypeError_(f"{tf.label} already has a value. Clear it first or keep this value as a detail.")
        value = validate_value(f.value, tf.field_type, label=tf.label, choices=tf.choices, validation=tf.validation)
        with transaction.atomic():
            if target is not None:
                target.delete()
            f.key, f.value, f.scope, f.label = to, value, DocumentField.TYPE, ""
            f.status, f.confirmed_by, f.confirmed_at = DocumentField.CONFIRMED, actor, timezone.now()
            f.save()
        S._history(doc, actor, "previous_value_mapped", key=key, to=to)
    else:
        raise TypeError_("Unknown action.")
    S.apply_confirmed_fields(doc)


def remap_ocr(*, actor, doc: Document) -> int:
    """Run the field extraction again on the text already recognised, for the current type (no new OCR scan)."""
    from . import services as S
    from .extraction import extract
    from .ocr_runs import document_text

    text = document_text(doc) or doc.content_text or ""
    if not text.strip():
        raise TypeError_("This document has no recognised text yet. Run OCR first.")
    owner_names = [n for n in (doc.owner.display_name, doc.owner.full_name) if n]
    template = doc.doc_type.template if doc.doc_type_id else "generic"
    n = store_proposals(doc, extract(text, owner_names=owner_names, template=template), doc.current_version)
    S._history(doc, actor, "ocr_remapped", type=doc.doc_type.name if doc.doc_type_id else None, suggestions=n)
    S.apply_confirmed_fields(doc)
    return n


# ------------------------------------------------------------------ custom details and promotion

def custom_key(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")[:50]
    return f"custom:{slug or 'detail'}"


def promote(*, actor, doc_type: DocumentType, doc: Document, key: str, request=None) -> DocumentTypeField:
    """Add one document's custom detail to its type's template (explicit administrator action). Other documents
    are not changed; they simply show the new, empty template field."""
    f = doc.fields.filter(key=key).exclude(scope=DocumentField.TYPE).first()
    if f is None:
        raise TypeError_("Only an additional detail of this document can be added to the template.")
    if doc.doc_type_id != doc_type.pk:
        raise TypeError_("The document is not of this type.")
    label = f.label or standard_label(key.removeprefix("custom:"))
    new_key = key.removeprefix("custom:")
    if not KEY_RX.match(new_key):
        new_key = re.sub(r"[^a-z0-9_]", "_", new_key.lower()).lstrip("_0123456789")[:60] or "detail"
    if doc_type.template_fields.filter(key=new_key).exists():
        raise TypeError_(f"The template already has a field '{new_key}'.")
    order = (doc_type.template_fields.order_by("-order").values_list("order", flat=True).first() or 0) + 10
    std = STANDARD.get(new_key)
    tf = DocumentTypeField.objects.create(doc_type=doc_type, key=new_key, label=label[:80],
                                          field_type=std[1] if std else "text", role=std[2] if std else "",
                                          order=order, extract=bool(std), searchable=std[3] if std else True,
                                          choices=list(std[4]) if std else [])
    with transaction.atomic():
        doc.fields.filter(key=new_key).exclude(pk=f.pk).delete()
        f.key, f.scope, f.label = new_key, DocumentField.TYPE, ""
        f.save(update_fields=["key", "scope", "label", "updated_at"])
    sync_ocr_fields(doc_type)
    audit.record("settings.document_type_field_promote", request=request, target_type="document_type",
                 target_id=str(doc_type.pk), key=new_key)
    return tf


# ------------------------------------------------------------------ reports

def report() -> dict:
    qs = Document.objects.filter(archived_at__isnull=True)
    typed = qs.filter(doc_type__isnull=False).count()
    untyped = qs.filter(doc_type__isnull=True).count()
    suggested = qs.filter(doc_type__isnull=True).exclude(type_suggestions=[]).count()
    folder_hint = sum(1 for d in qs.filter(doc_type__isnull=True).select_related("folder")[:5000]
                      if folder_suggestion(d.folder) is not None)
    return {"typed": typed, "untyped": untyped, "with_suggestions": suggested, "folder_suggestions": folder_hint,
            "unmapped_values": DocumentField.objects.filter(scope=DocumentField.UNMAPPED,
                                                            document__archived_at__isnull=True).count()}
