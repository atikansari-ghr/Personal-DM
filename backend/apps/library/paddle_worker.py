"""PaddleOCR / PP-OCRv5 worker (Change Set Q). Runs in its own virtual environment, never inside the web app.

    python paddle_worker.py run REQUEST.json RESULT.json   recognise page images (no network: local model folders only)
    python paddle_worker.py selftest                       real minimal inference on a generated image, prints JSON
    python paddle_worker.py versions                       library versions, CPU features and installed models (JSON)
    python paddle_worker.py install-models LANG [LANG...] [--model mobile|server]
                                                           download the models into $PADDLE_PDX_CACHE_HOME (installer)

The application starts this script with a memory limit, a time limit and a private temporary directory, one process per
OCR job, so a PaddlePaddle crash or a runaway page cannot take the web application, PostgreSQL or ClamAV down. It never
writes recognised text anywhere except RESULT.json in that private directory, and logs no document content.

Language routing: PP-OCRv5 has one recognition model per script. A bilingual profile (e.g. Arabic + English) runs
the page through each model and keeps, for every detected text line, the reading with the higher recognition score;
lines found by only one model are kept as they are.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DET = {"mobile": "PP-OCRv5_mobile_det", "server": "PP-OCRv5_server_det"}
REC = {"en": "en_PP-OCRv5_mobile_rec", "ar": "arabic_PP-OCRv5_mobile_rec", "hi": "devanagari_PP-OCRv5_mobile_rec",
       "te": "te_PP-OCRv5_mobile_rec", "ta": "ta_PP-OCRv5_mobile_rec"}
DOC_ORI, TEXTLINE_ORI, UNWARP = "PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_textline_ori", "UVDoc"


def _home() -> Path:
    return Path(os.environ.get("PADDLE_PDX_CACHE_HOME") or Path.home() / ".paddlex")


def model_dir(name: str) -> Path:
    return _home() / "official_models" / name


def required_models(langs: list[str], model: str = "mobile", orientation=True, textline=True, unwarping=False) -> list[str]:
    names = [DET.get(model, DET["mobile"])] + [REC[x] for x in langs if x in REC]
    if orientation:
        names.append(DOC_ORI)
    if textline:
        names.append(TEXTLINE_ORI)
    if unwarping:
        names.append(UNWARP)
    return names


def missing_models(names: list[str]) -> list[str]:
    return [n for n in names if not (model_dir(n) / "inference.yml").exists() and not any(model_dir(n).glob("inference.*"))]


def _versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("paddle", "paddleocr", "paddlex"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "?")
        except Exception as exc:  # noqa: BLE001 - reported, not fatal here
            out[mod] = f"not importable ({exc.__class__.__name__})"
    try:
        flags = Path("/proc/cpuinfo").read_text(errors="replace")
        out["cpu_avx"] = " avx " in flags or " avx\n" in flags or "avx2" in flags
    except OSError:
        out["cpu_avx"] = None
    root = _home() / "official_models"
    out["models"] = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    out["home"] = str(_home())
    return out


def _engine(lang: str, opts: dict):
    from paddleocr import PaddleOCR

    det = DET.get(opts.get("model") or "mobile", DET["mobile"])
    kw = dict(text_detection_model_name=det, text_detection_model_dir=str(model_dir(det)),
              text_recognition_model_name=REC[lang], text_recognition_model_dir=str(model_dir(REC[lang])),
              use_doc_orientation_classify=bool(opts.get("orientation")), use_doc_unwarping=bool(opts.get("unwarping")),
              use_textline_orientation=bool(opts.get("textline")), device="cpu", cpu_threads=int(opts.get("threads") or 2))
    if opts.get("orientation"):
        kw.update(doc_orientation_classify_model_name=DOC_ORI, doc_orientation_classify_model_dir=str(model_dir(DOC_ORI)))
    if opts.get("unwarping"):
        kw.update(doc_unwarping_model_name=UNWARP, doc_unwarping_model_dir=str(model_dir(UNWARP)))
    if opts.get("textline"):
        kw.update(textline_orientation_model_name=TEXTLINE_ORI, textline_orientation_model_dir=str(model_dir(TEXTLINE_ORI)))
    return PaddleOCR(**kw)


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / area if area > 0 else 0.0


def merge(candidates: list[dict]) -> list[dict]:
    """Keep the best reading per text line (highest score), then reading order (rows top to bottom, left to right)."""
    kept: list[dict] = []
    for c in sorted(candidates, key=lambda x: -x["score"]):
        if all(_iou(c["box"], k["box"]) < 0.5 for k in kept):
            kept.append(c)
    if not kept:
        return kept
    heights = sorted(k["box"][3] - k["box"][1] for k in kept)
    row = max(4.0, heights[len(heights) // 2] * 0.6)
    return sorted(kept, key=lambda k: (round(((k["box"][1] + k["box"][3]) / 2) / row), k["box"][0]))


def run(request: dict) -> dict:
    langs = [x for x in request.get("langs") or ["en"] if x in REC]
    if not langs:
        return {"ok": False, "error": "profile", "message": "No supported recognition language in the profile."}
    opts = {k: request.get(k) for k in ("model", "orientation", "textline", "unwarping", "threads")}
    missing = missing_models(required_models(langs, opts.get("model") or "mobile", bool(opts["orientation"]),
                                             bool(opts["textline"]), bool(opts["unwarping"])))
    if missing:
        return {"ok": False, "error": "model_missing", "message": "PP-OCRv5 model(s) not installed: " + ", ".join(missing)
                + ". Run: sudo personaldocs ocr install-models"}
    t0 = time.monotonic()
    engines = {lang: _engine(lang, opts) for lang in langs}
    load = time.monotonic() - t0
    pages = []
    for item in request.get("images") or []:
        candidates, angle = [], None
        for lang, eng in engines.items():
            for res in eng.predict(item["path"]):
                pre = res.get("doc_preprocessor_res") or {}
                if angle is None and isinstance(pre, dict):
                    angle = pre.get("angle")
                boxes = res.get("rec_boxes")
                for i, (text, score) in enumerate(zip(res.get("rec_texts") or [], res.get("rec_scores") or [])):
                    if not str(text).strip():
                        continue
                    box = [float(v) for v in boxes[i]] if boxes is not None and len(boxes) > i else [0, 0, 0, 0]
                    candidates.append({"text": str(text), "score": round(float(score), 4), "box": [round(v, 1) for v in box],
                                       "lang": lang})
        pages.append({"page": item.get("page", 1), "angle": angle if angle is None else int(angle), "lines": merge(candidates)})
    v = _versions()
    det = DET.get(opts.get("model") or "mobile", DET["mobile"])
    return {"ok": True, "engine": "paddleocr", "versions": {k: v.get(k) for k in ("paddle", "paddleocr", "paddlex")},
            "models": {"det": det, "rec": {x: REC[x] for x in langs}}, "pages": pages,
            "seconds": round(time.monotonic() - t0, 2), "load_seconds": round(load, 2)}


SELFTEST_TEXT = "PERSONAL DOCUMENTS OCR SELF TEST 2027"


def selftest() -> dict:
    """Real inference on a generated image (no document involved). Import alone is never reported as healthy."""
    import tempfile

    from PIL import Image, ImageDraw, ImageFont

    with tempfile.TemporaryDirectory(prefix="paddle-selftest-") as d:
        img = Image.new("RGB", (1100, 160), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
            if Path(f).exists():
                font = ImageFont.truetype(f, 44)
                break
        if font is None:
            try:
                font = ImageFont.load_default(size=44)
            except TypeError:
                font = ImageFont.load_default()
        draw.text((30, 50), SELFTEST_TEXT, fill="black", font=font)
        path = Path(d) / "selftest.png"
        img.save(path)
        res = run({"images": [{"path": str(path), "page": 1}], "langs": ["en"], "model": "mobile", "orientation": False,
                   "textline": False, "unwarping": False, "threads": 1})
    if not res.get("ok"):
        return {**res, "healthy": False}
    text = " ".join(line["text"] for p in res["pages"] for line in p["lines"])
    norm = "".join(ch for ch in text.upper() if ch.isalnum())
    want = "".join(ch for ch in SELFTEST_TEXT if ch.isalnum())
    ok = want in norm
    return {"ok": True, "healthy": ok, "text": text, "expected": SELFTEST_TEXT, "seconds": res["seconds"],
            "versions": res["versions"], "models": res["models"]}


def install_models(langs: list[str], model: str = "mobile") -> dict:
    """Download models (network needed; installer only). Runs one tiny pipeline per language so every model loads."""
    from paddleocr import PaddleOCR

    done = []
    for lang in langs:
        if lang not in REC:
            continue
        PaddleOCR(text_detection_model_name=DET.get(model, DET["mobile"]), text_recognition_model_name=REC[lang],
                  use_doc_orientation_classify=True, use_doc_unwarping=False, use_textline_orientation=True, device="cpu")
        done.append(REC[lang])
    return {"ok": True, "installed": done, "missing": missing_models(required_models(langs, model)), "home": str(_home())}


def main(argv: list[str]) -> int:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    try:
        if cmd == "run" and len(argv) == 3:
            out = run(json.loads(Path(argv[1]).read_text()))
            Path(argv[2]).write_text(json.dumps(out, ensure_ascii=False))
            return 0 if out.get("ok") else 3
        if cmd == "selftest":
            out = selftest()
        elif cmd == "versions":
            out = _versions()
        elif cmd == "install-models":
            model = "mobile"
            langs = [a for a in argv[1:] if not a.startswith("--")]
            if "--model" in argv:
                model = argv[argv.index("--model") + 1]
                langs = [a for a in langs if a != model]
            out = install_models(langs or ["en"], model)
        else:
            print(__doc__)
            return 2
    except Exception as exc:  # noqa: BLE001 - reported to the caller as JSON, never with document content
        out = {"ok": False, "error": "failed", "message": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
        if cmd != "run":  # installer commands never touch documents: show where it failed, for diagnosis
            import traceback

            frames = traceback.extract_tb(exc.__traceback__)[-3:]
            out["where"] = [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames]
            traceback.print_exc(file=sys.stderr)
        if cmd == "run" and len(argv) == 3:
            Path(argv[2]).write_text(json.dumps(out))
            return 3
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") and out.get("healthy", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
