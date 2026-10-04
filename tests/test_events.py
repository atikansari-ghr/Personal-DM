"""Event notifications other than expiry: access, imports, processing, backup and integrity alerts."""
from unittest import mock

import pytest
from conftest import personal_root, run_jobs, upload
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import config
from apps.library.models import Folder
from apps.notify.models import Notification, OutboxMessage

pytestmark = pytest.mark.django_db


def _enable_email(user):
    config.set_value("smtp.enabled", True)
    config.set_value("smtp.host", "smtp.invalid")
    user.email = f"{user.username}@example.invalid"
    user.save()
    config.set_user(user, "me.channels", ["in_app", "email"])


def test_access_granted_notifies_grantee_once_with_minimal_external_text(family, clients):
    mom = family["mom"]
    _enable_email(mom)
    folder = Folder.objects.create(parent=personal_root(family["son1"]), name="Passport Z9988776", owner=family["son1"])
    r = clients["dad"].put(f"/api/folders/{folder.id}/permissions", {"user": str(mom.pk), "caps": ["view"]}, format="json")
    assert r.status_code == 200
    n = Notification.objects.get(user=mom, kind="access")
    assert "Passport Z9988776" in n.title and n.link == f"/folders/{folder.id}"
    email = OutboxMessage.objects.get(user=mom, kind="access", channel="email")
    assert "Z9988776" not in email.subject + email.body and "/folders/" in email.body
    # changing capabilities of an existing view grant does not notify again
    clients["dad"].put(f"/api/folders/{folder.id}/permissions", {"user": str(mom.pk), "caps": ["view", "download"]}, format="json")
    assert Notification.objects.filter(user=mom, kind="access").count() == 1


def test_group_grant_notifies_members_but_not_actor(family, clients):
    from apps.accounts.models import FamilyGroup

    group = FamilyGroup.objects.get(name="My family")
    shared = Folder.objects.get(name="Shared family")
    clients["dad"].put(f"/api/folders/{shared.id}/permissions", {"group": str(group.pk), "caps": ["view"]}, format="json")
    notified = set(Notification.objects.filter(kind="access").values_list("user__username", flat=True))
    assert notified == {"mom", "son1", "daughter", "son2", "son3"}


def test_event_alerts_preference_limits_external_channels_only(family, clients):
    mom = family["mom"]
    _enable_email(mom)
    config.set_user(mom, "me.event_alerts", False)
    folder = Folder.objects.create(parent=personal_root(family["son1"]), name="Trip", owner=family["son1"])
    clients["dad"].put(f"/api/folders/{folder.id}/permissions", {"user": str(mom.pk), "caps": ["view"]}, format="json")
    assert Notification.objects.filter(user=mom, kind="access").exists()
    assert not OutboxMessage.objects.filter(user=mom, kind="access").exclude(channel="in_app").exists()


def test_import_finished_notifies_importer(family, clients):
    entries = [{"path": "Sam Sample/a.pdf", "size": 10}]
    s = clients["dad"].post("/api/imports", {"source_type": "browser", "entries": entries}, format="json").json()
    clients["dad"].put(f"/api/imports/{s['id']}", {"mapping": {"Sam Sample": {"action": "user", "user": str(family["son1"].pk)}}}, format="json")
    clients["dad"].post(f"/api/imports/{s['id']}/start")
    f = SimpleUploadedFile("a.pdf", b"%PDF-1.4 synthetic")
    clients["dad"].post(f"/api/imports/{s['id']}/items", {"path": "Sam Sample/a.pdf", "file": f}, format="multipart")
    n = Notification.objects.get(user=family["dad"], kind="import")
    assert "1 imported" in n.title


def test_processing_failure_notifies_uploader(family, clients):
    from apps.library import sandbox

    with mock.patch("apps.library.processing._thumbnail_pdf", side_effect=sandbox.ToolError("pdftoppm timed out")):
        upload(clients["son1"], personal_root(family["son1"]), name="x.pdf")
        run_jobs()
    assert Notification.objects.filter(user=family["son1"], kind="processing").count() == 1


def test_backup_failure_and_integrity_problems_notify_admins_once_a_day(family, tmp_path):
    from apps.ops import backup, integrity
    from apps.notify import events

    config.set_value("backup.target", str(tmp_path / "missing"))
    for _ in range(2):
        with pytest.raises(backup.BackupError):
            backup.run_backup()
    assert Notification.objects.filter(kind="backup").count() == 1
    assert Notification.objects.get(kind="backup").user == family["dad"]
    events.integrity_problems(3)
    events.integrity_problems(3)
    assert Notification.objects.filter(kind="integrity", user=family["dad"]).count() == 1
    assert not Notification.objects.filter(kind__in=["backup", "integrity"]).exclude(user=family["dad"]).exists()
    assert integrity  # imported for clarity
