"""Named sign-in designs (Change Set W): protected built-ins, custom designs with responsive wallpapers, a focal point,
contrast-aware colours, activation with Revert, reference-aware asset cleanup and a safe fallback.

Images are validated by decoded content (``branding.process``: JPEG, PNG or WebP, size and pixel limits) and
re-encoded, so EXIF/GPS data is dropped. The original (up to 4000 px) is kept; Desktop, Tablet and Mobile
derivatives are cropped around the focal point (``ImageOps.fit``), never stretched. Files are served only through a
design id and a variant name, never by file name.
"""
from __future__ import annotations

import colorsys
import io
import os
import secrets
from pathlib import Path

from django.db import transaction
from PIL import Image, ImageOps

from . import branding, config

BUILTINS = (("minimal", "Minimal (default)"), ("nature", "Nature"), ("travel", "Travel"), ("family", "Family"),
            ("neutral", "Neutral"))
DEFAULT_KEY = "minimal"
# Desktop: the wallpaper half of a wide screen; Tablet: landscape tablets; Mobile: the band above the form.
VARIANTS = {"desktop": (1600, 1500), "tablet": (1200, 900), "mobile": (1080, 540)}
ORIGINAL_LONGEST = 4000
PALETTE_KEYS = ("bg", "surface", "ink", "ink_soft", "heading", "muted", "brand", "brand_ink", "brand_soft", "line",
                "input_bg", "link")
ACTIVE, PREVIOUS = "login.active_design", "login.previous_design"


class DesignError(ValueError):
    pass


def _model():
    from .models import SigninDesign

    return SigninDesign


# ------------------------------------------------------------------ built-ins and the active design

def ensure_builtins():
    """The protected built-in templates always exist (idempotent)."""
    D = _model()
    for key, name in BUILTINS:
        D.objects.get_or_create(builtin_key=key, defaults={"name": name, "template": key})
    return D.objects.get(builtin_key=DEFAULT_KEY)


def default_design():
    return ensure_builtins()


def active():
    """The active design; a missing or unusable one falls back to the protected default (and is marked)."""
    D = _model()
    did = config.get(ACTIVE)
    d = D.objects.filter(pk=did).first() if did else None
    if d is None:
        return default_design()
    if not d.builtin and d.assets.get("original") and not _assets_ok(d):
        _mark_unavailable(d, "The wallpaper file is missing or damaged.")
        fallback = default_design()
        _set_active(fallback, actor=None, reason="fallback")
        _alert(f"The active sign-in design “{d.name}” could not be shown, so the built-in default is used. "
               "Open Settings → Overview & sign-in to repair or replace its wallpaper.", tag=f"design-fallback:{d.pk}")
        return fallback
    return d


def _set_active(d, *, actor, reason: str) -> None:
    """Atomic switch: active, previous, and the legacy settings a rollback to the previous release would read."""
    current = config.get(ACTIVE)
    with transaction.atomic():
        if current and int(current) != d.pk:
            config.set_value(PREVIOUS, int(current), actor=actor)
        config.set_value(ACTIVE, d.pk, actor=actor)
        if d.builtin:
            config.set_value("login.design", d.builtin_key, actor=actor)
        elif d.assets.get("original"):
            config.set_value("login.wallpaper_file", d.assets["original"], actor=actor)
            config.set_value("login.design", "custom", actor=actor)
        else:
            config.set_value("login.design", d.template if d.template in dict(BUILTINS) else DEFAULT_KEY, actor=actor)
    from . import audit

    audit.record("settings.signin_design_activate", actor=actor, target_type="signin_design", target_id=str(d.pk),
                 design=d.name, reason=reason)


def activate(d, *, actor=None, reason: str = "manual") -> None:
    if not d.builtin and d.assets.get("original") and not _assets_ok(d):
        raise DesignError("This design's wallpaper is missing or damaged. Replace the wallpaper first.")
    if d.state != d.OK and (d.builtin or _assets_ok(d)):
        d.state, d.state_detail = d.OK, ""
        d.save(update_fields=["state", "state_detail", "updated_at"])
    _set_active(d, actor=actor, reason=reason)


