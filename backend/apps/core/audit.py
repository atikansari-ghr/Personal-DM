"""Audit trail helper. Never pass passwords, tokens, OTPs, full document numbers or OCR text."""
from __future__ import annotations

import logging

from .models import AuditEvent

log = logging.getLogger("personaldocs.audit")

_FORBIDDEN_KEYS = {"password", "token", "otp", "code", "secret", "document_number", "text", "ocr_text"}


def client_ip(request) -> str | None:
    """Real client IP; forwarded headers are only trusted from PD_TRUSTED_PROXY_IPS (see security.netutil)."""
    from apps.security.netutil import client_ip as _client_ip

    return _client_ip(request)


def record(action: str, *, request=None, actor=None, outcome: str = "success", target=None, target_type: str = "",
           target_id: str = "", subject_user=None, **context) -> AuditEvent:
    if actor is None and request is not None and getattr(request, "user", None) is not None and request.user.is_authenticated:
        actor = request.user
    if target is not None:
        target_type = target_type or target.__class__.__name__.lower()
        target_id = target_id or str(target.pk)
    clean = {k: v for k, v in context.items() if k.lower() not in _FORBIDDEN_KEYS}
    event = AuditEvent.objects.create(
        actor=actor if (actor is not None and getattr(actor, "pk", None)) else None,
        actor_label=(getattr(actor, "username", "") or clean.pop("actor_label", "")) if actor else clean.pop("actor_label", ""),
        action=action,
        outcome=outcome,
        target_type=target_type,
        target_id=str(target_id),
        subject_user=subject_user,
        ip=client_ip(request),
        context=clean,
    )
    log.info("audit %s outcome=%s target=%s:%s", action, outcome, target_type, target_id)
    return event
