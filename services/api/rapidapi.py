"""RapidAPI gateway verification, plan resolution, metering, and fallback limiter.

Everything here is framework-agnostic (no FastAPI import) so it is directly unit
testable. The FastAPI layer (``deps.py`` / ``main.py``) calls these functions.

Credential model (matches the OpenAPI security schemes):

- RapidAPI: the gateway injects ``X-RapidAPI-Key`` (the consumer's key),
  ``X-RapidAPI-Host`` (must match the expected host), and, on paid setups,
  ``X-RapidAPI-Proxy-Secret`` (a shared secret proving the request came through
  the gateway and not directly). ``X-RapidAPI-User`` / ``X-RapidAPI-Subscription``
  identify the consumer and their plan slug. Verification is by expected pattern
  and (when configured) the proxy secret, not by obscurity.
- Direct: ``X-API-Key`` is sha256-hashed server-side; the raw key is never stored
  or logged. (Direct-key -> plan resolution is deployment specific and left to
  the caller via ``resolve_direct_plan``.)

Metering rule (plans.yaml): a request is billed only when it is a completed,
terminal feasibility analysis that was NOT served from the 24h dedupe cache.
Auth errors, validation errors, unsupported coverage, insufficient_data, rate
limits, and server errors are never billed.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Mapping, Optional

# Terminal statuses that represent a completed, billable analysis. insufficient_data
# is terminal but not billable (it means the request could not be resolved).
_BILLABLE_STATUSES = frozenset(
    {"likely_feasible", "likely_constrained", "needs_professional_review"}
)


@dataclass
class Credentials:
    """Resolved caller identity."""

    kind: str                       # "rapidapi" | "direct"
    consumer_id: str                # opaque/hashed consumer identifier
    plan_slug: Optional[str] = None  # RapidAPI subscription slug, if provided
    rapidapi_host: Optional[str] = None
    valid: bool = True
    error: Optional[str] = None      # reason string when valid is False


def _get(headers: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive header lookup."""
    if name in headers:
        return headers[name]
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return None