def apply_legacy_settings(changed, *, actor=None) -> None:
    """``login.design`` / ``login.overlay`` / ``login.position`` set through the generic settings API (clients from
    before Change Set W) act on the named designs: a built-in key activates that built-in, "custom" the migrated
    custom wallpaper design; overlay and position apply to the active custom design."""
    D = _model()
    if "login.design" in changed:
        key = config.get("login.design")
        target = D.objects.filter(builtin_key=key).first() if key != "custom" else \
            D.objects.filter(builtin_key__isnull=True).exclude(assets={}).order_by("-updated_at").first()
        if target is not None and str(config.get(ACTIVE) or "") != str(target.pk):
            activate(target, actor=actor, reason="legacy setting")
    d = active()
    if d.builtin:
        return
    if "login.overlay" in changed:
        d.overlay = int(config.get("login.overlay") or 0)
        d.save(update_fields=["overlay", "updated_at"])
    if "login.position" in changed:
        focal = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5)}
        update(d, dict(zip(("focal_x", "focal_y"), focal.get(config.get("login.position"), (0.5, 0.5)))), actor=actor)


def revert(*, actor=None):
    D = _model()
    prev = D.objects.filter(pk=config.get(PREVIOUS)).first() if config.get(PREVIOUS) else None
    if prev is None:
        raise DesignError("There is no previous design to go back to.")
    activate(prev, actor=actor, reason="revert")
    return prev


# ------------------------------------------------------------------ create, edit, delete

def create(*, name: str, template: str = DEFAULT_KEY, source=None, actor=None):
    D = _model()
    name = (name or "").strip()[:80]
    if not name:
        raise DesignError("Give the design a name.")
    if source is not None:  # Duplicate / Create from template: everything except the name; files are shared
        d = D(name=name, template=source.template, assets=dict(source.assets), focal_x=source.focal_x,
              focal_y=source.focal_y, overlay=source.overlay, color_mode=source.color_mode,
              analysis=dict(source.analysis), overrides=dict(source.overrides), palette=dict(source.palette),
              created_by=actor)
    else:
        if template not in dict(BUILTINS):
            raise DesignError("Choose one of the built-in templates.")
        d = D(name=name, template=template, created_by=actor)
    d.save()
    return d


def update(d, data: dict, *, actor=None):
    if d.builtin:
        raise DesignError("Built-in designs are protected. Duplicate it to make your own version.")
    if "name" in data:
        name = str(data["name"] or "").strip()[:80]
        if not name:
            raise DesignError("Give the design a name.")
        d.name = name
    for k in ("focal_x", "focal_y"):
        if k in data:
            try:
                v = float(data[k])
            except (TypeError, ValueError):
                raise DesignError("The focal point must be between 0 and 1.")
            if not 0 <= v <= 1:
                raise DesignError("The focal point must be between 0 and 1.")
            setattr(d, k, round(v, 3))
    if "overlay" in data:
        try:
            v = int(data["overlay"])
        except (TypeError, ValueError):
            raise DesignError("The overlay is a percentage from 0 to 80.")
        if not 0 <= v <= 80:
            raise DesignError("The overlay is a percentage from 0 to 80.")
        d.overlay = v
    if "template" in data:
        if data["template"] not in dict(BUILTINS):
            raise DesignError("Choose one of the built-in templates.")
        d.template = data["template"]
    if "color_mode" in data:
        if data["color_mode"] not in d.COLOR_MODES:
            raise DesignError("Choose Auto, Light, Dark or Custom.")
        d.color_mode = data["color_mode"]
    if "overrides" in data:
        d.overrides = clean_overrides(data["overrides"])
    focal_changed = any(k in data for k in ("focal_x", "focal_y"))
    d.save()
    if focal_changed and d.assets.get("original"):
        _make_derivatives(d)  # re-crop around the new focal point; colours follow the visible area
    refresh_palette(d)
    return d


