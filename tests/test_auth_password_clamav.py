"""Change Set P — passkey on the sign-in screen, administrator password reset, security notification templates and
ClamAV daemon/socket repair. AT-196..AT-210 (the change prompt numbers them AT-176..AT-190; those numbers were already
used by the rich-notification change set, so the mapping is AT-(n+20)). Synthetic accounts and documentation-range
addresses only; the EICAR string is the harmless standard antivirus test pattern."""
from __future__ import annotations

import os
import pwd
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetToken, User, WebAuthnCredential
from apps.core import config
from apps.core.models import AuditEvent
from apps.notify.models import Notification, NotificationTemplate, OutboxMessage
from apps.security.models import HealthState, LoginEvent
from conftest import PASSWORD, client_for
from fake_clamd import FakeClamd
from soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db

ORIGIN, RP = "https://docs.example.com", "docs.example.com"


@pytest.fixture(autouse=True)
def _origin(settings):
    settings.PUBLIC_ORIGIN = ORIGIN
    settings.CSRF_TRUSTED_ORIGINS = [ORIGIN]


def register(client, auth, name="Personal iPhone"):
    opts = client.post("/api/me/passkeys", {"step": "options"}, format="json").json()
    return client.post("/api/me/passkeys", {"credential": auth.register(opts), "name": name}, format="json")


def passwordless(client, auth):
    opts = client.post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json")
    assert opts.status_code == 200, opts.content
    cred = auth.assert_(opts.json())
    return client.post("/api/auth/passkey/verify", {"purpose": "passwordless", "credential": cred}, format="json"), cred


# ------------------------------------------------------------------ passkeys on the initial sign-in screen

def test_at196_passkey_offered_before_password(family):
    s = APIClient().get("/api/session").json()
    assert s["passwordless_enabled"] is True and s["passkey_mode"] == "passwordless"  # default policy
    config.set_value("auth.allow_passkeys", False)
    s = APIClient().get("/api/session").json()
    assert s["passwordless_enabled"] is False and s["passkey_mode"] == "off"


def test_at197_passwordless_sign_in_without_username_or_password(family, clients):
    auth = SoftAuthenticator(ORIGIN, RP)  # discoverable credential with user verification (platform authenticator)
    r = register(clients["mom"], auth)
    assert r.status_code == 201 and r.json()["passwordless_turned_on"] is True  # on by default after enrolment
    c = APIClient()
    r, cred = passwordless(c, auth)  # no username, no password
    assert r.status_code == 200 and c.get("/api/me").json()["username"] == "mom"
    ev = LoginEvent.objects.filter(result="success").latest("at")
    assert ev.method == "passkey" and ev.user == family["mom"]
    # replay of the same signed assertion is refused (single-use challenge)
    assert APIClient().post("/api/auth/passkey/verify", {"purpose": "passwordless", "credential": cred}, format="json").status_code == 400
    # the person can opt out; then the passkey only works after the password
    assert clients["mom"].post("/api/me/passwordless", {"enabled": False}, format="json").status_code == 200
    assert passwordless(APIClient(), auth)[0].status_code == 403


def test_at198_policy_modes_and_main_admin_recovery(family, clients):
    dad_key, mom_key = SoftAuthenticator(ORIGIN, RP), SoftAuthenticator(ORIGIN, RP)
    register(clients["dad"], dad_key)
    register(clients["mom"], mom_key)
    config.set_value("auth.passkey_mode", "mfa")  # Password + Passkey as MFA
    assert APIClient().post("/api/auth/passkey/options", {"purpose": "passwordless"}, format="json").status_code == 403
    c = APIClient()
    assert c.post("/api/auth/login", {"username": "mom", "password": PASSWORD}, format="json").json()["status"] == "second_factor_required"
    opts = c.post("/api/auth/passkey/options", {"purpose": "2fa"}, format="json").json()
    assert c.post("/api/auth/passkey/verify", {"purpose": "2fa", "credential": mom_key.assert_(opts)}, format="json").status_code == 200
    assert LoginEvent.objects.filter(result="success").latest("at").method == "password+passkey"
    # Main administrator: password + recovery code path keeps working in both modes
    codes = User.objects.get(username="dad").recovery_codes.filter(used_at__isnull=True)
    assert codes.exists()
    from django.core.management import call_command
    import io

    out = io.StringIO()
    call_command("recover_admin", "dad", "--generate", stdout=out)  # server console recovery is unchanged
    assert "Temporary password" in out.getvalue()
    config.set_value("auth.passkey_mode", "passwordless")
    assert passwordless(APIClient(), mom_key)[0].status_code == 200


