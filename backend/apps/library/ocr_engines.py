"""OCR engines (Change Set Q): PaddleOCR / PP-OCRv5 (default) and Tesseract (Legacy / fallback).

    profile -> engine routing
      English                 PaddleOCR: en_PP-OCRv5_mobile_rec              Tesseract: eng
      Arabic + English        PaddleOCR: arabic_ + en_PP-OCRv5_mobile_rec    Tesseract: ara+eng
      Hindi + English         PaddleOCR: devanagari_ + en_PP-OCRv5_mobile_rec Tesseract: hin+eng
      Telugu + English        PaddleOCR: te_ + en_PP-OCRv5_mobile_rec        Tesseract: tel+eng
      Tamil + English         PaddleOCR: ta_ + en_PP-OCRv5_mobile_rec        Tesseract: tam+eng

PaddleOCR runs in its own virtual environment (settings.PADDLE_PYTHON) through apps/library/paddle_worker.py, one
process per job, with a memory limit, a CPU/time limit, a private temporary directory and no network access needed
(models are local in settings.PADDLE_HOME). Its health is a real inference self-test, never just an import.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.core import config
from apps.core.registry import OCR_PROFILES

from . import sandbox

WORKER = Path(__file__).with_name("paddle_worker.py")
PADDLE_LANGS = {"en": ["en"], "ar_en": ["ar", "en"], "hi_en": ["hi", "en"], "te_en": ["te", "en"], "ta_en": ["ta", "en"]}
TESSERACT_LANGS = {"en": ["eng"], "ar_en": ["ara", "eng"], "hi_en": ["hin", "eng"], "te_en": ["tel", "eng"], "ta_en": ["tam", "eng"]}
LOW_SCORE = 0.6  # PaddleOCR line score below this is shown as low confidence (and kept out of field extraction)
ENGINE_LABELS = {"paddleocr": "PaddleOCR PP-OCRv5", "tesseract": "Tesseract (Legacy)", "unknown": "Unknown / Legacy"}


class EngineError(Exception):
    def __init__(self, message: str, category: str = "failed"):
        super().__init__(message)
        self.category = category  # unavailable | model_missing | timeout | memory | failed


@dataclass
class PageResult:
    page: int
    lines: list = field(default_factory=list)  # [{"text", "score" 0-1, "box" [x1,y1,x2,y2], "lang"}]
    angle: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(ln["text"] for ln in self.lines)

    def reliable_text(self) -> str:
        return "\n".join(ln["text"] for ln in self.lines if ln["score"] >= LOW_SCORE)


@dataclass
class RunResult:
    engine: str
    model: str
    version: str
    profile: str
    languages: list
    pages: list = field(default_factory=list)
    seconds: float = 0.0

    def text(self, paged: bool) -> str:
        if not paged:
            return "\n".join(p.text for p in self.pages)
        return "\n\n".join(f"[Page {p.page}]\n{p.text}" for p in self.pages)

    def reliable_text(self) -> str:
        return "\n".join(p.reliable_text() for p in self.pages)

    def lines(self) -> list:
        return [ln for p in self.pages for ln in p.lines]

    def quality(self) -> dict:
        lines = self.lines()
        scores = [ln["score"] for ln in lines]
        low = [i for i, ln in enumerate(lines) if ln["score"] < LOW_SCORE]
        return {"engine": self.engine, "model": self.model, "engine_version": self.version, "profile": self.profile,
                "confidence": round(100 * sum(scores) / len(scores), 1) if scores else 0, "low_lines": low,
                "line_count": len(lines), "line_confidence": [round(100 * s) for s in scores][:2000],
                "rotation": next((p.angle for p in self.pages if p.angle), 0) or 0, "seconds": self.seconds,
                "steps": [s for s, on in (("orientation", config.get("processing.paddle_orientation")),
                                         ("text-line orientation", config.get("processing.paddle_textline")),
                                         ("unwarping", config.get("processing.paddle_unwarping"))) if on]}

    def blocks(self) -> list:
        return [{"page": p.page, "angle": p.angle, "lines": p.lines} for p in self.pages]


# ------------------------------------------------------------------ profiles

def offered_profiles() -> list[str]:
    return [p for p in (config.get("processing.ocr_profiles") or ["en"]) if p in OCR_PROFILES] or ["en"]


def profile_for(doc) -> str:
    if doc is not None and doc.doc_type_id and doc.doc_type and doc.doc_type.ocr_profile in OCR_PROFILES:
        return doc.doc_type.ocr_profile
    p = config.get("processing.ocr_default_profile")
    return p if p in OCR_PROFILES else "en"


def profile_status() -> list[dict]:
    st = paddle_status()
    models = set(st.get("models") or [])
    out = []
    for key, label in OCR_PROFILES.items():
        from .paddle_worker import REC

        needed = [REC[x] for x in PADDLE_LANGS[key]]
        out.append({"key": key, "label": label, "offered": key in offered_profiles(), "paddle_models": needed,
                    "paddle_installed": all(m in models for m in needed), "tesseract_languages": TESSERACT_LANGS[key]})
    return out


# ------------------------------------------------------------------ PaddleOCR status / health

def paddle_python() -> Path:
    return Path(settings.PADDLE_PYTHON)


def paddle_home() -> Path:
    return Path(settings.PADDLE_HOME)


def _worker_env() -> dict:
    threads = str(int(config.get("processing.paddle_cpu_threads")))
    return {"PADDLE_PDX_CACHE_HOME": str(paddle_home()), "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            "OMP_NUM_THREADS": threads, "OMP_THREAD_LIMIT": threads, "FLAGS_use_mkldnn": "1",
            "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def _call(args: list[str], timeout: int, memory_mb: int | None = None, cwd: Path | None = None) -> dict:
    if not paddle_python().exists():
        raise EngineError(f"PaddleOCR is not installed ({paddle_python()} is missing). Run: sudo personaldocs repair",
                          "unavailable")
    own = cwd is None
    workdir = cwd or Path(tempfile.mkdtemp(prefix="paddle-", dir=settings.TMP_DIR))
    try:
        threads = int(config.get("processing.paddle_cpu_threads"))
        proc = sandbox.run([str(paddle_python()), str(WORKER), *args], timeout=timeout, cwd=workdir,
                           memory_mb=memory_mb or int(config.get("processing.paddle_memory_mb")),
                           extra_env=_worker_env(), cpu_seconds=timeout * max(1, threads) + 30)
    except sandbox.ToolError as exc:
        raise EngineError(str(exc), "timeout" if "timed out" in str(exc) else "unavailable")
    finally:
        if own:
            shutil.rmtree(workdir, ignore_errors=True)
    out = (proc.stdout or b"").decode(errors="replace").strip().splitlines()
    try:
        return json.loads(out[-1]) if out else {}
    except ValueError:
        err = (proc.stderr or b"").decode(errors="replace")
        category = "memory" if "MemoryError" in err or "bad_alloc" in err or proc.returncode in (-9, 137) else "failed"
        raise EngineError(f"PaddleOCR stopped unexpectedly (exit {proc.returncode}).", category)


def paddle_status(refresh: bool = False) -> dict:
    """Installed? which versions and models? Cheap (no inference); cached for 10 minutes."""
    from apps.security.models import HealthState

    st = HealthState.get("paddleocr_status")
    fresh = st.get("checked_at") and (timezone.now().timestamp() - st.get("checked_ts", 0)) < 600
    if refresh or not fresh:
        info = {"installed": paddle_python().exists(), "python": str(paddle_python()), "home": str(paddle_home())}
        if info["installed"]:
            try:
                info.update(_call(["versions"], timeout=120, memory_mb=2048))
                info["error"] = ""
            except EngineError as exc:
                info["error"] = str(exc)
        st = HealthState.put("paddleocr_status", **info, checked_at=timezone.now().isoformat(),
                             checked_ts=timezone.now().timestamp())
    from .paddle_worker import required_models

    needed = set()
    for p in offered_profiles():
        needed.update(required_models(PADDLE_LANGS[p], config.get("processing.paddle_model"),
                                      config.get("processing.paddle_orientation"), config.get("processing.paddle_textline"),
                                      config.get("processing.paddle_unwarping")))
    have = set(st.get("models") or [])
    health = HealthState.get("paddleocr_health")
    return {**st, "required_models": sorted(needed), "missing_models": sorted(needed - have),
            "selftest": health or None, "healthy": bool(st.get("installed") and not (needed - have) and health.get("healthy"))}


def paddle_selftest(actor=None) -> dict:
    """Real minimal inference (the only thing that makes PaddleOCR "healthy")."""
    from apps.core import audit
    from apps.security.models import HealthState

    t0 = time.monotonic()
    try:
        res = _call(["selftest"], timeout=300)
    except EngineError as exc:
        res = {"ok": False, "healthy": False, "error": exc.category, "message": str(exc)}
    res = {k: v for k, v in res.items() if k in ("ok", "healthy", "text", "expected", "seconds", "versions", "models",
                                                    "error", "message")}
    res.update(at=timezone.now().isoformat(), wall_seconds=round(time.monotonic() - t0, 1))
    HealthState.put("paddleocr_health", **res)
    audit.record("ocr.engine_selftest", actor=actor, outcome="success" if res.get("healthy") else "failure", engine="paddleocr")
    return res


def resolve_engine(requested: str | None = None) -> tuple[str, str]:
    """(engine, note). An explicitly requested engine is used as asked; the default may fall back to Tesseract."""
    engine = requested or config.get("processing.ocr_engine") or "paddleocr"
    if engine == "tesseract":
        return "tesseract", ""
    st = paddle_status()
    usable = st.get("installed") and not st.get("error") and not st.get("missing_models")
    if usable:
        return "paddleocr", ""
    reason = st.get("error") or ("missing models: " + ", ".join(st.get("missing_models") or [])
                                 if st.get("installed") else "PaddleOCR is not installed")
    if requested is None and config.get("processing.ocr_engine_fallback"):
        return "tesseract", f"PaddleOCR unavailable ({reason}); Tesseract fallback used"
    raise EngineError(f"PaddleOCR is not available: {reason}. Run `sudo personaldocs repair`, or choose Tesseract (Legacy).",
                      "unavailable")


# ------------------------------------------------------------------ recognition

def prepare_image(src: Path, dst: Path) -> Path:
    """Upright (EXIF) RGB PNG, long side at most 4000 px: bounded memory for any photo or scan."""
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = int(config.get("processing.max_image_megapixels")) * 1_000_000
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if max(im.size) > 4000:
            f = 4000 / max(im.size)
            im = im.resize((round(im.width * f), round(im.height * f)), resample=Image.LANCZOS)
        im.save(dst, "PNG")
    return dst


def render_pdf_pages(path: Path, pages: list[int], workdir: Path, timeout: int) -> list[tuple[Path, int]]:
    out = []
    for n in pages:
        prefix = workdir / f"p{n}"
        proc = sandbox.run([settings.PDFTOPPM_CMD, "-png", "-r", "300", "-f", str(n), "-l", str(n), "-singlefile",
                            str(path), str(prefix)], timeout=min(timeout, 300), cwd=workdir)
        png = workdir / f"p{n}.png"
        if proc.returncode != 0 or not png.exists():
            raise sandbox.ToolError(f"page {n} could not be rendered")
        out.append((prepare_image(png, workdir / f"p{n}-in.png"), n))
        png.unlink(missing_ok=True)
    return out


def paddle_recognise(images: list[tuple[Path, int]], profile: str, workdir: Path, timeout: int) -> RunResult:
    req = {"images": [{"path": str(p), "page": n} for p, n in images], "langs": PADDLE_LANGS.get(profile, ["en"]),
           "model": config.get("processing.paddle_model"), "orientation": bool(config.get("processing.paddle_orientation")),
           "textline": bool(config.get("processing.paddle_textline")), "unwarping": bool(config.get("processing.paddle_unwarping")),
           "threads": int(config.get("processing.paddle_cpu_threads"))}
    (workdir / "request.json").write_text(json.dumps(req))
    try:
        threads = int(config.get("processing.paddle_cpu_threads"))
        proc = sandbox.run([str(paddle_python()), str(WORKER), "run", "request.json", "result.json"], timeout=timeout,
                           cwd=workdir, memory_mb=int(config.get("processing.paddle_memory_mb")), extra_env=_worker_env(),
                           cpu_seconds=timeout * max(1, threads) + 30)
    except sandbox.ToolError as exc:
        raise EngineError(str(exc), "timeout" if "timed out" in str(exc) else "unavailable")
    try:
        res = json.loads((workdir / "result.json").read_text())
    except (OSError, ValueError):
        err = (proc.stderr or b"").decode(errors="replace")
        category = "memory" if ("MemoryError" in err or "bad_alloc" in err or proc.returncode in (-9, 137)) else "failed"
        raise EngineError("PaddleOCR stopped without a result" + (" (memory limit reached; raise “PaddleOCR memory limit”)"
                                                                  if category == "memory" else "") + ".", category)
    finally:
        (workdir / "result.json").unlink(missing_ok=True)
    if not res.get("ok"):
        raise EngineError(res.get("message") or "PaddleOCR failed.", res.get("error") or "failed")
    vers = res.get("versions") or {}
    models = res.get("models") or {}
    model = " + ".join([models.get("det", "")] + list((models.get("rec") or {}).values()))
    return RunResult(engine="paddleocr", model=model[:200], profile=profile, languages=PADDLE_LANGS.get(profile, ["en"]),
                     version=f"PaddleOCR {vers.get('paddleocr')} / PaddlePaddle {vers.get('paddle')}",
                     pages=[PageResult(page=p["page"], lines=p.get("lines") or [], angle=p.get("angle")) for p in res["pages"]],
                     seconds=float(res.get("seconds") or 0))


def tesseract_recognise(images: list[tuple[Path, int]], profile: str | None, langs: list[str] | None, timeout: int,
                        rotate=None) -> RunResult:
    """Tesseract with the existing preprocessing (Legacy); used for Test / Compare and image runs."""
    from PIL import Image

    from . import ocr as ocrlib

    langs = langs or TESSERACT_LANGS.get(profile or "en", ["eng"])
    t0 = time.monotonic()
    pages = []
    for path, n in images:
        with Image.open(path) as im:
            im.load()
            r = ocrlib.recognise(im, ocrlib.Options(rotate=rotate), lang="+".join(langs), timeout=timeout)
        pages.append(PageResult(page=n, angle=r.rotation, lines=[{"text": ln.text, "score": round(ln.confidence / 100, 4),
                                                                   "box": [0, 0, 0, 0], "lang": "+".join(langs)} for ln in r.lines]))
    return RunResult(engine="tesseract", model="Tesseract " + "+".join(langs), version=tesseract_version(), profile=profile or "",
                     languages=langs, pages=pages, seconds=round(time.monotonic() - t0, 2))


def tesseract_version() -> str:
    import subprocess

    try:
        out = subprocess.run([settings.TESSERACT_CMD, "--version"], capture_output=True, timeout=10)
        return (out.stdout or out.stderr).decode(errors="replace").splitlines()[0].strip()[:80]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "tesseract (version unknown)"
