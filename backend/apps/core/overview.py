"""Overview building blocks: widget layout rules, Gregorian + Hijri date, public holidays and weather.

Holidays come from the bundled `holidays` library (no hard-coded dates). Islamic holidays depend on the moon sighting,
so the library's calculated dates are marked *provisional* until an administrator confirms or corrects them with a
HolidayOverride. The Hijri date is computed with `hijridate` (Umm al-Qura calendar) in the installation timezone,
shifted by the administrator's ±2 day adjustment.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import requests
from django.utils import timezone

from . import config
from .registry import WIDGETS, SettingError

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ layout

STYLES = ("rect", "compact", "circle", "compact_circle")
# Width in columns of a 4-column desktop grid: (min, default, max). Tablets use 2 columns and phones 1, so a widget
# never runs off-screen; CSS grid places widgets in order without overlap.
SIZES = {
    "date": (1, 1, 2), "weather": (1, 1, 2), "summary": (2, 2, 4), "calendar": (1, 2, 2), "holidays": (1, 2, 4),
    "shared": (1, 2, 4), "activity": (1, 2, 4), "recent": (2, 2, 4), "upcoming": (1, 2, 4), "review_queue": (2, 4, 4),
    "backup": (2, 4, 4), "family": (2, 4, 4), "saved_views": (2, 4, 4),
    "security": (2, 2, 4), "documents": (1, 1, 2), "members": (1, 1, 2), "expiring": (1, 1, 2), "storage": (1, 1, 2), "review": (1, 1, 2),
}
# Lists, tables and calendars stay rectangular; a circle only fits a single value.
CIRCLE_OK = {"date", "weather", "documents", "members", "expiring", "storage", "review"}
WIDGET_OPTIONS = {
    "date": {"show_hijri": bool, "arabic_month": bool},
    "holidays": {"count": int, "countries": list},
    "calendar": {"countries": list},
    "recent": {"count": int},
    "shared": {"count": int},
    "activity": {"count": int},
}


def layout_limits() -> dict:
    return {k: {"min": a, "default": b, "max": c, "circle": k in CIRCLE_OK, "options": list(WIDGET_OPTIONS.get(k, {}))}
            for k, (a, b, c) in SIZES.items()}


def normalize_layout(value) -> dict:
    """{widget: {"w": columns, "style": ..., "settings": {...}}}, clamped to each widget's limits."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise SettingError("The layout must map widgets to their size and style.")
    out: dict = {}
    for wid, cfg in value.items():
        if wid not in WIDGETS or not isinstance(cfg, dict):
            raise SettingError(f"Unknown widget: {wid}.")
        lo, default, hi = SIZES.get(wid, (1, 2, 4))
        entry: dict = {}
        if "w" in cfg:
            try:
                w = int(cfg["w"])
            except (TypeError, ValueError):
                raise SettingError("Widget width must be a whole number of columns.")
            entry["w"] = max(lo, min(hi, w))
        style = cfg.get("style", "rect")
        if style not in STYLES:
            raise SettingError(f"Style must be one of: {', '.join(STYLES)}.")
        if style.endswith("circle") and wid not in CIRCLE_OK:
            style = "compact" if style == "compact_circle" else "rect"
        entry["style"] = style
        settings_in = cfg.get("settings") or {}
        if not isinstance(settings_in, dict):
            raise SettingError("Widget settings must be an object.")
        opts = {}
        for key, kind in WIDGET_OPTIONS.get(wid, {}).items():
            if key not in settings_in:
                continue
            v = settings_in[key]
            if kind is bool:
                opts[key] = bool(v)
            elif kind is int:
                try:
                    opts[key] = max(1, min(20, int(v)))
                except (TypeError, ValueError):
                    raise SettingError("Counts must be whole numbers.")
            elif kind is list:
                names = country_names()
                opts[key] = [c.upper() for c in v if isinstance(c, str) and c.upper() in names][:12] if isinstance(v, list) else []
        if opts:
            entry["settings"] = opts
        out[wid] = entry
    return out


