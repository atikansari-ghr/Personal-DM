"""Synthetic document generators (no Django imports; usable from scripts)."""
import io


def make_text_pdf(text: str) -> bytes:
    """Minimal born-digital PDF with real text (synthetic content)."""
    lines = text.split("\n")
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({ln.replace('(', '').replace(')', '')}) Tj T*" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_image_pdf(text: str) -> bytes:
    """Image-only PDF (a 'scan') containing rendered synthetic text."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1700, 1100), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 56)
    except OSError:
        font = ImageFont.load_default(size=56)
    y = 120
    for line in text.split("\n"):
        d.text((100, y), line, fill="black", font=font)
        y += 110
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    return buf.getvalue()
