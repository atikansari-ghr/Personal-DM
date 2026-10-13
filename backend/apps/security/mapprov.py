"""Sign-in map tile provider (Change Set U).

Root cause of the observed failure: the app sends ``Referrer-Policy: same-origin`` for everything, so the browser's tile
requests to tile.openstreetmap.org carried no ``Referer``. The OpenStreetMap tile usage policy rejects such requests and
answers with an "Access blocked" picture (HTTP 403) that the map then showed as tiles.

The fix follows the providers' policies instead of working around them:

* tile images (and the one-tile probe) are requested with ``strict-origin-when-cross-origin``: the provider sees only
  this site's origin (no path, no query, no sign-in address). Nothing else changes for the rest of the app;
* the provider is configurable: OpenStreetMap (small, low-volume use only), MapTiler or Stadia Maps with the
  administrator's own domain-restricted key, or a custom/self-hosted tile server;
* a failing provider shows a clear *Map unavailable* state; tiles are never retried in a loop, and sign-in records,
  Trusted Zones, GeoIP and risk never depend on the map.

Sign-in addresses are never sent to a tile provider; positions come from Trusted Zone pins and the local GeoIP database.
"""
from __future__ import annotations

from django.utils import timezone

from apps.core import config

HEALTH_KEY = "map_tiles"
REFERRER_POLICY = "strict-origin-when-cross-origin"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty"
DEFAULT_PROVIDER = "openfreemap"

# Change Set V: place, road and country labels in ENGLISH regardless of the browser's language. Raster tiles have
# their label language baked in (OpenStreetMap's standard tiles show local names, e.g. Arabic in Saudi Arabia), so the
# default is now a vector map: the browser draws OpenFreeMap's OpenStreetMap vector tiles with MapLibre and every label
# reads name:en (falling back to the Latin transliteration, then the local name). OpenFreeMap needs no key or
# registration and permits this use with attribution.
PRESETS = {
    "openfreemap": {"label": "OpenFreeMap — English labels (vector, no key)", "url": OPENFREEMAP_STYLE, "kind": "vector",
                    "attribution": "OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors", "key": False, "english": True,
                    "note": "Free, no key or registration. Labels are drawn in English by the browser (needs WebGL; without it the "
                            "map falls back to standard OpenStreetMap tiles with local-language labels)."},
    "osm": {"label": "OpenStreetMap standard tiles (local-language labels, low-volume use)", "url": OSM_URL, "kind": "raster",
            "attribution": "© OpenStreetMap contributors", "key": False,
            "note": "Free volunteer-run servers: fine for an occasional look at a family sign-in map, not for heavy use. "
                    "Follow the OpenStreetMap tile usage policy; choose another provider if you are blocked."},
    "maptiler": {"label": "MapTiler (API key)", "url": "https://api.maptiler.com/maps/streets-v2/256/{z}/{x}/{y}.png?key={key}",
                 "attribution": "© MapTiler © OpenStreetMap contributors", "key": True,
                 "note": "Create a key at maptiler.com and restrict it to this site's address."},
    "stadia": {"label": "Stadia Maps (API key)", "url": "https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}.png?api_key={key}",
               "attribution": "© Stadia Maps © OpenMapTiles © OpenStreetMap contributors", "key": True,
               "note": "Create a key at stadiamaps.com and restrict it to this site's address."},
    "custom": {"label": "Custom or self-hosted tile server", "url": "", "attribution": "", "key": False,
               "note": "Any https:// tile server you are allowed to use, for example your own."},
}

MESSAGES = {
    401: "The provider refused the API key (HTTP 401). Check the key in Settings → Security → Access policy → Sign-in map provider.",
    403: "The provider blocked the tiles (HTTP 403). For OpenStreetMap this means its tile usage policy was not met "
         "(for example a proxy that removes the Referer header) or the use is too heavy; for keyed providers, the key "
         "is not allowed for this site's address. Choose another provider or fix the key's allowed domains.",
    429: "The provider is limiting requests (HTTP 429). Try again later or use a provider with a higher quota.",
    "network": "The tile server could not be reached from this browser (network, DNS, TLS or a Content-Security-Policy "
               "set by your reverse proxy). Sign-in records and Trusted Zones still work without the map.",
}


def provider() -> str:
    p = config.get("security.map_provider") or DEFAULT_PROVIDER
    # installations that set a custom tile address before providers existed keep using it
    if not config.is_set("security.map_provider"):
        url = config.get("security.map_tile_url") or ""
        if url and url != OSM_URL:
            return "custom"
    return p if p in PRESETS else DEFAULT_PROVIDER


