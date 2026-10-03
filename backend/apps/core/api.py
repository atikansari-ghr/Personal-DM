"""Shared API helpers."""
from __future__ import annotations

from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_handler


class Conflict(APIException):
    status_code = 409
    default_detail = "Conflict."


def exception_handler(exc, context):
    response = drf_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        response.data = {"error": str(response.data["detail"]), **{k: v for k, v in response.data.items() if k != "detail"}}
    elif response is not None and isinstance(response.data, (dict, list)):
        response.data = {"error": "Please correct the highlighted fields.", "fields": response.data}
    return response


def paginate(request, qs, default=50, maximum=200):
    try:
        limit = min(maximum, max(1, int(request.query_params.get("limit", default))))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        limit, offset = default, 0
    total = qs.count()
    return qs[offset:offset + limit], {"total": total, "limit": limit, "offset": offset}