# ------------------------------------------------------------------ date

def local_today() -> date:
    tz = ZoneInfo(config.get("general.timezone") or "UTC")
    return timezone.now().astimezone(tz).date()


def hijri_of(d: date) -> dict:
    """Hijri (Umm al-Qura) date for `d`, honouring the administrator's adjustment. Range: 1343–1500 AH."""
    from hijridate import Gregorian

    shifted = d + timedelta(days=int(config.get("overview.hijri_adjust") or 0))
    try:
        h = Gregorian(shifted.year, shifted.month, shifted.day).to_hijri()
    except (OverflowError, ValueError):
        return {}
    return {"day": h.day, "month": h.month, "year": h.year, "month_name": h.month_name(),
            "month_name_ar": h.month_name(language="ar"), "notation": "AH"}


def today_info() -> dict:
    d = local_today()
    return {"date": d.isoformat(), "weekday": d.strftime("%A"), "timezone": config.get("general.timezone"),
            "hijri": hijri_of(d), "hijri_calendar": "Umm al-Qura", "hijri_adjust": int(config.get("overview.hijri_adjust") or 0)}


# ------------------------------------------------------------------ holidays

_FIX = {" And ": " and ", " Of ": " of ", " The ": " the ", " Da ": " da ", "Mc Donald": "McDonald"}
_LUNAR = re.compile(r"\b(eid|id-?ul|idul|bakrid|arafah|ramadan|hijri|islamic new year|muharram|ashura|mawlid|milad|"
                    r"prophet|isra|laylat|shab-?e|al-adha|al-fitr)\b", re.I)


@lru_cache(maxsize=1)
def country_names() -> dict[str, str]:
    from holidays.registry import COUNTRIES

    out = {}
    for _mod, spec in COUNTRIES.items():
        name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", spec[0])
        for a, b in _FIX.items():
            name = name.replace(a, b)
        out[spec[1]] = name
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def flag(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code.upper()) if re.fullmatch(r"[A-Za-z]{2}", code) else ""


def configured_countries() -> list[str]:
    names = country_names()
    return [c for c in (config.get("overview.holiday_countries") or []) if c in names]


def holidays_between(start: date, end: date, countries: list[str] | None = None) -> list[dict]:
    """Holidays of the chosen countries between start and end (inclusive), with overrides applied."""
    import holidays as hol

    from .models import HolidayOverride

    countries = [c for c in (countries if countries is not None else configured_countries()) if c in country_names()]
    if not countries or end < start:
        return []
    years = list(range(start.year, end.year + 1))
    overrides = {(o.country, o.date): o for o in
                 HolidayOverride.objects.filter(country__in=countries, date__gte=start, date__lte=end)}
    out = []
    names = country_names()
    for code in countries:
        try:
            lib = hol.country_holidays(code, years=years, language="en_US")
        except (NotImplementedError, KeyError):
            try:
                lib = hol.country_holidays(code, years=years)
            except Exception:  # an unsupported subdivision/language never breaks the Overview
                continue
        for day, label in sorted(lib.items()):
            if not (start <= day <= end) or (code, day) in overrides:
                continue
            for name in str(label).split("; "):
                provisional = "estimated" in name.lower() or bool(_LUNAR.search(name))
                out.append({"date": day.isoformat(), "country": code, "country_name": names[code], "flag": flag(code),
                            "name": name.replace(" (estimated)", ""), "observed": "(observed)" in name,
                            "status": "provisional" if provisional else "confirmed", "source": "holidays library",
                            "calculated": provisional})
        for (c, day), o in overrides.items():
            if c != code or o.hidden:
                continue
            out.append({"date": day.isoformat(), "country": code, "country_name": names[code], "flag": flag(code),
                        "name": o.name, "observed": False, "status": o.status, "source": o.source or "administrator",
                        "calculated": False, "override": o.id})
    out.sort(key=lambda h: (h["date"], h["country"], h["name"]))
    return out