def clean_overrides(raw) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        if k not in PALETTE_KEYS:
            continue
        v = str(v or "").strip()
        if not v:
            continue
        if not _is_hex(v):
            raise DesignError(f"{k}: use a colour such as #1f5135.")
        out[k] = v.lower()
    return out


def delete(d, *, actor=None) -> dict:
    """Deleting the active design first activates the protected default, atomically. Files only this design used
    are removed; shared and built-in files stay."""
    if d.builtin:
        raise DesignError("Built-in designs are protected and cannot be deleted.")
    D = _model()
    with transaction.atomic():
        was_active = str(config.get(ACTIVE) or "") == str(d.pk)
        if was_active:
            _set_active(default_design(), actor=actor, reason="active design deleted")
        if str(config.get(PREVIOUS) or "") == str(d.pk):
            config.set_value(PREVIOUS, None, actor=actor)
        files = set(d.assets.values())
        name, pk = d.name, d.pk
        d.delete()
        _remove_from_rotation(pk)
    removed = cleanup_files(files)
    from . import audit

    audit.record("settings.signin_design_delete", actor=actor, target_type="signin_design", target_id=str(pk),
                 design=name, files_removed=len(removed))
    return {"was_active": was_active, "files_removed": len(removed), "remaining": D.objects.count()}


def referenced_files() -> set:
    refs = set()
    for assets in _model().objects.values_list("assets", flat=True):
        refs |= {v for v in (assets or {}).values() if v}
    refs |= {config.get("login.wallpaper_file") or "", config.get("login.logo_file") or ""}
    refs.discard("")
    return refs


def cleanup_files(candidates) -> list[str]:
    refs = referenced_files()
    out = []
    for name in candidates:
        if not name or name in refs or "/" in name or ".." in name:
            continue
        path = branding.branding_dir() / name
        if path.exists():
            path.unlink()
            out.append(name)
    return out


def _remove_from_rotation(pk: int) -> None:
    rot = dict(config.get("login.rotation") or {})
    if pk in (rot.get("pool") or []):
        rot["pool"] = [x for x in rot["pool"] if x != pk]
        config.set_value("login.rotation", rot)


# ------------------------------------------------------------------ wallpaper and logo files

def _write(data: bytes, stem: str) -> str:
    branding.branding_dir().mkdir(parents=True, exist_ok=True)
    name = f"{stem}-{secrets.token_hex(10)}.webp"
    tmp = branding.branding_dir() / f"{name}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o640)
    os.replace(tmp, branding.branding_dir() / name)
    return name


def _encode(img: Image.Image, quality: int = 84) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)  # no exif: metadata is never written
    return buf.getvalue()


def set_wallpaper(d, data: bytes, *, actor=None):
    """Validate, keep the original (EXIF dropped), derive Desktop/Tablet/Mobile, re-run the Auto analysis.
    A Custom palette keeps the administrator's chosen colours."""
    if d.builtin:
        raise DesignError("Built-in designs are protected. Duplicate it to add a wallpaper.")
    branding.process("wallpaper", data)  # content validation: format, size, pixels, minimum size
    Image.MAX_IMAGE_PIXELS = branding.LIMITS["wallpaper"][1]
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((ORIGINAL_LONGEST, ORIGINAL_LONGEST), Image.Resampling.LANCZOS)
    old = {k: v for k, v in d.assets.items() if k != "logo"}
    assets = {k: v for k, v in d.assets.items() if k == "logo"}
    assets["original"] = _write(_encode(img, 90), "design-original")
    d.assets = assets
    d.focal_x, d.focal_y = 0.5, 0.5
    d.state, d.state_detail = d.OK, ""
    d.save()
    if str(config.get(ACTIVE) or "") == str(d.pk):  # keep the rollback setting on the new file before cleanup
        config.set_value("login.wallpaper_file", assets["original"], actor=actor)
    _make_derivatives(d, img)
    refresh_palette(d)
    cleanup_files(old.values())
    return d


