"""One structured notification, rendered for every channel (Change Set O).

    Message(event, severity, category, icon, title, heading, summary, details, actions, guidance, …)
        ├── render_in_app()   -> card stored with the in-app notification (icons, details, actions)
        ├── render_email()    -> subject, plain text (the earlier layout) and responsive HTML (no JavaScript)
        ├── render_telegram() -> HTML-formatted text with emoji and inline URL buttons
        └── render_push()     -> short title/body for lock screens (privacy level per person)

Security rules (the rendering is a security boundary):
* every user-controlled value is escaped for the channel (HTML entities for email and Telegram HTML);
* actions are application paths only (``/documents/<id>`` …). They open the app, where sign-in and the normal
  permission checks apply; a link never grants access by itself and never carries a token;
* there is no "release from quarantine" action outside the authenticated app;
* names are masked or hidden outside the app (``notifications.include_names``), long digit runs are masked, document
  numbers are left out unless the administrator allows a masked number in email/Telegram — never in push;
* no attachments, no OCR text, no tracking pixels or external images.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from django.conf import settings
from django.utils import timezone

from apps.core import config

from . import icons, templates
from .event_defs import EVENTS

PLACEHOLDERS = {
    "app_name": "Application name", "recipient_name": "Recipient's display name", "event_title": "Event title",
    "document_name": "Document name", "document_type": "Document type", "owner_name": "Document owner",
    "expiry_date": "Expiry date", "days_remaining": "Days remaining", "folder_path": "Folder path",
    "event_time": "Date and time of the event", "device": "Device / browser", "location": "Approximate location",
    "ip_address": "IP address", "security_status": "Security status", "count": "Number of items",
}
NAME_PLACEHOLDERS = {"document_name", "folder_path"}  # masked / hidden outside the app like other names
_PH = re.compile(r"\{([a-z_]+)\}")
_SAFE_PATH = re.compile(r"^/(?!/)[A-Za-z0-9/_\-?=&.%:]*$")
SEVERITY_RANK = {"info": 0, "success": 0, "warning": 1, "critical": 2}


@dataclass
class Detail:
    label: str
    value: Any
    icon: str = "info"
    sensitive: bool = False  # document number: masked, opt-in for email/Telegram, never in push
    emphasis: bool = False   # shown in the severity colour (expiry date, days left)


@dataclass
class Action:
    key: str
    label: str
    path: str = ""
    primary: bool = False
    in_app_only: bool = False  # needs a click inside the signed-in app (e.g. Snooze)


@dataclass
class Message:
    event: str
    title: Any  # str or ``lambda name: …`` (names masked outside the app)
    severity: str = ""
    category: str = ""
    icon: str = ""
    heading: Any = ""
    summary: Any = ""
    details: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    guidance: list = field(default_factory=list)
    items: list = field(default_factory=list)
    items_label: str = "Files"
    more: int = 0
    link: str = ""
    context: dict = field(default_factory=dict)
    when: Any = None
    test: bool = False
    draft: Any = None  # unsaved template override (administrator preview)
    push_title: str = ""  # lock-screen title without names (default: the event's label)

    def __post_init__(self):
        ev = EVENTS.get(self.event)
        self.category = self.category or (ev.category if ev else "system")
        self.icon = self.icon or (ev.icon if ev else "info")
        self.severity = self.severity if self.severity in icons.SEVERITY else (ev.severity if ev else "info")
        self.when = self.when or timezone.now()
        self.actions = [a for a in self.actions if a and (a.in_app_only or safe_path(a.path))]
        if self.link and not safe_path(self.link):
            self.link = ""


def safe_path(path: str) -> bool:
    """Application paths only; quarantine release never leaves the authenticated app."""
    return bool(path) and bool(_SAFE_PATH.match(path)) and "/api/" not in path and "release" not in path.lower()


def floor_severity(event: str, severity: str) -> str:
    """Critical events are never presented below Warning, whatever a template says."""
    from .catalog import is_critical

    if event in EVENTS and is_critical(event) and SEVERITY_RANK.get(severity, 0) < 1:
        return "warning"
    return severity


# ------------------------------------------------------------------ templates (administrator overrides)

class TemplateError(ValueError):
    pass


def check_template_text(value: str, *, field_name: str, limit: int = 200) -> str:
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or "")).strip()
    if len(value) > limit:
        raise TemplateError(f"{field_name} is longer than {limit} characters.")
    unknown = [p for p in _PH.findall(value) if p not in PLACEHOLDERS]
    if unknown:
        raise TemplateError(f"{field_name}: unknown placeholder {{{unknown[0]}}}. Allowed: "
                            + ", ".join(f"{{{p}}}" for p in PLACEHOLDERS) + ".")
    stripped = _PH.sub("", value)
    if "{" in stripped or "}" in stripped:
        raise TemplateError(f"{field_name}: use only {{placeholder}} names; other braces are not allowed.")
    return value


def fill(text_value: str, context: dict, external: bool) -> str:
    def repl(m):
        key = m.group(1)
        val = str(context.get(key, "") or "")
        if external and key in NAME_PLACEHOLDERS:
            val = templates.name(val)
        return val
    return _PH.sub(repl, text_value)


def _override(event: str, channel: str):
    from .models import NotificationTemplate

    rows = {t.channel: t for t in NotificationTemplate.objects.filter(event=event, channel__in=["", channel])}
    return rows.get(channel) or rows.get("")


def apply_template(msg: Message, channel: str, external: bool) -> dict:
    """Title / heading / summary / icon / severity / action labels after the administrator's overrides."""
    ctx = {"app_name": config.get("general.app_name"), "event_time": templates.local_stamp(msg.when), **msg.context}
    out = {"title": templates.text(msg.title, external), "heading": templates.text(msg.heading, external),
           "summary": templates.text(msg.summary, external), "icon": msg.icon, "severity": msg.severity, "labels": {}}
    t = msg.draft if msg.draft is not None else (_override(msg.event, channel) if msg.event in EVENTS else None)
    if t is not None:
        ctx["event_title"] = out["title"]
        for f in ("title", "heading", "summary"):
            if getattr(t, f):
                out[f] = fill(getattr(t, f), ctx, external)
        if t.icon in icons.ICONS:
            out["icon"] = t.icon
        if t.severity in icons.SEVERITY:
            out["severity"] = t.severity
        out["labels"] = {k: str(v)[:40] for k, v in (t.action_labels or {}).items() if v}
    out["severity"] = floor_severity(msg.event, out["severity"])
    return out