def upcoming_holidays(days: int = 120, limit: int = 8, countries: list[str] | None = None) -> list[dict]:
    today = local_today()
    rows = holidays_between(today, today + timedelta(days=days), countries)
    # one entry per holiday run (a three-day Eid shows once, with its last day)
    merged: list[dict] = []
    for h in rows:
        prev = next((m for m in reversed(merged) if m["country"] == h["country"] and m["name"] == h["name"]), None)
        if prev and (date.fromisoformat(h["date"]) - date.fromisoformat(prev.get("end", prev["date"]))).days <= 1:
            prev["end"] = h["date"]
            continue
        merged.append(dict(h))
    for m in merged:
        m["days_away"] = (date.fromisoformat(m["date"]) - today).days
    return merged[:limit]


def month_calendar(year: int, month: int, countries: list[str] | None = None) -> dict:
    import calendar as cal

    first = date(year, month, 1)
    last = date(year, month, cal.monthrange(year, month)[1])
    hols = holidays_between(first, last, countries)
    days = []
    for n in range(1, last.day + 1):
        d = date(year, month, n)
        days.append({"date": d.isoformat(), "day": n, "weekday": d.weekday(), "hijri": hijri_of(d).get("day"),
                     "holidays": [h for h in hols if h["date"] == d.isoformat()]})
    h1, h2 = hijri_of(first), hijri_of(last)
    hijri_label = ""
    if h1 and h2:
        hijri_label = (f"{h1['month_name']} {h1['year']}" if h1["month"] == h2["month"]
                       else f"{h1['month_name']} – {h2['month_name']} {h2['year']}")
    return {"year": year, "month": month, "label": first.strftime("%B %Y"), "hijri_label": hijri_label,
            "today": local_today().isoformat(), "first_weekday": first.weekday(), "days": days,
            "countries": [{"code": c, "name": country_names()[c], "flag": flag(c)}
                          for c in (countries if countries is not None else configured_countries()) if c in country_names()]}


# ------------------------------------------------------------------ weather

class WeatherError(Exception):
    pass


WMO = {0: ("Clear sky", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "cloud-sun"), 3: ("Overcast", "cloud"),
       45: ("Fog", "fog"), 48: ("Fog", "fog"), 51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Drizzle", "rain"),
       61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"), 71: ("Light snow", "snow"),
       73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 80: ("Showers", "rain"), 81: ("Showers", "rain"),
       82: ("Heavy showers", "rain"), 95: ("Thunderstorm", "storm"), 96: ("Thunderstorm", "storm"), 99: ("Thunderstorm", "storm")}