def hash_key(raw: str) -> str:
    """sha256 of an API key. The raw key is never persisted or logged."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_consumer(raw: str) -> str:
    """Opaque, privacy-minimized consumer id (sha256, truncated for readability)."""
    return "c_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def verify_rapidapi_host(host: Optional[str], expected_host: str) -> bool:
    """The incoming X-RapidAPI-Host must match the expected gateway host exactly."""
    return bool(host) and host.strip().lower() == expected_host.strip().lower()


def parse_credentials(
    headers: Mapping[str, str],
    *,
    expected_host: str,
    proxy_secret: Optional[str] = None,
) -> Credentials:
    """Resolve caller credentials from request headers.

    RapidAPI is preferred when its headers are present. The two credential styles
    must not be mixed (sending both RapidAPI headers and an X-API-Key is treated
    as invalid to avoid ambiguity).
    """
    rapid_key = _get(headers, "X-RapidAPI-Key")
    rapid_host = _get(headers, "X-RapidAPI-Host")
    direct_key = _get(headers, "X-API-Key")

    if rapid_key and direct_key:
        return Credentials(
            kind="direct",
            consumer_id="",
            valid=False,
            error="Do not send RapidAPI gateway headers together with X-API-Key.",
        )

    if rapid_key or rapid_host:
        if not verify_rapidapi_host(rapid_host, expected_host):
            return Credentials(
                kind="rapidapi",
                consumer_id="",
                rapidapi_host=rapid_host,
                valid=False,
                error="X-RapidAPI-Host does not match the expected gateway host.",
            )
        if not rapid_key:
            return Credentials(
                kind="rapidapi",
                consumer_id="",
                rapidapi_host=rapid_host,
                valid=False,
                error="Missing X-RapidAPI-Key.",
            )
        # When a proxy secret is configured, it must be present and correct.
        if proxy_secret:
            incoming = _get(headers, "X-RapidAPI-Proxy-Secret")
            if not incoming or incoming != proxy_secret:
                return Credentials(
                    kind="rapidapi",
                    consumer_id="",
                    rapidapi_host=rapid_host,
                    valid=False,
                    error="Invalid or missing X-RapidAPI-Proxy-Secret.",
                )
        # Prefer the stable per-user id; fall back to the key.
        user = _get(headers, "X-RapidAPI-User") or rapid_key
        plan_slug = _get(headers, "X-RapidAPI-Subscription")
        return Credentials(
            kind="rapidapi",
            consumer_id=hash_consumer(user),
            plan_slug=plan_slug,
            rapidapi_host=rapid_host,
            valid=True,
        )

    if direct_key:
        return Credentials(
            kind="direct",
            consumer_id=hash_consumer(hash_key(direct_key)),
            valid=True,
        )

    return Credentials(
        kind="direct",
        consumer_id="",
        valid=False,
        error="Missing API credentials. Provide RapidAPI gateway headers or the "
        "X-API-Key header.",
    )


def resolve_plan_name(creds: Credentials, catalog, *, direct_default: str = "BASIC") -> str:
    """Map credentials to a plan name using the config catalog.

    RapidAPI subscription slug wins when it maps to a known plan; otherwise the
    catalog default is used. Direct keys default to ``direct_default`` (a real
    deployment would look the key hash up in a table).
    """
    if creds.kind == "rapidapi":
        name = catalog.plan_for_rapidapi_slug(creds.plan_slug)
        return name or catalog.default_plan_name
    return direct_default if catalog.get_plan(direct_default) else catalog.default_plan_name


@dataclass
class MeteringDecision:
    billable: bool
    reason: str


def decide_metering(
    *,
    status_code: int,
    feasibility_status: Optional[str],
    cache_hit: bool,
) -> MeteringDecision:
    """Decide whether a completed request is a billable unit.

    A billable unit is exactly one completed, terminal, non-cached feasibility
    analysis. Everything else (errors, unsupported coverage, insufficient_data,
    cache hits) is not billed.
    """
    if status_code != 200:
        return MeteringDecision(False, f"non_200_status:{status_code}")
    if cache_hit:
        return MeteringDecision(False, "cache_hit_within_dedupe_window")
    if feasibility_status not in _BILLABLE_STATUSES:
        return MeteringDecision(False, f"non_billable_status:{feasibility_status}")
    return MeteringDecision(True, "completed_feasibility_analysis")


@dataclass
class QuotaCheck:
    allowed: bool
    used: int
    quota: Optional[int]
    reason: str


def check_monthly_quota(used_this_month: int, monthly_quota: Optional[int]) -> QuotaCheck:
    """Hard-cap monthly quota check (no overages in v1)."""
    if monthly_quota is None:
        return QuotaCheck(True, used_this_month, None, "no_quota_configured")
    if used_this_month >= monthly_quota:
        return QuotaCheck(False, used_this_month, monthly_quota, "quota_exceeded")
    return QuotaCheck(True, used_this_month, monthly_quota, "within_quota")


class InMemoryRateLimiter:
    """Fallback per-consumer burst limiter (fixed-window per minute).

    Used only when the RapidAPI gateway does not enforce rate limits. Thread safe
    for a single process; a multi-process deployment relies on the gateway and on
    ``api_usage_events`` counts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, int]] = {}  # consumer -> (window_start, count)

    def allow(self, consumer_id: str, limit_per_minute: int, *, now: Optional[float] = None) -> bool:
        if limit_per_minute <= 0:
            return True
        ts = int(now if now is not None else time.time())
        window = ts // 60
        with self._lock:
            start, count = self._buckets.get(consumer_id, (window, 0))
            if start != window:
                start, count = window, 0
            if count >= limit_per_minute:
                self._buckets[consumer_id] = (start, count)
                return False
            self._buckets[consumer_id] = (start, count + 1)
            return True
