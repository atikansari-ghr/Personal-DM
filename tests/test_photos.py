"""Profile photos (AT-37, AT-38): upload, crop, replace, remove, validation, metadata stripping, authorization."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts import photos
from apps.accounts.models import FamilyGroup, GroupMembership, User
from conftest import client_for

pytestmark = pytest.mark.django_db


def image_bytes(fmt="JPEG", size=(800, 600), color=(30, 120, 60), exif_gps=False) -> bytes:
    img = Image.new("RGB", size, color)
    img.paste((200, 30, 30), (0, 0, size[0] // 4, size[1]))  # red stripe on the left for crop checks
    buf = io.BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x010F] = "SyntheticCam"  # Make
        exif[0x8825] = {1: "N", 2: (24.0, 42.0, 0.0), 3: "E", 4: (46.0, 43.0, 0.0)}  # GPS IFD (synthetic coordinates)
        kwargs["exif"] = exif
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def up(client, url, data: bytes, name="photo.jpg", **extra):
    return client.post(url, {"file": SimpleUploadedFile(name, data, content_type="image/jpeg"), **extra}, format="multipart")


def test_at37_upload_crop_replace_remove(family, clients):
    son = family["son1"]
    c = clients["son1"]
    r = up(c, "/api/me/photo", image_bytes(), crop_x="0", crop_y="0", crop_size="0.5")
    assert r.status_code == 200, r.content
    version = r.json()["photo_version"]
    assert version
    son.refresh_from_db()
    full, thumb = photos.path_for(son, thumb=False), photos.path_for(son, thumb=True)
    with Image.open(full) as im:
        assert im.format == "WEBP" and im.size == (512, 512)
        assert im.convert("RGB").getpixel((10, 256))[0] > 150  # crop started at the red left edge
    with Image.open(thumb) as im:
        assert im.size == (96, 96)
    old_name = son.photo_name
    assert up(c, "/api/me/photo", image_bytes("PNG", color=(10, 10, 200)), "p.png").status_code == 200
    son.refresh_from_db()
    assert son.photo_name != old_name and not (photos.photo_dir() / f"{old_name}.webp").exists()  # replaced, old file gone
    assert c.delete("/api/me/photo").json()["photo_version"] is None
    son.refresh_from_db()
    assert son.photo_name == "" and not list(photos.photo_dir().glob("*.webp"))
    # initials fallback data is always present
    me = c.get("/api/me").json()
    assert me["initials"] == "SS" and me["avatar_color"] and me["photo_version"] is None


def test_metadata_and_location_are_stripped(family, clients):
    data = image_bytes(exif_gps=True)
    with Image.open(io.BytesIO(data)) as im:
        assert im.getexif().get(0x8825)  # the synthetic upload really carries GPS data
    assert up(clients["mom"], "/api/me/photo", data).status_code == 200
    mom = User.objects.get(username="mom")
    for thumb in (False, True):
        raw = photos.path_for(mom, thumb).read_bytes()
        with Image.open(io.BytesIO(raw)) as im:
            assert not im.getexif() and "exif" not in im.info and "xmp" not in im.info
        assert b"SyntheticCam" not in raw and b"Exif" not in raw


@pytest.mark.parametrize("payload,name", [
    (b"%PDF-1.4 not an image", "photo.jpg"),
    (b"GIF89a" + b"\x00" * 100, "photo.gif"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "photo.png"),
])
def test_invalid_files_rejected(family, clients, payload, name):
    r = up(clients["dad"], "/api/me/photo", payload, name)
    assert r.status_code == 400
    assert not User.objects.get(username="dad").photo_name


def test_gif_and_oversize_and_bomb_rejected(family, clients):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, "GIF")
    assert up(clients["dad"], "/api/me/photo", buf.getvalue(), "a.gif").status_code == 400  # real GIF: unsupported format
    big = b"\xff\xd8" + b"0" * (photos.MAX_BYTES + 10)
    assert up(clients["dad"], "/api/me/photo", big).status_code == 400
    bomb = io.BytesIO()
    Image.new("L", (9000, 9000)).save(bomb, "PNG", optimize=True)  # 81 MP compresses to a small file
    assert len(bomb.getvalue()) < photos.MAX_BYTES
    r = up(clients["dad"], "/api/me/photo", bomb.getvalue(), "bomb.png")
    assert r.status_code == 400
    assert "dimensions" in r.json()["error"] or "supported" in r.json()["error"]


def test_at38_photo_access_requires_authentication_and_visibility(family, clients):
    son = family["son1"]
    up(clients["son1"], "/api/me/photo", image_bytes())
    url = f"/api/users/{son.pk}/photo"
    r = clients["mom"].get(url)  # same family group
    assert r.status_code == 200 and r["Content-Type"] == "image/webp" and "private" in r["Cache-Control"]
    assert clients["mom"].get(url + "?size=full").status_code == 200
    assert APIClient().get(url).status_code in (401, 403)  # anonymous
    outsider = User.objects.create(username="cousin", display_name="Cousin Sample")
    grp = FamilyGroup.objects.create(name="Extended")
    GroupMembership.objects.create(group=grp, user=outsider)
    assert client_for(outsider).get(url).status_code == 404  # not a visible member: same as "no photo"
    assert clients["dad"].get(url).status_code == 200  # main administrator
    son.refresh_from_db()
    assert son.photo_name not in clients["mom"].get("/api/family/members").content.decode()  # file name never exposed


def test_admin_manages_member_photo(family, clients):
    son = family["son2"]
    assert up(clients["mom"], f"/api/family/members/{son.pk}/photo", image_bytes()).status_code == 403
    assert up(clients["dad"], f"/api/family/members/{son.pk}/photo", image_bytes()).status_code == 200
    son.refresh_from_db()
    assert son.photo_name
    members = {m["id"]: m for m in clients["dad"].get("/api/family/members").json()["members"]}
    assert members[str(son.pk)]["photo_version"]
    assert clients["dad"].delete(f"/api/family/members/{son.pk}/photo").status_code == 200
    from apps.core.models import AuditEvent

    assert AuditEvent.objects.filter(action="family.photo_update", subject_user=son).exists()
    assert AuditEvent.objects.filter(action="family.photo_remove", subject_user=son).exists()


def test_photo_does_not_affect_identity(family, clients):
    """Two accounts with identical photos remain separate; authorization ignores photos."""
    data = image_bytes()
    up(clients["son1"], "/api/me/photo", data)
    up(clients["son2"], "/api/me/photo", data)
    assert clients["son1"].get("/api/me").json()["id"] != clients["son2"].get("/api/me").json()["id"]
    assert clients["son2"].delete(f"/api/family/members/{family['son1'].pk}/photo").status_code == 403
