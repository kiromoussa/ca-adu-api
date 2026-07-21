"""Environment- and config-driven settings.

Secrets and connection strings come from the environment (never hard-coded).
Plan tiers, quotas, and metering behavior come from ``config/plans.yaml`` - the
single source of truth - not from constants in code.

The YAML loaders import ``yaml`` lazily so this module (and anything that only
needs env values) imports even in a minimal environment; ``PlanCatalog`` can
also be constructed directly from a dict, which is what unit tests do.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


def _repo_root() -> Path:
    # services/api/settings.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[2]


def _config_dir() -> Path:
    override = os.environ.get("ADU_CONFIG_DIR")
    if override:
        return Path(override)
    return _repo_root() / "config"


class PlanCatalog:
    """Read-only view over the plans/billing/metering config."""

    def __init__(self, data: dict[str, Any]):
        self._data = data or {}
        self._plans: dict[str, dict[str, Any]] = self._data.get("plans", {}) or {}
        # Map RapidAPI plan slug -> plan name for gateway subscription resolution.
        self._by_slug: dict[str, str] = {}
        for name, plan in self._plans.items():
            slug = plan.get("rapidapi_plan_slug")
            if slug:
                self._by_slug[str(slug).lower()] = name

    @property
    def plan_names(self) -> list[str]:
        return list(self._plans.keys())

    @property
    def default_plan_name(self) -> str:
        return "BASIC" if "BASIC" in self._plans else (self.plan_names[0] if self.plan_names else "BASIC")

    def get_plan(self, name: Optional[str]) -> Optional[dict[str, Any]]:
        if not name:
            return None
        return self._plans.get(name) or self._plans.get(name.upper())

    def plan_for_rapidapi_slug(self, slug: Optional[str]) -> Optional[str]:
        if not slug:
            return None
        return self._by_slug.get(str(slug).lower())

    def monthly_quota(self, name: str) -> Optional[int]:
        plan = self.get_plan(name)
        return plan.get("monthly_quota") if plan else None

    def rate_limit_per_minute(self, name: str) -> int:
        plan = self.get_plan(name)
        if plan and plan.get("rate_limit_per_minute"):
            return int(plan["rate_limit_per_minute"])
        return int(
            self._data.get("metering", {})
            .get("burst_limiter", {})
            .get("default_requests_per_minute", 60)
        )

    def dedupe_window_hours(self) -> int:
        return int(self._data.get("billing", {}).get("dedupe", {}).get("window_hours", 24))

    def idempotency_window_hours(self) -> int:
        return int(
            self._data.get("billing", {})
            .get("dedupe", {})
            .get("idempotency", {})
            .get("window_hours", 24)
        )


@lru_cache(maxsize=1)
def load_plan_catalog() -> PlanCatalog:
    """Load ``config/plans.yaml`` into a :class:`PlanCatalog` (cached)."""
    import yaml

    path = _config_dir() / "plans.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return PlanCatalog(data)


class Settings:
    """Runtime settings resolved from the environment."""

    def __init__(self) -> None:
        self.db_url: Optional[str] = os.environ.get("SUPABASE_DB_URL")
        self.supabase_url: Optional[str] = os.environ.get("SUPABASE_URL")
        self.service_role_key: Optional[str] = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        # Expected RapidAPI gateway host (verified against the incoming header).
        self.rapidapi_host: str = os.environ.get("RAPIDAPI_HOST", "aduatlas.p.rapidapi.com")
        # Shared secret the RapidAPI gateway injects as X-RapidAPI-Proxy-Secret.
        self.rapidapi_proxy_secret: Optional[str] = os.environ.get("RAPIDAPI_PROXY_SECRET")
        # Optional: direct (non-RapidAPI) API keys, mapping sha256(key)->plan.
        self.geocoder_timeout_s: float = float(os.environ.get("GEOCODER_TIMEOUT_S", "8"))
        self.request_timeout_s: float = float(os.environ.get("REQUEST_TIMEOUT_S", "20"))
        self.enable_share_tokens: bool = os.environ.get("ENABLE_SHARE_TOKENS", "true").lower() == "true"

    @property
    def has_db(self) -> bool:
        return bool(self.db_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
