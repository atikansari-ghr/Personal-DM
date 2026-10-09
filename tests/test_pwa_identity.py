"""Change Set S: PWA identity (AT-260, AT-263 server/asset side). Browser install checks are in tests/e2e/pwa.mjs."""
import json
import struct
from pathlib import Path

import pytest

PUBLIC = Path(__file__).resolve().parents[1] / "frontend" / "public"
INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def _png_size(path: Path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    w, h = struct.unpack(">II", data[16:24])
    color_type = data[25]
    return w, h, color_type


def test_at260_manifest_fields_and_icons():
    m = json.loads((PUBLIC / "manifest.webmanifest").read_text())
    assert m["name"] == "Personal Documents Management System"
    assert m["short_name"] == "Personal DM" and len(m["short_name"]) <= 12  # fits under a Home Screen icon
    assert (m["id"], m["start_url"], m["scope"], m["display"]) == ("/", "/", "/", "standalone")
    assert m["theme_color"].startswith("#") and m["background_color"].startswith("#")
    purposes = {}
    for icon in m["icons"]:
        f = PUBLIC / icon["src"].lstrip("/")
        assert f.exists(), icon["src"]
        if icon["type"] == "image/png":
            w, h, _ = _png_size(f)
            assert f"{w}x{h}" == icon["sizes"], icon
        purposes.setdefault(icon.get("purpose", "any"), set()).add(icon["sizes"])
    assert {"192x192", "512x512"} <= purposes["any"]
    assert {"192x192", "512x512"} <= purposes["maskable"]


def test_at261_apple_touch_icon_markup_and_asset():
    html = INDEX.read_text()
    assert '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"' in html
    assert 'name="apple-mobile-web-app-title" content="Personal DM"' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    for name in ("apple-touch-icon.png", "apple-touch-icon-precomposed.png"):
        w, h, color_type = _png_size(PUBLIC / name)
        assert (w, h) == (180, 180)
    ico = (PUBLIC / "favicon.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and struct.unpack("<H", ico[4:6])[0] == 3
    assert _png_size(PUBLIC / "favicon-32.png")[:2] == (32, 32)
    assert _png_size(PUBLIC / "favicon-16.png")[:2] == (16, 16)


def test_at263_icons_are_opaque_where_platforms_need_it():
    from PIL import Image

    # iOS paints transparent pixels black; maskable icons are cropped by the platform: both must be full bleed.
    for name in ("apple-touch-icon.png", "icon-maskable-512.png", "icon-maskable-192.png"):
        im = Image.open(PUBLIC / name).convert("RGBA")
        w, h = im.size
        for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            assert im.getpixel(xy)[3] == 255, (name, xy)
    # maskable: the artwork (white document/shield) stays inside the 80 % safe circle
    im = Image.open(PUBLIC / "icon-maskable-512.png").convert("RGB")
    r = 0.4 * 512
    for x in range(0, 512, 4):
        for y in range(0, 512, 4):
            if (x - 256) ** 2 + (y - 256) ** 2 > r * r:
                p = im.getpixel((x, y))
                assert not (p[0] > 200 and p[1] > 200 and p[2] > 200), (x, y, p)


@pytest.mark.django_db
def test_at263_spa_never_answers_file_paths_with_html(client, settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    settings.FRONTEND_DIST = dist
    for p in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico", "/missing.webmanifest", "/x/y.js"):
        r = client.get(p)
        assert r.status_code == 404 and r["Content-Type"].startswith("text/plain"), p
    r = client.get("/folders/some-folder")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/html")
