from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.urls import path, re_path

from apps.accounts import google
from apps.accounts import views as acc
from apps.core import views as core
from apps.library import export, views as lib, views_import as imp, views_share as share
from apps.mailimport import views as mail
from apps.notify import views as notify
from apps.ops import views as ops
from apps.security import views as sec


def spa(request, *args, **kwargs):
    """Serve the built single-page app for any non-API route."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse("Frontend not built. Run `npm run build` in frontend/.", status=503, content_type="text/plain")
    resp = FileResponse(open(index, "rb"), content_type="text/html")
    resp["Cache-Control"] = "no-cache"
    return resp


def service_worker(request):
    sw = settings.FRONTEND_DIST / "sw.js"
    if not sw.exists():
        raise Http404
    resp = FileResponse(open(sw, "rb"), content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    resp["Service-Worker-Allowed"] = "/"
    return resp


api = [
    # session & auth
    path("session", acc.session_state),
    path("auth/login", acc.login_view),
    path("auth/totp", acc.totp_verify),
    path("auth/logout", acc.logout_view),
    path("auth/password/change", acc.change_password),
    path("auth/password/forgot", acc.forgot_password),
    path("auth/password/reset", acc.reset_password),
    path("auth/reauth", acc.reauth),
    path("auth/google/start", google.start),
    path("auth/google/callback", google.callback),
    path("auth/google/diagnostics", google.diagnostics),
    # setup
    path("setup/verify", acc.setup_verify),
    path("setup/complete", acc.setup_complete),
    # my account
    path("me", acc.me),
    path("me/totp/setup", acc.totp_setup),
    path("me/totp/enable", acc.totp_enable),
    path("me/totp/disable", acc.totp_disable),
    path("me/recovery-codes", acc.recovery_codes),
    path("me/sessions", acc.my_sessions),
    path("me/photo", acc.my_photo),
    path("users/<uuid:pk>/photo", acc.user_photo),
    path("me/sessions/revoke", acc.sign_out_everywhere),
    path("me/sessions/<uuid:pk>", acc.revoke_session),
    path("me/google", google.my_link),
    path("me/channels", notify.my_channels),
    path("me/telegram", notify.telegram_link),
    path("me/telegram/check", notify.telegram_check),
    path("me/email-accounts", mail.accounts),
    path("me/email-accounts/<int:pk>", mail.account_detail),
    path("me/email-accounts/<int:pk>/test", mail.account_test),
    path("me/email-accounts/<int:pk>/poll", mail.account_poll),
    path("me/email-accounts/<int:pk>/rules", mail.rules),
    path("me/email-accounts/<int:pk>/rules/<int:rid>", mail.rule_delete),
    # family
    path("family/members", acc.members),
    path("family/members/<uuid:pk>", acc.member_detail),
    path("family/members/<uuid:pk>/reset-password", acc.member_reset_password),
    path("family/members/<uuid:pk>/reset-totp", acc.member_reset_totp),
    path("family/members/<uuid:pk>/photo", acc.member_photo),
    path("family/groups", acc.groups),
    path("family/groups/<uuid:pk>", acc.group_detail),
    path("family/delegations", acc.delegation),
    # library
    path("dashboard", lib.dashboard),
    path("folders", lib.folders),
    path("folders/<uuid:pk>", lib.folder_detail),
    path("folders/<uuid:pk>/archive", lib.folder_archive),
    path("folders/<uuid:pk>/restore", lib.folder_restore),
    path("folders/<uuid:pk>/apply-template", lib.folder_apply_template),
    path("folders/<uuid:pk>/permissions", lib.folder_permissions),
    path("documents", lib.documents),
    path("documents/bulk", lib.documents_bulk),
    path("documents/<uuid:pk>", lib.document_view),
    path("documents/<uuid:pk>/versions", lib.document_versions),
    path("documents/<uuid:pk>/versions/<uuid:vid>/current", lib.document_set_version),
    path("documents/<uuid:pk>/renew", lib.document_renew),
    path("documents/<uuid:pk>/fields", lib.document_fields),
    path("documents/<uuid:pk>/fields/<str:key>/reveal", lib.field_reveal),
    path("documents/<uuid:pk>/archive", lib.document_archive),
    path("documents/<uuid:pk>/restore", lib.document_restore),
    path("documents/<uuid:pk>/reprocess", lib.document_reprocess),
    path("documents/<uuid:pk>/permissions", lib.document_permissions),
    path("documents/<uuid:pk>/file", lib.document_file),
    path("documents/<uuid:pk>/preview", lib.document_preview),
    path("documents/<uuid:pk>/thumbnail", lib.document_thumbnail),
    path("documents/<uuid:pk>/text", lib.document_text),
    path("documents/<uuid:pk>/similar", lib.document_similar),
    path("documents/<uuid:pk>/shares", share.document_shares),
    path("shares/<uuid:sid>", share.share_revoke),
    path("search/autocomplete", lib.autocomplete),
    path("views", lib.saved_views),
    path("views/<int:pk>", lib.saved_view_detail),
    path("metadata", lib.metadata),
    path("metadata/<str:kind>/<str:pk>", lib.metadata_delete),
    path("imports", imp.import_sessions),
    path("imports/<uuid:pk>", imp.import_detail),
    path("imports/<uuid:pk>/start", imp.import_start),
    path("imports/<uuid:pk>/retry", imp.import_retry),
    path("imports/<uuid:pk>/items", imp.import_upload_item),
    path("imports/<uuid:pk>/pending", imp.import_pending),
    path("imports/<uuid:pk>/report", imp.import_report),
    path("export/plan", export.export_plan),
    path("export/download", export.export_download),
    path("offline/validate", export.offline_validate),
    path("offline/audit", export.offline_audit),
    # notifications
    path("notifications", notify.notifications),
    path("notifications/read", notify.mark_read),
    path("notifications/test", notify.test_channel),
    path("notifications/deliveries", notify.delivery_history),
    path("notifications/preview", notify.template_preview),
    path("notifications/run", notify.run_reminders_now),
    # settings, admin, ops
    path("settings", core.settings_api),
    path("audit", core.audit_log),
    path("jobs", core.jobs_api),
    path("jobs/<uuid:pk>/retry", core.job_retry),
    path("health", core.health),
    path("admin/health", core.admin_health),
    path("admin/email-connectors", mail.admin_connectors),
    path("backup", ops.backup_status),
    path("backup/run", ops.backup_now),
    path("backup/nas", ops.nas_api),
    path("integrity", ops.integrity_api),
    path("admin/security/logins", sec.logins),
    path("admin/security/policy", sec.access_policy),
    path("admin/security/policy/rollback", sec.access_policy_rollback),
    path("admin/security/policy/test", sec.access_policy_test),
    path("admin/security/temporary", sec.temporary_access),
    path("admin/security/temporary/<int:pk>", sec.temporary_access_detail),
    path("admin/security/ip-rules", sec.ip_rules),
    path("admin/security/ip-rules/<int:pk>", sec.ip_rule_detail),
    path("admin/security/geoip", sec.geoip_api),
    path("admin/security/geoip/upload", sec.geoip_upload),
    path("admin/security/traffic", sec.traffic_api),
    path("admin/security/traffic/report.html", sec.traffic_html),
    path("help", core.help_index),
    path("help/<str:slug>", core.help_guide),
]

urlpatterns = [path(f"api/{p.pattern}", p.callback) for p in api] + [
    path("s/<str:token>", share.public_share),
    path("s/<str:token>/file", share.public_share_file),
    path("sw.js", service_worker),
    re_path(r"^api/.*$", lambda r: HttpResponse('{"error": "Not found"}', status=404, content_type="application/json")),
    re_path(r"^(?!static/).*$", spa),
]