def remove_wallpaper(d):
    if d.builtin:
        raise DesignError("Built-in designs are protected.")
    old = [v for k, v in d.assets.items() if k != "logo"]
    d.assets = {k: v for k, v in d.assets.items() if k == "logo"}
    d.analysis = {}
    d.save()
    if str(config.get(ACTIVE) or "") == str(d.pk):
        config.set_value("login.wallpaper_file", "")
        config.set_value("login.design", d.template if d.template in dict(BUILTINS) else DEFAULT_KEY)
    refresh_palette(d)
    cleanup_files(old)
    return d


def set_logo(d, data: bytes | None):
    if d.builtin:
        raise DesignError("Built-in designs are protected. Duplicate it to add a logo.")
    old = d.assets.get("logo")
    assets = dict(d.assets)
    if data:
        assets["logo"] = _write(branding.process("logo", data), "design-logo")
    else:
        assets.pop("logo", None)
    d.assets = assets
    d.save(update_fields=["assets", "updated_at"])
    if old:
        cleanup_files([old])
    return d


def _open_original(d) -> Image.Image:
    path = branding.branding_dir() / d.assets["original"]
    Image.MAX_IMAGE_PIXELS = branding.LIMITS["wallpaper"][1]
    with Image.open(path) as im:
        return im.convert("RGB")


def _make_derivatives(d, img: Image.Image | None = None) -> None:
    img = img or _open_original(d)
    old = [d.assets.get(k) for k in VARIANTS]
    assets = dict(d.assets)
    for variant, size in VARIANTS.items():
        # cover-crop around the focal point: same aspect as the area it fills, never stretched
        crop = ImageOps.fit(img, size, Image.Resampling.LANCZOS, centering=(d.focal_x, d.focal_y))
        assets[variant] = _write(_encode(crop), f"design-{variant}")
    d.assets = assets
    d.save(update_fields=["assets", "updated_at"])
    cleanup_files([o for o in old if o])


def ensure_derivatives(d) -> None:
    """Designs migrated from the previous release have only an original: derive the rest on first use."""
    if d.assets.get("original") and not all(d.assets.get(k) for k in VARIANTS) and _file_ok(d.assets["original"]):
        _make_derivatives(d)
        refresh_palette(d)


def _file_ok(name: str | None) -> bool:
    if not name or "/" in name or ".." in name:
        return False
    path = branding.branding_dir() / name
    if not path.is_file():
        return False
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001 - any decoding error means the file cannot be shown
        return False


def _assets_ok(d) -> bool:
    return _file_ok(d.assets.get("original"))


def asset_path(d, variant: str) -> Path | None:
    if variant not in ("original", "logo", *VARIANTS):
        return None
    if variant in VARIANTS:
        ensure_derivatives(d)
    name = d.assets.get(variant)
    if not name or "/" in name or ".." in name:
        return None
    path = branding.branding_dir() / name
    return path if path.is_file() else None


def _mark_unavailable(d, detail: str) -> None:
    from .models import SigninDesign

    SigninDesign.objects.filter(pk=d.pk).update(state=SigninDesign.UNAVAILABLE, state_detail=detail[:300])
    d.state, d.state_detail = SigninDesign.UNAVAILABLE, detail[:300]


