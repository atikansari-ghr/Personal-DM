"""Overview API: calendar, holidays, weather and the administrator's holiday corrections."""
from __future__ import annotations

from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsActiveAuthenticated, IsMainAdmin

from . import audit, config, overview, ratelimit
from .models import HolidayOverride


def _err(msg, status=400, **extra):
    return Response({"error": msg, **extra}, status=status)


def _countries(request) -> list[str] | None:
    raw = request.query_params.get("countries")
    if raw is None:
        return None
    names = overview.country_names()
    return [c for c in (x.strip().upper() for x in raw.split(",")) if c in names][:12]


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def calendar(request):
    month = request.query_params.get("month") or overview.local_today().strftime("%Y-%m")
    try:
        y, m = (int(x) for x in month.split("-"))
        date(y, m, 1)
        if not 1900 <= y <= 2100:
            raise ValueError
    except ValueError:
        return _err("Use a month like 2026-06.")
    return Response(overview.month_calendar(y, m, _countries(request)))


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def upcoming_holidays(request):
    try:
        count = max(1, min(20, int(request.query_params.get("count") or 6)))
    except ValueError:
        count = 6
    return Response({"holidays": overview.upcoming_holidays(limit=count, countries=_countries(request)),
                     "countries": overview.configured_countries()})


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def countries(request):
    return Response({"countries": [{"code": c, "name": n, "flag": overview.flag(c)} for c, n in overview.country_names().items()],
                     "selected": overview.configured_countries()})


def _city(user):
    return config.get_user(user, "me.weather_city") or config.get("weather.default_city")


@api_view(["GET", "PUT"])
@permission_classes([IsActiveAuthenticated])
def weather(request):
    """GET the forecast for the person's city · PUT {"city": {...}} chooses the city (null = installation default)."""
    if request.method == "PUT":
        try:
            config.set_user(request.user, "me.weather_city", request.data.get("city"))
        except Exception as exc:  # SettingError
            return _err(str(exc))
    return Response(overview.weather_for(_city(request.user), force=request.query_params.get("refresh") == "1"
                                         and bool(request.user.is_main_admin)))


@api_view(["GET"])
@permission_classes([IsActiveAuthenticated])
def weather_cities(request):
    if not config.get("weather.enabled"):
        return _err("The weather widget is turned off by the administrator.", 409)
    bucket = f"weather-search:{request.user.pk}"
    if ratelimit.too_many(bucket, 30, 60):
        return _err("Too many searches; wait a minute.", 429)
    ratelimit.hit(bucket)
    try:
        return Response({"cities": overview.search_cities(request.query_params.get("q", ""))})
    except overview.WeatherError as exc:
        return _err(str(exc), 502)


@api_view(["POST"])
@permission_classes([IsMainAdmin])
def weather_test(request):
    try:
        result = overview.test_connection()
    except overview.WeatherError as exc:
        audit.record("settings.weather_test", request=request, outcome="failure")
        return _err(str(exc), 502)
    audit.record("settings.weather_test", request=request)
    return Response(result)


@api_view(["PUT"])
@permission_classes([IsMainAdmin])
def weather_default_city(request):
    try:
        config.set_value("weather.default_city", request.data.get("city"), actor=request.user)
    except Exception as exc:
        return _err(str(exc))
    return Response({"city": config.get("weather.default_city")})


def _override_json(o: HolidayOverride) -> dict:
    return {"id": o.id, "country": o.country, "country_name": overview.country_names().get(o.country, o.country),
            "flag": overview.flag(o.country), "date": o.date.isoformat(), "name": o.name, "status": o.status,
            "hidden": o.hidden, "source": o.source, "updated_at": o.updated_at}


def _apply_override(o: HolidayOverride, d) -> str:
    if "country" in d:
        code = str(d.get("country") or "").upper()
        if code not in overview.country_names():
            return "Choose a country from the list."
        o.country = code
    if "date" in d:
        try:
            o.date = date.fromisoformat(str(d.get("date")))
        except ValueError:
            return "Enter the date as YYYY-MM-DD."
    if "hidden" in d:
        o.hidden = bool(d["hidden"])
    if "name" in d:
        o.name = str(d.get("name") or "").strip()[:120]
    if "status" in d:
        if d["status"] not in (HolidayOverride.CONFIRMED, HolidayOverride.PROVISIONAL):
            return "Status must be confirmed or provisional."
        o.status = d["status"]
    if "source" in d:
        o.source = str(d.get("source") or "").strip()[:200]
    if not o.hidden and not o.name:
        return "Enter the holiday name (or choose to hide the library holiday on this date)."
    if not o.country or not o.date:
        return "Choose a country and a date."
    clash = HolidayOverride.objects.filter(country=o.country, date=o.date).exclude(pk=o.pk).exists()
    return "There is already a correction for this country and date; edit it instead." if clash else ""


@api_view(["GET", "POST"])
@permission_classes([IsMainAdmin])
def holiday_overrides(request):
    if request.method == "GET":
        return Response({"overrides": [_override_json(o) for o in HolidayOverride.objects.all()]})
    o = HolidayOverride(created_by=request.user)
    err = _apply_override(o, request.data)
    if err:
        return _err(err)
    o.save()
    audit.record("settings.holiday_override", request=request, target_type="holiday", target_id=str(o.id),
                 country=o.country, date=o.date.isoformat())
    return Response(_override_json(o), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsMainAdmin])
def holiday_override_detail(request, pk):
    o = HolidayOverride.objects.filter(pk=pk).first()
    if o is None:
        return _err("Unknown correction.", 404)
    if request.method == "DELETE":
        audit.record("settings.holiday_override_delete", request=request, target_type="holiday", target_id=str(o.id))
        o.delete()
        return Response(status=204)
    err = _apply_override(o, request.data)
    if err:
        return _err(err)
    o.save()
    audit.record("settings.holiday_override", request=request, target_type="holiday", target_id=str(o.id),
                 country=o.country, date=o.date.isoformat())
    return Response(_override_json(o))