def resolved() -> dict:
    """The effective tile template and attribution (the API key, if any, is inserted: tiles are loaded by the browser)."""
    p = provider()
    preset = PRESETS[p]
    if p == "custom":
        url = config.get("security.map_tile_url") or ""
        attribution = config.get("security.map_attribution") or ""
    else:
        url = preset["url"]
        attribution = preset["attribution"]
    key = (config.get("security.map_api_key") or "") if preset["key"] else ""
    if preset["key"]:
        url = url.replace("{key}", key) if key else ""
    return {"provider": p, "url": url, "attribution": attribution, "needs_key": preset["key"], "key_set": bool(key),
            "kind": preset.get("kind", "raster"), "english": bool(preset.get("english"))}


def health() -> dict:
    from .models import HealthState

    return HealthState.get(HEALTH_KEY) or {"state": "unknown", "detail": "Not tested yet."}


def public_config(user=None) -> dict:
    r = resolved()
    enabled = bool(config.get("security.map_enabled"))
    vector = r["kind"] == "vector"
    out = {"enabled": enabled and bool(r["url"]), "provider": r["provider"], "provider_label": PRESETS[r["provider"]]["label"],
           "kind": r["kind"], "style_url": r["url"] if vector else "", "english_labels": r["english"],
           "fallback_tile_url": OSM_URL if vector else "", "fallback_attribution": PRESETS["osm"]["attribution"] if vector else "",
           "tile_url": "" if vector else r["url"], "attribution": r["attribution"], "referrer_policy": REFERRER_POLICY,
           "privacy": "The map loads ordinary map data (tiles) from the provider shown here. Your sign-in addresses are never "
                      "sent to it or to any geolocation service; positions come from Trusted Zone pins and this server's GeoIP database."}
    if enabled and not r["url"]:
        out["unavailable"] = "No map provider key is configured." if r["needs_key"] else "No tile address is configured."
    if user is not None and getattr(user, "is_main_admin", False):
        out["health"] = health()
        out["admin"] = True
    return out


def tile_origin() -> str:
    """Origin(s) the browser may load map data from (Content-Security-Policy img-src and connect-src)."""
    import urllib.parse

    if not config.get("security.map_enabled"):
        return ""
    r = resolved()
    u = urllib.parse.urlsplit(r["url"] or "")
    origin = ""
    if u.scheme == "https" and u.hostname and "{" not in u.hostname.replace("{s}", ""):
        origin = f"https://{u.netloc}".replace("{s}", "*")
    if origin and r["kind"] == "vector":
        origin += " https://tile.openstreetmap.org"  # raster fallback for browsers without WebGL
    return origin


def record_test(status, error: str = "", actor=None) -> dict:
    """Store the result of a browser-side test tile (the only place the provider sees a real browser request).
    ``status`` is the HTTP status, or None with ``error`` for a network/CORS failure."""
    from apps.core import audit

    from .models import HealthState

    prev = health()
    now = timezone.now().isoformat()
    try:
        status = int(status) if status not in (None, "") else None
    except (TypeError, ValueError):
        status = None
    ok = status is not None and 200 <= status < 300
    if status is None and (error or "").startswith("unknown"):
        data = {"state": "unknown", "status": None, "checked_at": now, "last_ok": prev.get("last_ok"), "provider": provider(),
                "detail": "The tile server does not let this page read its answer (no CORS headers), so the test cannot tell. "
                          "Open the sign-in map: if tiles show, the provider works."}
        HealthState.objects.update_or_create(key=HEALTH_KEY, defaults={"data": data})
        audit.record("security.map_provider_test", actor=actor, outcome="unknown")
        return data
    if ok:
        data = {"state": "ok", "status": status, "detail": "Test tile loaded.", "checked_at": now, "last_ok": now,
                "provider": provider()}
    else:
        detail = MESSAGES.get(status) if status in MESSAGES else (
            MESSAGES["network"] if status is None else f"The provider answered HTTP {status}.")
        data = {"state": "failed", "status": status, "detail": detail, "checked_at": now, "last_ok": prev.get("last_ok"),
                "provider": provider(), "error": (error or "")[:120]}
    HealthState.objects.update_or_create(key=HEALTH_KEY, defaults={"data": data})
    audit.record("security.map_provider_test", actor=actor, outcome="success" if ok else "failure", status=status)
    return data
