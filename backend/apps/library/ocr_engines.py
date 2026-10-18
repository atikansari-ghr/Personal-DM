"""OCR engines: light-ocr (PP-OCRv6 Small, Change Set Z), Tesseract and PaddleOCR / PP-OCRv5 (Change Set Q).

The Main Admin sets the order under Settings → OCR → OCR Engines (``processing.ocr_engine_order``): the first engine
is the Primary, the others are Fallbacks in that order. In Auto mode (``processing.ocr_mode``) an engine that is not
installed, fails its health check or does not serve the language profile hands the run to the next one, and the run
records which engine produced the text and why the others were skipped. An engine that crashes on a document fails
that run safely (the previous result stays), as before. OCR engine priority is
independent of AI: AI never chooses or changes it.

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
ENGINE_LABELS = {"light-ocr": "light-ocr (PP-OCRv6 Small)", "paddleocr": "PaddleOCR PP-OCRv5", "tesseract": "Tesseract",
                 "unknown": "Unknown / Legacy"}
ENGINES = ("light-ocr", "tesseract", "paddleocr")
DEFAULT_ORDER = ["light-ocr", "tesseract", "paddleocr"]  # recommended for new installations
LIGHT_OCR_VERSION = "0.5.9"
LIGHT_OCR_ADDRESS_SPACE_MB = 8192  # virtual address space for one light-ocr process (see _light_call)
LIGHT_PROFILES = {"en"}  # PP-OCRv6 Small reads Latin script (and Chinese); other profiles go to the next engine


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


# ------------------------------------------------------------------ light-ocr status / health

def light_ocr_cli() -> Path:
    return Path(settings.LIGHT_OCR_HOME) / "node_modules" / "@arcships" / "light-ocr" / "src" / "cli.cjs"


def _light_workdir() -> Path:
    Path(settings.TMP_DIR).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="lightocr-", dir=settings.TMP_DIR))


def _light_call(args: list[str], timeout: int, cwd: Path):
    if not light_ocr_cli().exists():
        raise EngineError(f"light-ocr is not installed ({light_ocr_cli()} is missing). Run: sudo personaldocs repair",
                          "unavailable")
    try:
        # The limit is on virtual address space, not RAM: ONNX Runtime and Node reserve far more than they use, and
        # glibc reserves a malloc arena per thread (more cores, more reservations). With a 3 GB cap the native addon
        # could not load on hosts with many cores ("Unable to load the verified native addon", exit 70), so light-ocr
        # gets a generous cap and at most two arenas; its real use stays around 300-500 MB.
        return sandbox.run([settings.NODE_CMD, str(light_ocr_cli()), *args], timeout=timeout, cwd=cwd,
                           memory_mb=LIGHT_OCR_ADDRESS_SPACE_MB,
                           extra_env={"NODE_OPTIONS": "--max-old-space-size=1024", "MALLOC_ARENA_MAX": "2",
                                      "UV_THREADPOOL_SIZE": "2"}, cpu_seconds=timeout * 4 + 30)
    except sandbox.ToolError as exc:
        raise EngineError(str(exc), "timeout" if "timed out" in str(exc) else "unavailable")


def _light_error(proc) -> str:
    """light-ocr's own explanation (last non-empty stderr line), short and without paths of the documents."""
    import re

    lines = [ln.strip() for ln in (proc.stderr or b"").decode(errors="replace").splitlines() if ln.strip()]
    lines = [ln for ln in lines if not re.match(r"^\d+: 0x|^at |^=+|^-+$", ln)]  # stack frames and banners
    msg = next((ln for ln in reversed(lines) if ln.startswith("light-ocr:")), "") or next(
        (ln for ln in lines if re.search(r"(?i)error|fatal|unable|cannot|failed", ln)), "") or (lines[-1] if lines else "")
    return msg.replace("light-ocr:", "").strip()[:160]


