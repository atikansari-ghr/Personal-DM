#!/usr/bin/env python3
"""Documentation checks (Change Set T, AT-332 .. AT-334). Run: python3 scripts/check_docs.py

Fails on:
* internal links to missing files, or to anchors that do not exist in the target guide;
* images referenced by a guide that do not exist, and images without alt text;
* screenshots in docs/images/screenshots that no document references (orphans), unless listed in ORPHAN_OK;
* "Learn more" / help links in the frontend and setting help keys that point to missing guides or anchors;
* outdated UI terms (the UI renamed them) in the guides;
* Change Set T guides without a "reviewed" date, and critical flows without at least one screenshot.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GUIDES = DOCS / "guides"
SHOTS = DOCS / "images" / "screenshots"
# Captures used only by other tooling (layout audit, social preview) or kept for history.
ORPHAN_OK = {"social-preview.png"}
# Terms the UI no longer uses (left) -> the current label (right).
TERMS = {
    r"Settings → Storage & backup → Backup settings": "Settings → Backup & Recovery → Policies & schedule",
    r"WhatsApp is planned for a later release": "WhatsApp Personal (experimental)",
}
REVIEWED_REQUIRED = ["backup-restore", "disaster-recovery", "notifications", "discord", "whatsapp-personal", "security-map",
                     "documentation"]
CRITICAL_FLOWS = {"backup-restore": 5, "security-map": 3, "notifications": 1, "discord": 1}

errors: list[str] = []


def slugify(h: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    out = set(re.findall(r"\{#([a-z0-9-]+)\}", text)) | set(re.findall(r'<a id="([a-z0-9-]+)"', text))
    for h in re.findall(r"^#+ (.+)$", text, re.M):
        out.add(slugify(re.sub(r"\s*\{#[a-z0-9-]+\}\s*$", "", h)))
    return out


def md_files() -> list[Path]:
    return sorted([*GUIDES.glob("*.md"), *DOCS.glob("*.md"), ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md"])


def check_links_and_images() -> set[str]:
    used: set[str] = set()
    for f in md_files():
        if not f.exists():
            continue
        text = re.sub(r"```.*?```", "", f.read_text(encoding="utf-8"), flags=re.S)
        for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)\)", text):
            if src.startswith("http"):
                continue
            target = (f.parent / src).resolve()
            if not target.exists():
                errors.append(f"{f.relative_to(ROOT)}: missing image {src}")
            if not alt.strip():
                errors.append(f"{f.relative_to(ROOT)}: image {src} has no alt text")
            used.add(target.name)
        for link in re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)", text):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, anchor = link.partition("#")
            target = f if not path else (f.parent / path).resolve()
            if not target.exists():
                errors.append(f"{f.relative_to(ROOT)}: link to missing {link}")
                continue
            if anchor and target.suffix == ".md" and anchor not in anchors(target):
                errors.append(f"{f.relative_to(ROOT)}: link to missing anchor {link}")
        for name in re.findall(r"images/screenshots/([A-Za-z0-9_.-]+\.png)", f.read_text(encoding="utf-8")):
            used.add(name)
    return used


def check_orphans(used: set[str]) -> None:
    referenced = set(used)
    for p in [*ROOT.joinpath("tests", "e2e").glob("*.mjs"), ROOT / "docs" / "images" / "screenshot-manifest.json"]:
        if p.exists():
            referenced |= set(re.findall(r"([A-Za-z0-9_.-]+\.png)", p.read_text(encoding="utf-8")))
    for shot in sorted(SHOTS.glob("*.png")):
        if shot.name not in used and shot.name not in ORPHAN_OK:
            errors.append(f"orphaned screenshot (not referenced by any document): docs/images/screenshots/{shot.name}")
    del referenced


def check_help_links() -> None:
    srcs = list((ROOT / "frontend" / "src").rglob("*.tsx"))
    for f in srcs:
        for slug, anchor in re.findall(r'/help/([a-z0-9-]+)(?:#([a-z0-9-]+))?', f.read_text(encoding="utf-8")):
            if slug == "asset":  # /api/help/asset/... (images), not a guide
                continue
            g = GUIDES / f"{slug}.md"
            if not g.exists():
                errors.append(f"{f.relative_to(ROOT)}: Learn more link to missing guide {slug}")
            elif anchor and anchor not in anchors(g):
                errors.append(f"{f.relative_to(ROOT)}: Learn more link to missing anchor {slug}#{anchor}")
    reg = (ROOT / "backend" / "apps" / "core" / "registry.py").read_text(encoding="utf-8")
    for slug, anchor in re.findall(r'help="([a-z0-9-]+)#([a-z0-9-]+)"', reg):
        g = GUIDES / f"{slug}.md"
        if not g.exists() or anchor not in anchors(g):
            errors.append(f"setting help {slug}#{anchor} does not resolve")


def check_terms_and_metadata() -> None:
    for f in GUIDES.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        for old, new in TERMS.items():
            if re.search(old, text):
                errors.append(f"{f.relative_to(ROOT)}: outdated term “{old}” (now “{new}”)")
    for slug in REVIEWED_REQUIRED:
        g = GUIDES / f"{slug}.md"
        if not g.exists():
            errors.append(f"missing guide {slug}.md")
        elif "<!-- reviewed:" not in g.read_text(encoding="utf-8"):
            errors.append(f"{slug}.md has no <!-- reviewed: YYYY-MM-DD --> date")
    for slug, n in CRITICAL_FLOWS.items():
        g = GUIDES / f"{slug}.md"
        if g.exists() and len(re.findall(r"!\[[^\]]+\]\(", g.read_text(encoding="utf-8"))) < n:
            errors.append(f"{slug}.md: critical flow needs at least {n} screenshot(s)")


def main() -> int:
    used = check_links_and_images()
    check_orphans(used)
    check_help_links()
    check_terms_and_metadata()
    for e in errors:
        print("FAIL:", e)
    print("documentation check:", "OK" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