# ------------------------------------------------------------------ helpers

def _value(d: Detail, channel: str) -> str | None:
    external = channel != "in_app"
    v = d.value
    if v in (None, ""):
        return None
    if d.sensitive:  # off unless the administrator allows a masked number; never on lock screens
        if channel == "push" or not config.get("notifications.include_document_number"):
            return None
        s = str(v)
        return "•" * max(0, len(s) - 4) + s[-4:] if len(s) > 4 else "••••"
    if external and isinstance(v, templates.Name):
        return templates.name(v)
    return templates.mask_numbers(str(v)) if external else str(v)


def _details(msg: Message, channel: str) -> list[tuple[Detail, str]]:
    out = []
    for d in msg.details:
        v = _value(d, channel)
        if v is not None:
            out.append((d, v))
    return out


def _actions(msg: Message, channel: str, labels: dict) -> list[Action]:
    acts = [a for a in msg.actions if channel == "in_app" or not a.in_app_only]
    if msg.link and not any(a.primary for a in acts):
        acts.insert(0, Action("open", "Open", msg.link, primary=True))
    return [Action(a.key, labels.get(a.key, a.label), a.path, a.primary, a.in_app_only) for a in acts][:5]


def _url(path: str) -> str:
    return f"{settings.PUBLIC_ORIGIN}{path}"


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


# ------------------------------------------------------------------ in-app

def render_in_app(msg: Message) -> dict:
    t = apply_template(msg, "in_app", external=False)
    return {
        "title": t["title"][:200], "summary": t["summary"] or t["heading"], "heading": t["heading"],
        "severity": t["severity"], "category": msg.category, "icon": icons.svg(t["icon"]), "icon_key": t["icon"],
        "icon_label": icons.label(t["icon"]),
        "details": [{"label": d.label, "value": v, "icon": icons.svg(d.icon), "emphasis": d.emphasis}
                    for d, v in _details(msg, "in_app")],
        "actions": [{"key": a.key, "label": a.label, "path": a.path, "primary": a.primary, "in_app": a.in_app_only}
                    for a in _actions(msg, "in_app", t["labels"])],
        "guidance": [templates.text(g, False) for g in msg.guidance],
        "items": [str(i) for i in msg.items[:templates.MAX_ITEMS]], "items_label": msg.items_label,
        "more": msg.more + max(0, len(msg.items) - templates.MAX_ITEMS), "test": msg.test,
    }


# ------------------------------------------------------------------ email

