"""Image OCR with preprocessing, orientation handling and confidence (Tesseract, local only).

The steps were chosen by measurement (``scripts/ocr_benchmark.py``, results in ``docs/OCR_BENCHMARK.md``) on
synthetic ID cards, phone photos, rotated/skewed/low-contrast/noisy/small scans and clean pages. Each step can be
switched off individually so the benchmark can compare variants.

Pipeline for an image:
1. EXIF orientation applied (phone photos are often stored sideways with an orientation tag).
2. Grayscale + contrast stretch (``autocontrast`` with a small cut-off).
3. Images smaller than 2400 px are upscaled so text is large enough (huge ones are downscaled), then a 3x3
   median filter removes sensor/JPEG speckle.
4. Orientation (0/90/180/270) from Tesseract's orientation model (``--psm 0``); when that is unsure, the
   orientation with the best OCR confidence on a reduced image wins. A manual rotation overrides both.
5. Small skew (±8°) measured with a projection profile and corrected.
6. Tesseract with word confidences (TSV). Lines are rebuilt from the TSV; each line keeps its mean confidence so
   junk can be shown as low confidence and kept out of field extraction.

Only the derived image is changed; the stored original is never modified.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from . import sandbox

log = logging.getLogger("personaldocs.ocr")

LOW_CONFIDENCE = 60  # mean word confidence (0-100) below which a line is treated as unreliable
TARGET_LONG_SIDE = 2400  # px; smaller images are upscaled to this (measured: helps small text and, with denoise, photos)
MAX_LONG_SIDE = 4200


@dataclass
class Options:
    exif: bool = True
    gray: bool = True
    contrast: bool = True
    upscale: bool = True
    orientation: bool = True
    deskew: bool = True
    threshold: bool = False  # measured: hurts photos with patterned backgrounds; benchmark option only
    denoise: bool = True  # median 3x3: removes sensor/JPEG speckle before upscaling
    psm: int = 3
    upscale_below: int | None = None  # benchmark override of TARGET_LONG_SIDE
    rotate: int | None = None  # manual override in degrees clockwise (0/90/180/270)


@dataclass
class Line:
    text: str
    confidence: float  # 0-100


@dataclass
class Result:
    text: str
    lines: list[Line] = field(default_factory=list)
    confidence: float = 0.0  # mean word confidence 0-100
    rotation: int = 0  # degrees clockwise applied
    skew: float = 0.0
    steps: list[str] = field(default_factory=list)

    def quality(self) -> dict:
        low = [i for i, ln in enumerate(self.lines) if ln.confidence < LOW_CONFIDENCE]
        return {"engine": "tesseract", "confidence": round(self.confidence, 1), "rotation": self.rotation,
                "skew": round(self.skew, 1), "steps": self.steps, "low_lines": low, "line_count": len(self.lines),
                "line_confidence": [round(ln.confidence) for ln in self.lines][:2000]}

    def reliable_text(self) -> str:
        """Text without low-confidence lines (used for field extraction)."""
        return "\n".join(ln.text for ln in self.lines if ln.confidence >= LOW_CONFIDENCE)


# ------------------------------------------------------------------ preprocessing

def prepare(img, opts: Options, steps: list[str]):
    from PIL import ImageFilter, ImageOps

    if opts.exif:
        before = img.size
        img = ImageOps.exif_transpose(img)
        if img.size != before:
            steps.append("exif-orientation")
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if opts.gray:
        img = img.convert("L")
        steps.append("grayscale")
    if opts.contrast:
        img = ImageOps.autocontrast(img, cutoff=1)
        steps.append("contrast")
    long_side = max(img.size)
    if opts.upscale and long_side < (opts.upscale_below or TARGET_LONG_SIDE):
        f = TARGET_LONG_SIDE / long_side
        img = img.resize((round(img.width * f), round(img.height * f)), resample=3)  # bicubic
        steps.append(f"upscale x{f:.1f}")
    elif long_side > MAX_LONG_SIDE:
        f = MAX_LONG_SIDE / long_side
        img = img.resize((round(img.width * f), round(img.height * f)), resample=1)
        steps.append(f"downscale x{f:.2f}")
    if opts.denoise:  # measured: after resizing is better than before
        img = img.filter(ImageFilter.MedianFilter(3))
        steps.append("denoise")
    return img


def _otsu(img):
    hist = img.convert("L").histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = sum_b = 0
    best, level = 0.0, 128
    for i in range(256):
        w_b += hist[i]
        if not w_b:
            continue
        w_f = total - w_b
        if not w_f:
            break
        sum_b += i * hist[i]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, level = between, i
    return img.convert("L").point(lambda p: 255 if p > level else 0)


def skew_angle(img, limit: float = 8.0, step: float = 0.5) -> float:
    """Text skew in degrees (positive = counter-clockwise), from the sharpness of the horizontal projection."""
    small = img.convert("L")
    small.thumbnail((700, 700))
    bw = _otsu(small).point(lambda p: 1 if p == 0 else 0)  # ink = 1

    def score(angle: float) -> float:
        rot = bw.rotate(angle, resample=0, expand=False, fillcolor=0)
        w, h = rot.size
        data = rot.tobytes()
        rows = [sum(data[y * w:(y + 1) * w]) for y in range(h)]
        return sum((rows[i + 1] - rows[i]) ** 2 for i in range(h - 1))

    best_angle, best = 0.0, score(0.0)
    a = -limit
    while a <= limit + 1e-9:
        if abs(a) > 1e-9:
            s = score(a)
            if s > best * 1.02:  # require a clear improvement; avoids rotating clean pages by noise
                best_angle, best = a, s
        a += step
    return best_angle


# ------------------------------------------------------------------ tesseract

def _tesseract(img, *, psm: int, lang: str, timeout: int, extra: list[str] | None = None, out: str = "tsv") -> str:
    with tempfile.TemporaryDirectory(dir=settings.TMP_DIR) as tmp:
        src = Path(tmp) / "page.png"
        img.save(src, "PNG", dpi=(300, 300))
        cmd = [settings.TESSERACT_CMD, str(src), "stdout", "-l", lang, "--psm", str(psm)] + (extra or []) + ([out] if out else [])
        proc = sandbox.run(cmd, timeout=timeout, cwd=Path(tmp))
        if proc.returncode != 0:
            raise sandbox.ToolError(f"tesseract failed: {proc.stderr.decode(errors='replace')[-300:]}")
        return proc.stdout.decode("utf-8", errors="replace")


def osd_rotation(img, timeout: int) -> tuple[int, float] | None:
    """(clockwise degrees to rotate, confidence) from Tesseract's orientation model, or None."""
    try:
        small = img.copy()
        small.thumbnail((1800, 1800))
        out = _tesseract(small, psm=0, lang="osd", timeout=min(timeout, 60), out="")
    except sandbox.ToolError:
        return None
    rot = re.search(r"Rotate:\s*(\d+)", out)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
    if not rot:
        return None
    return int(rot.group(1)) % 360, float(conf.group(1)) if conf else 0.0