def light_ocr_status(refresh: bool = False) -> dict:
    """Installed? which version? Cheap (no inference); cached for 10 minutes. Health is the self-test below."""
    from apps.security.models import HealthState

    st = HealthState.get("lightocr_status")
    fresh = st.get("checked_at") and (timezone.now().timestamp() - st.get("checked_ts", 0)) < 600
    if refresh or not fresh:
        info = {"installed": light_ocr_cli().exists(), "home": str(settings.LIGHT_OCR_HOME), "version": "", "error": ""}
        if info["installed"]:
            workdir = _light_workdir()
            try:
                proc = _light_call(["info", "--version"], timeout=60, cwd=workdir)
                out = (proc.stdout or b"").decode(errors="replace").strip()
                try:  # `info --version` prints {"npm": "0.5.9", "core": ..., "model": "ppocrv6-small-..."}
                    v = json.loads(out)
                    info["version"] = f"light-ocr {v.get('npm') or v.get('core')} ({v.get('model', '')})".replace(" ()", "")[:80]
                except (ValueError, AttributeError):
                    info["version"] = out.splitlines()[0][:80] if out else ""
                if proc.returncode != 0:
                    why = _light_error(proc)
                    info["error"] = f"light-ocr did not start (exit {proc.returncode})" + (f": {why}" if why else ". Is Node.js 20+ installed?")
            except EngineError as exc:
                info["error"] = str(exc)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        st = HealthState.put("lightocr_status", **info, checked_at=timezone.now().isoformat(),
                             checked_ts=timezone.now().timestamp())
    health = HealthState.get("lightocr_health")
    return {**st, "selftest": health or None, "healthy": bool(st.get("installed") and not st.get("error") and health.get("healthy"))}


