"""Shared fixtures. All data is synthetic; no real names, documents or credentials."""
from __future__ import annotations

import io
import zlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

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
    from apps.accounts import services as S
    from apps.accounts.models import User

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


def make_text_pdf(text: str) -> bytes:
    """Minimal born-digital PDF with real text (synthetic content)."""
    lines = text.split("\n")
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({ln.replace('(', '').replace(')', '')}) Tj T*" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_image_pdf(text: str) -> bytes:
    """Image-only PDF (a 'scan') containing rendered synthetic text."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1700, 1100), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 56)
    except OSError:
        font = ImageFont.load_default(size=56)
    y = 120
    for line in text.split("\n"):
        d.text((100, y), line, fill="black", font=font)
        y += 110
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    return buf.getvalue()


def upload(client, folder, name="sample.pdf", content=None, **data):
    content = content if content is not None else make_text_pdf("Sample document")
    f = SimpleUploadedFile(name, content, content_type="application/octet-stream")
    return client.post("/api/documents", {"folder": str(folder.id), "files": [f], **data}, format="multipart")


def run_jobs():
    from apps.core import jobs

    return jobs.run_pending(max_jobs=1000, heavy_limit=4)
