"""Read-only loader for config/jurisdictions.yaml and config/sources.yaml.

These YAML files are the config-driven source of truth for which jurisdictions
exist, their coverage status, and the official municipal-code source (publisher,
base URL, license notes) backing each one. This module only READS them; it never
writes config. Ingestion uses it to look up the code source for a jurisdiction
and to seed / reconcile the source_registry row for that source.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


class RegistryError(RuntimeError):
    """Raised when config is missing a jurisdiction or its code source."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RegistryError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise RegistryError(f"config file is not a mapping: {path}")
    return data


@lru_cache(maxsize=8)
def _jurisdictions_doc(config_dir_str: str) -> dict[str, Any]:
    return _load_yaml(Path(config_dir_str) / "jurisdictions.yaml")


@lru_cache(maxsize=8)
def _sources_doc(config_dir_str: str) -> dict[str, Any]:
    return _load_yaml(Path(config_dir_str) / "sources.yaml")


def load_jurisdictions(config_dir: Path) -> list[dict[str, Any]]:
    doc = _jurisdictions_doc(str(config_dir))
    return list(doc.get("jurisdictions", []) or [])


def load_sources(config_dir: Path) -> list[dict[str, Any]]:
    doc = _sources_doc(str(config_dir))
    return list(doc.get("sources", []) or [])


def get_jurisdiction(config_dir: Path, slug: str) -> dict[str, Any]:
    for j in load_jurisdictions(config_dir):
        if j.get("slug") == slug:
            return j
    raise RegistryError(
        f"jurisdiction '{slug}' not found in {config_dir / 'jurisdictions.yaml'}"
    )


def code_publisher_for(config_dir: Path, slug: str) -> str:
    """'american_legal' | 'municode' for a jurisdiction (from config)."""
    return str(get_jurisdiction(config_dir, slug).get("publisher_type", "")).strip()


def municipal_code_source(config_dir: Path, slug: str) -> dict[str, Any]:
    """Return the config/sources.yaml row for a jurisdiction's municipal code.

    Matches on source_type == 'municipal_code' and jurisdiction_slug == slug.
    """
    for src in load_sources(config_dir):
        if (
            src.get("source_type") == "municipal_code"
            and src.get("jurisdiction_slug") == slug
        ):
            return src
    raise RegistryError(
        f"no municipal_code source for '{slug}' in {config_dir / 'sources.yaml'}"
    )


def code_jurisdiction_slugs(config_dir: Path) -> list[str]:
    """Slugs that have a municipal_code source configured."""
    slugs: list[str] = []
    for src in load_sources(config_dir):
        if src.get("source_type") == "municipal_code":
            slug = src.get("jurisdiction_slug")
            if slug and slug not in slugs:
                slugs.append(slug)
    return slugs


if __name__ == "__main__":  # offline self-check against the real repo config
    from config import Settings

    cfg = Settings.from_env(require_supabase=False).config_dir
    js = load_jurisdictions(cfg)
    assert any(j.get("slug") == "los_angeles" for j in js), "LA missing from config"
    la_src = municipal_code_source(cfg, "los_angeles")
    assert la_src.get("publisher") == "american_legal", la_src
    assert code_publisher_for(cfg, "los_angeles") == "american_legal"
    assert "los_angeles" in code_jurisdiction_slugs(cfg)
    print(
        f"registry OK: {len(js)} jurisdictions, "
        f"{len(code_jurisdiction_slugs(cfg))} with code sources"
    )
