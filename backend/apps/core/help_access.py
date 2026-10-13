"""Permission-aware Help (Change Set V).

Every guide declares who it is for with ``<!-- audience: X -->`` (no marker = everyone). Parts of a guide that only
some people may read are wrapped in ``<!-- audience-section: X -->`` … ``<!-- /audience-section -->``.

Audiences, from widest to narrowest:
  all         everyone who can sign in
  delegate    family/user administration: delegates of a family group, Administrators and the main administrator
  admin       Administrators (security and operations) and the main administrator
  main_admin  the main administrator only (backup administration, NAS, Recovery Key, disaster recovery,
              installation, updates, authentik/Google setup, OCR engine administration, …)
  maintainer  contributor documentation (main administrator only)

The filter runs on the server for the index, categories, search results and excerpts, the guide text itself, and
direct URLs (an unauthorised guide answers 404, so its title is not revealed). Links inside a readable guide that
point to a guide the person may not open are turned into plain text. Visibility is computed per request, so a
permission change applies at once.
"""
from __future__ import annotations

import re

AUDIENCES = ("all", "delegate", "admin", "main_admin", "maintainer")
_SECTION = re.compile(r"<!-- audience-section: ([a-z_]+) -->.*?<!-- /audience-section -->\n?", re.S)
_GUIDE_LINK = re.compile(r"\[([^\]]+)\]\((?:\.\./guides/|/help/)?([a-z0-9\-]+)(?:\.md)?(#[^)\s]*)?\)")


def audience_of(text: str) -> str:
    m = re.search(r"<!-- audience: ([a-z_]+) -->", text)
    return m.group(1) if m and m.group(1) in AUDIENCES else "all"


def allowed(user, audience: str) -> bool:
    if audience in ("all", "", None):
        return True
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_main_admin", False):
        return True
    if audience == "admin":
        return bool(getattr(user, "is_admin", False))
    if audience == "delegate":
        if getattr(user, "is_admin", False):
            return True
        from apps.accounts.models import Delegation  # noqa: PLC0415

        return Delegation.objects.filter(delegate=user).exists()
    return False  # main_admin / maintainer


def visible_markdown(text: str, user, *, readable_slugs: set[str] | None = None) -> str:
    """The guide as this person may read it: restricted sections removed, links to unreadable guides unlinked."""
    out = _SECTION.sub(lambda m: m.group(0) if allowed(user, m.group(1)) else "", text)
    if readable_slugs is not None:
        def unlink(m):
            is_guide_link = ".md" in m.group(0) or "/help/" in m.group(0)
            return m.group(0) if (not is_guide_link or m.group(2) in readable_slugs) else m.group(1)
        out = _GUIDE_LINK.sub(unlink, out)
    return out
