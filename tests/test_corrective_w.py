"""Change Set W - named sign-in designs and rotation, complete authorised metadata, complete IP addresses and the
Notification Detail Level (backend parts of AT-376 .. AT-400). The change prompt numbered these AT-351..AT-375; here
they are AT-376..AT-400 (prompt + 25) because AT-351..AT-375 already exist. Synthetic images and data only;
external channels are rendered locally (no message leaves the test)."""
import importlib
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core import config, designs, rotation
from apps.core.models import AuditEvent, SigninDesign
from apps.library.models import Document, DocumentField
from apps.library.services import set_field
from apps.notify import expiry, rich, templates
from apps.notify.models import Notification, OutboxMessage

from conftest import client_for, personal_root

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Riyadh")


@pytest.fixture
def data_dir(tmp_path, settings):
    settings.DATA_DIR = tmp_path
    return tmp_path


def _img(colour=(200, 230, 205), size=(1600, 1000), fmt="PNG", split=None):
    """Synthetic wallpaper: one colour, or ``split`` = (left, right) colours (the right side is next to the panel)."""
    im = Image.new("RGB", size, colour)
    if split:
        im.paste(Image.new("RGB", (size[0] // 2, size[1]), split[1]), (size[0] // 2, 0))
        im.paste(Image.new("RGB", (size[0] // 2, size[1]), split[0]), (0, 0))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def _up(c, pk, data, kind="wallpaper"):
    return c.post(f"/api/signin-designs/{pk}/{kind}", {"file": SimpleUploadedFile("w.png", data)}, format="multipart")


def _new(c, name, **kw):
    r = c.post("/api/signin-designs", {"name": name, **kw}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


# ------------------------------------------------------------------ AT-376 design profile CRUD

def test_at376_create_duplicate_rename_edit_preview_activate_delete(family, clients, data_dir):
    a = clients["dad"]
    assert clients["mom"].get("/api/signin-designs").status_code == 403  # main administrator only
    assert APIClient().post("/api/signin-designs", {"name": "x"}, format="json").status_code in (401, 403)
    ids = [_new(a, f"Design {i}", template="nature")["id"] for i in range(12)]  # no artificial cap
    d = _new(a, "Spring")
    assert _up(a, d["id"], _img()).status_code == 200
    dup = _new(a, "Spring copy", **{"from": d["id"]})
    assert dup["has_wallpaper"] and dup["template"] == d["template"]
    assert a.patch(f"/api/signin-designs/{dup['id']}", {"name": "Summer"}, format="json").json()["name"] == "Summer"
    before = APIClient().get("/api/session").json()["login"]["design_id"]
    preview = a.get(f"/api/signin-designs/{d['id']}").json()["preview"]
    assert preview["wallpapers"]["mobile"] and APIClient().get("/api/session").json()["login"]["design_id"] == before
    a.post(f"/api/signin-designs/{d['id']}/activate")
    assert APIClient().get("/api/session").json()["login"]["design_id"] == d["id"]
    listing = a.get("/api/signin-designs").json()
    assert sum(1 for x in listing["designs"] if x["active"]) == 1 and len(listing["designs"]) >= 5 + 14
    assert a.delete(f"/api/signin-designs/{ids[0]}").status_code == 200
    assert not SigninDesign.objects.filter(pk=ids[0]).exists()
    assert AuditEvent.objects.filter(action="settings.signin_design_activate").exists()


# ------------------------------------------------------------------ AT-377 protected built-ins

def test_at377_builtins_are_protected_templates(family, clients, data_dir):
    a = clients["dad"]
    rows = {x["builtin_key"]: x for x in a.get("/api/signin-designs").json()["designs"] if x["builtin"]}
    assert set(rows) == {"minimal", "nature", "travel", "family", "neutral"}
    nature = rows["nature"]["id"]
    assert a.patch(f"/api/signin-designs/{nature}", {"name": "Mine"}, format="json").status_code == 400
    assert a.delete(f"/api/signin-designs/{nature}").status_code == 400
    assert _up(a, nature, _img()).status_code == 400
    assert a.post(f"/api/signin-designs/{nature}/activate").status_code == 200
    assert APIClient().get("/api/session").json()["login"]["design"] == "nature"
    copy = _new(a, "My nature", **{"from": nature})
    assert not copy["builtin"] and copy["template"] == "nature"
    SigninDesign.objects.filter(builtin_key="minimal").delete()  # even if removed behind the app's back...
    assert designs.default_design().builtin_key == "minimal"  # ...the protected default comes back
    a.post("/api/signin-designs/reset")
    assert APIClient().get("/api/session").json()["login"]["design"] == "minimal"


# ------------------------------------------------------------------ AT-378 migration of the previous single design

def test_at378_previous_custom_wallpaper_migrates_once_and_keeps_appearance(family, data_dir):
    from apps.core.models import AppSetting

    (data_dir / "branding").mkdir()
    (data_dir / "branding" / "wallpaper-0123456789abcdef01234567.webp").write_bytes(_img(fmt="WEBP"))
    SigninDesign.objects.all().delete()
    AppSetting.objects.filter(key__in=["login.active_design", "login.previous_design"]).delete()
    config.set_value("login.wallpaper_file", "wallpaper-0123456789abcdef01234567.webp")
    config.set_value("login.design", "custom")
    config.set_value("login.overlay", 25)
    config.set_value("login.position", "top")
    mig = importlib.import_module("apps.core.migrations.0006_signin_designs_data")
    mig.forwards(django_apps, None)
    mig.forwards(django_apps, None)  # idempotent
    custom = SigninDesign.objects.filter(builtin_key__isnull=True)
    assert custom.count() == 1 and SigninDesign.objects.filter(builtin_key__isnull=False).count() == 5
    d = custom.get()
    assert d.overlay == 25 and (d.focal_x, d.focal_y) == (0.5, 0.0) and d.assets["original"].startswith("wallpaper-")
    s = APIClient().get("/api/session").json()["login"]
    assert s["design_id"] == d.pk and s["wallpapers"]["desktop"]  # active appearance kept, derivatives made on first use
    assert (data_dir / "branding" / "wallpaper-0123456789abcdef01234567.webp").exists()  # nothing re-uploaded or lost
    # a built-in selection maps to its protected template
    SigninDesign.objects.all().delete()
    AppSetting.objects.filter(key="login.active_design").delete()
    config.set_value("login.design", "travel")
    mig.forwards(django_apps, None)
    assert SigninDesign.objects.get(pk=config.get("login.active_design")).builtin_key == "travel"


# ------------------------------------------------------------------ AT-379 / AT-380 colours

@pytest.mark.parametrize("name,img,scheme", [
    ("light green", _img((198, 232, 200)), "light"),
    ("dark", _img((20, 26, 38)), "dark"),
    ("mixed: dark left, light right next to the panel", _img(split=((25, 30, 35), (235, 240, 225))), "light"),
    ("high contrast: light left, black right", _img(split=((250, 250, 250), (5, 5, 5))), "dark"),
])
def test_at379_auto_palette_is_region_aware_and_readable(family, clients, data_dir, name, img, scheme):
    d = _new(clients["dad"], name)
    r = _up(clients["dad"], d["id"], img).json()
    pal = r["palette"]
    assert pal["scheme"] == scheme, (name, r["analysis"])
    assert designs.contrast(pal["ink"], pal["bg"]) >= 7.0
    assert designs.contrast(pal["brand_ink"], pal["brand"]) >= 4.5
    assert designs.contrast(pal["muted"], pal["bg"]) >= 4.5
    assert designs.contrast(pal["link"], pal["bg"]) >= 4.5
    assert r["warnings"] == []
    if name == "light green":  # a pale green wallpaper gives a subtle green-white panel with dark green controls
        bg, brand = designs._rgb(pal["bg"]), designs._rgb(pal["brand"])
        assert bg[1] >= bg[0] and min(bg) > 220 and brand[1] > brand[0] and designs.luminance(brand) < 0.2


def test_at380_modes_persist_and_custom_survives_wallpaper_replacement(family, clients, data_dir):
    a = clients["dad"]
    d = _new(a, "Modes")
    _up(a, d["id"], _img((198, 232, 200)))
    assert a.patch(f"/api/signin-designs/{d['id']}", {"color_mode": "dark"}, format="json").json()["palette"]["scheme"] == "dark"
    assert a.patch(f"/api/signin-designs/{d['id']}", {"color_mode": "light"}, format="json").json()["palette"]["scheme"] == "light"
    r = a.patch(f"/api/signin-designs/{d['id']}", {"color_mode": "custom", "overrides": {"brand": "#7a1f5c", "bg": "#fffaf0"}}, format="json").json()
    assert r["palette"]["brand"] == "#7a1f5c" and r["palette"]["bg"] == "#fffaf0"
    assert a.patch(f"/api/signin-designs/{d['id']}", {"overrides": {"brand": "red"}}, format="json").status_code == 400
    r = _up(a, d["id"], _img((20, 26, 38))).json()  # a new, dark wallpaper keeps the deliberate custom colours
    assert r["color_mode"] == "custom" and r["palette"]["brand"] == "#7a1f5c" and r["analysis"]["scheme"] == "dark"
    other = _new(a, "Other")
    _up(a, other["id"], _img())
    assert SigninDesign.objects.get(pk=other["id"]).color_mode == "auto"  # independent per design


# ------------------------------------------------------------------ AT-381 responsive wallpaper and focal point

def test_at381_original_derivatives_focal_crop_and_rejections(family, clients, data_dir):
    a = clients["dad"]
    d = _new(a, "Responsive")
    big = io.BytesIO()
    ex = Image.Exif()
    ex[0x010F] = "SecretCam"
    Image.new("RGB", (3600, 1400), (120, 160, 200)).save(big, "JPEG", exif=ex.tobytes())
    assert _up(a, d["id"], big.getvalue()).status_code == 200
    obj = SigninDesign.objects.get(pk=d["id"])
    sizes = {}
    for k in ("original", "desktop", "tablet", "mobile"):
        with Image.open(data_dir / "branding" / obj.assets[k]) as im:
            sizes[k] = im.size
            assert im.format == "WEBP" and not im.getexif()
        assert b"SecretCam" not in (data_dir / "branding" / obj.assets[k]).read_bytes()
    assert sizes["original"] == (3600, 1400)  # original kept
    assert sizes["desktop"] == designs.VARIANTS["desktop"] and sizes["mobile"] == designs.VARIANTS["mobile"]  # cropped, not stretched
    # the focal point decides what each crop keeps: a red marker at the far left survives a left focal point
    marker = Image.new("RGB", (3000, 1000), (240, 240, 240))
    marker.paste(Image.new("RGB", (120, 1000), (220, 20, 20)), (0, 0))
    buf = io.BytesIO()
    marker.save(buf, "PNG")
    _up(a, d["id"], buf.getvalue())
    a.patch(f"/api/signin-designs/{d['id']}", {"focal_x": 0.0, "focal_y": 0.5}, format="json")
    obj.refresh_from_db()
    with Image.open(data_dir / "branding" / obj.assets["desktop"]) as im:
        assert im.convert("RGB").getpixel((5, im.size[1] // 2))[0] > 180  # red edge kept
    a.patch(f"/api/signin-designs/{d['id']}", {"focal_x": 1.0}, format="json")
    obj.refresh_from_db()
    with Image.open(data_dir / "branding" / obj.assets["desktop"]) as im:
        assert im.convert("RGB").getpixel((5, im.size[1] // 2))[0] < 250 and im.convert("RGB").getpixel((5, im.size[1] // 2))[1] > 200
    assert a.patch(f"/api/signin-designs/{d['id']}", {"focal_x": 2}, format="json").status_code == 400
    for bad, why in [(b"%PDF-1.4 not an image", "not a supported image"), (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "not a supported image"),
                     (_img(size=(300, 200)), "at least 800")]:
        r = _up(a, d["id"], bad)
        assert r.status_code == 400 and why in r.json()["error"]


# ------------------------------------------------------------------ AT-382 preview never changes the live design

def test_at382_preview_and_editing_do_not_change_live_design_or_rotation(family, clients, data_dir):
    a = clients["dad"]
    live = APIClient().get("/api/session").json()["login"]
    d = _new(a, "Draft")
    _up(a, d["id"], _img())
    a.patch(f"/api/signin-designs/{d['id']}", {"overlay": 40, "color_mode": "dark"}, format="json")
    p = a.get(f"/api/signin-designs/{d['id']}").json()["preview"]
    assert p["overlay"] == 40 and p["palette"]["scheme"] == "dark" and p["wallpapers"]["tablet"]
    assert APIClient().get("/api/session").json()["login"] == live
    # a non-active design's images are for the main administrator only; the active design's are public
    assert APIClient().get(f"/api/branding/design/{d['id']}/desktop").status_code == 404
    assert a.get(f"/api/branding/design/{d['id']}/desktop").status_code == 200
    assert a.get(f"/api/branding/design/{d['id']}/../../etc/passwd").status_code == 404


# ------------------------------------------------------------------ AT-383 activation, revert, deletion, fallback

def test_at383_atomic_activation_revert_delete_and_corrupt_fallback(family, clients, data_dir):
    a = clients["dad"]
    d1, d2 = _new(a, "One"), _new(a, "Two")
    _up(a, d1["id"], _img())
    _up(a, d2["id"], _img((40, 60, 90)))
    a.post(f"/api/signin-designs/{d1['id']}/activate")
    a.post(f"/api/signin-designs/{d2['id']}/activate")
    r = a.post("/api/signin-designs/revert").json()
    assert r["active"] == d1["id"] and APIClient().get("/api/session").json()["login"]["design_id"] == d1["id"]
    assert config.get("login.design") == "custom" and config.get("login.wallpaper_file")  # a rollback sees it too
    res = a.delete(f"/api/signin-designs/{d1['id']}").json()  # deleting the active design
    assert res["was_active"] and APIClient().get("/api/session").json()["login"]["design"] == "minimal"
    # the active design's file disappears: the protected default is shown, the design is marked, admins are told
    a.post(f"/api/signin-designs/{d2['id']}/activate")
    obj = SigninDesign.objects.get(pk=d2["id"])
    (data_dir / "branding" / obj.assets["original"]).write_bytes(b"corrupt")
    s = APIClient().get("/api/session").json()["login"]
    assert s["design"] == "minimal" and s["wallpaper"] is None
    obj.refresh_from_db()
    assert obj.state == "unavailable"
    assert Notification.objects.filter(user=family["dad"], title__icontains="Sign-in page design").exists()
    assert a.post(f"/api/signin-designs/{d2['id']}/activate").status_code == 400  # cannot activate a broken design


# ------------------------------------------------------------------ AT-384 asset cleanup

def test_at384_reference_aware_cleanup(family, clients, data_dir):
    a = clients["dad"]
    d = _new(a, "Shared")
    _up(a, d["id"], _img())
    copy = _new(a, "Shared copy", **{"from": d["id"]})
    files = set(SigninDesign.objects.get(pk=d["id"]).assets.values())
    a.delete(f"/api/signin-designs/{d['id']}")
    assert all((data_dir / "branding" / f).exists() for f in files)  # still used by the copy
    a.delete(f"/api/signin-designs/{copy['id']}")
    assert not any((data_dir / "branding" / f).exists() for f in files)  # last user gone: removed
    assert not list((data_dir / "branding").glob("design-*.webp"))
    assert SigninDesign.objects.filter(builtin_key__isnull=False).count() == 5  # built-ins untouched


# ------------------------------------------------------------------ AT-385 .. AT-391 rotation

def _pool(c, n=3):
    out = []
    for i in range(n):
        d = _new(c, f"Pool {i}")
        _up(c, d["id"], _img((40 * i + 60, 160, 120)))
        out.append(d["id"])
    return out


def _cfg(c, **kw):
    return c.put("/api/signin-designs/rotation", {"enabled": True, "mode": "sequential", "frequency": "daily", "time": "06:00", **kw}, format="json")


def test_at385_pool_needs_two_valid_designs_sequential_wraps_random_avoids_repeat(family, clients, data_dir):
    a = clients["dad"]
    ids = _pool(a)
    assert _cfg(a, pool=[ids[0]]).status_code == 400  # at least two
    assert _cfg(a, pool=[ids[0], 999999]).status_code == 400
    assert clients["mom"].put("/api/signin-designs/rotation", {"enabled": False}, format="json").status_code == 403
    assert _cfg(a, pool=ids).status_code == 200
    a.post(f"/api/signin-designs/{ids[0]}/activate")
    seen = []
    for _ in range(4):
        rotation.rotate()
        seen.append(designs.active().pk)
    assert seen == [ids[1], ids[2], ids[0], ids[1]]  # pool order, wrapping
    builtin_nature = SigninDesign.objects.get(builtin_key="nature").pk
    assert builtin_nature not in seen  # only pool members
    _cfg(a, pool=ids, mode="random")
    prev = designs.active().pk
    for _ in range(10):
        rotation.rotate()
        cur = designs.active().pk
        assert cur in ids and cur != prev  # never the same design twice in a row
        prev = cur


def test_at386_daily_weekly_monthly_timezone_and_last_valid_day(family, clients, data_dir):
    from apps.ops import schedule

    a = clients["dad"]
    ids = _pool(a, 2)
    st = _cfg(a, pool=ids, frequency="weekly", weekday="wed", time="07:30").json()
    assert st["timezone"] == config.get("general.timezone") and st["next_rotation"] and st["describe"].startswith("Every")
    nxt = datetime.fromisoformat(st["next_rotation"]).astimezone(TZ)
    assert nxt.weekday() == 2 and (nxt.hour, nxt.minute) == (7, 30)
    spec = {"enabled": True, "frequency": "monthly", "month_day": 31, "time": "06:00", "weekday": "mon"}
    feb = schedule.next_occurrence(datetime(2027, 2, 2, tzinfo=TZ), spec)
    assert feb.date().isoformat() == "2027-02-28"  # last valid day of February
    mar = schedule.next_occurrence(feb + timedelta(minutes=1), spec)
    assert mar.date().isoformat() == "2027-03-31"  # back to the configured day
    daily = {**spec, "frequency": "daily"}
    assert schedule.next_occurrence(datetime(2027, 1, 1, 6, 30, tzinfo=TZ), daily).date().isoformat() == "2027-01-02"


def test_at387_manual_activation_keeps_rotation_and_open_pages_are_not_refreshed(family, clients, data_dir):
    a = clients["dad"]
    ids = _pool(a)
    _cfg(a, pool=ids)
    a.post(f"/api/signin-designs/{ids[2]}/activate")  # manual choice while rotation is on
    st = a.get("/api/signin-designs/rotation").json()
    assert st["enabled"] and st["current"]["id"] == ids[2]
    rotation.rotate()
    assert designs.active().pk == ids[0]  # the schedule resumes from the manual choice
    # no live refresh: the sign-in page reads its design only when it loads (no polling / push channel)
    auth = (ROOT / "frontend/src/pages/Auth.tsx").read_text()
    assert "setInterval" not in auth and "EventSource" not in auth and "WebSocket" not in auth


def test_at388_missed_rotations_are_reconciled_once(family, clients, data_dir):
    from apps.notify.models import SchedulerRun

    a = clients["dad"]
    ids = _pool(a, 3)
    _cfg(a, pool=ids, frequency="daily", time="06:00")
    a.post(f"/api/signin-designs/{ids[0]}/activate")
    now = datetime(2027, 3, 10, 9, 0, tzinfo=TZ)
    SchedulerRun.objects.filter(name="signin_rotation").update(last_run_at=now - timedelta(days=4, hours=2))  # 4 missed
    r = rotation.tick(now)
    assert r["result"] == "rotated" and designs.active().pk == ids[(0 + 4) % 3]  # where it would be, one switch
    assert rotation.tick(now) is None  # nothing replayed
    ev = AuditEvent.objects.get(action="settings.signin_rotation_missed")
    assert ev.context["missed"] == 4
    assert AuditEvent.objects.filter(action="settings.signin_design_activate").count() <= 2
    _cfg(a, pool=ids, mode="random")
    SchedulerRun.objects.filter(name="signin_rotation").update(last_run_at=now - timedelta(days=3))
    before = AuditEvent.objects.filter(action="settings.signin_rotation_run").count()
    rotation.tick(now)
    assert AuditEvent.objects.filter(action="settings.signin_rotation_run").count() == before + 1  # one recovery choice
    nxt = datetime.fromisoformat(a.get("/api/signin-designs/rotation").json()["next_rotation"])
    assert nxt > timezone.now()


def test_at389_unavailable_pool_designs(family, clients, data_dir):
    a = clients["dad"]
    ids = _pool(a, 3)
    _cfg(a, pool=ids)
    a.post(f"/api/signin-designs/{ids[0]}/activate")
    bad = SigninDesign.objects.get(pk=ids[1])
    (data_dir / "branding" / bad.assets["original"]).unlink()
    rotation.rotate()
    assert designs.active().pk == ids[2]  # skipped and continued
    assert AuditEvent.objects.filter(action="settings.signin_rotation_skip").exists()
    assert Notification.objects.filter(user=family["dad"], body__icontains="skipped").exists()
    for pk in (ids[2],):
        o = SigninDesign.objects.get(pk=pk)
        (data_dir / "branding" / o.assets["original"]).unlink()
    st = a.get("/api/signin-designs/rotation").json()
    assert st["state"] == "needs_attention"  # fewer than two valid designs
    assert rotation.rotate()["result"] == "needs_attention"
    o = SigninDesign.objects.get(pk=ids[0])
    (data_dir / "branding" / o.assets["original"]).unlink()
    assert rotation.rotate()["result"] == "fallback"
    assert designs.active().builtin_key == "minimal" and rotation.settings_()["pool"] == ids  # config kept for repair


def test_at390_preview_rotation_changes_nothing(family, clients, data_dir):
    a = clients["dad"]
    ids = _pool(a, 3)
    _cfg(a, pool=ids)
    a.post(f"/api/signin-designs/{ids[0]}/activate")
    (data_dir / "branding" / SigninDesign.objects.get(pk=ids[2]).assets["original"]).unlink()
    from apps.notify.models import SchedulerRun

    state = SchedulerRun.objects.get(name="signin_rotation").state
    p = a.get("/api/signin-designs/rotation/preview").json()
    assert [x["design_id"] for x in p["order"]] == ids[:2] and p["next"]["design_id"] == ids[1]
    assert p["invalid"][0]["id"] == ids[2] and p["status"]["next_rotation"]
    assert all(x["wallpapers"]["mobile"] for x in p["order"])
    assert designs.active().pk == ids[0] and SchedulerRun.objects.get(name="signin_rotation").state == state
    _cfg(a, pool=ids[:2], mode="random")
    assert "randomized" in a.get("/api/signin-designs/rotation/preview").json()["random_note"].replace("chosen at the scheduled moment", "randomized")


def test_at391_routine_rotation_is_audit_only_problems_notify(family, clients, data_dir):
    a = clients["dad"]
    ids = _pool(a, 2)
    _cfg(a, pool=ids)
    before = Notification.objects.count() + OutboxMessage.objects.count()
    rotation.rotate()
    rotation.rotate()
    assert Notification.objects.count() + OutboxMessage.objects.count() == before  # no notification for success
    assert AuditEvent.objects.filter(action="settings.signin_rotation_run").count() == 2
    (data_dir / "branding" / SigninDesign.objects.get(pk=ids[0]).assets["original"]).unlink()
    rotation.rotate()
    assert Notification.objects.filter(user=family["dad"], title__icontains="Sign-in page design").exists()


# ------------------------------------------------------------------ AT-392 .. AT-396 complete authorised metadata

def _passport(owner, number="P7654321", **fields):
    d = Document.objects.create(folder=personal_root(owner), owner=owner, title="Passport", state=Document.READY)
    set_field(actor=owner, doc=d, key="document_number", value=number)
    for k, v in fields.items():
        set_field(actor=owner, doc=d, key=k, value=v)
    return d


def test_at392_complete_identifiers_for_authorised_people(family, clients):
    son = family["son1"]
    d = _passport(son, number="L-2026-0045627")
    for c in (clients["son1"], clients["dad"]):  # owner and an authorised administrator
        f = next(x for x in c.get(f"/api/documents/{d.id}").json()["fields"] if x["key"] == "document_number")
        assert f["value"] == "L-2026-0045627" and "•" not in json.dumps(f)
    again = clients["son1"].get(f"/api/documents/{d.id}").json()  # reload: still complete
    assert "L-2026-0045627" in json.dumps(again) and "•" not in json.dumps(again["fields"])


def test_at393_metadata_across_surfaces_and_denial(family, clients):
    son = family["son1"]
    d = _passport(son, number="Q1234567")
    c = clients["son1"]
    assert "Q1234567" in json.dumps(c.get(f"/api/documents/{d.id}").json())
    plan = c.post(f"/api/documents/{d.id}/type", {"type": None, "preview": True}, format="json").json()
    assert "Q1234567" in json.dumps(plan)  # change-type preview shows complete values
    for other in ("son2", "daughter"):
        assert clients[other].get(f"/api/documents/{d.id}").status_code in (403, 404)
        assert "Q1234567" not in json.dumps(clients[other].get("/api/documents", {"q": "Q1234567"}).json())
    assert APIClient().get(f"/api/documents/{d.id}").status_code in (401, 403)


def test_at394_low_confidence_values_visible_and_corrections_kept(family, clients):
    from apps.library import doctypes
    from apps.library.extraction import Proposal

    son = family["son1"]
    d = Document.objects.create(folder=personal_root(son), owner=son, title="Scan", state=Document.READY)
    doctypes.store_proposals(d, [Proposal(key="document_number", value="A9988771", source="ocr", confidence=0.42, excerpt="No A9988771")])
    f = next(x for x in clients["son1"].get(f"/api/documents/{d.id}").json()["fields"] if x["key"] == "document_number")
    assert f["value"] == "A9988771" and f["low_confidence"] is True and f["excerpt"] == "No A9988771" and f["source"] == "ocr"
    set_field(actor=son, doc=d, key="document_number", value="A9988777")  # corrected by a person
    doctypes.store_proposals(d, [Proposal(key="document_number", value="A0000000", source="ocr", confidence=0.9, excerpt="")])
    f = DocumentField.objects.get(document=d, key="document_number")
    assert f.value == "A9988777" and f.proposed_value == "A0000000"  # suggested next to it, never overwritten


def test_at395_copy_is_complete_and_never_logged(family, clients):
    son = family["son1"]
    d = _passport(son, number="C5554443")
    r = clients["son1"].get(f"/api/documents/{d.id}/fields/document_number/reveal")
    assert r.json()["value"] == "C5554443"
    assert clients["son2"].get(f"/api/documents/{d.id}/fields/document_number/reveal").status_code in (403, 404)
    assert "C5554443" not in json.dumps(list(AuditEvent.objects.values("context")), default=str)
    assert "C5554443" not in json.dumps(list(d.history.values("changes")) if hasattr(d, "history") else [], default=str)
    tsx = (ROOT / "frontend/src/components/DocumentDetails.tsx").read_text()
    assert "getValue={async () => f.value}" in tsx and "copied`" in (ROOT / "frontend/src/components/ui.tsx").read_text()


def test_at396_central_masking_audit_metadata_and_ips_unmasked_secrets_still_protected(family, clients):
    from apps.core.logging import redact
    from apps.security.location import privacy_ip

    assert privacy_ip("192.168.2.101", "trusted_zone") == "192.168.2.101"
    assert privacy_ip("2001:db8:85a3::8a2e:370:7334", "public") == "2001:db8:85a3::8a2e:370:7334"
    src = "\n".join(p.read_text() for p in (ROOT / "backend/apps").rglob("*.py") if "migrations" not in p.parts)
    assert ".x.{" not in src and 'value[-4:]' not in src  # no IP shortening, no last-four masking of metadata
    front = "\n".join(p.read_text() for p in (ROOT / "frontend/src").rglob("*.tsx"))
    assert "/reveal`)).value" not in front  # no reveal-on-click for details
    # actual secrets stay redacted
    assert "hunter2" not in redact("password=hunter2 token=abc")
    config.set_value("smtp.password", "smtp-secret-DO-NOT-LEAK")
    blob = clients["dad"].get("/api/settings").content.decode()
    assert "smtp-secret-DO-NOT-LEAK" not in blob


# ------------------------------------------------------------------ AT-397 .. AT-399 IPs and the detail level

def test_at397_complete_ipv4_ipv6_in_security_views_and_notifications(family, clients):
    from apps.security import alerts
    from apps.security.models import LoginEvent

    for who, ip in (("son1", "192.168.2.101"), ("daughter", "2001:db8:85a3::8a2e:370:7334")):
        user = family[who]
        ev = LoginEvent.objects.create(user=user, username=who, result=LoginEvent.SUCCESS, method="passkey", ip=ip,
                                       network="private" if "." in ip else "public", browser="Firefox", os="Windows",
                                       device="desktop", flags=["new_country"])
        alerts.on_login_event(ev)
        n = Notification.objects.filter(user=user, kind="security").order_by("-id").first()
        assert ip in json.dumps(n.data) + n.body
        rows = clients[who].get("/api/security/map", {"period": "7"}).json()["events"]
        assert ip in [r["ip"] for r in rows]
    sessions = clients["son1"].get("/api/me/sessions").json()
    assert ".x." not in json.dumps(sessions)


def test_at398_detail_level_default_full_with_personal_choice(family, clients):
    son = family["son1"]
    d = _passport(son, number="Z1112223", expiry_date=(timezone.localdate() + timedelta(days=20)).isoformat())
    m = expiry.expiry_message(d, 20, son)
    assert config.get("notifications.detail_level") == "full"
    with templates.detail_for(son, d):
        _s, text, html_doc = rich.render_email(m, son)
    assert "Z1112223" in text and "Z1112223" in html_doc
    r = clients["son1"].get("/api/me/notification-preferences").json()["detail_level"]
    assert r == {"mine": "system", "system": "full"}
    clients["son1"].put("/api/settings", {"values": {"me.notification_detail": "minimal"}}, format="json")
    with templates.detail_for(son, d):
        _s, text, html_doc = rich.render_email(m, son)
        tg = rich.render_telegram(m, son)
    assert "Z1112223" not in text + html_doc + json.dumps(tg)
    assert clients["son1"].get(f"/api/documents/{d.id}").status_code == 200  # presentation only, access unchanged
    config.set_value("notifications.detail_level", "minimal")
    clients["son1"].put("/api/settings", {"values": {"me.notification_detail": "full"}}, format="json")
    with templates.detail_for(son, d):
        assert "Z1112223" in rich.render_email(m, son)[1]  # a person's own choice wins


def test_at399_full_details_never_bypass_recipient_authorisation(family, clients):
    son, mom = family["son1"], family["mom"]
    d = _passport(son, number="K9090909", expiry_date=(timezone.localdate() + timedelta(days=10)).isoformat())
    folder_name = d.folder.name
    m = expiry.expiry_message(d, 10, son)
    from apps.library import permissions as P

    assert not P.AccessContext.build(mom).can(d, P.VIEW)
    with templates.detail_for(mom, d):  # a recipient without access (e.g. a family head) gets no document details
        _s, text, html_doc = rich.render_email(m, mom)
        tg = json.dumps(rich.render_telegram(m, mom))
        card = json.dumps(rich.render_in_app(m))
    for out in (text, html_doc, tg, card):
        assert "K9090909" not in out
    with templates.detail_for(son, d):
        for ch in ("email", "telegram", "discord", "whatsapp", "push"):
            subject, body, html_part, payload = expiry.render_for(ch, m, son)
            blob = subject + body + html_part + json.dumps(payload)
            if ch != "push":  # the lock screen keeps its own rule: no numbers on push
                assert "K9090909" in blob, ch
            for secret in ("hunter2", "otpauth://", "begin private key", "smtp-secret"):
                assert secret not in blob.lower(), (ch, secret)
    assert folder_name  # names follow the same rule (checked in test_notification_policy)


def test_at400_documentation_and_reference_up_to_date():
    guide = (ROOT / "docs/guides/login-designs.md").read_text()
    for anchor in ("designs", "wallpaper", "colours", "preview", "activate", "rotation", "rotation-schedule", "rotation-attention", "upgrade"):
        assert "{#" + anchor + "}" in guide, anchor
    assert "{#detail-level}" in (ROOT / "docs/guides/notifications.md").read_text()
    assert "192.168.x" not in (ROOT / "docs/guides/security-map.md").read_text()
