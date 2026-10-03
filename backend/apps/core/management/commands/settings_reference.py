from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.registry import SETTINGS


def render() -> str:
    lines = ["# Settings reference", "", "Generated from `backend/apps/core/registry.py` by `manage.py settings_reference`. Do not edit by hand.", ""]
    section = None
    for s in SETTINGS:
        if s.section != section:
            section = s.section
            lines += [f"## Section: {section}", ""]
        default = "(secret, not shown)" if s.secret else f"`{s.default!r}`"
        allowed = ", ".join(map(str, s.choices)) if s.choices else (
            f"{s.min if s.min is not None else ''}–{s.max if s.max is not None else ''}" if (s.min is not None or s.max is not None) else s.type)
        lines += [
            f"### {s.label} (`{s.key}`)", "",
            s.description, "",
            f"- **Default:** {default}",
            f"- **Allowed values:** {allowed}",
            f"- **Scope:** {s.scope} · **Editable by:** {'main administrator' if s.editable_by == 'main_admin' else 'each user'}",
            f"- **Depends on:** {', '.join(s.depends_on) or 'nothing'}",
            f"- **Effect of changing:** {s.effect or 'Takes effect immediately.'}",
            f"- **Restart needed:** {'yes (worker)' if s.restart else 'no'}",
            f"- **Learn more:** [{s.help}](guides/{s.help.split('#')[0]}.md#{s.help.split('#')[1] if '#' in s.help else ''})",
        ]
        if s.example:
            lines.append(f"- **Example:** {s.example}")
        lines.append("")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Regenerate docs/SETTINGS_REFERENCE.md from the settings registry."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, **opts):
        target = Path(settings.DOCS_DIR) / "SETTINGS_REFERENCE.md"
        text = render()
        if opts["check"]:
            if not target.exists() or target.read_text() != text:
                raise SystemExit("SETTINGS_REFERENCE.md is out of date; run manage.py settings_reference")
            return
        target.write_text(text)
        self.stdout.write(f"wrote {target}")