def render_email(msg: Message, user) -> tuple[str, str, str]:
    """(subject, plain text, html). The plain text keeps the earlier one-layout format."""
    t = apply_template(msg, "email", external=True)
    sev_emoji, sev_label, fg, bg, border = icons.SEVERITY[t["severity"]]
    app = config.get("general.app_name")
    subject = templates.subject(("[TEST] " if msg.test else "") + t["title"])
    details = _details(msg, "email")
    actions = _actions(msg, "email", t["labels"])
    lines = [x for x in (t["heading"], t["summary"]) if x] + [templates.text(g, True) for g in msg.guidance]
    text = templates.render(user=user, title=("[TEST] " if msg.test else "") + f"{sev_label.upper()}: {t['title']}",
                            lines=lines, facts=[(d.label, v) for d, v in details], items=msg.items,
                            items_label=msg.items_label, more=msg.more, link=msg.link)
    extra = [a for a in actions if a.path and a.path != msg.link]
    if extra:
        text += "\n" + "\n".join(f"{a.label}: {_url(a.path)}" for a in extra)
    text += f"\n\nThis is an automated notification from {app}. Please do not reply."

    rows = "".join(
        f'<tr><td style="padding:6px 10px 6px 0;color:#5b6b62;font-size:14px;white-space:nowrap;vertical-align:top">'
        f'{icons.emoji(d.icon)}&nbsp;{_e(d.label)}</td>'
        f'<td dir="auto" style="padding:6px 0;font-size:14px;color:{fg if d.emphasis else "#1b2a21"};'
        f'font-weight:{700 if d.emphasis else 400};word-break:break-word">{_e(v)}</td></tr>' for d, v in details)
    items = ""
    if msg.items:
        shown = [templates.name(str(n)) for n in msg.items[:templates.MAX_ITEMS]]
        extra_n = msg.more + max(0, len(msg.items) - templates.MAX_ITEMS)
        items = (f'<p style="margin:14px 0 4px;font-weight:700;font-size:14px">{_e(msg.items_label)}</p><ol style="margin:0;padding-left:20px;font-size:14px">'
                 + "".join(f'<li dir="auto">{_e(n)}</li>' for n in shown) + "</ol>"
                 + (f'<p style="font-size:13px;color:#5b6b62">… and {extra_n} more (see the report)</p>' if extra_n else ""))
    buttons = "".join(
        f'<a href="{_e(_url(a.path))}" style="display:inline-block;margin:4px 6px 4px 0;padding:11px 18px;border-radius:8px;'
        f'font-size:15px;font-weight:700;text-decoration:none;'
        + ("background:#1e6b3a;color:#ffffff;border:1px solid #1e6b3a" if a.primary else "background:#ffffff;color:#1e6b3a;border:1px solid #9cc5ab")
        + f'">{_e(a.label)}</a>' for a in actions if a.path)
    guidance = "".join(f'<li dir="auto">{_e(templates.text(g, True))}</li>' for g in msg.guidance)
    test_banner = ('<tr><td style="background:#5b2d91;color:#fff;padding:8px 24px;font-size:13px;font-weight:700">'
                   'TEST — sample notification, no real event happened</td></tr>' if msg.test else "")
    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>{_e(t['title'])}</title></head>
<body style="margin:0;padding:0;background:#f2f5f3;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1b2a21">
<span style="display:none;max-height:0;overflow:hidden">{_e(t['summary'] or t['heading'])}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f5f3"><tr><td align="center" style="padding:16px 8px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;border:1px solid #dbe5df">
{test_banner}
<tr><td style="padding:18px 24px;border-bottom:1px solid #e3ebe6">
  <table role="presentation" width="100%"><tr>
    <td style="font-size:17px;font-weight:700;color:#1e6b3a">🔒 {_e(app)}</td>
    <td align="right"><span style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:{fg};border:1px solid {border};font-size:12px;font-weight:700">{sev_emoji} {_e(sev_label)} · {_e(icons.CATEGORY_LABELS.get(msg.category, msg.category))}</span></td>
  </tr></table>
</td></tr>
<tr><td style="padding:22px 24px 6px;background:{bg}">
  <div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{fg};font-weight:700">{icons.emoji(t['icon'])} {_e(t['title'])}</div>
  <h1 dir="auto" style="margin:8px 0 6px;font-size:22px;line-height:1.3;color:#1b2a21">{_e(t['heading'] or t['title'])}</h1>
  <p dir="auto" style="margin:0 0 16px;font-size:15px;line-height:1.5;color:#33443a">{_e(t['summary'])}</p>