def test_at199_passkey_management_is_audited(family, clients):
    c = clients["son1"]
    a, b = SoftAuthenticator(ORIGIN, RP), SoftAuthenticator(ORIGIN, RP)
    assert register(c, a, "Office Laptop").status_code == 201
    assert register(c, b, "Security Key").status_code == 201
    rows = list(WebAuthnCredential.objects.filter(user=family["son1"]).order_by("created_at"))
    assert [r.name for r in rows] == ["Office Laptop", "Security Key"]
    assert c.patch(f"/api/me/passkeys/{rows[0].pk}", {"name": "Home PC"}, format="json").status_code == 200
    assert c.delete(f"/api/me/passkeys/{rows[1].pk}").status_code == 204
    actions = set(AuditEvent.objects.filter(actor=family["son1"]).values_list("action", flat=True))
    assert {"account.passkey_register", "account.passkey_rename", "account.passkey_revoke"} <= actions
    events = set(Notification.objects.filter(user=family["son1"]).values_list("event", flat=True))
    assert {"security.passkey_added", "security.passkey_removed"} <= events
    r, _ = passwordless(APIClient(), a)
    assert r.status_code == 200
    ctx = str(list(AuditEvent.objects.values_list("context", flat=True)))
    assert rows[0].credential_id not in ctx  # raw credential IDs are not logged


# ------------------------------------------------------------------ administrator password reset

def _admin(family):
    mom = family["mom"]
    mom.is_admin = True  # Administrator role (not main administrator)
    mom.save()
    return client_for(mom)


def test_at200_admin_temporary_password_shown_once_and_forced_change(family, clients):
    admin = _admin(family)
    son = family["son1"]
    r = admin.post(f"/api/family/members/{son.pk}/reset-password", {"method": "temporary"}, format="json")
    assert r.status_code == 200, r.content
    temp = r.json()["temporary_password"]
    assert len(temp) >= 16 and any(ch.isdigit() for ch in temp) and "no-store" in r["Cache-Control"]
    listing = admin.get("/api/family/members").content.decode()
    assert temp not in listing  # never retrievable later
    c = APIClient()
    assert c.post("/api/auth/login", {"username": "son1", "password": temp}, format="json").json()["must_change_password"] is True
    assert c.get("/api/dashboard").status_code == 403  # must set a new password first
    assert c.post("/api/auth/password/change", {"current_password": temp, "new_password": "Own-Sample-Pass-42"}, format="json").status_code == 200
    son.refresh_from_db()
    assert not son.must_change_password
    events = list(Notification.objects.filter(user=son).values_list("event", flat=True))
    assert "security.temporary_password" in events and "security.password_changed" in events


def test_at201_temporary_password_never_stored_or_sent(family, clients):
    admin = _admin(family)
    son = family["son1"]
    son.email = "son1@example.invalid"
    son.save()
    old_session = client_for(son)
    tok = PasswordResetToken.objects.create(user=son, token_hash="x" * 64, expires_at=timezone.now() + timedelta(minutes=30))
    sent = []
    with mock.patch("apps.notify.mailer.send_mail_now", side_effect=lambda *a, **k: sent.append((a, k))):
        temp = admin.post(f"/api/family/members/{son.pk}/reset-password", {"method": "temporary"}, format="json").json()["temporary_password"]
    son.refresh_from_db()
    assert son.password != temp and "$" in son.password and son.check_password(temp)  # only the salted hash is stored
    blob = (str(list(AuditEvent.objects.values())) + str(list(Notification.objects.values())) + str(list(OutboxMessage.objects.values()))
            + str(list(LoginEvent.objects.values())) + str(sent))
    assert temp not in blob  # not in the database, audit, notifications, outbox or any email
    tok.refresh_from_db()
    assert tok.used_at is not None  # earlier reset links are invalidated
    assert old_session.get("/api/dashboard").status_code in (401, 403)  # sessions revoked by default
    ev = AuditEvent.objects.filter(action="family.password_reset_by_admin").latest("at")
    assert ev.actor == family["mom"] and ev.context.get("method") == "temporary_password" and ev.context.get("sessions_revoked") is True


