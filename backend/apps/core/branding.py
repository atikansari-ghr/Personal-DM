"""Sign-in page branding: preset designs, an optional custom wallpaper and logo.

Uploads are validated by decoded content (JPEG, PNG or WebP only; size and megapixel limits), re-encoded from pixels
so EXIF/GPS metadata is dropped, and stored locally under <data>/branding with a random name. They are served by
the application (no external CDN) because the sign-in page shows them before anyone signs in, so administrators
are told not to use private family photos.
"""
from __future__ import annotations

import io
import os
import secrets
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config

PRESETS = ("minimal", "nature", "travel", "family", "neutral")
ALLOWED = {"JPEG", "PNG", "WEBP"}
LIMITS = {
    # kind: (max upload bytes, max megapixels, min width, min height, longest stored side)
    "wallpaper": (10 * 1024 * 1024, 50_000_000, 800, 500, 2400),
    "logo": (2 * 1024 * 1024, 16_000_000, 32, 32, 512),
}
SETTING = {"wallpaper": "login.wallpaper_file", "logo": "login.logo_file"}


class BrandingError(ValueError):
    pass


def branding_dir() -> Path:
    return Path(settings.DATA_DIR) / "branding"


def process(kind: str, data: bytes) -> bytes:
    max_bytes, max_px, min_w, min_h, longest = LIMITS[kind]
    if not data:
        raise BrandingError("Choose an image file.")
    if len(data) > max_bytes:
        raise BrandingError(f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
    Image.MAX_IMAGE_PIXELS = max_px
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt, (w, h) = probe.format, probe.size
            probe.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError, ValueError):
        raise BrandingError("This file is not a supported image (JPEG, PNG or WebP).")
    if fmt not in ALLOWED:
        raise BrandingError("Only JPEG, PNG and WebP images are supported.")
    if w * h > max_px:
        raise BrandingError("The image has too many pixels.")
    if w < min_w or h < min_h:
        raise BrandingError(f"The image must be at least {min_w} × {min_h} pixels.")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError):
        raise BrandingError("The image could not be read.")
    keep_alpha = kind == "logo" and img.mode in ("RGBA", "LA", "P")
    img = img.convert("RGBA" if keep_alpha else "RGB")
    img.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82 if kind == "wallpaper" else 90, method=4)  # no exif=...: metadata dropped
    return buf.getvalue()


def save(kind: str, data: bytes, actor=None) -> str:
    out = process(kind, data)
    branding_dir().mkdir(parents=True, exist_ok=True)
    name = f"{kind}-{secrets.token_hex(12)}.webp"
    tmp = branding_dir() / f"{name}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(out)
    os.chmod(tmp, 0o640)
    os.replace(tmp, branding_dir() / name)
    old = config.get(SETTING[kind])
    config.set_value(SETTING[kind], name, actor=actor)
    if old and old != name:
        (branding_dir() / old).unlink(missing_ok=True)
    return name


def clear(kind: str, actor=None) -> None:
    old = config.get(SETTING[kind])
    config.set_value(SETTING[kind], "", actor=actor)
    if old:
        (branding_dir() / old).unlink(missing_ok=True)
    if kind == "wallpaper" and config.get("login.design") == "custom":
        config.set_value("login.design", "minimal", actor=actor)


def path_for(kind: str) -> Path | None:
    name = config.get(SETTING[kind])
    if not name or "/" in name or ".." in name:
        return None
    path = branding_dir() / name
    return path if path.exists() else None


def public() -> dict:
    """What the sign-in page needs (shown before sign-in, so nothing private)."""
    wall, logo = config.get("login.wallpaper_file"), config.get("login.logo_file")
    design = config.get("login.design")
    if design == "custom" and not wall:
        design = "minimal"
    return {"design": design, "title": config.get("login.title") or config.get("general.app_name"),
            "tagline": config.get("login.tagline"), "overlay": config.get("login.overlay"),
            "position": config.get("login.position"),
            "wallpaper": f"/api/branding/wallpaper?v={wall[10:18]}" if wall and design == "custom" else None,
            "has_wallpaper": bool(wall), "logo": f"/api/branding/logo?v={logo[5:13]}" if logo else None}
