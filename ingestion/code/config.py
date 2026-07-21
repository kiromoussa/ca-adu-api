"""Runtime configuration for the OFFLINE code-ingestion + extraction + QA jobs.

All secrets come from the environment - nothing is hard-coded:
  - SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (DB writes; service role)
  - AZURE_OPENAI_ENDPOINT (ending in /openai/v1), AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT (e.g. gpt-5.4), AZURE_OPENAI_API_VERSION (optional)

Politeness / resilience / snapshot options have safe defaults and env overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Optional local .env convenience (no-op in production where env is injected).
try:  # pragma: no cover - import guard only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
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
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "adu-atlas-code-ingestion/0.1 (+https://github.com/ca-adu-api)"
)


def _default_config_dir() -> Path:
    """Repo config/ dir (ingestion/code/config.py -> parents[2] == repo root)."""
    override = os.environ.get("ADU_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config"


def _default_snapshot_dir() -> Path:
    override = os.environ.get("ADU_SNAPSHOT_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "snapshots"


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot built from the environment."""

    supabase_url: str
    supabase_service_role_key: str

    # Azure OpenAI (offline extraction only; may be blank until extract runs).
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    extraction_max_tokens: int = 16_000

    # HTTP / Playwright politeness + resilience.
    user_agent: str = _DEFAULT_UA
    nav_timeout_ms: int = 45_000
    selector_timeout_ms: int = 15_000
    rate_limit_seconds: float = 2.0
    max_retries: int = 3
    max_sections_per_jurisdiction: int = 25
    headless: bool = True

    # Immutable-snapshot options.
    config_dir: Path = field(default_factory=_default_config_dir)
    snapshot_dir: Path = field(default_factory=_default_snapshot_dir)
    save_local_snapshots: bool = True
    storage_bucket: str = "source-snapshots"
    upload_snapshots_to_storage: bool = True

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def has_azure_openai(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    @classmethod
    def from_env(cls, *, require_supabase: bool = True) -> "Settings":
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if require_supabase and (not url or not key):
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. On Render "
                "they are declared in render.yaml (sync:false); locally put them "
                "in a .env file or export them."
            )

        return cls(
            supabase_url=url,
            supabase_service_role_key=key,
            azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip(),
            azure_openai_api_key=os.environ.get("AZURE_OPENAI_API_KEY", "").strip(),
            azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip(),
            azure_openai_api_version=os.environ.get(
                "AZURE_OPENAI_API_VERSION", "2024-10-21"
            ).strip(),
            extraction_max_tokens=_env_int("EXTRACTION_MAX_TOKENS", 16_000),
            user_agent=os.environ.get("ADU_CODE_USER_AGENT", _DEFAULT_UA),
            nav_timeout_ms=_env_int("ADU_CODE_NAV_TIMEOUT_MS", 45_000),
            selector_timeout_ms=_env_int("ADU_CODE_SELECTOR_TIMEOUT_MS", 15_000),
            rate_limit_seconds=_env_float("ADU_CODE_RATE_LIMIT_SECONDS", 2.0),
            max_retries=_env_int("ADU_CODE_MAX_RETRIES", 3),
            max_sections_per_jurisdiction=_env_int(
                "ADU_CODE_MAX_SECTIONS_PER_JURISDICTION", 25
            ),
            headless=_env_bool("ADU_CODE_HEADLESS", True),
            config_dir=_default_config_dir(),
            snapshot_dir=_default_snapshot_dir(),
            save_local_snapshots=_env_bool("ADU_CODE_SAVE_LOCAL_SNAPSHOTS", True),
            storage_bucket=os.environ.get(
                "ADU_SNAPSHOT_BUCKET", "source-snapshots"
            ).strip(),
            upload_snapshots_to_storage=_env_bool(
                "ADU_UPLOAD_SNAPSHOTS", True
            ),
        )


if __name__ == "__main__":  # offline self-check (no env required)
    s = Settings.from_env(require_supabase=False)
    assert s.config_dir.name == "config", s.config_dir
    assert s.azure_openai_api_version
    print("config OK (config_dir=%s)" % s.config_dir)
