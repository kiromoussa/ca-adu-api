"""Runtime configuration for the scraper worker.

All secrets are read from the environment. Nothing is hard-coded. On Render the
two required values (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) are declared in
render.yaml as sync:false and injected by the dashboard.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load a local .env when present. This is a no-op in production (Render injects
# real env vars), and python-dotenv is an optional convenience for local runs.
try:  # pragma: no cover - import guard only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "ca-adu-zoning-api-scraper/0.1 (+https://github.com/ca-adu-api)"
)


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot built from the environment."""

    supabase_url: str
    supabase_service_role_key: str

    # Playwright / networking
    headless: bool = True
    user_agent: str = _DEFAULT_UA
    nav_timeout_ms: int = 45_000
    selector_timeout_ms: int = 15_000

    # politeness + resilience
    rate_limit_seconds: float = 2.0
    max_retries: int = 3
    max_sections_per_city: int = 25

    # filesystem
    snapshot_dir: Path = field(default_factory=lambda: Path("scraper/snapshots"))
    save_snapshots: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the "
                "environment. On Render they are declared in render.yaml "
                "(sync:false) and set in the dashboard; locally put them in a "
                ".env file or export them in your shell."
            )

        snapshot_dir = Path(
            os.environ.get("SCRAPER_SNAPSHOT_DIR", "scraper/snapshots")
        )

        return cls(
            supabase_url=url,
            supabase_service_role_key=key,
            headless=_env_bool("SCRAPER_HEADLESS", True),
            user_agent=os.environ.get("SCRAPER_USER_AGENT", _DEFAULT_UA),
            nav_timeout_ms=_env_int("SCRAPER_NAV_TIMEOUT_MS", 45_000),
            selector_timeout_ms=_env_int("SCRAPER_SELECTOR_TIMEOUT_MS", 15_000),
            rate_limit_seconds=_env_float("SCRAPER_RATE_LIMIT_SECONDS", 2.0),
            max_retries=_env_int("SCRAPER_MAX_RETRIES", 3),
            max_sections_per_city=_env_int("SCRAPER_MAX_SECTIONS_PER_CITY", 25),
            snapshot_dir=snapshot_dir,
            save_snapshots=_env_bool("SCRAPER_SAVE_SNAPSHOTS", True),
        )
