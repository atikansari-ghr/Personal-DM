"""PP-OCRv5 (PaddleOCR) vs Tesseract (Legacy) on synthetic samples only (Change Set Q).

Usage (repository root, development environment, PaddleOCR runtime installed):
    PD_PADDLE_PYTHON=/opt/personaldocs/paddle-venv/bin/python PD_PADDLE_HOME=/var/lib/personaldocs/paddle \
    PD_DEBUG=1 .venv/bin/python scripts/ocr_engine_benchmark.py [--markdown out.md] [--only english]

Scores per sample and engine:
  F1        word-level F1 against the ground truth (Latin-script samples, as in scripts/ocr_benchmark.py)
  accuracy  character accuracy, 1 - CER, after whitespace normalisation (every sample; the only fair metric for
            Arabic, Devanagari, Telugu and Tamil)
  s/page    wall time per page including model loading (the worker starts per run, as in production)
  peak RSS  largest resident memory of any OCR child process (reported once per engine pass)
Engine confidences are reported separately and never compared with each other.
No real document, name or number is used. Categories that need real-world samples are reported as Not Run.
"""
import argparse
import io
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests"), str(ROOT / "scripts")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "personaldocs.settings")
os.environ.setdefault("PD_DEBUG", "1")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from apps.core.registry import OCR_PROFILES  # noqa: E402
from apps.library import ocr_engines  # noqa: E402
from apps.library.ocr_admin import _cer_accuracy  # noqa: E402
from ocr_benchmark import score  # noqa: E402
from ocr_samples import blur, jpeg, noise, on_table, samples  # noqa: E402

NOTO = Path("/usr/share/fonts/truetype/noto")

# Fictional wording only.
MULTI = {
    "ar_en": ("NotoNaskhArabic-Regular.ttf", True, ["بطاقة هوية تجريبية", "SAMPLE RESIDENT CARD", "الاسم نموذج اختبار",
                                                    "Name Test Sample", "رقم ١٢٣٤٥٦٧٨٩٠", "ID 2345678901"]),
    "hi_en": ("NotoSansDevanagari-Regular.ttf", False, ["नमूना पहचान पत्र", "SAMPLE IDENTITY CARD", "नाम परीक्षण नमूना",
                                                        "Name Test Sample", "जन्म तिथि 01-01-1990"]),
    "te_en": ("NotoSansTelugu-Regular.ttf", False, ["నమూనా గుర్తింపు కార్డు", "SAMPLE IDENTITY CARD", "పేరు పరీక్ష",
                                                    "Name Test Sample"]),
    "ta_en": ("NotoSansTamil-Regular.ttf", False, ["மாதிரி அடையாள அட்டை", "SAMPLE IDENTITY CARD", "பெயர் சோதனை",
                                                   "Name Test Sample"]),
}


