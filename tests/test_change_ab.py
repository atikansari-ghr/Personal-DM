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
    assert n is not None and f"job={job_id}" in n.link and "df: checking" not in json.dumps([n.body, n.summary, n.data])


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
         "bot": "123456789:AA" + "c" * 33, "pem": "-----BEGIN PRIVATE KEY-----\nMIIEvQ\n-----END PRIVATE KEY-----"}


def test_at484_sanitizer_patterns_and_known_values(db):
    text = (f"password={SYNTH['smtp']} Authorization: Bearer abcdefghijkl {SYNTH['token']} {SYNTH['sk']} {SYNTH['bot']}\n"
            f"postgres://pd:dbpass123@localhost/x Cookie: sessionid=abc123; pd_csrftoken=zzz\n{SYNTH['pem']}\n"
            "api_key: 'k-123456' NAS_PASSWORD=nas-secret-1 recovery_key=word-word-word "
            "https://discord.com/api/webhooks/123/abcDEF AKIAABCDEFGHIJKLMNOP")
    out = sanitize.redact(text, secrets=[SYNTH["smtp"]])
    for s in (SYNTH["smtp"], SYNTH["token"], SYNTH["sk"], SYNTH["bot"], "dbpass123", "abc123", "zzz", "MIIEvQ", "k-123456",
              "nas-secret-1", "word-word-word", "abcDEF", "AKIAABCDEFGHIJKLMNOP", "abcdefghijkl"):
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