def normalize_city(value):
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise SettingError("Choose a city from the search results.")
    try:
        lat, lon = float(value["latitude"]), float(value["longitude"])
    except (KeyError, TypeError, ValueError):
        raise SettingError("The city needs a latitude and longitude.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise SettingError("The coordinates are out of range.")
    name = str(value.get("name") or "").strip()[:80]
    if not name:
        raise SettingError("The city needs a name.")
    return {"name": name, "country": str(value.get("country") or "")[:80], "country_code": str(value.get("country_code") or "")[:3],
            "admin1": str(value.get("admin1") or "")[:80], "latitude": round(lat, 4), "longitude": round(lon, 4),
            "timezone": str(value.get("timezone") or "")[:64]}


def _params_with_key(params: dict) -> dict:
    key = config.get("weather.api_key")
    return {**params, "apikey": key} if key else params


def _get(url: str, params: dict) -> dict:
    try:
        resp = requests.get(url, params=_params_with_key(params), timeout=8)
    except requests.Timeout:
        raise WeatherError("The weather service did not answer in time.")
    except requests.RequestException:
        raise WeatherError("The weather service could not be reached.")
    if resp.status_code in (401, 403):
        raise WeatherError("The weather service refused the request; check the API key.")
    if resp.status_code != 200:
        raise WeatherError(f"The weather service answered with HTTP {resp.status_code}.")
    try:
        return resp.json()
    except ValueError:
        raise WeatherError("The weather service sent an unreadable answer.")


def search_cities(q: str) -> list[dict]:
    q = (q or "").strip()[:80]
    if len(q) < 2:
        return []
    data = _get(config.get("weather.geocoding_url"), {"name": q, "count": 8, "language": "en", "format": "json"})
    out = []
    for r in data.get("results") or []:
        try:
            out.append(normalize_city(r))
        except SettingError:
            continue
    return out


def _forecast(city: dict) -> dict:
    fahrenheit = config.get("weather.units") == "fahrenheit"
    params = {"latitude": city["latitude"], "longitude": city["longitude"], "timezone": "auto", "forecast_days": 5,
              "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min"}
    if fahrenheit:
        params["temperature_unit"] = "fahrenheit"
    data = _get(config.get("weather.base_url"), params)
    try:
        cur = data["current"]
        daily = data["daily"]
        days = [{"date": daily["time"][i], "code": daily["weather_code"][i],
                 "label": WMO.get(daily["weather_code"][i], ("", "cloud"))[0], "icon": WMO.get(daily["weather_code"][i], ("", "cloud"))[1],
                 "max": daily["temperature_2m_max"][i], "min": daily["temperature_2m_min"][i]} for i in range(len(daily["time"]))]
        code = cur.get("weather_code")
        return {"temperature": cur["temperature_2m"], "code": code, "label": WMO.get(code, ("", "cloud"))[0],
                "icon": WMO.get(code, ("", "cloud"))[1], "humidity": cur.get("relative_humidity_2m"),
                "wind": cur.get("wind_speed_10m"), "unit": "°F" if fahrenheit else "°C", "days": days[:5]}
    except (KeyError, TypeError, IndexError):
        raise WeatherError("The weather service sent an unexpected answer.")


def weather_for(city: dict | None, force: bool = False) -> dict:
    """Cached forecast. On failure the last good forecast is returned marked stale, or an 'unavailable' state."""
    from .models import WeatherCache

    if not config.get("weather.enabled"):
        return {"status": "disabled"}
    if not city:
        return {"status": "no_city"}
    key = f"{config.get('weather.provider')}:{city['latitude']:.2f},{city['longitude']:.2f}:{config.get('weather.units')}"
    row = WeatherCache.objects.filter(key=key).first()
    max_age = timedelta(minutes=int(config.get("weather.cache_minutes") or 30))
    if row and not force and timezone.now() - row.fetched_at < max_age:
        return {"status": "ok", "city": city, **row.data, "fetched_at": row.fetched_at.isoformat(), "stale": False}
    try:
        data = _forecast(city)
    except WeatherError as exc:
        log.info("weather unavailable: %s", exc)
        if row and timezone.now() - row.fetched_at < timedelta(hours=24):
            return {"status": "ok", "city": city, **row.data, "fetched_at": row.fetched_at.isoformat(), "stale": True,
                    "error": str(exc)}
        return {"status": "unavailable", "city": city, "error": str(exc)}
    now = timezone.now()
    WeatherCache.objects.update_or_create(key=key, defaults={"data": data, "fetched_at": now})
    return {"status": "ok", "city": city, **data, "fetched_at": now.isoformat(), "stale": False}


def test_connection() -> dict:
    """Administrator check: city search plus one forecast, without touching the cache."""
    started = datetime.now()
    cities = search_cities("Riyadh")
    if not cities:
        raise WeatherError("City search answered, but returned no results.")
    data = _forecast(cities[0])
    return {"ok": True, "city": cities[0]["name"], "temperature": data["temperature"], "unit": data["unit"],
            "ms": int((datetime.now() - started).total_seconds() * 1000)}