def test_at202_reset_email_branded_single_use_and_expiring(family, clients):
    config.set_value("smtp.enabled", True)
    admin = _admin(family)
    son = family["son1"]
    son.email = "son1@example.invalid"
    son.save()
    mails = []
    capture = lambda to, subject, body, html="": mails.append({"to": to, "subject": subject, "body": body, "html": html})  # noqa: E731
    with mock.patch("apps.notify.mailer.send_mail_now", side_effect=capture):
        r = admin.post(f"/api/family/members/{son.pk}/reset-password", {"method": "email"}, format="json")
        assert r.status_code == 200 and r.json()["email"] == "s•••@example.invalid"
        admin.post(f"/api/family/members/{son.pk}/reset-password", {"method": "email"}, format="json")  # newer request
    reset_mails = [m for m in mails if "token=" in m["body"]]
    assert len(reset_mails) == 2
    first = reset_mails[0]["body"].split("token=")[1].split()[0]
    second = reset_mails[1]["body"].split("token=")[1].split()[0]
    html = reset_mails[1]["html"]
    assert "Reset password" in html and "<script" not in html and "If you did not ask for a password reset" in html
    assert f"{ORIGIN}/reset-password?token={second}" in html
    row = PasswordResetToken.objects.filter(user=son).latest("created_at")
    assert timedelta(minutes=29) < row.expires_at - row.created_at <= timedelta(minutes=30)  # default 30 minutes
    c = APIClient()
    assert c.post("/api/auth/password/reset", {"token": first, "password": "Fresh-Sample-71"}, format="json").status_code == 400  # replaced
    assert c.post("/api/auth/password/reset", {"token": second, "password": "Fresh-Sample-71"}, format="json").status_code == 200
    assert c.post("/api/auth/password/reset", {"token": second, "password": "Again-Sample-72"}, format="json").status_code == 400  # single use
    assert "security.password_changed" in Notification.objects.filter(user=son).values_list("event", flat=True)
    stored = str(list(Notification.objects.values())) + str(list(OutboxMessage.objects.values())) + str(list(AuditEvent.objects.values()))
    assert second not in stored and first not in stored
    # internet-facing installations refuse reset links without https
    from django.conf import settings as dj

    config.set_value("security.deployment", "internet")
    with mock.patch.object(dj, "PUBLIC_ORIGIN", "http://docs.example.com"):
        r = admin.post(f"/api/family/members/{son.pk}/reset-password", {"method": "email"}, format="json")
    assert r.status_code == 400 and "https" in r.json()["error"]


