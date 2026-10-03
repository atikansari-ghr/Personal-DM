"""Database-backed rate limiting (works across multiple gunicorn workers without Redis)."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import RateLimitHit


def too_many(bucket: str, limit: int, window_seconds: int) -> bool:
    since = timezone.now() - timedelta(seconds=window_seconds)
    return RateLimitHit.objects.filter(bucket=bucket, at__gte=since).count() >= limit


def hit(bucket: str) -> None:
    RateLimitHit.objects.create(bucket=bucket)


def clear(bucket: str) -> None:
    RateLimitHit.objects.filter(bucket=bucket).delete()


def prune(older_than_seconds: int = 86400) -> int:
    return RateLimitHit.objects.filter(at__lt=timezone.now() - timedelta(seconds=older_than_seconds)).delete()[0]