def parse_tsv(tsv: str) -> tuple[list[Line], float]:
    lines: dict[tuple, list[tuple[str, float]]] = {}
    confs = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            continue
        word = (row.get("text") or "").strip()
        if conf < 0 or not word:
            continue
        key = (int(row["page_num"]), int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append((word, conf))
        confs.append(conf)
    out = [Line(" ".join(w for w, _ in words), sum(c for _, c in words) / len(words)) for _, words in sorted(lines.items())]
    return out, (sum(confs) / len(confs) if confs else 0.0)


def _rotate(img, clockwise: int):
    return img.rotate(-clockwise, expand=True, fillcolor=255) if clockwise % 360 else img


def recognise(img, opts: Options | None = None, *, lang: str = "eng", timeout: int = 300) -> Result:
    """Run the pipeline on a PIL image and return text with confidences."""
    opts = opts or Options()
    steps: list[str] = []
    work = prepare(img, opts, steps)
    rotation = 0
    if opts.rotate is not None:
        rotation = opts.rotate % 360
        steps.append(f"manual rotation {rotation}°")
    elif opts.orientation:
        found = osd_rotation(work, timeout)
        if found and found[1] >= 2.0:
            rotation = found[0]
            steps.append(f"orientation {rotation}° (confidence {found[1]:.1f})")
        else:  # little text: try the four orientations on a reduced image and keep the most confident
            trial = work.copy()
            trial.thumbnail((1400, 1400))
            best = (-1.0, 0)
            for r in (0, 90, 180, 270):
                try:
                    _l, c = parse_tsv(_tesseract(_rotate(trial, r), psm=opts.psm, lang=lang, timeout=min(timeout, 60)))
                except sandbox.ToolError:
                    continue
                if c > best[0] + 3:  # 0° wins ties
                    best = (c, r)
            rotation = best[1]
            steps.append(f"orientation {rotation}° (by confidence)")
    work = _rotate(work, rotation)
    skew = 0.0
    if opts.deskew:
        skew = skew_angle(work)
        if skew:
            work = work.rotate(skew, resample=3, expand=True, fillcolor=255)
            steps.append(f"deskew {skew:+.1f}°")
    if opts.threshold:
        work = _otsu(work)
        steps.append("threshold")
    lines, conf = parse_tsv(_tesseract(work, psm=opts.psm, lang=lang, timeout=timeout))
    return Result(text="\n".join(ln.text for ln in lines), lines=lines, confidence=conf, rotation=rotation,
                  skew=skew, steps=steps)


def prepared_image(img, result: Result, opts: Options | None = None):
    """The image as OCR saw it (orientation and skew applied), for the searchable PDF."""
    opts = opts or Options()
    work = prepare(img, Options(exif=opts.exif, gray=False, contrast=False, upscale=False, psm=opts.psm), [])
    work = _rotate(work.convert("RGB"), result.rotation)
    if result.skew:
        work = work.rotate(result.skew, resample=3, expand=True, fillcolor=(255, 255, 255))
    return work
