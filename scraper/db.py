"""Supabase client wrapper (service role).

Thin layer over supabase-py that the scraper uses to read the city registry and
upsert scraped sections. Writes go through the service role key, which RLS
(migration 0002) grants full write access; the raw key is read from the
environment and never logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseWriter:
    """Service-role Supabase access for the scraper."""

    def __init__(self, url: str, service_role_key: str) -> None:
        if not url or not service_role_key:
            raise ValueError("Supabase url and service role key are required.")
        self._client: Client = create_client(url, service_role_key)

    @property
    def client(self) -> Client:
        return self._client

    # ------------------------------------------------------------------
    # cities
    # ------------------------------------------------------------------
    def get_cities(self) -> list[dict[str, Any]]:
        """Return all rows from the cities table."""
        res = (
            self._client.table("cities")
            .select("id, name, slug, publisher_type, base_url, last_scraped_at")
            .order("name")
            .execute()
        )
        return list(res.data or [])

    def touch_city_scraped(self, city_id: str) -> None:
        """Stamp cities.last_scraped_at = now() for one city."""
        self._client.table("cities").update(
            {"last_scraped_at": _utc_now_iso()}
        ).eq("id", city_id).execute()

    # ------------------------------------------------------------------
    # zoning_sections
    # ------------------------------------------------------------------
    def get_section_hash(self, city_id: str, section_url: str) -> str | None:
        """Return the stored content_hash for a section, or None if new."""
        res = (
            self._client.table("zoning_sections")
            .select("content_hash")
            .eq("city_id", city_id)
            .eq("section_url", section_url)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0].get("content_hash")
        return None

    def upsert_zoning_section(
        self,
        *,
        city_id: str,
        section_url: str,
        raw_text: str,
        content_hash: str,
        title_number: str | None = None,
        chapter_number: str | None = None,
        section_number: str | None = None,
    ) -> str:
        """Insert or update one zoning_sections row.

        Returns one of: "inserted", "updated", "unchanged". Skips the write
        entirely when the content_hash is unchanged so weekly runs do not churn
        last_updated on stable ordinances.
        """
        existing_hash = self.get_section_hash(city_id, section_url)
        if existing_hash is not None and existing_hash == content_hash:
            return "unchanged"

        payload: dict[str, Any] = {
            "city_id": city_id,
            "section_url": section_url,
            "raw_text": raw_text,
            "content_hash": content_hash,
            "title_number": title_number,
            "chapter_number": chapter_number,
            "section_number": section_number,
            "last_updated": _utc_now_iso(),
        }

        # (city_id, section_url) is the unique constraint from migration 0001.
        self._client.table("zoning_sections").upsert(
            payload, on_conflict="city_id,section_url"
        ).execute()

        return "inserted" if existing_hash is None else "updated"
