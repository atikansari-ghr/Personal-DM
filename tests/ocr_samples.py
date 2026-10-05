"""Synthetic OCR samples with ground truth (no real documents, names or numbers).

Each sample is (name, PIL image, ground-truth text, expected fields). Distortions model what families actually
upload: phone photos of ID cards on a table, pictures stored sideways with an EXIF orientation tag, upside-down
scans, slight skew, dim/low-contrast photos, tiny crops, sensor noise and JPEG compression.
Deterministic (fixed random seeds) so benchmark numbers are reproducible.
"""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT = "DejaVuSans.ttf"
FONT_BOLD = "DejaVuSans-Bold.ttf"


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default(size=size)


def id_card(lines: list[tuple[str, int, bool]], *, header: str = "SAMPLE ENERGY COMPANY", width: int = 1012,
            height: int = 638, ink=(25, 25, 35), paper=(244, 246, 241)) -> Image.Image:
    """A CR80-proportioned card: coloured header, photo box and text lines (text, size, bold)."""
    img = Image.new("RGB", (width, height), paper)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 92], fill=(20, 92, 64))
    d.text((32, 24), header, fill=(255, 255, 255), font=_font(40, True))
    d.rectangle([32, 130, 262, 420], fill=(200, 205, 210), outline=(150, 150, 150), width=3)
    y = 130
    for text, size, bold in lines:
        d.text((300, y), text, fill=ink, font=_font(size, bold))
        y += int(size * 1.55)
    return img