def test_at203_main_administrator_protection(family, clients):
    admin = _admin(family)
    dad = family["dad"]
    r = admin.post(f"/api/family/members/{dad.pk}/reset-password", {"method": "temporary"}, format="json")
    assert r.status_code == 403 and "main administrator" in r.json()["error"]
    assert admin.post(f"/api/family/members/{dad.pk}/reset-password", {"method": "email"}, format="json").status_code == 403
    assert admin.post(f"/api/family/members/{family['mom'].pk}/reset-password", {}, format="json").status_code == 400  # own account
    assert clients["son1"].post(f"/api/family/members/{family['son2'].pk}/reset-password", {}, format="json").status_code == 403
    # the main administrator can reset an Administrator, after a fresh confirmation
    stale = client_for(dad)
    s = stale.session
    s["reauth_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    s.save()
    assert stale.post(f"/api/family/members/{family['mom'].pk}/reset-password", {}, format="json").json()["code"] == "reauth_required"
    assert clients["dad"].post(f"/api/family/members/{family['mom'].pk}/reset-password", {}, format="json").status_code == 200


# ------------------------------------------------------------------ security notification templates

SECURITY_EVENTS = ["security.password_reset_requested", "security.password_admin_reset", "security.temporary_password",
                   "security.password_changed", "security.passkey_added", "security.passkey_removed", "account.login",
                   "security.new_country", "security.account_locked", "security.totp_enabled", "security.totp_disabled",
                   "security.authentik", "security.google"]


def test_at204_security_templates_render_with_protected_content(family, clients):
    from apps.notify import rich
    from apps.notify.event_defs import EVENTS

    dad = family["dad"]
    for ev in SECURITY_EVENTS:
        assert ev in EVENTS and EVENTS[ev].mandatory, ev
        r = clients["dad"].post(f"/api/notifications/templates/{ev}/preview", {}, format="json")
        assert r.status_code == 200, (ev, r.content)
        p = r.json()
        must = EVENTS[ev].mandatory[0]
        import html as _html

        assert must in p["email"]["text"] and _html.escape(must, quote=True) in p["email"]["html"], ev
        assert _html.escape(must, quote=True) in p["telegram"]["text"] and must in p["in_app"]["mandatory"], ev
        assert p["push"]["title"] and "TEST" in p["push"]["title"]
    # customisation: branding, title, introduction, icon, button label, footer — but mandatory text stays
    ev = "security.temporary_password"
    r = clients["dad"].put(f"/api/notifications/templates/{ev}", {
        "title": "Sample Family Vault: password reset", "summary": "Hello {recipient_name}, an administrator reset your password.",
        "icon": "shield", "brand": "Sample Family Vault", "footer": "Questions? Ask <b>the family admin</b> in person.",
        "action_labels": {"review_activity": "Check my account"}}, format="json")
    assert r.status_code == 200, r.content
    msg = rich.sample(ev, "Sample Person")
    subject, text, html = rich.render_email(msg, dad)
    assert "Sample Family Vault" in html and "Check my account" in html and "Questions? Ask &lt;b&gt;" in html
    assert EVENTS[ev].mandatory[0] in text and "&lt;b&gt;" in html and "<b>the family admin</b>" not in html
    tg = rich.render_telegram(msg, dad)
    assert "Questions? Ask &lt;b&gt;" in tg["text"] and EVENTS[ev].mandatory[0] in tg["text"]
    # cannot weaken: critical security events never below Warning, unknown placeholders and code are refused
    bad = clients["dad"].put(f"/api/notifications/templates/{ev}", {"severity": "info"}, format="json")
    assert bad.status_code == 400
    assert clients["dad"].put(f"/api/notifications/templates/{ev}", {"footer": "{password}"}, format="json").status_code == 400
    assert NotificationTemplate.objects.filter(event=ev).count() == 1
    # a secret (token) link can never be dispatched through the stored channels
    with pytest.raises(ValueError):
        rich.Message(event="security.password_reset_requested", title="x", secret_link="https://evil.example/reset-password?token=a")
    from apps.notify.expiry import dispatch

    m = rich.Message(event="security.password_reset_requested", title="x", secret_link=f"{ORIGIN}/reset-password?token=abc")
    with pytest.raises(ValueError):
        dispatch(dad, m, kind="security", key="k")


def test_at204_account_locked_and_link_events_are_sent(family, clients):
    config.set_value("auth.login_rate_limit", 3)
    for _ in range(5):
        APIClient().post("/api/auth/login", {"username": "son2", "password": "Wrong-Sample-0"}, format="json")
    n = Notification.objects.filter(user=family["son2"], event="security.account_locked")
    assert n.count() == 1 and "Wrong-Sample-0" not in str(list(Notification.objects.values()))
    from apps.notify.events import google_link_changed

    google_link_changed(family["son2"], linked=True)
    assert Notification.objects.filter(user=family["son2"], event="security.google").exists()


# ------------------------------------------------------------------ ClamAV daemon / socket (simulated Debian 13 host)

class FakeHost:
    """Simulates the systemctl/dpkg/clamconf/freshclam/runuser commands of a Debian 13 host. "systemctl start" of the
    ClamAV units starts a FakeClamd on the socket path; "stop" removes it (RemoveOnStop=True)."""

    def __init__(self, tmp: Path, *, daemon=True, conf_socket="/var/run/clamav/clamd.ctl", signatures=True, condition="yes",
                 result="success"):
        self.tmp = tmp
        self.run_dir = tmp / "run" / "clamav"
        self.run_dir.mkdir(parents=True)
        self.sock = str(self.run_dir / "clamd.ctl")
        self.db = tmp / "lib"
        self.db.mkdir()
        if signatures:
            (self.db / "main.cvd").write_text("x")
            (self.db / "daily.cld").write_text("x")
        self.conf = tmp / "clamd.conf"
        self.conf.write_text(f"#Automatically Generated by clamav-daemon postinst\nLocalSocket {conf_socket}\nFixStaleSocket true\n"
                             "LocalSocketGroup clamav\nLocalSocketMode 666\nTCPSocket 3310\nUser clamav\n")
        self.server = FakeClamd(self.sock) if daemon else None
        self.condition, self.result = condition, result
        self.calls: list[list[str]] = []

    def active(self):
        return self.server is not None

    def __call__(self, cmd, timeout=60, env=None):
        self.calls.append(list(cmd))
        out, code = "", 0
        if cmd[:2] == ["systemctl", "show"]:
            unit = cmd[2]
            act = "active" if self.active() else "inactive"
            if unit == "clamav-daemon.socket":
                out = f"LoadState=loaded\nActiveState={act}\nUnitFileState=enabled\nConditionResult={self.condition}\nListen={self.sock} (Stream)\n"
            elif unit == "clamav-daemon.service":
                out = (f"LoadState=loaded\nActiveState={act}\nSubState={'running' if self.active() else 'dead'}\nUnitFileState=enabled\n"
                       f"Result={self.result}\nConditionResult={self.condition}\n")
            else:
                out = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
        elif cmd[:2] == ["systemctl", "start"] and "clamav-daemon.service" in cmd:
            if self.server is None and (self.db / "main.cvd").exists():
                self.server = FakeClamd(self.sock)
        elif cmd[:2] == ["systemctl", "stop"] and "clamav-daemon.service" in cmd:
            if self.server is not None:
                self.server.stop()
                self.server = None
        elif cmd[0] == "dpkg-query":
            out = "install ok installed"
        elif cmd[0] == "clamconf":
            out = "Checking configuration files in /etc/clamav\nConfig file: clamd.conf\n"
        elif cmd[0] == "freshclam":
            (self.db / "main.cvd").write_text("x")
            (self.db / "daily.cld").write_text("x")
            out = "Database updated"
        elif cmd[0] == "runuser":
            p = subprocess.run(cmd[cmd.index("--") + 1:], capture_output=True, text=True, timeout=timeout)
            return p
        elif cmd[0] == "journalctl":
            out = ""
        return subprocess.CompletedProcess(cmd, code, out, "")

    def close(self):
        if self.server is not None:
            self.server.stop()


def _checker(host: FakeHost, cls=None, **kw):
    from apps.ops.clamav_check import Clamav

    return (cls or Clamav)(run=host, conf=host.conf, db_dir=host.db, run_dir=host.run_dir, dropin=host.tmp / "dropin" / "50-personaldocs.conf",
                  tmpfiles=host.tmp / "tmpfiles" / "personaldocs-clamav.conf", service_user=pwd.getpwuid(os.geteuid()).pw_name,
                  sleep=lambda s: None, **kw)


@pytest.fixture
def short_tmp():
    import shutil
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="pdav-", dir="/tmp"))  # Unix socket paths must stay short
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_at205_diagnosis_finds_the_socket_cause_not_metadata(family, short_tmp):
    # the observed state: signatures and engine metadata present, daemon "active", socket file gone, and clamd.conf
    # names /var/run/... while the systemd socket unit listens on /run/...
    host = FakeHost(short_tmp, daemon=True)
    host.server.stop()
    host.server = object()  # systemd still reports the units active
    try:
        os.unlink(host.sock)
    except FileNotFoundError:
        pass
    d = _checker(host, as_root=True).diagnose()
    by = {c["key"]: c for c in d["checks"]}
    assert d["status"] == "unavailable"
    assert by["signatures"]["state"] == "ok" and by["socket_file"]["state"] == "fail" and "FileNotFoundError" in by["socket_file"]["detail"]
    assert by["socket_path"]["state"] == "warn" and "does not match" in by["socket_path"]["detail"]
    assert "LocalSocket" in d["cause"] and "differs from the systemd socket" in d["cause"]
    assert by["tcp"]["state"] == "fail"  # TCPSocket in clamd.conf is reported
    host.server = None
    # the start condition case: no signatures when the daemon was started -> skipped
    host2 = FakeHost(short_tmp / "b", daemon=False, signatures=False, condition="no")
    d2 = _checker(host2, as_root=True).diagnose()
    assert d2["status"] == "unavailable" and "No signature files" in d2["cause"]
    # the application never calls metadata "healthy": cached engine info + missing socket -> Unavailable
    HealthState.put("antivirus", reachable=True, scan_ok=True, engine="ClamAV 1.4.3", signatures="28146",
                    signatures_date=timezone.now().isoformat(), checked_at=(timezone.now() - timedelta(hours=1)).isoformat())
    config.set_value("antivirus.enabled", True)
    config.set_value("antivirus.socket", host.sock)
    from apps.security import antivirus

    h = antivirus.health(refresh=True)
    assert h["state"] == "unavailable" and h["state_label"] == "Unavailable" and "FileNotFoundError" in h["error"]
    assert h["engine"] == "ClamAV 1.4.3" and h["metadata_stale"] is True
    host.close()
    host2.close()