def _alert(text: str, *, tag: str) -> None:
    """Main administrators only, once a day per problem (rotation successes are never notified)."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.notify import events

    for admin in User.objects.filter(is_active=True, is_main_admin=True):
        events.notify(admin, "security.policy_change", key=f"{tag}:{timezone.now():%Y%m%d}",
                      title="Sign-in page design needs attention", icon="warning", severity="warning",
                      lines=[text], link="/settings/overview#login-design")


# ------------------------------------------------------------------ colours

def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb[:3])


def _is_hex(v: str) -> bool:
    return len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])


def _rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = luminance(a if not isinstance(a, str) else _rgb(a)), luminance(b if not isinstance(b, str) else _rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a, b, t: float):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _hls(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb[:3]))


def _from_hls(h, l, s):  # noqa: E741 - colour lightness
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s))))


def _until(rgb, against, target: float, darker: bool):
    """Move ``rgb`` darker or lighter (same hue) until it reaches the contrast ratio against ``against``."""
    h, l, s = _hls(rgb)  # noqa: E741
    for _ in range(60):
        if contrast(_from_hls(h, l, s), against) >= target:
            break
        l += -0.02 if darker else 0.02  # noqa: E741
        if l <= 0 or l >= 1:
            break
    return _from_hls(h, l, s)


def analyse(img: Image.Image) -> dict:
    """Dominant and accent colours, and the brightness of the wallpaper strip next to the sign-in panel (the right
    edge on desktop, the bottom edge of the mobile band), which decides a light or dark panel."""
    small = img.copy()
    small.thumbnail((240, 240))
    w, h = small.size
    edge = small.crop((int(w * 0.72), 0, w, h)).resize((24, 24))
    bottom = small.crop((0, int(h * 0.75), w, h)).resize((24, 12))
    px = list(edge.getdata()) + list(bottom.getdata())
    avg = tuple(sum(p[i] for p in px) / len(px) for i in range(3))
    quant = small.convert("RGB").quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette()[:24]
    counts = sorted(quant.getcolors(), reverse=True)
    colours = [((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), n) for n, i in counts if i < 8]
    total = sum(n for _c, n in colours) or 1
    dominant = colours[0][0] if colours else avg
    best, score = None, 0.0
    for c, n in colours:
        _h, l, s = _hls(c)  # noqa: E741
        if s < 0.18 or l < 0.08 or l > 0.92:
            continue
        sc = s * (n / total) ** 0.5
        if sc > score:
            best, score = c, sc
    return {"edge": _hex(avg), "edge_luminance": round(luminance(avg), 3), "dominant": _hex(dominant),
            "accent": _hex(best) if best else None, "scheme": "light" if luminance(avg) > 0.36 else "dark"}


def build_palette(analysis: dict, mode: str) -> dict:
    """A readable palette that matches the wallpaper. Readability wins over an exact colour match: body text >= 7:1,
    muted text and button text >= 4.5:1, borders visible."""
    if not analysis:
        return {}
    scheme = mode if mode in ("light", "dark") else analysis.get("scheme", "light")
    edge = _rgb(analysis["edge"])
    accent = _rgb(analysis["accent"]) if analysis.get("accent") else (47, 122, 79)
    ah, _al, as_ = _hls(accent)
    if scheme == "light":
        bg = _mix((255, 255, 255), edge, 0.10)
        surface = _mix((255, 255, 255), edge, 0.04)
        ink = _until(_from_hls(ah, 0.14, min(as_, 0.45)), bg, 7.0, darker=True)
        brand = _until(accent, (255, 255, 255), 4.6, darker=True)
        brand_ink = (255, 255, 255)
        muted = _until(_mix(ink, bg, 0.45), bg, 4.6, darker=True)
        line = _mix(bg, ink, 0.16)
        input_bg = _mix((255, 255, 255), edge, 0.03)
        brand_soft = _mix(bg, brand, 0.14)
    else:
        bg = _mix((14, 20, 17), edge, 0.18)
        surface = _mix((22, 30, 26), edge, 0.16)
        ink = _until(_from_hls(ah, 0.93, min(as_, 0.25)), bg, 7.0, darker=False)
        brand = _until(accent, (12, 16, 14), 4.6, darker=False)
        brand_ink = (12, 16, 14)
        muted = _until(_mix(ink, bg, 0.4), bg, 4.6, darker=False)
        line = _mix(bg, ink, 0.2)
        input_bg = _mix(bg, (255, 255, 255), 0.05)
        brand_soft = _mix(bg, brand, 0.2)
    link = brand if contrast(brand, bg) >= 4.5 else _until(brand, bg, 4.6, darker=scheme == "light")
    pal = {"scheme": scheme, "bg": _hex(bg), "surface": _hex(surface), "ink": _hex(ink), "ink_soft": _hex(_mix(ink, bg, 0.2)),
           "heading": _hex(ink), "muted": _hex(muted), "brand": _hex(brand), "brand_ink": _hex(brand_ink),
           "brand_soft": _hex(brand_soft), "line": _hex(line), "input_bg": _hex(input_bg), "link": _hex(link)}
    return pal


def refresh_palette(d) -> dict:
    """Re-run the analysis from the Desktop derivative (what people actually see) and rebuild the palette.
    Custom mode keeps the administrator's colours on top of the generated ones."""
    analysis = {}
    path = d.assets.get("desktop") or d.assets.get("original")
    if path and _file_ok(path):
        with Image.open(branding.branding_dir() / path) as im:
            analysis = analyse(im.convert("RGB"))
    d.analysis = analysis
    pal = build_palette(analysis, d.color_mode)
    if d.color_mode == d.CUSTOM:
        pal = {**pal, **d.overrides}
        if pal and "scheme" not in pal:
            pal["scheme"] = "light"
    d.palette = pal
    d.save(update_fields=["analysis", "palette", "updated_at"])
    return pal


