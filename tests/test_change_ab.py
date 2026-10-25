"""Change Set AB — WebGUI Maintenance & Operations, persistent diagnostics, Active Sessions.

Acceptance tests AT-481..AT-500: the change prompt's AT-456..AT-475 renumbered (+25), because AT-456..AT-480 are
already used by Change Sets Z and AA.

Root operations (check for updates, upgrade, restart, repair, rollback) go through the real root host helper
(apps/ops/host_helper.py) with a *stand-in* `personaldocs` command: a small bash script that sources the real CLI's
progress functions (step / meta / die, extracted from scripts/personaldocs) and plays one scenario. So the helper,
the progress protocol, the job sync, the failure analysis and the API are real; the Debian packaging work an upgrade
does is not — a real upgrade on a Debian 13 host (AT-488) is reported as BLOCKED in docs/TEST_REPORT.md.
"""
import json
import re
import shutil
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core import config
from apps.core.models import AuditEvent, Job
from apps.notify.models import Notification
from apps.ops import diagnostics, host, maintenance as M, sanitize
from apps.ops.host_helper import HostHelper
from apps.ops.models import MaintenanceJob as MJ
from conftest import PASSWORD, client_for, run_jobs

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
HAS_JQ = shutil.which("jq") is not None


# ------------------------------------------------------------------ helpers

def _stepup(client):
    r = client.post("/api/backup/stepup", {"password": PASSWORD}, format="json")
    assert r.status_code == 200, r.content


def _helpers_sh(tmp_path) -> Path:
    """The real CLI's helper section (log, redact, die, step, meta, progress_fail …)."""
    src = (ROOT / "scripts" / "personaldocs").read_text()
    start = src.index("# ------------------------------------------------------------------ helpers")
    end = src.index("# ------------------------------------------------------------------ preflight")
    p = tmp_path / "cli-helpers.sh"
    p.write_text(src[start:end])
    return p


def _fake_cli(tmp_path, body: str) -> Path:
    """A stand-in `personaldocs` executable: real progress functions, scripted scenario (``$1`` is the command)."""
    p = tmp_path / "personaldocs"
    p.write_text(f"""#!/usr/bin/env bash
set -Eeuo pipefail
LOG_DIR=/nonexistent; LOG=/dev/null; UNITS=(personaldocs-web personaldocs-worker personaldocs-scheduler)
. "{_helpers_sh(tmp_path)}"
CMD=${{1:-}}
echo "fake personaldocs $*"
{body}
""")
    p.chmod(0o755)
    return p


def _helper(tmp_path, body: str) -> HostHelper:
    from django.conf import settings

    h = HostHelper(Path(settings.DATA_DIR), cli=str(_fake_cli(tmp_path, body)))
    h._write("helper.json", {"installed": True})
    return h


UPGRADE_OK = """
FAIL_OUTCOME=remains_operational
step lock running; step lock ok
step preflight running; meta version_from "0.1.0-aaaaaaaaaa"; step preflight ok "installed release 0.1.0"
step target running main; meta version_to "0.2.0-bbbbbbbbbb"; step target ok
step disk running; step disk ok "9000 MB free"
step backup running; meta backup_ref "verified pre-upgrade recovery point"; step backup ok "verified recovery point created"
step backup_verify running; step backup_verify ok "database snapshot readable"
step fetch running; step fetch ok
step dependencies running; step dependencies ok
step frontend running; step frontend ok
step migrations running; FAIL_OUTCOME=recovery_required; step migrations ok
step restart running; step restart ok
step health running; step health ok "all services active; /api/health OK"
FAIL_OUTCOME=""; meta outcome succeeded
echo "Upgraded 0.1.0 -> 0.2.0"
"""


def _main(family):
    return family["dad"]


def _scoped_admin(family):
    User.objects.filter(pk=family["mom"].pk).update(is_admin=True)
    return User.objects.get(pk=family["mom"].pk)


def _start(client, op, **body):
    if op in ("upgrade", "restart", "rollback"):
        _stepup(client)
        body.setdefault("confirm", True)
    return client.post(f"/api/maintenance/run/{op}", body, format="json")


def _drive(h: HostHelper, client, job_id: str) -> dict:
    """The root helper processes its queue (as personaldocs-host.service would), then the page polls."""
    h.apply()
    client.get(f"/api/maintenance/jobs/{job_id}")  # polling folds the helper's result into the job
    run_jobs()  # repair verification runs in the worker
    return client.get(f"/api/maintenance/jobs/{job_id}").json()


# ================================================================== AT-481 (456) permissions