def test_at206_repair_restores_daemon_socket_and_access(family, short_tmp):
    host = FakeHost(short_tmp, daemon=False)
    try:
        c = _checker(host, as_root=True)
        out = c.repair(wait_seconds=10)
        conf = host.conf.read_text()
        assert f"LocalSocket {host.sock}" in conf and "TCPSocket" not in conf and "LocalSocketMode 666" in conf
        assert conf.count("LocalSocket ") == 1 and "EnableVersionCommand true" in conf
        assert (host.conf.with_name("clamd.conf.personaldocs-backup")).exists()
        assert "Restart=on-failure" in (short_tmp / "dropin" / "50-personaldocs.conf").read_text()
        assert "d /run/clamav 0755 clamav clamav" in (short_tmp / "tmpfiles" / "personaldocs-clamav.conf").read_text()
        res = out["result"]
        by = {x["key"]: x for x in res["checks"]}
        assert res["status"] == "healthy", res
        assert by["access"]["state"] == "ok" and "PONG" in by["access"]["detail"]  # the service identity connects
        assert by["self_test"]["state"] == "ok" and "EICAR: detected" in by["self_test"]["detail"]
        started = [x for x in host.calls if x[:2] == ["systemctl", "start"]]
        assert any("clamav-daemon.socket" in x and "clamav-daemon.service" in x for x in started)
        assert ["systemctl", "daemon-reload"] in host.calls
        assert not any(x[0] in ("sh", "bash") for x in host.calls)  # fixed commands only
        # idempotent: a second repair keeps the same configuration and stays healthy
        before = host.conf.read_text()
        assert c.repair(wait_seconds=10)["result"]["status"] == "healthy" and host.conf.read_text() == before
    finally:
        host.close()