def palette_warnings(pal: dict) -> list[str]:
    out = []
    if not pal:
        return out
    pairs = [("ink", "bg", 4.5, "Text"), ("brand_ink", "brand", 4.5, "Button text"), ("muted", "bg", 3.0, "Secondary text"),
             ("link", "bg", 4.5, "Links")]
    for a, b, need, label in pairs:
        if pal.get(a) and pal.get(b) and contrast(pal[a], pal[b]) < need:
            out.append(f"{label} contrast is {contrast(pal[a], pal[b]):.1f}:1 (needs {need}:1).")
    return out


# ------------------------------------------------------------------ what the sign-in page and the editor see

def asset_url(d, variant: str) -> str | None:
    name = d.assets.get(variant)
    if not name:
        return None
    return f"/api/branding/design/{d.pk}/{variant}?v={name.rsplit('-', 1)[-1][:8]}"


def payload(d) -> dict:
    """Public sign-in data for one design (also used by previews). Nothing private: no file names."""
    if not d.builtin:
        ensure_derivatives(d)
    has_wall = bool(d.assets.get("original"))
    legacy_logo = config.get("login.logo_file")
    logo = asset_url(d, "logo") or (f"/api/branding/logo?v={legacy_logo[5:13]}" if legacy_logo else None)
    walls = {k: asset_url(d, k) for k in VARIANTS} if has_wall else None
    return {"design": d.template if not d.builtin else d.builtin_key, "design_id": d.pk, "design_name": d.name,
            "title": config.get("login.title") or config.get("general.app_name"), "tagline": config.get("login.tagline"),
            "overlay": d.overlay, "position": _position(d), "focal": [d.focal_x, d.focal_y],
            "wallpaper": (walls or {}).get("desktop"), "wallpapers": walls, "has_wallpaper": has_wall, "logo": logo,
            "palette": d.palette or None}


def _position(d) -> str:
    named = {(0.5, 0.5): "center", (0.5, 0.0): "top", (0.5, 1.0): "bottom", (0.0, 0.5): "left", (1.0, 0.5): "right"}
    return named.get((round(d.focal_x, 3), round(d.focal_y, 3)), "focal")


def design_json(d, *, active_id=None, previous_id=None) -> dict:
    return {"id": d.pk, "name": d.name, "builtin": d.builtin, "builtin_key": d.builtin_key, "template": d.template,
            "has_wallpaper": bool(d.assets.get("original")), "has_logo": bool(d.assets.get("logo")),
            "focal_x": d.focal_x, "focal_y": d.focal_y, "overlay": d.overlay, "color_mode": d.color_mode,
            "analysis": d.analysis, "overrides": d.overrides, "palette": d.palette,
            "warnings": palette_warnings(d.palette), "state": d.state, "state_detail": d.state_detail,
            "active": d.pk == active_id, "previous": d.pk == previous_id,
            "thumbnail": asset_url(d, "mobile") or asset_url(d, "original"), "preview": payload(d),
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}