</td></tr>
<tr><td style="padding:16px 24px">
  {f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">{rows}</table>' if rows else ''}
  {items}
  {f'<div style="margin:18px 0 6px">{buttons}</div>' if buttons else ''}
  {f'<ul style="margin:14px 0 0;padding:12px 12px 12px 30px;background:#fff8e6;border-radius:8px;font-size:14px;line-height:1.5">{guidance}</ul>' if guidance else ''}
</td></tr>
<tr><td style="padding:14px 24px 20px;border-top:1px solid #e3ebe6;font-size:12px;line-height:1.5;color:#5b6b62">
  Sent {_e(templates.local_stamp(msg.when))} to {_e(user.display_name or user.username)}. Links open {_e(app)}; you sign in and your normal permissions apply.<br>
  This is an automated notification. Please do not reply.
</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html_doc


# ------------------------------------------------------------------ Telegram

def render_telegram(msg: Message, user) -> dict:
    """Telegram Bot API ``sendMessage`` fields (parse_mode HTML). Buttons need an https address; otherwise the
    links are written into the text."""
    t = apply_template(msg, "telegram", external=True)
    sev_emoji, sev_label, *_ = icons.SEVERITY[t["severity"]]
    out = []
    if msg.test:
        out.append("🧪 <b>TEST</b> — sample notification, no real event happened")
    out.append(f"{icons.emoji(t['icon'])} <b>{_e(t['title'])}</b>")
    out.append(f"<i>{sev_emoji} {_e(sev_label)} · {_e(icons.CATEGORY_LABELS.get(msg.category, msg.category))}</i>")
    if t["heading"]:
        out += ["", f"<b>{_e(t['heading'])}</b>"]
    if t["summary"]:
        out.append(_e(t["summary"]))
    details = _details(msg, "telegram")
    if details:
        out.append("")
        out += [f"{icons.emoji(d.icon)} {_e(d.label)}: " + (f"<b>{_e(v)}</b>" if d.emphasis else _e(v)) for d, v in details]
    if msg.items:
        out += ["", f"<b>{_e(msg.items_label)}</b>"]
        out += [f"{i}. {_e(templates.name(str(n)))}" for i, n in enumerate(msg.items[:templates.MAX_ITEMS], 1)]
        extra_n = msg.more + max(0, len(msg.items) - templates.MAX_ITEMS)
        if extra_n:
            out.append(f"… and {extra_n} more (see the report)")
    for g in msg.guidance:
        out.append(f"💡 {_e(templates.text(g, True))}")
    out += ["", f"⏱️ {_e(templates.local_stamp(msg.when))}"]
    actions = [a for a in _actions(msg, "telegram", t["labels"]) if a.path]
    payload: dict = {"parse_mode": "HTML", "disable_web_page_preview": True}
    if actions and settings.PUBLIC_ORIGIN.startswith("https://"):
        rows, row = [], []
        for a in actions:
            row.append({"text": a.label, "url": _url(a.path)})
            if len(row) == 2 or a.primary:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        payload["reply_markup"] = {"inline_keyboard": rows}
    elif actions:
        out.append("")
        out += [f'🔗 <a href="{_e(_url(a.path))}">{_e(a.label)}</a>' for a in actions]
    payload["text"] = "\n".join(out)[:4000]
    return payload


# ------------------------------------------------------------------ Web Push

def render_push(msg: Message, user) -> dict:
    """Lock-screen safe: never numbers or document text; names only with the person's "Detailed" choice."""
    t = apply_template(msg, "push", external=True)
    level = config.get_user(user, "me.push_preview") or "standard"
    if level == "minimal":
        title, body = config.get("general.app_name"), "You have a new notification. Open the app to read it."
    else:
        base = t["title"] if level == "detailed" else (msg.push_title or (EVENTS[msg.event].label if msg.event in EVENTS else t["title"]))
        title = f"{icons.emoji(t['icon'])} {base}"
        body = t["summary"] or t["heading"]
        if level != "detailed":
            body = re.sub(r"[“\"].*?[”\"]", "a document", body)  # names in quotes are left out
        body = templates.mask_numbers(body)
    if msg.test:
        title = f"TEST · {title}"
    actions = _actions(msg, "push", t["labels"])
    target = next((a.path for a in actions if a.primary), msg.link) or "/notifications"
    return {"title": title[:120], "body": body[:240], "url": target, "tag": f"{msg.event}:{msg.context.get('tag', '')}"[:60],
            "severity": t["severity"], "test": msg.test}


# ------------------------------------------------------------------ convenience

def from_legacy(event: str, *, title, lines=(), facts=(), items=(), items_label="Files", more=0, link="",
                severity="", icon="", summary="", heading="", details=None, actions=None, guidance=None,
                context=None, test=False) -> Message:
    """Build a Message from the older ``notify()`` arguments (title + lines + facts)."""
    lines = [ln for ln in lines if ln]
    built = list(details or [])
    for k, v in facts:
        if v in (None, ""):
            continue
        built.append(Detail(k, v, icons.FACT_ICONS.get(k, "info")))
    return Message(event=event, title=title, heading=heading, summary=summary or (lines[0] if lines else ""),
                   guidance=guidance if guidance is not None else lines[1:], details=built, actions=list(actions or []),
                   items=list(items), items_label=items_label, more=more, link=link, severity=severity, icon=icon,
                   context=dict(context or {}), test=test)


Renderer = Callable[[Message], dict]


# ------------------------------------------------------------------ sanitised samples (preview / TEST messages)

SAMPLE_DOC = "00000000-0000-0000-0000-000000000000"


def sample(event: str, recipient_name: str = "Sample Person") -> Message:
    """Clearly marked sample data for previews and TEST deliveries. Never real people, documents or addresses
    (IP addresses come from the documentation range 203.0.113.0/24)."""
    ev = EVENTS[event]
    login = [Detail("Device", "Windows 11 · Chrome", "device"), Detail("IP address", "203.0.113.25", "globe_location"),
             Detail("Country", "Testland", "globe_location"), Detail("Sign-in method", "password + passkey", "key"),
             Detail("Date/time", templates.local_stamp(), "time")]
    ctx = {"recipient_name": recipient_name, "document_name": "Sample passport", "document_type": "Passport",
           "owner_name": "Sample Person", "expiry_date": "10 Dec 2026", "days_remaining": "45", "folder_path": "Identity > Passport",
           "device": "Windows 11 · Chrome", "location": "Testland", "ip_address": "203.0.113.25", "security_status": "At Risk",
           "count": "3", "document_id": SAMPLE_DOC, "folder_id": SAMPLE_DOC}
    from .events import default_actions

    if event == "expiry.reminder":
        return Message(event=event, title="Sample Person's Passport expires in 45 days", heading="Your Passport is expiring soon",
                       push_title="Passport Expiry Alert",
                       summary="The document will expire in 45 days (10 Dec 2026).", severity="warning", context=ctx,
                       details=[Detail("Document type", "Passport", "document"), Detail("Full name", templates.Name("Sample Person"), "user"),
                                Detail("Passport number", "X1234567", "key", sensitive=True),
                                Detail("Expiry date", "10 Dec 2026", "calendar", emphasis=True),
                                Detail("Days left", "45 days", "time", emphasis=True),
                                Detail("Location", templates.Name("Identity > Passport"), "folder")],
                       actions=[Action("open_document", "Open Document", f"/documents/{SAMPLE_DOC}", primary=True),
                                Action("folder", "Go to Folder", f"/folders/{SAMPLE_DOC}"),
                                Action("reminders", "View Expiry Reminders", "/search?expiring_days=90"),
                                Action("snooze", "Snooze 7 days", "", in_app_only=True)],
                       guidance=["Renew the document before the expiry date.", "Upload the renewed document with Add renewed document."],
                       link=f"/documents/{SAMPLE_DOC}", test=True)
    details: list = []
    summary = ev.description
    if ev.category == "security" and event.startswith(("security.new", "account.", "security.failed", "security.policy_exception")):
        details = login
    elif event == "antivirus.threat":
        details = [Detail("File", templates.Name("sample-invoice.pdf"), "document"), Detail("Detection", "Eicar-Test-Signature", "alarm"),
                   Detail("Status", "Quarantined", "shield")]
        summary = "A file was quarantined. Preview, download, OCR and Local AI are blocked for it."
    elif event in ("document.added", "import.finished"):
        details = [Detail("Folder", templates.Name("Identity > Residence permit"), "folder"), Detail("Count", "3", "document")]
    elif event.startswith(("processing.", "document.")):
        details = [Detail("Document", templates.Name("Sample residence permit"), "document"), Detail("Folder", templates.Name("Identity"), "folder")]
    elif event in ("security.operations", "backup.failed", "integrity.failed", "security.health"):
        details = [Detail("Server", "Debian 13 (sample)", "system"), Detail("Status", "Needs attention", "health")]
    return Message(event=event, title=ev.label, heading=ev.label, summary=summary, details=details, context=ctx,
                   actions=default_actions(event, link="/notifications", context=ctx), link="/notifications", test=True)

