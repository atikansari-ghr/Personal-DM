"""Shared fixtures. All data is synthetic; no real names, documents or credentials."""
from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from fixtures import make_image_pdf, make_text_pdf  # noqa: F401 - re-exported for tests

PASSWORD = "Sample-Passw0rd!"

SYNTHETIC_FAMILY = [
    ("dad", "Alex Sample", "dad"),
    ("mom", "Maria Sample", "mom"),
    ("son1", "Sam Sample", "son1"),
    ("daughter", "Dana Sample", "daughter"),
    ("son2", "Theo Sample", "son2"),
    ("son3", "Leo Sample", "son3"),
]


@pytest.fixture(autouse=True)
def _clean_config(settings, tmp_path, monkeypatch):
    """Each test gets its own storage directories and encryption key."""
    from django.db import transaction

    from apps.core import crypto

    # Test transactions never commit, so run on_commit hooks (job enqueues, file cleanup) immediately.
    monkeypatch.setattr(transaction, "on_commit", lambda fn, using=None, robust=False: fn())

    settings.DATA_DIR = tmp_path / "data"
    settings.CONFIG_DIR = tmp_path / "config"
    settings.ORIGINALS_DIR = settings.DATA_DIR / "storage" / "originals"
    settings.DERIVATIVES_DIR = settings.DATA_DIR / "storage" / "derivatives"
    settings.STAGING_DIR = settings.DATA_DIR / "staging"
    settings.TMP_DIR = settings.DATA_DIR / "tmp"
    settings.EXPORT_TMP_DIR = settings.DATA_DIR / "exports"
    crypto.reset_cache()
    crypto.ensure_key()  # the installer always creates the key
    from apps.library import storage

    storage.ensure_dirs()
    yield
    crypto.reset_cache()


def setup_payload(**extra):
    return {
        "group_name": "My family",
        "timezone": "Asia/Riyadh",
        "members": [
            {"slot": slot, "display_name": name, "username": user, "password": PASSWORD}
            for slot, name, user in SYNTHETIC_FAMILY
        ],
        **extra,
    }


@pytest.fixture
def family(db):
    from django.core.management import call_command

    from apps.accounts import services as S
    from apps.accounts.models import User

    call_command("seed_defaults", stdout=io.StringIO())  # transactional tests flush migration-seeded rows
    S.complete_setup(setup_payload())
    users = {u.username: u for u in User.objects.all()}
    User.objects.update(must_change_password=False)
    for u in users.values():
        u.refresh_from_db()
    return users


def client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    s = c.session
    s["epoch"] = user.session_epoch
    s["reauth_at"] = __import__("django.utils.timezone", fromlist=["now"]).now().isoformat()
    s.save()
    return c


@pytest.fixture
def clients(family):
    return {name: client_for(u) for name, u in family.items()}


def personal_root(user):
    from apps.library.models import Folder

    return Folder.objects.get(owner=user, kind=Folder.PERSONAL_ROOT)


def upload(client, folder, name="sample.pdf", content=None, **data):
    content = content if content is not None else make_text_pdf("Sample document")
    f = SimpleUploadedFile(name, content, content_type="application/octet-stream")
    return client.post("/api/documents", {"folder": str(folder.id), "files": [f], **data}, format="multipart")


def run_jobs():
    from apps.core import jobs

    return jobs.run_pending(max_jobs=1000, heavy_limit=4)
