"""Stand-in for apps/library/paddle_worker.py in tests (CI has no 1.3 GB PaddlePaddle runtime).

Speaks the same protocol (run / selftest / versions) and reads the text with the Tesseract CLI so documents get real
recognised text. Behaviour is switched with a file "fake_mode" in $PADDLE_PDX_CACHE_HOME:
  ok (default) | fail (worker reports an error) | crash (exit without a result) | slow (sleeps 30 s)
The live PaddleOCR test (tests/test_ocr_engines_lifecycle.py::test_live_*) runs the real worker instead.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("PADDLE_PDX_CACHE_HOME") or ".")
MODELS = ["PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec", "arabic_PP-OCRv5_mobile_rec", "devanagari_PP-OCRv5_mobile_rec",
          "te_PP-OCRv5_mobile_rec", "ta_PP-OCRv5_mobile_rec", "PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_textline_ori"]
TESS = {"en": "eng", "ar": "ara", "hi": "hin", "te": "tel", "ta": "tam"}


def mode() -> str:
    try:
        return (HOME / "fake_mode").read_text().strip()
    except OSError:
        return "ok"


def recognise(path: str, langs: list[str]) -> list[dict]:
    lang = "+".join(TESS[x] for x in langs if x in TESS) or "eng"
    out = subprocess.run(["tesseract", path, "stdout", "-l", lang, "--psm", "3"], capture_output=True, timeout=120)
    lines = [ln for ln in out.stdout.decode(errors="replace").splitlines() if ln.strip()]
    return [{"text": ln, "score": 0.95, "box": [10.0, 40.0 * i, 900.0, 40.0 * i + 30], "lang": langs[0]} for i, ln in enumerate(lines)]


def main(argv):
    m = mode()
    if argv[0] == "versions":
        print(json.dumps({"python": "3.13", "paddle": "3.2.2", "paddleocr": "3.7.0", "paddlex": "3.7.2", "cpu_avx": True,
                          "models": MODELS, "home": str(HOME)}))
        return 0
    if argv[0] == "selftest":
        ok = m == "ok"
        print(json.dumps({"ok": ok, "healthy": ok, "text": "PERSONAL DOCUMENTS OCR SELF TEST 2027" if ok else "",
                          "expected": "PERSONAL DOCUMENTS OCR SELF TEST 2027", "seconds": 0.1,
                          "versions": {"paddle": "3.2.2", "paddleocr": "3.7.0"}, **({} if ok else {"message": "fake failure"})}))
        return 0 if ok else 1
    if argv[0] == "run":
        req = json.loads(Path(argv[1]).read_text())
        if m == "crash":
            return 9
        if m == "slow":
            time.sleep(30)
        if m == "fail":
            Path(argv[2]).write_text(json.dumps({"ok": False, "error": "failed", "message": "fake PaddleOCR failure"}))
            return 3
        (HOME / "last_request.json").write_text(json.dumps(req))  # lets tests check routing (never document text)
        pages = [{"page": im["page"], "angle": 0, "lines": recognise(im["path"], req["langs"])} for im in req["images"]]
        Path(argv[2]).write_text(json.dumps({
            "ok": True, "engine": "paddleocr", "versions": {"paddle": "3.2.2", "paddleocr": "3.7.0", "paddlex": "3.7.2"},
            "models": {"det": "PP-OCRv5_mobile_det", "rec": {x: f"{x}_PP-OCRv5_mobile_rec" for x in req["langs"]}},
            "pages": pages, "seconds": 0.2, "load_seconds": 0.1}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
