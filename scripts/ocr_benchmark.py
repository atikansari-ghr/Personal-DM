"""OCR pipeline benchmark on synthetic samples (no real data).

Usage (from the repository root, development environment):
    PD_DEBUG=1 .venv/bin/python scripts/ocr_benchmark.py [--markdown docs/OCR_BENCHMARK.md]

Compares the previous behaviour ("baseline": Tesseract on the raw pixels, no EXIF orientation, no preprocessing,
as OCRmyPDF did for images) with preprocessing variants. Scores per sample:
  recall    share of ground-truth words found
  precision share of recognised words that are ground-truth words (junk lowers it)
  F1        harmonic mean
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "personaldocs.settings")
os.environ.setdefault("PD_DEBUG", "1")

import django  # noqa: E402

django.setup()

from apps.library import ocr  # noqa: E402
from ocr_samples import samples  # noqa: E402


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)*", text.lower()) if len(w) >= 2]


def score(found: str, truth: str) -> tuple[float, float, float]:
    t, f = words(truth), words(found)
    if not f:
        return 0.0, 0.0, 0.0
    ts, fs = set(t), set(f)
    recall = sum(1 for w in t if w in fs) / len(t)
    precision = sum(1 for w in f if w in ts) / len(f)
    f1 = 0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)
    return recall, precision, f1


VARIANTS = {
    "baseline (before)": ocr.Options(exif=False, gray=False, contrast=False, denoise=False, upscale=False, orientation=False, deskew=False),
    "+ EXIF orientation": ocr.Options(gray=False, contrast=False, denoise=False, upscale=False, orientation=False, deskew=False),
    "+ grayscale/contrast": ocr.Options(denoise=False, upscale=False, orientation=False, deskew=False),
    "+ orientation (0/90/180/270)": ocr.Options(denoise=False, upscale=False, deskew=False),
    "+ deskew": ocr.Options(denoise=False, upscale=False),
    "+ denoise": ocr.Options(upscale=False),
    "+ upscale < 2400 px (chosen)": ocr.Options(),
    "chosen + threshold (rejected)": ocr.Options(threshold=True),
    "chosen, psm 6 (rejected)": ocr.Options(psm=6),
    "chosen, psm 11 (rejected)": ocr.Options(psm=11),
}


def run(variants=VARIANTS):
    data = samples()
    table = {}
    for vname, opts in variants.items():
        rows = []
        t0 = time.time()
        for sname, img, truth, _fields in data:
            res = ocr.recognise(img.copy() if not hasattr(img, "getexif") else img, opts)
            rows.append((sname, *score(res.text, truth), res.confidence))
        table[vname] = (rows, time.time() - t0)
    return data, table


def markdown(data, table) -> str:
    names = [s[0] for s in data]
    out = ["| Variant | " + " | ".join(names) + " | Mean F1 | Time |", "|---|" + "---|" * (len(names) + 2)]
    for vname, (rows, secs) in table.items():
        f1s = [r[3] for r in rows]
        out.append(f"| {vname} | " + " | ".join(f"{f:.2f}" for f in f1s) + f" | **{sum(f1s) / len(f1s):.2f}** | {secs:.0f}s |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown")
    args = ap.parse_args()
    data, table = run()
    md = markdown(data, table)
    print(md)
    if args.markdown:
        Path(args.markdown).write_text(md + "\n")
