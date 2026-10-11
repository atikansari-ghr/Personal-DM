"""Backup Recovery Key generations and Recovery Readiness.

The key is created on the first encrypted backup and stored only encrypted with the installation key. It is shown
to the main administrator on request (after step-up authentication); it is never logged, audited, notified, or
written to diagnostics. ``readiness()`` reports whether an Emergency Recovery Package for the active generation
was exported - only metadata, never where it is kept.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core import config, crypto

from . import bk_crypto as C
from .models import EmergencyExport, RecoveryCopy, RecoveryKey


def active() -> RecoveryKey | None:
    return RecoveryKey.objects.filter(state=RecoveryKey.ACTIVE).order_by("-generation").first()


@transaction.atomic
def ensure_active() -> RecoveryKey:
    row = RecoveryKey.objects.select_for_update().filter(state=RecoveryKey.ACTIVE).order_by("-generation").first()
    if row is not None:
        return row
    raw = C.new_recovery_key()
    gen = (RecoveryKey.objects.order_by("-generation").values_list("generation", flat=True).first() or 0) + 1
    return RecoveryKey.objects.create(generation=gen, key_enc=crypto.encrypt(C.format_key(raw)), fingerprint=C.fingerprint(raw),
                                      state=RecoveryKey.ACTIVE, activated_at=timezone.now())


def raw_key(generation: int) -> bytes:
    row = RecoveryKey.objects.filter(generation=generation).exclude(state=RecoveryKey.RETIRED).first()
    if row is None:
        raise C.DecryptError(f"Recovery Key generation {generation} is not available on this installation.")
    return C.parse_key(crypto.decrypt(row.key_enc))


def reveal_text(generation: int) -> str:
    """Formatted key for the reveal dialog. Callers must have checked main-administrator step-up authentication."""
    return C.format_key(raw_key(generation))


def new_pending() -> tuple[RecoveryKey, bytes]:
    raw = C.new_recovery_key()
    gen = (RecoveryKey.objects.order_by("-generation").values_list("generation", flat=True).first() or 0) + 1
    row = RecoveryKey.objects.create(generation=gen, key_enc=crypto.encrypt(C.format_key(raw)), fingerprint=C.fingerprint(raw),
                                     state=RecoveryKey.PENDING)
    return row, raw


def retire_unused() -> list[int]:
    """Retire old generations that no retained copy references any more (only after verified migration)."""
    out = []
    for row in RecoveryKey.objects.filter(state=RecoveryKey.RETIRING):
        if not RecoveryCopy.objects.filter(generation=row.generation).exclude(state=RecoveryCopy.DELETED).exists():
            row.state, row.retired_at = RecoveryKey.RETIRED, timezone.now()
            row.key_enc = ""  # only now is the old material destroyed: nothing retained needs it
            row.save(update_fields=["state", "retired_at", "key_enc"])
            out.append(row.generation)
    return out


def readiness() -> dict:
    """Recovery Readiness: Not Ready (no package) / Outdated (package is for an older generation) / Ready."""
    key = active()
    last = EmergencyExport.objects.first()
    if key is None:
        return {"state": "no_key", "label": "No Recovery Key yet", "detail": "The key is created with the first encrypted backup.",
                "generation": None, "exported_at": None, "exported_generation": None}
    current = EmergencyExport.objects.filter(generation=key.generation).first()
    if current:
        state, label = "ready", "Ready"
        detail = "An Emergency Recovery Package for the current key was exported."
    elif last:
        state, label = "outdated", "Outdated"
        detail = "The Recovery Key was rotated after the last export. Export a new Emergency Recovery Package."
    else:
        state, label = "not_exported", "Not Ready"
        detail = "No Emergency Recovery Package has been exported. Export one and store it offline."
    return {"state": state, "label": label, "detail": detail, "generation": key.generation, "fingerprint": key.fingerprint,
            "exported_at": (current or last).exported_at.isoformat() if (current or last) else None,
            "exported_generation": (current or last).generation if (current or last) else None}


def emergency_package(actor) -> dict:
    """Build (not store) an Emergency Recovery Package for the active generation; the caller seals it."""
    key = ensure_active()
    return {"generation": key.generation, "raw": raw_key(key.generation), "fingerprint": key.fingerprint,
            "installation": config.get("general.installation_id") or "personaldocs"}


INSTRUCTIONS = """PERSONAL DOCUMENTS MANAGEMENT SYSTEM - EMERGENCY RECOVERY PACKAGE

Keep this file OFFLINE (USB stick in a safe, password vault). Do not store it next to your backups.
It contains the Backup Recovery Key, sealed with the passphrase you chose when exporting it.
Without the passphrase this file cannot be opened. Nobody can reset the passphrase.

To recover onto a clean Debian 13 server:
  1. Run the installer and choose "Recover Existing Installation"
     (bash -c "$(curl -fsSL <your repository>/personal-DM.sh)" -- recover),
     or on an installed server: sudo personaldocs recover
  2. Choose where the encrypted backup is (USB/local folder, NAS, S3, Google Drive, OneDrive).
  3. When asked for the key, choose "Emergency Recovery Package", give the path of this file and type the passphrase.
  4. Review the Restore Impact Analysis, choose Normal or Compromise recovery, and follow the prompts.

Full runbook: docs/guides/disaster-recovery.md (also under Help -> Disaster recovery in the app).
"""
