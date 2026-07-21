"""FastAPI dependency wiring: repository, geocoder, plan catalog, limiter, auth.

Singletons (repository pool, geocoder, plan catalog, in-memory limiter) are built
once and reused. Authentication resolves RapidAPI/direct credentials and the
caller's plan, and enforces the fallback burst limiter. The monthly quota is
enforced in the feasibility endpoint (only the billable endpoint consumes quota).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from fastapi import Request

from ..core.db import PostgresRepository
from ..core.geocode import Geocoder, build_default_geocoder
from ..core.repository import FeasibilityRepository
from . import errors, rapidapi
from .rapidapi import Credentials, InMemoryRateLimiter
from .settings import PlanCatalog, Settings, get_settings, load_plan_catalog


@lru_cache(maxsize=1)
def get_repository() -> FeasibilityRepository:
    settings = get_settings()
    if not settings.has_db:
        raise errors.ApiError(
            errors.CODE_INTERNAL,
            "Database is not configured (SUPABASE_DB_URL is unset).",
        )
    return PostgresRepository(settings.db_url)  # type: ignore[arg-type]


@lru_cache(maxsize=1)
def get_geocoder() -> Geocoder:
    settings = get_settings()
    # Census keyless primary; Google / Mapbox appended only when their env keys
    # are set. Never fabricates a point on low-confidence / no-match.
    return build_default_geocoder(timeout_s=settings.geocoder_timeout_s)


@lru_cache(maxsize=1)
def get_catalog() -> PlanCatalog:
    return load_plan_catalog()


@lru_cache(maxsize=1)
def get_rate_limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter()


@dataclass
class AuthContext:
    credentials: Credentials
    plan_name: str
    plan: dict[str, Any]

    @property
    def consumer_id(self) -> str:
        return self.credentials.consumer_id

    @property
    def provider(self) -> str:
        return "rapidapi" if self.credentials.kind == "rapidapi" else "direct"

    def feature(self, name: str) -> bool:
        return bool((self.plan.get("features") or {}).get(name, False))


def authenticate(request: Request) -> AuthContext:
    """Resolve credentials + plan and apply the fallback burst limiter.

    Raises 401 on invalid credentials and 429 (rate_limited) when the burst limit
    is exceeded. Does not consume monthly quota (that is billable-endpoint only).
    """
    settings: Settings = get_settings()
    catalog = get_catalog()
    creds = rapidapi.parse_credentials(
        request.headers,
        expected_host=settings.rapidapi_host,
        proxy_secret=settings.rapidapi_proxy_secret,
    )
    if not creds.valid:
        raise errors.unauthorized(creds.error or "Missing or invalid API credentials.")

    plan_name = rapidapi.resolve_plan_name(creds, catalog)
    plan = catalog.get_plan(plan_name) or {}

    limiter = get_rate_limiter()
    rpm = catalog.rate_limit_per_minute(plan_name)
    if not limiter.allow(creds.consumer_id, rpm):
        raise errors.rate_limited(rpm)

    return AuthContext(credentials=creds, plan_name=plan_name, plan=plan)