def light_ocr_selftest(actor=None) -> dict:
    """Real recognition of a generated sample (never a family document): the only thing that makes light-ocr healthy."""
    from PIL import Image, ImageDraw, ImageFont

    from apps.core import audit
    from apps.security.models import HealthState

    expected = "SAMPLE 12345"
    t0 = time.monotonic()
    workdir = _light_workdir()
    try:
        img = Image.new("RGB", (900, 220), "white")
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 72)
        except OSError:
            font = ImageFont.load_default(size=72)
        ImageDraw.Draw(img).text((40, 60), expected, fill="black", font=font)
        img.save(workdir / "selftest.png")
        res = light_ocr_recognise([(workdir / "selftest.png", 1)], workdir, timeout=120)
        text = res.text(False)
        ok = expected.replace(" ", "") in text.replace(" ", "").upper()
        out = {"ok": ok, "healthy": ok, "text": text[:80], "expected": expected, "seconds": res.seconds,
               "version": res.version, "model": res.model}
        if not ok:
            out.update(error="failed", message="light-ocr ran but did not read the sample text.")
    except EngineError as exc:
        out = {"ok": False, "healthy": False, "error": exc.category, "message": str(exc)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    out.update(at=timezone.now().isoformat(), wall_seconds=round(time.monotonic() - t0, 1))
    HealthState.put("lightocr_health", **out)
    audit.record("ocr.engine_selftest", actor=actor, outcome="success" if out.get("healthy") else "failure", engine="light-ocr")
    return out


# ------------------------------------------------------------------ engine order (Primary / Fallbacks)

def engine_order() -> list[str]:
    order = [e for e in (config.get("processing.ocr_engine_order") or []) if e in ENGINES]
    return list(dict.fromkeys(order)) or ["tesseract"]


def primary_engine() -> str:
    return engine_order()[0]


def unavailable_reason(engine: str, profile: str | None = None) -> str:
    """'' when the engine can run now for this language profile; otherwise why not (shown to people and recorded)."""
    if engine == "tesseract":
        return ""
    if engine == "light-ocr":
        if profile and profile not in LIGHT_PROFILES:
            return f"it does not read the {OCR_PROFILES.get(profile, profile)} profile"
        st = light_ocr_status()
        if not st.get("installed"):
            return "light-ocr is not installed"
        if st.get("error"):
            return st["error"]
        health = st.get("selftest") or {}
        if health and not health.get("healthy"):
            return "its self-test failed: " + (health.get("message") or health.get("error") or "unknown error")
        return ""
    if engine == "paddleocr":
        st = paddle_status()
        if st.get("installed") and not st.get("error") and not st.get("missing_models"):
            return ""
        return st.get("error") or ("missing models: " + ", ".join(st.get("missing_models") or [])
                                   if st.get("installed") else "PaddleOCR is not installed")
    return "unknown engine"


def resolve_engine(requested: str | None = None, profile: str | None = None) -> tuple[str, str]:
    """(engine, note). An explicitly requested engine is used as asked (or fails); otherwise the configured order is
    walked: Primary first, then — in Auto mode only — each Fallback in turn. ``note`` says truthfully which engines
    were skipped and why."""
    if requested:
        reason = unavailable_reason(requested, profile)
        if reason:
            raise EngineError(f"{ENGINE_LABELS.get(requested, requested)} is not available: {reason}. Run `sudo personaldocs "
                              "repair`, or choose another engine.", "unavailable")
        return requested, ""
    order = engine_order()
    candidates = order if config.get("processing.ocr_mode") != "primary_only" else order[:1]
    skipped = []
    for engine in candidates:
        reason = unavailable_reason(engine, profile)
        if not reason:
            note = "; ".join(skipped) + f"; fallback to {ENGINE_LABELS[engine]} used" if skipped else ""
            return engine, note
        skipped.append(f"{ENGINE_LABELS[engine]} unavailable ({reason})")
    raise EngineError("No OCR engine is available: " + "; ".join(skipped) + (
        ". OCR mode is “Primary only”, so no fallback engine was tried." if len(candidates) < len(order) else
        ". Run `sudo personaldocs repair`."), "unavailable")


def engines_overview() -> list[dict]:
    """Settings → OCR → OCR Engines: each engine in the configured order with its availability."""
    order = engine_order()
    rest = [e for e in ENGINES if e not in order]
    out = []
    for i, e in enumerate(order + rest):
        reason = unavailable_reason(e)
        out.append({"engine": e, "label": ENGINE_LABELS[e], "position": i + 1 if e in order else None,
                    "role": ("Primary" if i == 0 else f"Fallback {i}") if e in order else "Not used",
                    "available": not reason, "reason": reason})
    return out


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


def light_ocr_recognise(images: list[tuple[Path, int]], workdir: Path, timeout: int, profile: str = "en") -> RunResult:
    """One light-ocr process per page image (JSON output); lines map to the same shape as PaddleOCR's."""
    t0 = time.monotonic()
    pages, model, version = [], "", ""
    for path, n in images:
        proc = _light_call([str(path), "--format", "json", "--quiet", "--provider", "cpu"], timeout=timeout, cwd=workdir)
        try:
            data = json.loads((proc.stdout or b"").decode(errors="replace"))
        except ValueError:
            err = (proc.stderr or b"").decode(errors="replace")
            category = "memory" if ("out of memory" in err.lower() or proc.returncode in (-9, 137)) else "failed"
            why = _light_error(proc)
            raise EngineError(f"light-ocr stopped without a result (exit {proc.returncode})" + (f": {why}" if why else "")
                              + ".", category)
        for pg in data.get("pages") or []:
            lines = []
            for ln in pg.get("lines") or []:
                text = str(ln.get("text") or "").strip()
                if not text:
                    continue
                pts = [p for p in (ln.get("box") or []) if isinstance(p, dict)]
                xs, ys = [p.get("x", 0) for p in pts] or [0], [p.get("y", 0) for p in pts] or [0]
                lines.append({"text": text, "score": round(float(ln.get("confidence") or 0), 4),
                              "box": [min(xs), min(ys), max(xs), max(ys)], "lang": "en"})
            pages.append(PageResult(page=n, lines=lines))
            model = str(pg.get("modelBundleId") or model)
    version = f"light-ocr {LIGHT_OCR_VERSION}"
    st = light_ocr_status()
    if st.get("version"):
        version = st["version"] if "light-ocr" in st["version"] else f"light-ocr {st['version']}"
    return RunResult(engine="light-ocr", model=(model or "PP-OCRv6 Small")[:200], version=version[:80], profile=profile,
                     languages=["en"], pages=pages, seconds=round(time.monotonic() - t0, 2))


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