def test_at481_permissions_main_admin_scoped_admin_normal_user(family, tmp_path):
    _helper(tmp_path, "exit 0")
    main, scoped, normal = client_for(_main(family)), client_for(_scoped_admin(family)), client_for(family["son1"])
    # normal users: no access at all
    for url in ("/api/maintenance", "/api/maintenance/health", "/api/maintenance/jobs", "/api/maintenance/system",
                "/api/maintenance/caches"):
        assert normal.get(url).status_code == 403, url
    assert normal.post("/api/maintenance/doctor").status_code == 403
    assert normal.post("/api/maintenance/run/check_updates").status_code == 403
    # scoped administrator: read-only Status, Doctor and Health
    ov = scoped.get("/api/maintenance")
    assert ov.status_code == 200 and ov.json()["can_manage"] is False
    assert scoped.get("/api/maintenance/health").status_code == 200
    assert scoped.get("/api/maintenance/jobs").status_code == 200
    assert scoped.post("/api/maintenance/doctor").status_code == 202  # diagnostic only
    for op in ("check_updates", "upgrade", "restart", "repair", "rollback", "clear_caches"):
        assert scoped.post(f"/api/maintenance/run/{op}", {"confirm": True}, format="json").status_code == 403, op
    assert scoped.get("/api/maintenance/system").status_code == 403
    assert scoped.get("/api/maintenance/caches").status_code == 403
    # main administrator: everything, high-risk actions need confirmation and step-up
    assert main.get("/api/maintenance").json()["can_manage"] is True
    assert main.get("/api/maintenance/system").status_code == 200
    r = main.post("/api/maintenance/run/upgrade", {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "confirm_required"
    r = main.post("/api/maintenance/run/upgrade", {"confirm": True}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "stepup_required"
    r = _start(main, "restart")
    assert r.status_code == 202
    # the step-up is consumed: a second high-risk action needs a new one
    MJ.objects.update(status=MJ.CANCELLED)
    r = main.post("/api/maintenance/run/restart", {"confirm": True}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "stepup_required"
    # scoped admins cannot read a root operation's details or any log
    job = MJ.objects.filter(operation="restart").first()
    assert scoped.get(f"/api/maintenance/jobs/{job.id}").status_code == 403
    assert scoped.get(f"/api/maintenance/jobs/{job.id}/log").status_code == 403
    # CSRF: session-authenticated POSTs without the token are refused
    from rest_framework.test import APIClient

    c = APIClient(enforce_csrf_checks=True)
    c.force_login(_main(family))
    assert c.post("/api/maintenance/run/check_updates").status_code == 403


def test_at481_helper_runs_only_allowlisted_commands(tmp_path):
    h = HostHelper(tmp_path, cli="/usr/local/bin/personaldocs")
    job = str(uuid.uuid4())
    assert h.maintenance_command({"action": "app_upgrade", "job": job}) == ["/usr/local/bin/personaldocs", "upgrade"]
    assert h.maintenance_command({"action": "app_upgrade", "job": job, "params": {"ref": "v1.2.3"}})[-2:] == ["--ref", "v1.2.3"]
    for bad in ("main; rm -rf /", "$(id)", "../../etc", "-x", "a b", "`id`"):
        with pytest.raises(ValueError):
            h.maintenance_command({"action": "app_upgrade", "job": job, "params": {"ref": bad}})
    assert h.maintenance_command({"action": "app_repair", "params": {"items": ["jobs", "services"]}})[-2:] == ["--only", "jobs,services"]
    for bad in (["rm"], ["jobs;id"], [], "jobs"):
        with pytest.raises(ValueError):
            h.maintenance_command({"action": "app_repair", "params": {"items": bad}})
    with pytest.raises(ValueError):
        h.maintenance_command({"action": "app_shell"})
    # an invalid job id or unknown action is refused before anything runs
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / "request.json").write_text(json.dumps({"id": "abc", "action": "app_upgrade", "job": "../x"}))
    assert h.apply()["state"] == "failed"
    (tmp_path / "host" / "request.json").write_text(json.dumps({"id": "abd", "action": "bash", "job": job}))
    assert h.apply()["state"] == "failed"


# ================================================================== AT-482 (457) durable jobs

def test_at482_jobs_survive_refresh_relogin_and_restart(family, tmp_path):
    h = _helper(tmp_path, 'step restart running; step restart ok; step health running; step health ok')
    c = client_for(_main(family))
    job_id = _start(c, "restart").json()["id"]
    # the web application "restarts" before the helper reports: nothing lives in memory, only in the database/files
    first = client_for(_main(family)).get(f"/api/maintenance/jobs/{job_id}").json()
    assert first["status"] == MJ.QUEUED and first["steps"][0]["status"] == "succeeded"  # authorize
    h.apply()  # the root helper keeps working while the web app restarts
    # a new sign-in (fresh session) sees the same job, its steps and its result
    again = client_for(_main(family)).get(f"/api/maintenance/jobs/{job_id}").json()
    assert again["status"] == MJ.SUCCEEDED and again["exit_code"] == 0
    assert [s["key"] for s in again["steps"]] == ["authorize", "lock", "restart", "health", "release_lock", "report"]
    assert all(s["status"] == "succeeded" for s in again["steps"] if s["key"] != "lock")
    assert all(s["started_at"] and s["finished_at"] for s in again["steps"] if s["status"] == "succeeded")
    hist = c.get("/api/maintenance/jobs").json()
    assert hist["jobs"][0]["id"] == job_id
    # the scheduler also syncs jobs nobody is watching (a browser disconnect is not a failure)
    job2 = _start(c, "restart").json()["id"]
    h.apply()
    from apps.notify.management.commands.scheduler import tick

    tick()
    assert MJ.objects.get(pk=job2).status == MJ.SUCCEEDED


def test_at482_history_filters_and_retention(family, tmp_path):
    _helper(tmp_path, "exit 0")
    c = client_for(_main(family))
    old = MJ.objects.create(operation="doctor", status=MJ.SUCCEEDED, requested_at=timezone.now() - timedelta(days=800),
                            finished_at=timezone.now() - timedelta(days=800), log_name="x.app.log")
    mid = MJ.objects.create(operation="clear_caches", status=MJ.FAILED, requested_at=timezone.now() - timedelta(days=100),
                            finished_at=timezone.now() - timedelta(days=100), log_name=f"{uuid.uuid4()}.app.log")
    new = MJ.objects.create(operation="doctor", status=MJ.SUCCEEDED)
    assert {j["id"] for j in c.get("/api/maintenance/jobs?operation=doctor").json()["jobs"]} == {str(old.id), str(new.id)}
    assert [j["id"] for j in c.get("/api/maintenance/jobs?status=failed").json()["jobs"]] == [str(mid.id)]
    d = (timezone.now() - timedelta(days=101)).date().isoformat()
    to = (timezone.now() - timedelta(days=99)).date().isoformat()
    assert [j["id"] for j in c.get(f"/api/maintenance/jobs?from={d}&to={to}").json()["jobs"]] == [str(mid.id)]
    assert c.get("/api/maintenance/jobs?from=yesterday").status_code == 400
    # retention: logs after 90 days, history after 730 days; audit retention is separate
    M.app_log_dir().mkdir(parents=True, exist_ok=True)
    (M.app_log_dir() / mid.log_name).write_text("log")
    out = M.purge()
    assert out["jobs"] == 1 and not MJ.objects.filter(pk=old.pk).exists()
    mid.refresh_from_db()
    assert mid.log_name == "" and not (M.app_log_dir() / f"{mid.id}.app.log").exists()
    assert MJ.objects.filter(pk=new.pk).exists()
    assert config.get("maintenance.log_retention_days") == 90 and config.get("maintenance.history_days") == 730


# ================================================================== AT-483 (458) error visibility

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at483_failure_shows_summary_technical_details_and_full_log(family, tmp_path):
    h = _helper(tmp_path, """
FAIL_OUTCOME=remains_operational
step lock running; step lock ok
step preflight running; meta version_from "0.1.0-aaaaaaaaaa"; step preflight ok
step target running; meta version_to "0.2.0-bbbbbbbbbb"; step target ok
step disk running
echo "df: checking /var/lib/personaldocs"
die "less than 2 GB free (812 MB); free space before upgrading"
""")
    c = client_for(_main(family))
    job_id = _start(c, "upgrade").json()["id"]
    j = _drive(h, c, job_id)
    # Summary
    assert j["status"] == MJ.FAILED and j["summary"] == "Upgrade Failed — Existing Version Remains Operational."
    assert j["recovery_state"] == "remains_operational"
    assert j["version_from"] == "0.1.0-aaaaaaaaaa" and j["version_to"] == "0.2.0-bbbbbbbbbb"
    # Technical Details: failed step, component, timestamp, exit code, exact error, log context, condition, action
    d = j["details"]
    assert d["failed_step"] == "disk" and d["component"] == "Storage" and d["exit_code"] == 1 and d["timestamp"]
    assert d["error"] == "less than 2 GB free (812 MB); free space before upgrading"
    assert any("df: checking" in ln for ln in d["log_context"])
    assert d["condition"] == "The disk is full or nearly full." and "Free disk space" in d["recommended"]
    assert d["rollback_required"] is False and j["failure_class"] == "disk_full"
    steps = {s["key"]: s for s in j["steps"]}
    assert steps["disk"]["status"] == "failed" and steps["backup"]["status"] == "not_run"
    assert steps["release_lock"]["status"] == "succeeded"
    # Full Log: view and download (sanitised server-side)
    log = c.get(f"/api/maintenance/jobs/{job_id}/log")
    assert log.status_code == 200 and "less than 2 GB free" in log.content.decode() and "Content-Disposition" not in log
    dl = c.get(f"/api/maintenance/jobs/{job_id}/log?download=1")
    assert dl["Content-Disposition"].startswith("attachment;") and "no-store" in dl["Cache-Control"]
    assert AuditEvent.objects.filter(action="maintenance.log_downloaded").exists()
    # Retry creates a linked job; the failed one stays in the history
    _stepup(c)
    r = c.post(f"/api/maintenance/jobs/{job_id}/retry", {"confirm": True}, format="json")
    assert r.status_code == 202 and r.json()["parent"] == job_id
    assert c.get(f"/api/maintenance/jobs/{job_id}").json()["retries"] == [r.json()["id"]]
    # a notification with a deep link, without the log
    n = Notification.objects.filter(user=_main(family), kind="maintenance").first()
    assert n is not None and f"/settings/system?job={job_id}" == n.link and "df: checking" not in json.dumps([n.body, n.summary, n.data])


def test_at483_unreachable_helper_and_worker_are_reported_not_hidden(family, tmp_path, settings):
    c = client_for(_main(family))
    _stepup(c)
    r = c.post("/api/maintenance/run/restart", {"confirm": True}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "helper_unavailable"  # helper not installed: refused up front
    _helper(tmp_path, "exit 0")
    job_id = _start(c, "restart").json()["id"]
    MJ.objects.filter(pk=job_id).update(requested_at=timezone.now() - timedelta(minutes=11))
    j = c.get(f"/api/maintenance/jobs/{job_id}").json()  # the helper never picked it up
    assert j["status"] == MJ.FAILED and j["failure_class"] == "helper_unavailable"
    assert "sudo personaldocs repair" in j["details"]["recommended"]


# ================================================================== AT-484 (459) secret redaction

SYNTH = {"smtp": "Synth-Smtp-Pass-7Q2x", "token": "ghp_" + "A" * 36, "sk": "sk-" + "b" * 40,
         "bot": "123456789:" + "AA" + "c" * 33,
         "pem": "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQ\n-----END " + "PRIVATE KEY-----"}  # built at run time: no secret-shaped literal in the repository
AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def test_at484_sanitizer_patterns_and_known_values(db):
    text = (f"password={SYNTH['smtp']} Authorization: Bearer abcdefghijkl {SYNTH['token']} {SYNTH['sk']} {SYNTH['bot']}\n"
            f"postgres://pd:dbpass123@localhost/x Cookie: sessionid=abc123; pd_csrftoken=zzz\n{SYNTH['pem']}\n"
            "api_key: 'k-123456' NAS_PASSWORD=nas-secret-1 recovery_key=word-word-word "
            f"https://discord.com/api/webhooks/123/abcDEF {AWS}")
    out = sanitize.redact(text, secrets=[SYNTH["smtp"]])
    for s in (SYNTH["smtp"], SYNTH["token"], SYNTH["sk"], SYNTH["bot"], "dbpass123", "abc123", "zzz", "MIIEvQ", "k-123456",
              "nas-secret-1", "word-word-word", "abcDEF", AWS, "abcdefghijkl"):
        assert s not in out, s
    assert "[REDACTED]" in out and "postgres://pd:[REDACTED]@localhost" in out


@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at484_logs_reports_and_details_never_show_secrets(family, tmp_path, settings):
    config.set_value("smtp.password", SYNTH["smtp"])  # a secret this installation holds: redacted wherever it appears
    settings.PUBLIC_ORIGIN = "https://docs.example-home.invalid"
    h = _helper(tmp_path, f"""
FAIL_OUTCOME=remains_operational
step lock running; step lock ok
step backup running
echo "connecting to //nas-box/backups as backup-user password={SYNTH['smtp']} from 192.168.20.15"
echo "token {SYNTH['token']} key {SYNTH['sk']} user dad file /var/lib/personaldocs/storage/originals/ab/passport-scan.pdf"
echo "{SYNTH['smtp']}"
die "pre-upgrade backup failed or could not be verified (password={SYNTH['smtp']})"
""")
    c = client_for(_main(family))
    job_id = _start(c, "upgrade").json()["id"]
    j = _drive(h, c, job_id)
    blob = json.dumps(j)
    log = c.get(f"/api/maintenance/jobs/{job_id}/log?download=1").content.decode()
    report = c.get(f"/api/maintenance/jobs/{job_id}/report").content.decode()
    anon = c.get(f"/api/maintenance/jobs/{job_id}/report?anonymize=1").content.decode()
    for text in (blob, log, report, anon):
        for s in (SYNTH["token"], SYNTH["sk"]):
            assert s not in text
        assert SYNTH["smtp"] not in text
    assert "192.168.20.15" in report and "passport-scan.pdf" in report  # the plain report keeps operational detail
    # the anonymised support report also drops IP addresses, user and host names, document paths and network names
    for s in ("192.168.20.15", "passport-scan.pdf", "nas-box", "docs.example-home.invalid", " dad "):
        assert s not in anon, s
    assert re.search(r"ip-\d", anon) and "[path]/file-1.pdf" in anon and "//nas-share/[path]" in anon
    assert j["failure_class"] == "backup_failed" and "backup destination" in j["details"]["recommended"]
    # records are not changed by anonymisation; audit rows carry no log text
    assert User.objects.filter(username="dad").exists()
    assert not AuditEvent.objects.filter(context__icontains=SYNTH["smtp"]).exists()


# ================================================================== AT-485 (460) Doctor

def test_at485_doctor_is_diagnostic_grouped_and_shared_with_the_cli(family, tmp_path):
    from io import StringIO

    from django.core.management import call_command

    from apps.library.models import Document, Folder

    before = (Document.objects.count(), Folder.objects.count(), User.objects.count(), Job.objects.exclude(kind="maintenance_task").count())
    c = client_for(_main(family))
    job_id = c.post("/api/maintenance/doctor").json()["id"]
    run_jobs()
    j = c.get(f"/api/maintenance/jobs/{job_id}").json()
    assert j["status"] in (MJ.SUCCEEDED, MJ.WARNINGS) and j["summary"].startswith("Doctor:")
    res = j["result"]
    comps = {x["component"] for x in res["components"]}
    assert {"Database", "Filesystem", "Storage", "Services & workers", "Backup & recovery", "Security & authentication",
            "AI providers", "OCR engines"} <= comps
    statuses = {r["status"] for x in res["components"] for r in x["results"]}
    assert statuses <= set(diagnostics.STATUSES) and "PASS" in statuses
    assert "NOT CONFIGURED" in statuses  # AI is off in tests
    assert all(set(r) >= {"component", "check", "status", "detail", "recommended"} for x in res["components"] for r in x["results"])
    # nothing changed
    after = (Document.objects.count(), Folder.objects.count(), User.objects.count(), Job.objects.exclude(kind="maintenance_task").count())
    assert before == after
    # the same checks as `personaldocs doctor` (one implementation)
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("doctor", stdout=out)
    cli_names = [ln.split("] ", 1)[1].split(" - ")[0] for ln in out.getvalue().splitlines() if ln.startswith("[")]
    web_names = [r["check"] for x in res["components"] for r in x["results"]]
    assert set(cli_names) == set(web_names)
    # downloadable sanitised report; scoped admins may download Doctor reports too
    rep = client_for(_scoped_admin(family)).get(f"/api/maintenance/jobs/{job_id}/doctor-report")
    assert rep.status_code == 200 and "Personal DM Doctor report" in rep.content.decode()


def test_at485_doctor_critical_finding_notifies_main_admin(family, settings, tmp_path):
    settings.ORIGINALS_DIR = tmp_path / "missing-originals"  # a critical Filesystem failure
    c = client_for(_main(family))
    job_id = c.post("/api/maintenance/doctor").json()["id"]
    run_jobs()
    j = c.get(f"/api/maintenance/jobs/{job_id}").json()
    assert any(r["component"] == "Filesystem" for r in j["result"]["critical"])
    n = Notification.objects.filter(user=_main(family), kind="maintenance").first()
    assert n is not None and "critical" in n.title.lower()


# ================================================================== AT-486 (461) repair plan

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at486_repair_plan_before_change_confirm_backup_repair_verify(family, tmp_path, settings):
    h = _helper(tmp_path, """
step lock running; step lock ok
[ "$1" = repair ] && [ "$2" = --only ] || die "unexpected command"
for item in ${3//,/ }; do step "repair_$item" running; echo "repairing $item"; step "repair_$item" ok; done
step health running; step health ok
""")
    tmp = Path(settings.TMP_DIR)
    shutil.rmtree(tmp)  # a safe repairable condition: a missing application directory
    c = client_for(_main(family))
    job_id = c.post("/api/maintenance/run/repair", {}, format="json").json()["id"]
    run_jobs()  # Analyze (Doctor checks, read-only)
    j = c.get(f"/api/maintenance/jobs/{job_id}").json()
    assert j["status"] == MJ.CONFIRM and j["summary"].startswith("Repair plan ready")
    plan = {p["item"]: p for p in j["result"]["plan"]}
    assert "directories" in plan
    p = plan["directories"]
    assert {"problem", "proposed", "affects", "restart", "backup", "risk", "evidence"} <= set(p)
    assert p["risk"] == "low" and p["backup"] is False and p["restart"] is False
    assert any(str(tmp) in e for e in p["evidence"])
    assert not tmp.exists()  # nothing changed before confirmation
    assert not (host.host_dir() / "queue").exists() or not list((host.host_dir() / "queue").glob("*.json"))
    # confirmation requires step-up; unknown items are ignored, an empty choice is refused
    r = c.post(f"/api/maintenance/jobs/{job_id}/confirm", {"items": ["directories"]}, format="json")
    assert r.status_code == 403
    _stepup(c)
    assert c.post(f"/api/maintenance/jobs/{job_id}/confirm", {"items": ["rm -rf"]}, format="json").status_code == 400
    _stepup(c)
    r = c.post(f"/api/maintenance/jobs/{job_id}/confirm", {"items": ["directories"]}, format="json")
    assert r.status_code == 202
    run_jobs()  # execute: no backup needed for this item → root request
    queued = list((host.host_dir() / "queue").glob("*.json"))
    assert len(queued) == 1 and json.loads(queued[0].read_text())["params"] == {"items": ["directories"]}
    h.apply()
    tmp.mkdir(parents=True)  # what `personaldocs repair --only directories` does as root (the stand-in CLI cannot)
    h.apply()
    for _ in range(3):  # repeated polling while the worker has not verified yet queues the verification once
        c.get(f"/api/maintenance/jobs/{job_id}")
    assert Job.objects.filter(kind="maintenance_task", payload__phase="verify", payload__job=job_id).count() == 1
    j = _drive(h, c, job_id)
    assert j["status"] == MJ.SUCCEEDED and "verified" in j["summary"]
    keys = [s["key"] for s in j["steps"]]
    assert keys.index("confirm") < keys.index("repair_directories") < keys.index("verify")
    assert j["verification"]["remaining"] == []
    assert AuditEvent.objects.filter(action="maintenance.repair_confirmed").exists()


@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at486_repair_that_does_not_fix_is_partial_and_backup_failure_blocks(family, tmp_path, settings):
    h = _helper(tmp_path, 'step lock running; step lock ok; step repair_directories running; step repair_directories ok')
    shutil.rmtree(settings.TMP_DIR)
    c = client_for(_main(family))
    job_id = c.post("/api/maintenance/run/repair", {}, format="json").json()["id"]
    run_jobs()
    _stepup(c)
    c.post(f"/api/maintenance/jobs/{job_id}/confirm", {"items": ["directories"]}, format="json")
    run_jobs()
    j = _drive(h, c, job_id)  # the directory is still missing: verification says so
    assert j["status"] == MJ.PARTIAL and j["verification"]["remaining"]  # never reported as fixed
    assert Notification.objects.filter(user=_main(family), event="maintenance.repair_failed").exists() is False
    # an item that needs a backup is blocked when the backup fails (no destination configured in tests)
    job = MJ.objects.create(operation="repair", status=MJ.RUNNING, params={"items": ["migrations"]},
                            result={"plan": [{"item": "migrations", "backup": True}]}, steps=[])
    M._repair_execute(job)
    job.refresh_from_db()
    assert job.status == MJ.FAILED and job.failure_class == "backup_failed"
    assert not list((host.host_dir() / "queue").glob(f"*-{job.id}.json"))


# ================================================================== AT-487 (462) update check

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at487_check_for_updates_reports_versions_without_installing(family, tmp_path):
    h = _helper(tmp_path, """
[ "$1" = check-updates ] && [ "$2" = --json ] || die "unexpected"
step source running "https://github.com/OWNER/REPO.git (main)"; step source ok
step compare running; step compare ok available
jq -cn '{state:"available",installed_version:"0.1.0",installed_revision:"aaaaaaaaaaaa",available_version:"0.2.0",
 available_revision:"bbbbbbbbbbbb",channel:"main",source:"https://github.com/OWNER/REPO.git",tag:"",behind:3,
 commits:["bbbbbbb Add maintenance","ccccccc Fix",  "ddddddd Docs"],warnings:[],checked_at:"2026-01-01T00:00:00+00:00"}'
""")
    c = client_for(_main(family))
    job_id = c.post("/api/maintenance/run/check_updates", {}, format="json").json()["id"]
    j = _drive(h, c, job_id)
    assert j["status"] == MJ.SUCCEEDED and "0.2.0" in j["summary"]
    r = j["result"]
    assert r["installed_version"] == "0.1.0" and r["available_version"] == "0.2.0" and r["behind"] == 3
    assert r["source"] == "https://github.com/OWNER/REPO.git" and r["channel"] == "main"
    assert [s["key"] for s in j["steps"]] == ["source", "compare", "report", "release_lock"] or \
        {"source", "compare", "report"} <= {s["key"] for s in j["steps"]}
    assert not any(s["key"] in ("migrations", "restart", "fetch") for s in j["steps"])  # never installs
    ov = c.get("/api/maintenance").json()
    assert ov["last_update_check"]["result"]["available_version"] == "0.2.0"
    assert ov["installed"]["version"]


# ================================================================== AT-488 (463) successful upgrade (emulated)

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at488_upgrade_flow_with_emulated_cli(family, tmp_path):
    """The orchestration of a successful upgrade. A real upgrade on Debian 13 is BLOCKED here (no such host)."""
    h = _helper(tmp_path, UPGRADE_OK)
    c = client_for(_main(family))
    job_id = _start(c, "upgrade", ref="v0.2.0").json()["id"]
    q = json.loads(next((host.host_dir() / "queue").glob("*.json")).read_text())
    assert q["action"] == "app_upgrade" and q["params"] == {"ref": "v0.2.0"}
    j = _drive(h, c, job_id)
    assert j["status"] == MJ.SUCCEEDED and j["exit_code"] == 0
    assert j["summary"] == "Upgraded 0.1.0-aaaaaaaaaa → 0.2.0-bbbbbbbbbb; health checks passed."
    order = [s["key"] for s in j["steps"]]
    assert order == M.PLANS["upgrade"]
    assert all(s["status"] == "succeeded" for s in j["steps"])
    assert j["backup_ref"] == "verified pre-upgrade recovery point"
    n = Notification.objects.filter(user=_main(family), kind="maintenance").first()
    assert n is not None and "Upgrade completed" in n.title
    log = c.get(f"/api/maintenance/jobs/{job_id}/log").content.decode()
    assert "upgrade --ref v0.2.0" in log and "Upgraded 0.1.0 -> 0.2.0" in log


def test_at488_invalid_target_is_refused_before_anything_runs(family, tmp_path):
    _helper(tmp_path, "exit 0")
    c = client_for(_main(family))
    r = _start(c, "upgrade", ref="main; curl evil")
    assert r.status_code == 400 and not MJ.objects.exists()


# ================================================================== AT-489 (464) upgrade failure

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
@pytest.mark.parametrize("scenario,status,state,title", [
    ("""FAIL_OUTCOME=remains_operational; step lock running; step lock ok; step migrations running
        echo "django.db.utils.ProgrammingError: relation x does not exist"
        step migrations failed "migration failed; restoring the database snapshot and the previous release"
        FAIL_OUTCOME=remains_operational; meta verification "database restored from the snapshot; previous release healthy"
        die "upgrade aborted; previous release still active" """,
     MJ.FAILED, "remains_operational", "Upgrade Failed — Existing Version Remains Operational."),
    ("""FAIL_OUTCOME=recovery_required; meta version_from "0.1.0-a"; step health running
        step health failed "the new release did not become healthy"
        meta verification "no automatic rollback: the migrated database is not compatible with 0.1.0-a"
        die "the new schema is not compatible with 0.1.0-a; restore with: pg_restore from /var/lib/personaldocs/pre-upgrade/db.pgdump" """,
     MJ.RECOVERY, "recovery_required", "Upgrade Failed — Recovery Required."),
])
def test_at489_upgrade_failures_keep_exact_state_and_actions(family, tmp_path, scenario, status, state, title):
    h = _helper(tmp_path, scenario)
    c = client_for(_main(family))
    job_id = _start(c, "upgrade").json()["id"]
    j = _drive(h, c, job_id)
    assert j["status"] == status and j["recovery_state"] == state and j["summary"] == title
    d = j["details"]
    assert d["exit_code"] == 1 and d["error"] and d["recovery_guide"] == M.RECOVERY_GUIDE
    assert d["rollback_required"] is (state == "recovery_required")
    if state == "recovery_required":
        assert j["failure_class"] == "schema_incompatible"
        assert "Recovery Guide" in d["recommended"]
        assert Notification.objects.filter(user=_main(family), title__icontains="recovery required").exists()
    else:
        assert j["failure_class"] == "migration_failed"
        assert "database restored" in j["verification"]["result"]


# ================================================================== AT-490 (465) rollback safety

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at490_rollback_only_when_verified_and_never_blind(family, tmp_path):
    # automatic rollback after a failed health check, verified healthy
    h = _helper(tmp_path, """FAIL_OUTCOME=recovery_required; meta version_from "0.1.0-a"; meta version_to "0.2.0-b"
step health running; step health failed "the new release did not become healthy"
step rollback running; step rollback ok "previous release healthy"
FAIL_OUTCOME=rolled_back; meta verification "rolled back to 0.1.0-a; health checks passed"
die "rolled back to 0.1.0-a (schema compatible, verified healthy)" """)
    c = client_for(_main(family))
    j = _drive(h, c, _start(c, "upgrade").json()["id"])
    assert j["status"] == MJ.ROLLED_BACK and j["recovery_state"] == "rolled_back"
    assert "verified healthy" in j["summary"] and "health checks passed" in j["verification"]["result"]
    # a requested rollback with an incompatible schema is refused, the current version stays
    h = _helper(tmp_path, """FAIL_OUTCOME=remains_operational; step lock running; step lock ok
step compatibility running
die "database contains migrations unknown to 0.1.0-a; a code-only rollback is not safe. Restore the pre-upgrade recovery point instead" """)
    j = _drive(h, c, _start(c, "rollback").json()["id"])
    assert j["status"] == MJ.FAILED and j["recovery_state"] == "remains_operational"
    assert j["failure_class"] == "schema_incompatible" and "not safe" in j["details"]["error"]
    assert j["summary"] == "Rollback not performed — the current version remains active."
    # a rollback that does not end healthy is never reported as a rollback
    h = _helper(tmp_path, """FAIL_OUTCOME=recovery_required; step restart running; step restart ok; step health running
die "previous release is not healthy" """)
    j = _drive(h, c, _start(c, "rollback").json()["id"])
    assert j["status"] == MJ.RECOVERY and j["summary"] == "Rollback Failed — Recovery Required."


def test_at490_cli_rollback_checks_schema_before_switching():
    src = (ROOT / "scripts" / "personaldocs").read_text()
    rb = src[src.index("cmd_rollback() {"):src.index("REPAIR_ITEMS=(")]
    assert rb.index("schema_compatible") < rb.index('activate "$prev"')
    up = src[src.index("cmd_upgrade() {"):src.index("cmd_post_upgrade() {")]
    # backup and its verification come before any change; a failed backup stops the upgrade
    assert up.index("manage backup --pre-change") < up.index("manage migrate") < up.index('activate "$new"')
    assert "|| die \"pre-upgrade backup failed" in up and "pg_restore --list" in up
    # automatic rollback only when the schema is compatible, and only reported after health checks
    auto = up[up.index("if schema_compatible"):]
    assert auto.index("health && units_active") < auto.index("FAIL_OUTCOME=rolled_back")


# ================================================================== AT-491 (466) restart

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_at491_restart_confirmed_personal_dm_only_and_verified(family, tmp_path):
    h = _helper(tmp_path, """[ "$1" = restart ] && [ $# -eq 1 ] || die "unexpected"
step lock running; step lock ok; step restart running "${UNITS[*]}"; step restart ok
step health running; step health ok "all services active; /api/health OK" """)
    c = client_for(_main(family))
    assert c.post("/api/maintenance/run/restart", {"confirm": True}, format="json").status_code == 403  # step-up
    job_id = _start(c, "restart").json()["id"]
    assert json.loads(next((host.host_dir() / "queue").glob("*.json")).read_text())["action"] == "app_restart"
    j = _drive(h, c, job_id)
    assert j["status"] == MJ.SUCCEEDED and j["summary"].startswith("Personal DM services restarted")
    restart = next(s for s in j["steps"] if s["key"] == "restart")
    assert restart["detail"] == "personaldocs-web personaldocs-worker personaldocs-scheduler"
    src = (ROOT / "scripts" / "personaldocs").read_text()
    body = src[src.index("cmd_restart() {"):src.index("cmd_check_updates() {")]
    assert 'systemctl restart "$u"' in body and "reboot" not in body and "UNITS[@]" in body
    # failed health after the restart is a failure, not a success
    h = _helper(tmp_path, 'step restart running; step restart ok; step health running; die "the services did not become healthy after the restart"')
    j = _drive(h, c, _start(c, "restart").json()["id"])
    assert j["status"] == MJ.FAILED and j["details"]["failed_step"] == "health"


# ================================================================== AT-492 (467) concurrency

def test_at492_upgrade_repair_rollback_restart_never_overlap(family, tmp_path):
    _helper(tmp_path, "exit 0")
    c = client_for(_main(family))
    first = _start(c, "upgrade").json()
    for op in ("upgrade", "restart", "rollback"):
        r = _start(c, op)
        assert r.status_code == 409 and r.json()["code"] == "locked", op
    r = c.post("/api/maintenance/run/repair", {}, format="json")
    assert r.status_code == 409
    # read-only work may still run
    assert c.post("/api/maintenance/doctor").status_code == 202
    assert c.post("/api/maintenance/run/check_updates", {}, format="json").status_code == 202
    # the database constraint holds even without the API
    with pytest.raises(IntegrityError), transaction.atomic():
        MJ.objects.create(operation="repair", lock_group="system", status=MJ.RUNNING)
    MJ.objects.filter(pk=first["id"]).update(status=MJ.FAILED)
    assert _start(c, "restart").status_code == 202
    # and the CLI keeps its own lock for terminal sessions
    src = (ROOT / "scripts" / "personaldocs").read_text()
    for fn in ("cmd_upgrade() {", "cmd_rollback() {", "repair_only() {", "cmd_restart() {"):
        body = src[src.index(fn):src.index("\n}\n", src.index(fn))]
        assert "with_lock" in body, fn


def test_at492_cancel_only_before_work_starts(family, tmp_path):
    _helper(tmp_path, "exit 0")
    c = client_for(_main(family))
    job_id = _start(c, "restart").json()["id"]
    r = c.post(f"/api/maintenance/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == MJ.CANCELLED
    assert not list((host.host_dir() / "queue").glob("*.json"))


# ================================================================== CLI progress protocol

@pytest.mark.skipif(not HAS_JQ, reason="the CLI progress protocol uses jq")
def test_cli_progress_markers_are_json_and_redacted(tmp_path):
    progress = tmp_path / "p.jsonl"
    script = tmp_path / "t.sh"
    script.write_text(f"""set -Eeuo pipefail
LOG_DIR=/nonexistent; LOG=/dev/null; UNITS=(a)
. "{_helpers_sh(tmp_path)}"
export PD_PROGRESS_FILE="{progress}"
FAIL_OUTCOME=remains_operational
step lock running; step lock ok
step disk running "token=ghp_{'A' * 30}"
die "less than 2 GB free"
""")
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert r.returncode == 1
    rows = [json.loads(x) for x in progress.read_text().splitlines()]
    assert [(x["t"], x["key"], x["value"]) for x in rows] == [
        ("step", "lock", "running"), ("step", "lock", "ok"), ("step", "disk", "running"), ("step", "disk", "failed"),
        ("meta", "outcome", "remains_operational"), ("meta", "error", "less than 2 GB free")]
    assert "ghp_" not in progress.read_text()
    # without PD_PROGRESS_FILE the CLI behaves as before (no file, same exit code)
    r = subprocess.run(["bash", "-c", f'set -Eeuo pipefail; LOG_DIR=/x; LOG=/dev/null; UNITS=(a); . "{_helpers_sh(tmp_path)}"; step a running; die boom'],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "ERROR: boom" in r.stderr


def test_shellcheck_clean():
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck not installed")
    r = subprocess.run(["shellcheck", "-S", "error", str(ROOT / "scripts" / "personaldocs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ================================================================== health, system information, caches

def test_health_panels_system_info_and_safe_caches(family, settings):
    from django.conf import settings as dj

    from apps.core.models import WeatherCache

    c = client_for(_main(family))
    panels = {p["key"]: p for p in c.get("/api/maintenance/health").json()["panels"]}
    assert set(panels) == {"database", "ocr", "ai", "security", "backup", "storage"}
    assert panels["database"]["state"] == "ok" and panels["ai"]["state"] == "not_configured"
    info = c.get("/api/maintenance/system").json()
    assert {"application", "os", "cpu", "memory", "storage", "database", "ocr", "ai", "workers"} <= set(info)
    blob = json.dumps(info)
    assert dj.SECRET_KEY not in blob and "PASSWORD" not in blob.upper().replace("PASSWORD_", "")
    # safe caches: listed with size/effect/regeneration, cleared without touching documents, backups or logs
    shared = Path(dj.DATA_DIR) / "cache" / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "x.djcache").write_bytes(b"cache")
    tmp = Path(dj.TMP_DIR) / "ocr-old"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "page.png").write_bytes(b"x")
    import os
    import time

    old = time.time() - 3 * 86400
    os.utime(tmp, (old, old))
    fresh = Path(dj.TMP_DIR) / "ocr-running"
    fresh.mkdir()
    keep = [Path(dj.ORIGINALS_DIR) / "keep.pdf", Path(dj.DATA_DIR) / "pre-upgrade" / "db.pgdump", M.app_log_dir() / "old.app.log",
            Path(dj.STAGING_DIR) / "upload.part"]
    for k in keep:
        k.parent.mkdir(parents=True, exist_ok=True)
        k.write_bytes(b"keep")
        os.utime(k, (old, old))
    WeatherCache.objects.create(key="w", data={}, fetched_at=timezone.now())
    lst = c.get("/api/maintenance/caches").json()
    assert {x["key"] for x in lst["caches"]} == set(diagnostics.SAFE_CACHE_KEYS)
    assert all(x["effect"] and x["regeneration"] for x in lst["caches"])
    assert "documents and versions" in lst["never"]
    assert c.post("/api/maintenance/run/clear_caches", {}, format="json").status_code == 400  # confirmation
    job_id = c.post("/api/maintenance/run/clear_caches", {"confirm": True}, format="json").json()["id"]
    run_jobs()
    j = c.get(f"/api/maintenance/jobs/{job_id}").json()
    assert j["status"] == MJ.SUCCEEDED
    assert not shared.exists() and not tmp.exists() and fresh.exists()
    assert all(k.exists() for k in keep)


# ================================================================== Active Sessions

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SAFARI_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
PUBLIC_IP = "5.42.0.7"  # synthetic public address; GeoIP is emulated below


def _signin(username, ua=CHROME_WIN, ip="10.0.0.5"):
    from rest_framework.test import APIClient

    c = APIClient(HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)
    assert c.post("/api/auth/login", {"username": username, "password": PASSWORD}, format="json").status_code == 200
    return c


def _session_of(user, ua=None):
    from apps.accounts.models import UserSession

    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True, ended_at__isnull=True)
    return (qs.filter(user_agent=ua) if ua else qs).latest("created_at")


def _age(session, minutes):
    from apps.accounts.models import UserSession

    t = timezone.now() - timedelta(minutes=minutes)
    UserSession.objects.filter(pk=session.pk).update(last_activity_at=t, last_seen_at=t)


@pytest.fixture
def geo(monkeypatch):
    from apps.security import location

    monkeypatch.setattr(location, "geo_detail", lambda ip: {"country": "SA", "country_name": "Saudi Arabia", "city": "Riyadh"}
                        if str(ip) == PUBLIC_IP else None)


# ================================================================== AT-493 (468) Active vs Signed In

def test_at493_active_vs_signed_in_by_threshold(family):
    from apps.security import active_sessions as AS

    dad = _signin("dad")
    _signin("mom", SAFARI_IOS, "10.0.0.6")
    _signin("son1", CHROME_WIN, "10.0.0.7")
    _age(_session_of(family["mom"]), 3)
    _age(_session_of(family["son1"]), 8)
    data = dad.get("/api/security/sessions").json()
    state = {r["user"]["username"]: r["state"] for r in data["sessions"]}
    assert state == {"dad": "active", "mom": "active", "son1": "signed_in"}
    assert data["counts"]["active"] == 2 and data["counts"]["signed_in"] == 3 and data["threshold_minutes"] == 5
    # the threshold is a setting with safe bounds
    config.set_value("security.session_active_minutes", 2)
    state = {r["user"]["username"]: r["state"] for r in dad.get("/api/security/sessions").json()["sessions"]}
    assert state["mom"] == "signed_in"
    from apps.core.registry import BY_KEY

    d = BY_KEY["security.session_active_minutes"]
    assert (d.default, d.min, d.max) == (5, 2, 120)
    with pytest.raises(Exception):
        config.set_value("security.session_active_minutes", 1)
    assert AS.touch_interval() == timedelta(minutes=1)  # bounded writes, never per request


def test_at493_background_refreshes_do_not_count_as_activity(family):
    son = _signin("son1")
    s = _session_of(family["son1"])
    _age(s, 10)
    son.get("/api/notifications", HTTP_X_PD_BACKGROUND="1")  # polling: keeps the session alive only
    s.refresh_from_db()
    assert timezone.now() - s.last_activity_at > timedelta(minutes=9)
    assert timezone.now() - s.last_seen_at < timedelta(minutes=1)
    son.get("/api/dashboard")  # a real request is activity
    s.refresh_from_db()
    assert timezone.now() - s.last_activity_at < timedelta(minutes=1)
    # a second request right after does not write again
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as q:
        son.get("/api/me/sessions")
    assert not any("UPDATE" in x["sql"] and "accounts_usersession" in x["sql"] for x in q.captured_queries)
    own = son.get("/api/me/sessions").json()
    assert own["sessions"][0]["state"] == "active" and own["active_minutes"] == 5


def test_at493_upgrade_backfills_activity_from_last_seen():
    import importlib

    mig = importlib.import_module("apps.accounts.migrations.0010_session_activity")
    src = Path(mig.__file__).read_text()
    assert 'update(last_activity_at=F("last_seen_at"))' in src


# ================================================================== AT-494 (469) Active Sessions tile

def test_at494_tile_counts_rows_and_view_all(family, geo):
    dad = _signin("dad")
    _signin("mom", SAFARI_IOS, "10.0.0.6")
    _signin("son1", CHROME_WIN, PUBLIC_IP)
    _age(_session_of(family["mom"]), 3)
    _age(_session_of(family["son1"]), 8)
    from apps.security.models import TrustedZone

    TrustedZone.objects.create(name="Home", cidrs=["10.0.0.0/24"])
    assert dad.get("/api/dashboard").json()["active_sessions_tile"] is True  # the tile loads its own data
    tile = dad.get("/api/security/sessions/summary").json()
    assert tile["counts"] == {"active": 2, "signed_in": 3, "idle": 1, "untrusted": 1, "high_risk": 0}
    assert tile["link"] == "/settings/security?view=sessions"
    rows = {r["user"]["name"]: r for r in tile["sessions"]}
    assert rows["Alex Sample"]["state_label"] == "Active" and rows["Alex Sample"]["current"] is True
    assert rows["Alex Sample"]["location"]["text"] == "Home" and rows["Alex Sample"]["trust"] == "Trusted"
    assert rows["Sam Sample"]["location"] == {"text": "Riyadh, Saudi Arabia", "source": "GeoIP (approximate)", "approximate": True,
                                              "zone": "", "country": "SA"}
    assert rows["Sam Sample"]["untrusted"] is True and rows["Sam Sample"]["state"] == "signed_in"
    assert "ip" not in tile["sessions"][0]  # the tile shows no addresses
    # normal members do not get the tile data; the summary endpoint is for administrators
    son = _signin("son2", CHROME_WIN, "10.0.0.9")
    assert "active_sessions_tile" not in son.get("/api/dashboard").json()
    assert son.get("/api/security/sessions/summary").status_code == 403


# ================================================================== AT-495 (470) dashboard integration

def test_at495_tile_in_layouts_groups_resize_and_per_user(family):
    from apps.core import overview
    from apps.core.registry import DEFAULT_WIDGETS, WIDGETS

    assert "sessions" in WIDGETS and "sessions" in DEFAULT_WIDGETS
    lim = overview.layout_limits()["sessions"]
    assert lim["cols_min"] <= 3 and lim["cols_max"] == 12 and lim["circle"] is False  # compact … large
    dad = client_for(_main(family))
    # an existing customised layout (saved before the tile existed) keeps every group; the tile goes to General
    known = [w for w in WIDGETS if w != "sessions"]
    layout = {"groups": [{"id": "general", "name": "General", "widgets": ["date", "security"]},
                         {"id": "g-money", "name": "Money", "widgets": ["recent"]}], "known": known}
    config.set_user(_main(family), "me.dashboard_groups", layout)
    eff = overview.effective_groups(_main(family))
    gen = next(g for g in eff["groups"] if g["id"] == "general")
    money = next(g for g in eff["groups"] if g["id"] == "g-money")
    assert gen["widgets"][:2] == ["date", "security"] and "sessions" in gen["widgets"] and money["widgets"] == ["recent"]
    # move it into another group and resize it (compact → large); it persists per person
    base = dad.get("/api/dashboard/layout").json()
    groups = [{**g, "widgets": [w for w in g["widgets"] if w != "sessions"]} for g in base["groups"]]
    groups.append({"id": "g-sec", "name": "Security", "collapsed": False, "widgets": ["sessions"]})
    for cols, h in ((3, 2), (6, 4), (12, 6)):
        r = dad.put("/api/dashboard/layout", {"groups": groups, "layout": {"sessions": {"cols": cols, "h": h}}}, format="json")
        assert r.status_code == 200, r.content
        saved = client_for(_main(family)).get("/api/dashboard/layout").json()  # relogin sees the same
        assert saved["layout"]["sessions"]["cols"] == cols and saved["layout"]["sessions"]["h"] == h
    assert next(g for g in saved["groups"] if g["name"] == "Security")["widgets"] == ["sessions"]
    # another administrator's layout is untouched
    mom = _scoped_admin(family)
    assert not any(g["name"] == "Security" for g in overview.effective_groups(mom)["groups"])


# ================================================================== AT-496 (471) location and trust

def test_at496_trusted_zone_first_then_private_then_approximate_geoip(family, geo):
    from apps.security.models import TrustedZone

    TrustedZone.objects.create(name="Home", cidrs=["10.0.0.0/24"], pin_lat=24.7, pin_lon=46.7)
    dad = _signin("dad")  # 10.0.0.5 → Home
    _signin("mom", SAFARI_IOS, "192.168.7.20")  # private, not a zone
    _signin("son1", CHROME_WIN, PUBLIC_IP)  # public → GeoIP, approximate
    _signin("son2", CHROME_WIN, "5.42.0.8")  # public, not in the GeoIP data
    rows = {r["user"]["username"]: r for r in dad.get("/api/security/sessions").json()["sessions"]}
    assert rows["dad"]["location"]["source"] == "Trusted Zone" and rows["dad"]["location"]["zone"] == "Home"
    assert rows["dad"]["trust"] == "Trusted" and rows["dad"]["location"]["approximate"] is False
    assert rows["mom"]["location"]["source"] == "Private network" and rows["mom"]["trust"] == "Private network"
    assert rows["son1"]["location"] == {"text": "Riyadh, Saudi Arabia", "source": "GeoIP (approximate)", "approximate": True,
                                        "zone": "", "country": "SA"}
    assert rows["son1"]["trust"] == "Untrusted"
    assert rows["son2"]["location"]["text"].startswith("Unknown location")
    # a zone covering a public address wins over GeoIP
    TrustedZone.objects.create(name="Office VPN", cidrs=[f"{PUBLIC_IP}/32"])
    rows = {r["user"]["username"]: r for r in dad.get("/api/security/sessions").json()["sessions"]}
    assert rows["son1"]["location"]["zone"] == "Office VPN" and rows["son1"]["trust"] == "Trusted"
    # no GPS: nothing in the API or the frontend asks the browser for a position
    for f in (ROOT / "frontend" / "src").rglob("*.tsx"):
        assert "geolocation" not in f.read_text(), f


def test_at496_listing_has_no_n_plus_one(family, geo):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    dad = _signin("dad")
    for i in range(3):
        _signin("son1", CHROME_WIN, f"10.0.1.{i + 2}")
    with CaptureQueriesContext(connection) as small:
        dad.get("/api/security/sessions")
    for i in range(12):
        _signin("son2", SAFARI_IOS, f"10.0.2.{i + 2}")
        _signin("son3", CHROME_WIN, PUBLIC_IP)
    with CaptureQueriesContext(connection) as big:
        r = dad.get("/api/security/sessions")
    assert len(r.json()["sessions"]) == 28
    assert len(big.captured_queries) <= len(small.captured_queries) + 2, [q["sql"][:80] for q in big.captured_queries]


# ================================================================== AT-497 (472) full Active Sessions page

def test_at497_full_listing_filters_details_and_permissions(family, geo):
    from apps.security.models import TrustedZone

    TrustedZone.objects.create(name="Home", cidrs=["10.0.0.0/24"])
    dad = _signin("dad")
    _signin("mom", SAFARI_IOS, "10.0.0.6")
    _signin("son1", CHROME_WIN, PUBLIC_IP)
    _age(_session_of(family["son1"]), 30)
    data = dad.get("/api/security/sessions").json()
    assert data["can_terminate"] is True and {u["name"] for u in data["users"]} >= {"Alex Sample", "Maria Sample", "Sam Sample"}
    r = next(x for x in data["sessions"] if x["user"]["username"] == "mom")
    assert r["ip"] == "10.0.0.6"  # the complete address for the main administrator
    assert r["device"]["browser"] == "Safari" and r["device"]["os"] == "iOS" and r["device"]["kind"] == "mobile"
    assert r["device"]["state"] == "recognized" and r["method"].startswith("password")
    assert r["login_at"] and r["last_activity_at"] and r["risk"] in ("normal", "low")
    blob = json.dumps(data).lower()
    for secret in ("sessionid", "csrftoken", "session_key", "token_hash", "pd_device"):
        assert secret not in blob
    # filters
    q = lambda **f: [x["user"]["username"] for x in dad.get("/api/security/sessions", f).json()["sessions"]]  # noqa: E731
    assert q(state="signed_in") == ["son1"]
    assert sorted(q(state="active")) == ["dad", "mom"]
    assert q(user=family["mom"].pk) == ["mom"]
    assert q(trust="untrusted") == ["son1"]
    assert q(device="mobile") == ["mom"]
    assert q(location="riyadh") == ["son1"] and sorted(q(location="home")) == ["dad", "mom"]
    assert q(risk="high") == []
    # details
    sid = next(x["id"] for x in data["sessions"] if x["user"]["username"] == "son1")
    det = dad.get(f"/api/security/sessions/{sid}").json()
    assert det["can_terminate"] is True and det["age_seconds"] >= 0 and det["idle_seconds"] >= 29 * 60
    assert det["location"]["approximate"] is True
    # a scoped administrator sees only the delegated members; normal members nothing here (their own in My account)
    from apps.accounts.models import Delegation, FamilyGroup, GroupMembership

    mom = _scoped_admin(family)
    scoped = _signin("mom", CHROME_WIN, "10.0.0.8")
    own_only = {x["user"]["username"] for x in scoped.get("/api/security/sessions").json()["sessions"]}
    assert own_only == {"mom"}
    grp = FamilyGroup.objects.create(name="Delegated test group")
    GroupMembership.objects.create(group=grp, user=family["son1"])
    Delegation.objects.create(delegate=mom, group=grp, scopes=["membership"], granted_by=_main(family))
    seen = {x["user"]["username"] for x in scoped.get("/api/security/sessions").json()["sessions"]}
    assert seen == {"mom", "son1"}
    assert scoped.get("/api/security/sessions").json()["can_terminate"] is False
    assert scoped.post(f"/api/security/sessions/{sid}/terminate", {"confirm": True}, format="json").status_code == 403
    son = _signin("son2", CHROME_WIN, "10.0.0.9")
    assert son.get("/api/security/sessions").status_code == 403
    assert son.get(f"/api/security/sessions/{sid}").status_code == 403


# ================================================================== AT-498 (473) Terminate Session

def test_at498_terminate_invalidates_only_that_session(family):
    dad = _signin("dad")
    laptop = _signin("son1", CHROME_WIN, "10.0.0.5")
    phone = _signin("son1", SAFARI_IOS, "10.0.0.6")
    other = _signin("mom", CHROME_WIN, "10.0.0.7")
    target = _session_of(family["son1"], SAFARI_IOS)
    device = target.recognized_device
    # explicit confirmation
    r = dad.post(f"/api/security/sessions/{target.id}/terminate", {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "confirm_required"
    own = _session_of(family["dad"])
    assert dad.post(f"/api/security/sessions/{own.id}/terminate", {"confirm": True}, format="json").status_code == 400
    r = dad.post(f"/api/security/sessions/{target.id}/terminate", {"confirm": True}, format="json")
    assert r.status_code == 200
    # server-side invalidation: the phone's very next request is refused, even with its cookie
    assert phone.get("/api/dashboard").status_code in (401, 403)
    assert phone.get("/api/me/sessions").status_code in (401, 403)
    # unrelated sessions keep working, including the same person's laptop
    assert laptop.get("/api/dashboard").status_code == 200
    assert other.get("/api/dashboard").status_code == 200
    assert dad.get("/api/dashboard").status_code == 200
    # not Mark Unrecognized: the device stays recognised
    device.refresh_from_db()
    assert device.revoked_at is None and device.status != "unrecognized"
    # audit and notification
    ev = AuditEvent.objects.filter(action="security.session_terminated").first()
    assert ev is not None and ev.target_id == str(target.id)
    n = Notification.objects.filter(user=family["son1"], event="security.session_terminated").first()
    assert n is not None and "ended" in n.title.lower()
    # a second attempt: already ended
    assert dad.post(f"/api/security/sessions/{target.id}/terminate", {"confirm": True}, format="json").status_code == 404
    # only the main administrator may terminate
    _scoped_admin(family)
    scoped = _signin("mom", CHROME_WIN, "10.0.0.8")
    lap = _session_of(family["son1"], CHROME_WIN)
    assert scoped.post(f"/api/security/sessions/{lap.id}/terminate", {"confirm": True}, format="json").status_code == 403


def test_high_risk_session_notifies_main_admin_once(family):
    from apps.notify.management.commands.scheduler import tick

    _signin("dad")
    _signin("son1", SAFARI_IOS, "10.0.0.6")
    s = _session_of(family["son1"])
    # (Mark Unrecognized also ends the sessions; a session still valid on an unrecognised device is high risk)
    s.recognized_device.revoked_at = timezone.now()
    s.recognized_device.save(update_fields=["revoked_at"])
    tick()
    tick()
    assert Notification.objects.filter(user=family["dad"], event="security.session_high_risk").count() == 1


# ================================================================== AT-499 (474) guides and help

REQUIRED_HELP = ["maint.check_updates", "maint.upgrade", "maint.job", "maint.doctor", "maint.repair", "maint.health",
                 *[f"maint.health.{k}" for k in ("database", "ocr", "ai", "security", "backup", "storage")],
                 "maint.restart", "maint.caches", "maint.system_info", "maint.history", "maint.technical", "maint.full_log",
                 "maint.support_report", "maint.retry", "maint.rollback", "maint.recovery_required", "sessions.page",
                 "sessions.active", "sessions.signed_in", "sessions.trusted_zone", "sessions.approximate", "sessions.risk",
                 "sessions.terminate"]


def test_at499_guides_help_and_tooltips_are_complete_and_permission_aware(family):
    docs = ROOT / "docs"
    reg = (ROOT / "frontend" / "src" / "components" / "helpRegistry.ts").read_text()
    for hid in REQUIRED_HELP:
        m = re.search(rf'"{re.escape(hid)}": \{{ text: "([^"]+)", link: "(/help/[a-z-]+#[a-z-]+)", audience: "([a-z_]+)"', reg)
        assert m, f"help entry {hid} missing or without a Learn More link"
    # high-risk entries are only for the main administrator; Active/Signed In explanations are for everyone
    for hid in ("maint.upgrade", "maint.repair", "maint.restart", "maint.rollback", "sessions.terminate", "maint.full_log"):
        assert re.search(rf'"{re.escape(hid)}":.*audience: "main_admin"', reg), hid
    for hid in ("sessions.active", "sessions.signed_in", "sessions.approximate"):
        assert re.search(rf'"{re.escape(hid)}":.*audience: "all"', reg), hid
    guides = {p.stem: p.read_text() for p in (docs / "guides").glob("*.md")}
    assert guides["maintenance"].startswith("<!-- audience: admin -->") and guides["active-sessions"].startswith("<!-- audience: admin -->")
    need = {
        "maintenance": ["{#check-for-updates}", "{#update-application}", "{#upgrade-failure}", "{#technical-details}", "{#full-log}",
                        "{#support-report}", "{#doctor}", "{#repair}", "{#health-panels}", "{#restart}", "{#safe-caches}",
                        "{#system-information}", "{#job-history}", "{#rollback}", "{#recovery-required}", "{#permissions}"],
        "active-sessions": ["{#active-threshold}", "{#location-and-trust}", "{#risk}", "{#terminate-session}", "{#tile}", "{#visibility}"],
        "upgrades": ["{#webgui-upgrade}", "{#webgui-unavailable}", "{#change-set-ab}"],
        "troubleshooting": ["{#maintenance}", "{#maintenance-recovery}"],
        "backup-restore": ["{#pre-upgrade-backup}"],
        "security-center": ["{#maintenance-security}"],
    }
    for g, anchors in need.items():
        for a in anchors:
            assert a in guides[g], (g, a)
    user = (docs / "USER_GUIDE.md").read_text()
    sessions_part = user[user.index("{#sessions}"):user.index("{#recovery}")]
    assert "Active" in sessions_part and "Signed In" in sessions_part and "GPS" in sessions_part
    assert "Repair" not in sessions_part and "Rollback" not in sessions_part  # no Main Admin procedures in the User Guide
    assert "{#maintenance}" in (docs / "ADMIN_GUIDE.md").read_text()
    # troubleshooting covers the required topics
    t = guides["troubleshooting"]
    for topic in ("Database migrations", "Frontend build", "Restart", "Partially Failed", "pre-upgrade backup", "Rollback",
                  "Reconnecting", "stays **Running**", "OCR or AI health", "still shows **Active**", "Unknown location", "Trusted Zone"):
        assert topic in t, topic
    # Help: both guides are listed in their categories and hidden from family members
    from apps.core.views import HELP_CATEGORIES

    cats = dict(HELP_CATEGORIES)
    assert "maintenance" in cats["Installation & operations"] and "active-sessions" in cats["Security & sign-in"]
    son = client_for(family["son1"])
    assert son.get("/api/help/maintenance").status_code == 404 and son.get("/api/help/active-sessions").status_code == 404
    slugs = {g["slug"] for g in client_for(_main(family)).get("/api/help").json()["guides"]}
    assert {"maintenance", "active-sessions"} <= slugs
    # the docs checker (links, anchors, help links, screenshots) passes
    r = subprocess.run([".venv/bin/python" if (ROOT / ".venv").exists() else "python3", "scripts/check_docs.py"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


# ================================================================== AT-500 (475) release gate

def test_at500_release_gate_records_every_test_honestly():
    docs = ROOT / "docs"
    report = (docs / "TEST_REPORT.md").read_text()
    trace = (docs / "TRACEABILITY.md").read_text()
    start = report.index("## Change set AB")
    section = report[start:report.index("\n## ", start + 5)]
    for n in range(481, 501):
        assert f"AT-{n}" in section and f"AT-{n}" in trace, n
    for line in section.splitlines():
        if "Not Executed" in line or "Blocked" in line or "BLOCKED" in line:
            assert "| Passed" not in line and "PASS |" not in line, line  # an unexecuted test is never reported as passed
    assert "AT-488" in section and "BLOCKED" in section[section.index("AT-488"):section.index("AT-488") + 600]


def test_at495_upgrade_adds_the_tile_without_touching_custom_selections(family):
    """The data migration: administrators with an explicit widget list get the tile appended; members do not."""
    import importlib

    from django.apps import apps as django_apps

    from apps.core.models import UserSetting

    UserSetting.objects.update_or_create(user=_main(family), key="me.dashboard_widgets", defaults={"value": ["recent", "date"]})
    UserSetting.objects.update_or_create(user=family["son1"], key="me.dashboard_widgets", defaults={"value": ["recent"]})
    mig = importlib.import_module("apps.core.migrations.0009_active_sessions_tile")
    mig.add_tile(django_apps, None)
    mig.add_tile(django_apps, None)  # idempotent
    assert UserSetting.objects.get(user=_main(family), key="me.dashboard_widgets").value == ["recent", "date", "sessions"]
    assert UserSetting.objects.get(user=family["son1"], key="me.dashboard_widgets").value == ["recent"]
