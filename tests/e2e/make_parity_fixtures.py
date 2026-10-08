"""Synthetic files for the parity/viewer browser checks (no real data). Usage: python make_parity_fixtures.py OUTDIR"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import make_image_pdf, make_text_pdf  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

out = Path(sys.argv[1])
files = out / "files"
files.mkdir(parents=True, exist_ok=True)

writer = PdfWriter()
for n in range(1, 4):
    writer.add_page(PdfReader(io.BytesIO(make_text_pdf(f"SAMPLE MULTI-PAGE DOCUMENT\nPage {n} of 3"))).pages[0])
with open(files / "Sample policy (3 pages).pdf", "wb") as fh:
    writer.write(fh)


def image(path, fmt, size=(1200, 800), colour=(40, 120, 80)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=colour, width=12)
    d.text((80, 80), "SAMPLE IMAGE - NOT A REAL DOCUMENT", fill=colour)
    img.save(path, fmt)


# an image-only scan (needs OCR) with labelled values, for the selective OCR and review queue checks
(files / "Sample residence card.pdf").write_bytes(make_image_pdf(
    "SAMPLE RESIDENCE CARD - NOT A REAL DOCUMENT\nName SON1 SAMPLE\nCard No 2345678901\nExpiry Date 31/12/2030"))

image(files / "Sample photo.jpg", "JPEG")
image(files / "Sample diagram.png", "PNG", (600, 900), (30, 60, 160))
image(files / "Sample scan.webp", "WEBP")
(files / "Sample notes.txt").write_text("Synthetic notes for testing.\n")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("[Content_Types].xml", "<Types/>")
    zf.writestr("word/document.xml", "<w:document/>")
(files / "Sample letter.docx").write_bytes(buf.getvalue())
(files / "Sample damaged.pdf").write_bytes(b"%PDF-1.4\nthis is not a valid pdf body\n%%EOF\n")

imp = out / "import" / "Old"
(imp / "Address Update 22July2026").mkdir(parents=True, exist_ok=True)
(imp / "Address Update 22July2026" / "letter.pdf").write_bytes(make_text_pdf("Synthetic letter"))
(imp / "report.pdf").write_bytes(make_text_pdf("Synthetic report"))
print(out)

# Test OCR / Compare engines input (kept outside files/, so it is never uploaded to the library)
from PIL import ImageFont  # noqa: E402

_t = Image.new("RGB", (1400, 360), "white")
_d = ImageDraw.Draw(_t)
try:
    _f = ImageFont.truetype("DejaVuSans.ttf", 56)
except OSError:
    _f = ImageFont.load_default(size=56)
_d.text((60, 70), "SAMPLE PERMIT - NOT REAL", fill="black", font=_f)
_d.text((60, 190), "Permit No 4455667788", fill="black", font=_f)
_t.save(out / "ocr-test-sample.png", "PNG")
