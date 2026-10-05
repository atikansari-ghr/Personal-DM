"""Profile photos: validated, metadata-free, square WebP images stored privately.

* Only JPEG, PNG and WebP are accepted, judged by the decoded image content (not the file name or the
  browser's MIME type). Uploads are limited to 5 MB and 40 megapixels (decompression-bomb guard).
* The image is re-encoded from pixels only, so EXIF/GPS/XMP metadata is never kept; orientation is applied first.
* Stored as <data>/profile-photos/<random>.webp (512 px) and <random>-thumb.webp (96 px). The random name
  changes on every upload; files are only served through the authenticated API, never as static URLs.
* A photo is decoration only: identity and permissions always use the account id.
"""
from __future__ import annotations

import io
import os
import secrets
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
ALLOWED = {"JPEG", "PNG", "WEBP"}
FULL, THUMB = 512, 96


class PhotoError(ValueError):
    pass


def photo_dir() -> Path:
    return Path(settings.DATA_DIR) / "profile-photos"


def _crop_box(w: int, h: int, crop: dict | None) -> tuple[int, int, int, int]:
    side = min(w, h)
    if crop:
        try:
            x, y, size = float(crop.get("x", 0)), float(crop.get("y", 0)), float(crop.get("size", 0))
        except (TypeError, ValueError):
            raise PhotoError("Invalid crop values.")
        if size > 0:
            # Fractions of the (oriented) image: x/y of the top-left corner, size as a fraction of the shorter side.
            s = max(16, min(int(round(size * side)), side))
            left = int(round(x * w))
            top = int(round(y * h))
            left = max(0, min(left, w - s))
            top = max(0, min(top, h - s))
            return left, top, left + s, top + s
    left, top = (w - side) // 2, (h - side) // 2
    return left, top, left + side, top + side


def process(data: bytes, crop: dict | None = None) -> tuple[bytes, bytes]:
    if not data:
        raise PhotoError("Choose an image file.")
    if len(data) > MAX_BYTES:
        raise PhotoError("The image is larger than 5 MB.")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            w, h = probe.size
            probe.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError):
        raise PhotoError("This file is not a supported image (JPEG, PNG or WebP).")
    if fmt not in ALLOWED:
        raise PhotoError("Only JPEG, PNG and WebP images are supported.")
    if w * h > MAX_PIXELS or w < 16 or h < 16:
        raise PhotoError("The image dimensions are not supported (16 px to 40 megapixels).")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError):
        raise PhotoError("The image could not be read.")
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    square = img.crop(_crop_box(*img.size, crop))
    out = []
    for size in (FULL, THUMB):
        buf = io.BytesIO()
        square.resize((size, size), Image.Resampling.LANCZOS).save(buf, "WEBP", quality=85, method=4)  # no exif=...: metadata dropped
        out.append(buf.getvalue())
    return out[0], out[1]


def _write(name: str, data: bytes) -> None:
    photo_dir().mkdir(parents=True, exist_ok=True)
    path = photo_dir() / name
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def remove_files(user) -> None:
    for name in (user.photo_name, f"{user.photo_name}-thumb" if user.photo_name else ""):
        if name:
            (photo_dir() / f"{name}.webp").unlink(missing_ok=True)


def save(user, data: bytes, crop: dict | None = None) -> None:
    full, thumb = process(data, crop)
    old = user.photo_name
    name = secrets.token_hex(16)
    _write(f"{name}.webp", full)
    _write(f"{name}-thumb.webp", thumb)
    user.photo_name = name
    user.photo_updated_at = timezone.now()
    user.save(update_fields=["photo_name", "photo_updated_at"])
    if old:
        for n in (old, f"{old}-thumb"):
            (photo_dir() / f"{n}.webp").unlink(missing_ok=True)


def clear(user) -> None:
    remove_files(user)
    user.photo_name = ""
    user.photo_updated_at = None
    user.save(update_fields=["photo_name", "photo_updated_at"])


def path_for(user, thumb: bool) -> Path | None:
    if not user.photo_name:
        return None
    path = photo_dir() / (f"{user.photo_name}-thumb.webp" if thumb else f"{user.photo_name}.webp")
    return path if path.exists() else None


def version(user) -> str | None:
    return user.photo_updated_at.strftime("%Y%m%d%H%M%S") if user.photo_name and user.photo_updated_at else None
