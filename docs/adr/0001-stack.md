# ADR-0001: Django + PostgreSQL + React modular monolith

- Status: accepted (2026-10-03)

## Context
Self-hosted on a 2 vCPU / 4 GB Debian 13 LXC; native services only; one administrator maintains it. Needs typed API, permission-heavy queries, full-text search, durable background work.

## Decision
Python 3.13 / Django 5.2 LTS with Django REST Framework; PostgreSQL (Debian 13 ships 17) for data, FTS, sessions and the job queue; React 18 + TypeScript built by Vite into static files served on the same origin by WhiteNoise. gunicorn web + worker + scheduler as three systemd units.

## Consequences
Low service count (no Redis/Celery/Node at runtime). Django 5.2 is an LTS release (supported to 2028). The frontend is built in CI or once during install; the runtime never needs Node.