def test_at206_repair_through_the_host_helper_action(family, short_tmp, settings, tmp_path):
    from apps.ops import clamav_check, host_helper

    host = FakeHost(short_tmp, daemon=False)
    settings.DATA_DIR = tmp_path
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / "request.json").write_text('{"id": "abc123", "action": "antivirus_repair"}')
    real = clamav_check.Clamav

    def patched(run=None, **kw):
        return _checker(host, cls=real, as_root=True)
    try:
        with mock.patch.object(clamav_check, "Clamav", patched):
            out = host_helper.HostHelper(tmp_path, run=host).apply()
        assert out["state"] == "done" and out["diagnosis"]["status"] == "healthy", out.get("error")
        assert any(s["step"].startswith("wait for") and s["ok"] for s in out["steps"])
    finally:
        clamav_check.Clamav = real
        host.close()


def test_at207_self_test_clean_and_eicar_without_artifacts(family, clients, short_tmp, settings):
    from apps.library.models import DocumentVersion
    from apps.security import antivirus

    srv = FakeClamd(str(short_tmp / "c.sock"))
    settings.TMP_DIR = short_tmp / "tmp"
    try:
        config.set_value("antivirus.enabled", True)
        config.set_value("antivirus.socket", srv.path)
        versions = DocumentVersion.objects.count()
        r = clients["dad"].post("/api/security/antivirus/selftest", {}, format="json")
        assert r.status_code == 200
        res = r.json()
        assert res["ok"] and res["clean"] and res["eicar"] and res["artifacts_removed"]
        assert list((short_tmp / "tmp").iterdir()) == []  # temporary test files removed
        assert DocumentVersion.objects.count() == versions  # never stored as a family document, no quarantine entry
        assert AuditEvent.objects.filter(action="antivirus.self_test", outcome="success").exists()
        assert clients["son1"].post("/api/security/antivirus/selftest", {}, format="json").status_code == 403
        h = antivirus.health(refresh=True)
        assert h["state"] == "healthy" and h["self_test"]["ok"]
        # a scanner that answers but does not detect EICAR is an Error, not Healthy
        with mock.patch.object(antivirus, "scan_path", side_effect=[("clean", ""), ("clean", "")]):
            assert antivirus.self_test()["ok"] is False
        assert antivirus.health(refresh=True)["state"] == "error"
    finally:
        srv.stop()