def multi_card(profile: str) -> tuple[Image.Image, str]:
    font_name, rtl, lines = MULTI[profile]
    img = Image.new("RGB", (1500, 140 + 110 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    script = ImageFont.truetype(str(NOTO / font_name), 58)
    latin = ImageFont.truetype("DejaVuSans.ttf", 54)
    y = 70
    for ln in lines:
        is_latin = ln.isascii()
        f = latin if is_latin else script
        kw = {} if is_latin else ({"direction": "rtl", "language": "ar"} if rtl else {})
        x = img.width - 90 - d.textlength(ln, font=f, **kw) if (rtl and not is_latin) else 90
        d.text((x, y), ln, fill="black", font=f, **kw)
        y += 110
    return img, "\n".join(lines)


def cases(only: str | None):
    out = []
    if only in (None, "english"):
        for name, img, truth, _ in samples():
            out.append(("en", name, [img], truth))
        # multi-page scanned PDF stand-in (two rendered pages)
        page = samples()[1][1]
        out.append(("en", "scanned 2-page PDF (300 dpi render)", [page, page.rotate(180)], samples()[1][2] + "\n" + samples()[1][2]))
    if only in (None, "multilingual"):
        for prof in MULTI:
            img, truth = multi_card(prof)
            out.append((prof, f"{OCR_PROFILES[prof]} clean card", [img], truth))
            photo = jpeg(noise(blur(on_table(img, seed=11, angle=3.0, scale=0.7, canvas=(1800, 1300)), 0.8), seed=12, amount=14), 65)
            out.append((prof, f"{OCR_PROFILES[prof]} phone photo, skewed 3°", [photo], truth))
    return out


def child_peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024


def run(engine: str, profile: str, imgs: list[Image.Image], timeout: int = 600):
    with tempfile.TemporaryDirectory(prefix="ocrbench-", dir=settings.TMP_DIR) as tmp:
        work = Path(tmp)
        paths = []
        for i, im in enumerate(imgs, 1):
            raw = work / f"in-{i}.png"
            buf = io.BytesIO()
            im.save(buf, "PNG")
            raw.write_bytes(buf.getvalue())
            paths.append((ocr_engines.prepare_image(raw, work / f"page-{i}.png"), i))
        t0 = time.monotonic()
        if engine == "paddleocr":
            r = ocr_engines.paddle_recognise(paths, profile, work, timeout)
        else:
            r = ocr_engines.tesseract_recognise(paths, profile, None, timeout)
        return r, time.monotonic() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown")
    ap.add_argument("--only", choices=["english", "multilingual"])
    args = ap.parse_args()
    st = ocr_engines.paddle_status(refresh=True)
    rows, peaks = [], {}
    todo = cases(args.only)
    for engine in ("tesseract", "paddleocr"):  # Tesseract first: the RUSAGE_CHILDREN peak only grows
        for profile, name, imgs, truth in todo:
            try:
                r, secs = run(engine, profile, imgs)
                text = r.text(len(imgs) > 1)
                f1 = score(text, truth)[2] if profile == "en" else None
                rows.append({"sample": name, "profile": profile, "engine": engine, "ok": True, "f1": f1,
                             "acc": _cer_accuracy(truth, text), "spp": secs / len(imgs),
                             "conf": r.quality().get("confidence"), "lines": len(r.lines())})
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                rows.append({"sample": name, "profile": profile, "engine": engine, "ok": False, "error": str(exc)[:160]})
            print({k: v for k, v in rows[-1].items()}, flush=True)
        peaks[engine] = child_peak_mb()
    md = render(rows, st, peaks)
    print(md)
    if args.markdown:
        Path(args.markdown).write_text(md)


def render(rows, st, peaks) -> str:
    lines = [f"PaddleOCR {st.get('paddleocr') or '—'} / PaddlePaddle {st.get('paddle') or '—'} (model "
             f"{ocr_engines.config.get('processing.paddle_model')}, {ocr_engines.config.get('processing.paddle_cpu_threads')} CPU threads); "
             f"Tesseract {ocr_engines.tesseract_version() or '—'}.", "",
             "| Sample | Profile | Engine | Word F1 | Char accuracy | s/page | Engine confidence |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        label = ocr_engines.ENGINE_LABELS.get(r["engine"], r["engine"])
        if not r["ok"]:
            lines.append(f"| {r['sample']} | {r['profile']} | {label} | Failed: {r['error']} | | | |")
            continue
        f1 = f"{r['f1']:.2f}" if r["f1"] is not None else "—"
        conf = f"{r['conf']:.0f}" if isinstance(r.get("conf"), (int, float)) else "—"
        lines.append(f"| {r['sample']} | {r['profile']} | {label} | {f1} | {r['acc']:.1f}% | {r['spp']:.2f} | {conf} |")
    for engine in ("paddleocr", "tesseract"):
        ok = [r for r in rows if r["engine"] == engine and r["ok"]]
        if ok:
            en = [r["f1"] for r in ok if r["f1"] is not None]
            lines.append("")
            lines.append(f"**{ocr_engines.ENGINE_LABELS[engine]}:** mean char accuracy {sum(r['acc'] for r in ok) / len(ok):.1f}% "
                         f"over {len(ok)} samples" + (f"; mean word F1 (English) {sum(en) / len(en):.2f}" if en else "")
                         + f"; mean {sum(r['spp'] for r in ok) / len(ok):.2f} s/page"
                         + (f"; peak child RSS {peaks[engine]:.0f} MB" if engine == "tesseract" else
                            f"; peak child RSS {peaks[engine]:.0f} MB (includes the Tesseract pass if that was higher)") + ".")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