def patterned(card: Image.Image, seed: int) -> Image.Image:
    """Security-print style background: fine wavy lines and a tint behind the text, like real ID cards."""
    import math

    rnd = random.Random(seed)
    over = Image.new("RGBA", card.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for k in range(0, card.height, 9):
        pts = [(x, k + 4 * math.sin(x / 23 + k)) for x in range(0, card.width, 6)]
        d.line(pts, fill=(90 + rnd.randint(0, 40), 140, 120, 70), width=1)
    tint = Image.new("RGBA", card.size, (210, 225, 240, 60))
    base = card.convert("RGBA")
    base.alpha_composite(tint)
    base.alpha_composite(over)
    return base.convert("RGB")


def glare(img: Image.Image, cx: float = 0.6, cy: float = 0.4, strength: int = 120) -> Image.Image:
    g = Image.radial_gradient("L").resize(img.size).point(lambda p: max(0, strength - p))
    white = Image.new("RGB", img.size, (255, 255, 255))
    return Image.composite(white, img.convert("RGB"), g.transform(img.size, Image.AFFINE, (1, 0, (0.5 - cx) * img.width, 0, 1, (0.5 - cy) * img.height)))


def text_page(lines: list[str], width=1700, height=2200) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = 160
    for ln in lines:
        d.text((140, y), ln, fill="black", font=_font(40))
        y += 70
    return img


def on_table(card: Image.Image, *, seed: int, angle: float = 0.0, scale: float = 1.0, canvas=(1800, 1350)) -> Image.Image:
    """Place the card on a textured 'table' like a phone photo."""
    rnd = random.Random(seed)
    bg = Image.new("RGB", canvas, (120, 96, 72))
    px = bg.load()
    for y in range(0, canvas[1], 3):
        for x in range(0, canvas[0], 3):
            v = rnd.randint(-22, 22)
            c = (max(0, min(255, 120 + v)), max(0, min(255, 96 + v)), max(0, min(255, 72 + v)))
            for dy in range(3):
                for dx in range(3):
                    if x + dx < canvas[0] and y + dy < canvas[1]:
                        px[x + dx, y + dy] = c
    c = card.resize((int(card.width * scale), int(card.height * scale)))
    c = c.convert("RGBA").rotate(angle, resample=Image.BICUBIC, expand=True)
    bg.paste(c, ((canvas[0] - c.width) // 2, (canvas[1] - c.height) // 2), c)
    return bg


def noise(img: Image.Image, *, seed: int, amount: int = 28, salt: float = 0.0) -> Image.Image:
    rnd = random.Random(seed)
    img = img.convert("RGB")
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            if salt and rnd.random() < salt:
                px[x, y] = (0, 0, 0) if rnd.random() < 0.5 else (255, 255, 255)
                continue
            r, g, b = px[x, y]
            v = rnd.randint(-amount, amount)
            px[x, y] = (max(0, min(255, r + v)), max(0, min(255, g + v)), max(0, min(255, b + v)))
    return img


def jpeg(img: Image.Image, quality: int = 70, exif_orientation: int | None = None) -> Image.Image:
    buf = io.BytesIO()
    kw = {}
    if exif_orientation:
        ex = Image.Exif()
        ex[0x0112] = exif_orientation
        kw["exif"] = ex.tobytes()
    img.convert("RGB").save(buf, "JPEG", quality=quality, **kw)
    buf.seek(0)
    return Image.open(buf)


def low_contrast(img: Image.Image, factor: float = 0.32, base: int = 120) -> Image.Image:
    g = img.convert("L")
    return g.point(lambda p: int(base + (p - 128) * factor)).convert("RGB")


EMPLOYEE_LINES = [
    ("SAM SAMPLE", 46, True),
    ("EMPLOYEE", 34, False),
    ("Badge No    Expiry Date", 30, False),
    ("145070      12-31-2030", 36, True),
]
EMPLOYEE_TEXT = "SAMPLE ENERGY COMPANY SAM SAMPLE EMPLOYEE Badge No Expiry Date 145070 12-31-2030"
EMPLOYEE_FIELDS = {"document_number": "145070", "expiry_date": "2030-12-31"}

RESIDENT_LINES = [
    ("SAMPLE RESIDENT CARD", 38, True),
    ("Name: SAM SAMPLE", 32, False),
    ("ID No: 2345678901", 32, False),
    ("Date of Issue: 05/03/2019", 32, False),
    ("No Expiry Date", 32, True),
]
RESIDENT_TEXT = "SAMPLE AUTHORITY SAMPLE RESIDENT CARD Name SAM SAMPLE ID No 2345678901 Date of Issue 05/03/2019 No Expiry Date"
RESIDENT_FIELDS = {"document_number": "2345678901", "issue_date": "2019-03-05", "no_expiry": True}

PAGE_LINES = [
    "SAMPLE INSURANCE POLICY - NOT A REAL DOCUMENT",
    "Policy Number: POL-778899",
    "Policy holder: Sam Sample",
    "Date of Issue: 01 Jan 2025",
    "Valid until: 31 Dec 2026",
    "This synthetic page is used to check that clean scans are not degraded.",
]
PAGE_TEXT = " ".join(PAGE_LINES)
PAGE_FIELDS = {"issue_date": "2025-01-01", "expiry_date": "2026-12-31"}


def samples() -> list[tuple[str, Image.Image, str, dict]]:
    card = id_card(EMPLOYEE_LINES)
    resident = id_card(RESIDENT_LINES, header="SAMPLE AUTHORITY")
    printed = patterned(card, seed=7)
    photo = blur(on_table(printed, seed=1, angle=4.0, scale=0.55, canvas=(2000, 1500)), 1.1)
    out = [
        ("clean card scan", card, EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("clean text page", text_page(PAGE_LINES), PAGE_TEXT, PAGE_FIELDS),
        ("phone photo, patterned card, skewed 4°", jpeg(noise(photo, seed=2, amount=16), 62), EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("phone photo stored sideways (EXIF 6)", jpeg(noise(photo, seed=8, amount=12).rotate(90, expand=True), 70, exif_orientation=6),
         EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("upside-down scan", printed.rotate(180), EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("rotated 90° without EXIF", patterned(resident, 9).rotate(90, expand=True), RESIDENT_TEXT, RESIDENT_FIELDS),
        ("dim low-contrast photo", jpeg(blur(low_contrast(on_table(patterned(resident, 3), seed=3, angle=-2.5, scale=0.6), 0.25), 0.8), 60),
         RESIDENT_TEXT, RESIDENT_FIELDS),
        ("photo with glare", jpeg(glare(on_table(printed, seed=6, angle=1.0, scale=0.6), 0.45, 0.45, 150), 65), EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("small crop (420 px)", blur(printed.resize((420, 265)), 0.6), EMPLOYEE_TEXT, EMPLOYEE_FIELDS),
        ("noisy photo", jpeg(noise(on_table(patterned(resident, 4), seed=4, angle=1.5, scale=0.6), seed=5, amount=40, salt=0.01), 55),
         RESIDENT_TEXT, RESIDENT_FIELDS),
        ("skewed text page 3°", text_page(PAGE_LINES).rotate(-3, expand=True, fillcolor="white"), PAGE_TEXT, PAGE_FIELDS),
    ]
    return out


def as_jpeg_bytes(img: Image.Image) -> bytes:
    """For upload tests: keep an EXIF orientation tag if the sample has one."""
    buf = io.BytesIO()
    exif = img.getexif()
    img.convert("RGB").save(buf, "JPEG", quality=90, exif=exif.tobytes() if exif else b"")
    return buf.getvalue()


def blur(img: Image.Image, r: float = 1.0) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(r))


__all__ = ["samples", "as_jpeg_bytes", "ImageOps"]