def test_at207_diagnose_and_repair_endpoints_are_admin_only(family, clients, settings, tmp_path):
    settings.DATA_DIR = tmp_path
    assert clients["son1"].get("/api/security/antivirus/diagnose").status_code == 403
    assert clients["son1"].post("/api/security/antivirus/repair", {}, format="json").status_code == 403
    r = clients["dad"].get("/api/security/antivirus/diagnose")
    assert r.status_code == 200 and "checks" in r.json()["diagnosis"] and r.json()["manual_fix"] == "sudo personaldocs antivirus repair"
    # without the host helper the app cannot repair and says what to run instead (never claims success)
    r = clients["dad"].post("/api/security/antivirus/repair", {}, format="json")
    assert r.status_code == 409 and r.json()["manual_fix"] == "sudo personaldocs antivirus repair"
    (tmp_path / "host").mkdir(exist_ok=True)
    (tmp_path / "host" / "helper.json").write_text('{"installed": true}')
    r = clients["dad"].post("/api/security/antivirus/repair", {}, format="json")
    assert r.status_code == 202
    import json

    req = json.loads((tmp_path / "host" / "request.json").read_text())
    assert req["action"] == "antivirus_repair" and set(req) == {"id", "action", "requested_at", "requested_by"}


def test_at208_repair_is_persistent_configuration(short_tmp):
    """Reboot persistence on a real LXC is a manual test; here: the repair installs exactly the configuration that
    survives reboots (systemd drop-in with Restart=on-failure, tmpfiles.d entry for /run/clamav, enabled units)."""
    host = FakeHost(short_tmp, daemon=False)
    try:
        _checker(host, as_root=True).repair(wait_seconds=10)
        enabled = [x for x in host.calls if x[:2] == ["systemctl", "enable"]]
        assert enabled and {"clamav-daemon.socket", "clamav-daemon.service", "clamav-freshclam.service"} <= set(enabled[0])
        assert ["systemd-tmpfiles", "--create", str(short_tmp / "tmpfiles" / "personaldocs-clamav.conf")] in host.calls
        # restart of clamd (simulated): the socket comes back and the app connects again
        host("systemctl stop clamav-daemon.service".split())
        host("systemctl start clamav-daemon.socket clamav-daemon.service".split())
        assert _checker(host, as_root=True).diagnose()["status"] == "healthy"
    finally:
        host.close()


def test_at209_upload_scan_and_quarantine_still_work_after_repair(family, clients, short_tmp):
    from apps.library.models import Document
    from apps.security import antivirus
    from conftest import personal_root, upload
    from fake_clamd import EICAR
    from apps.core.jobs import run_pending

    host = FakeHost(short_tmp, daemon=False)
    try:
        _checker(host, as_root=True).repair(wait_seconds=10)
        config.set_value("antivirus.enabled", True)
        config.set_value("antivirus.socket", host.sock)
        r = upload(clients["son1"], personal_root(family["son1"]), name="note.txt", content=b"harmless synthetic text\n")
        doc = Document.objects.get(pk=r.json()["documents"][0]["id"])
        assert doc.current_version.av_status == "pending"
        run_pending()
        doc.current_version.refresh_from_db()
        assert doc.current_version.av_status == "clean"
        r = upload(clients["son1"], personal_root(family["son1"]), name="eicar.txt", content=EICAR)
        bad = Document.objects.get(pk=r.json()["documents"][0]["id"])
        run_pending()
        bad.current_version.refresh_from_db()
        assert bad.current_version.av_status == "quarantined"
        assert antivirus.health(refresh=True)["state"] == "healthy"
    finally:
        host.close()


def test_at210_security_health_uses_operational_state(family, short_tmp):
    from apps.security import antivirus, center

    HealthState.put("antivirus", reachable=True, scan_ok=True, engine="ClamAV 1.4.3", signatures="28146",
                    signatures_date=timezone.now().isoformat())
    config.set_value("antivirus.enabled", True)
    config.set_value("antivirus.socket", str(short_tmp / "missing.ctl"))
    antivirus.health(refresh=True)
    sh = center.security_health()
    comp = sh["components"]["antivirus"] if "components" in sh else sh["comp"]["antivirus"]
    assert comp["points"] == 0 and comp["status"] == "bad"
    assert sh["status"] != "Healthy"
    assert any("cannot be reached" in f for f in sh.get("forced", sh.get("reasons", [])))
