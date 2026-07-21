"""Service-role Supabase access for the OFFLINE code pipeline.

Writes only the tables this component owns or feeds:
  source_registry (reconciled from config), source_snapshots (immutable,
  content-hashed, append-only), zoning_sections, zoning_rules (candidates),
  rule_attributes, qa_issues, ingest_runs. Reads jurisdictions and
  state_rule_baselines.

Raw snapshot bytes are uploaded to Supabase Storage (best-effort); the DB row
records the content hash + storage path. History is never overwritten: a changed
capture is a NEW snapshot version, and identical captures dedup on content_hash.

The service-role key is read from Settings (env) and never logged. This module
is OFFLINE-only and must not be imported by the request path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from normalize import sha256_bytes

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# review_status for freshly extracted, human-unverified candidates. The DB
# CHECK constraint (migration 0005) allows pending|in_review|verified|rejected|
# superseded; 'pending' is the schema's representation of "extracted, awaiting
# review". We NEVER write 'verified' automatically.
REVIEW_STATUS_CANDIDATE = "pending"

# rule_attributes / zoning_rules compliance_flag vocabulary (DB CHECK).
FLAG_MATCHES = "matches_state_baseline"
FLAG_MORE_RESTRICTIVE = "possibly_more_restrictive_than_state_baseline"
FLAG_NEEDS_REVIEW = "needs_review"
FLAG_NOT_APPLICABLE = "not_applicable"


class CodeStore:
    """Thin service-role wrapper over the ADU Atlas schema for code ingestion."""

    def __init__(self, settings: Any) -> None:
        if not settings.has_supabase:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for DB access."
            )
        from supabase import create_client

        self._settings = settings
        self._client = create_client(
            settings.supabase_url, settings.supabase_service_role_key
        )

    @property
    def client(self):
        return self._client

    # ------------------------------------------------------------------
    # jurisdictions
    # ------------------------------------------------------------------
    def get_jurisdiction(self, slug: str) -> dict[str, Any] | None:
        res = (
            self._client.table("jurisdictions")
            .select("id, slug, name, coverage_status, supported_project_types")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # source_registry (reconciled from config/sources.yaml)
    # ------------------------------------------------------------------
    def ensure_source_registry(
        self, jurisdiction_id: str, source_cfg: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the source_registry row for a jurisdiction's municipal code.

        Reconciles from config: upserts on (jurisdiction_id, source_type, url).
        Never fabricates data - only registers the official source so snapshots
        and sections can reference it.
        """
        url = str(source_cfg.get("base_url") or "")
        publisher = str(source_cfg.get("publisher") or "other")
        existing = (
            self._client.table("source_registry")
            .select("*")
            .eq("jurisdiction_id", jurisdiction_id)
            .eq("source_type", "municipal_code")
            .eq("url", url)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            return existing[0]

        payload = {
            "jurisdiction_id": jurisdiction_id,
            "source_type": "municipal_code",
            "provider": publisher if publisher in _KNOWN_PROVIDERS else "other",
            "name": source_cfg.get("name") or f"{publisher} municipal code",
            "description": source_cfg.get("name"),
            "url": url,
            "endpoint": source_cfg.get("rest_service_url"),
            "license_notes": source_cfg.get("license_or_terms_notes"),
            "publisher": publisher,
            "active": True,
            "last_checked_at": _now_iso(),
        }
        inserted = (
            self._client.table("source_registry").insert(payload).execute()
        ).data
        return inserted[0]

    def touch_source_checked(
        self, source_registry_id: str, *, etag: str | None, last_modified: str | None
    ) -> None:
        self._client.table("source_registry").update(
            {
                "last_checked_at": _now_iso(),
                "last_retrieved_at": _now_iso(),
                "etag": etag,
                "last_modified": last_modified,
            }
        ).eq("id", source_registry_id).execute()

    # ------------------------------------------------------------------
    # source_snapshots (immutable, content-hashed, append-only)
    # ------------------------------------------------------------------
    def create_snapshot(
        self,
        *,
        source_registry_id: str,
        jurisdiction_id: str | None,
        raw_bytes: bytes,
        content_type: str = "text/html",
        http_status: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        retrieved_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Insert (or dedup) an immutable snapshot. Returns (snapshot_id, created).

        Dedup key is (source_registry_id, content_hash): an identical capture
        reuses the existing snapshot. Otherwise a new monotonic version row is
        inserted and the raw bytes are uploaded to Storage (best-effort).
        """
        digest = sha256_bytes(raw_bytes)
        existing = (
            self._client.table("source_snapshots")
            .select("id")
            .eq("source_registry_id", source_registry_id)
            .eq("content_hash", digest)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            return existing[0]["id"], False

        version = self._next_snapshot_version(source_registry_id)
        storage_path = self._upload_snapshot(
            source_registry_id, version, digest, raw_bytes, content_type
        )
        payload = {
            "source_registry_id": source_registry_id,
            "jurisdiction_id": jurisdiction_id,
            "version": version,
            "content_hash": digest,
            "storage_path": storage_path,
            "content_type": content_type,
            "byte_size": len(raw_bytes),
            "http_status": http_status,
            "etag": etag,
            "last_modified": last_modified,
            "retrieved_at": retrieved_at or _now_iso(),
            "metadata": metadata or {},
        }
        inserted = (
            self._client.table("source_snapshots").insert(payload).execute()
        ).data
        return inserted[0]["id"], True

    def _next_snapshot_version(self, source_registry_id: str) -> int:
        res = (
            self._client.table("source_snapshots")
            .select("version")
            .eq("source_registry_id", source_registry_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return (res[0]["version"] + 1) if res else 1

    def _upload_snapshot(
        self,
        source_registry_id: str,
        version: int,
        digest: str,
        raw_bytes: bytes,
        content_type: str,
    ) -> str | None:
        if not self._settings.upload_snapshots_to_storage:
            return None
        bucket = self._settings.storage_bucket
        path = f"{source_registry_id}/{version:06d}-{digest[:16]}.html"
        try:
            self._client.storage.from_(bucket).upload(
                path,
                raw_bytes,
                {"content-type": content_type, "upsert": "false"},
            )
            return f"{bucket}/{path}"
        except Exception as exc:  # bucket missing / permission / already exists
            logger.warning(
                "snapshot storage upload failed (%s/%s): %s; recording hash only",
                bucket,
                path,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # zoning_sections
    # ------------------------------------------------------------------
    def upsert_zoning_section(
        self,
        *,
        jurisdiction_id: str,
        source_registry_id: str | None,
        source_snapshot_id: str | None,
        section_url: str,
        raw_text: str,
        content_hash: str,
        code_title: str | None = None,
        title_number: str | None = None,
        chapter_number: str | None = None,
        section_number: str | None = None,
        section_label: str | None = None,
        heading: str | None = None,
        confidence: str = "medium",
        retrieved_at: str | None = None,
    ) -> tuple[str, str]:
        """Insert/update one zoning_sections row. Returns (outcome, section_id).

        outcome is 'inserted' | 'updated' | 'unchanged'. Unchanged rows (same
        content_hash) are not rewritten, but the snapshot link is refreshed so
        provenance always points at the latest immutable capture.
        """
        existing = (
            self._client.table("zoning_sections")
            .select("id, content_hash")
            .eq("jurisdiction_id", jurisdiction_id)
            .eq("section_url", section_url)
            .limit(1)
            .execute()
        ).data or []

        base = {
            "jurisdiction_id": jurisdiction_id,
            "source_registry_id": source_registry_id,
            "source_snapshot_id": source_snapshot_id,
            "section_url": section_url,
            "raw_text": raw_text,
            "content_hash": content_hash,
            "code_title": code_title,
            "title_number": title_number,
            "chapter_number": chapter_number,
            "section_number": section_number,
            "section_label": section_label,
            "heading": heading,
            "confidence": confidence,
            "data_status": "current",
            "retrieved_at": retrieved_at or _now_iso(),
        }

        if not existing:
            row = (
                self._client.table("zoning_sections").insert(base).execute()
            ).data[0]
            return "inserted", row["id"]

        section_id = existing[0]["id"]
        if existing[0].get("content_hash") == content_hash:
            # Content stable: only refresh the snapshot pointer + retrieved_at.
            self._client.table("zoning_sections").update(
                {
                    "source_snapshot_id": source_snapshot_id,
                    "source_registry_id": source_registry_id,
                    "retrieved_at": base["retrieved_at"],
                }
            ).eq("id", section_id).execute()
            return "unchanged", section_id

        self._client.table("zoning_sections").update(base).eq(
            "id", section_id
        ).execute()
        return "updated", section_id

    def get_zoning_sections(
        self, jurisdiction_id: str, *, only_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        query = (
            self._client.table("zoning_sections")
            .select(
                "id, jurisdiction_id, source_registry_id, source_snapshot_id, "
                "section_url, section_label, code_title, title_number, chapter_number, "
                "section_number, heading, raw_text, content_hash, updated_at"
            )
            .eq("jurisdiction_id", jurisdiction_id)
        )
        if only_ids:
            query = query.in_("id", only_ids)
        return query.execute().data or []

    # ------------------------------------------------------------------
    # zoning_rules (candidates) + rule_attributes
    # ------------------------------------------------------------------
    def latest_rule(
        self, jurisdiction_id: str, zone_code: str, project_type: str
    ) -> dict[str, Any] | None:
        res = (
            self._client.table("zoning_rules")
            .select("id, version, review_status, is_current")
            .eq("jurisdiction_id", jurisdiction_id)
            .eq("zone_code", zone_code)
            .eq("project_type", project_type)
            .order("version", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return res[0] if res else None

    def upsert_candidate_rule(
        self,
        *,
        jurisdiction_id: str,
        zone_code: str,
        zone_name: str | None,
        project_type: str,
        zoning_section_id: str | None,
        source_registry_id: str | None,
        source_snapshot_id: str | None,
        summary: str | None,
        confidence: str,
        retrieved_at: str | None = None,
    ) -> str:
        """Create or refresh a candidate zoning_rules row. Returns its id.

        - No prior row            -> insert version 1, review_status=pending.
        - Prior row is a pending  -> refresh it in place (still a candidate).
          candidate
        - Prior row is verified / -> insert a NEW version as a pending candidate;
          in_review / rejected /     the reviewed row is never overwritten.
          superseded
        """
        latest = self.latest_rule(jurisdiction_id, zone_code, project_type)
        payload = {
            "jurisdiction_id": jurisdiction_id,
            "zone_code": zone_code,
            "zone_name": zone_name,
            "project_type": project_type,
            "zoning_section_id": zoning_section_id,
            "source_registry_id": source_registry_id,
            "source_snapshot_id": source_snapshot_id,
            "summary": summary,
            "review_status": REVIEW_STATUS_CANDIDATE,
            "compliance_flag": FLAG_NEEDS_REVIEW,
            "confidence": confidence,
            "data_status": "current",
            # Candidates are NOT current until a human verifies them, so the
            # deterministic request path (which serves is_current + verified
            # rules) can never accidentally return unreviewed extraction output.
            "is_current": False,
            "retrieved_at": retrieved_at or _now_iso(),
        }

        if latest is None:
            payload["version"] = 1
            return (self._client.table("zoning_rules").insert(payload).execute()).data[0][
                "id"
            ]

        if latest.get("review_status") == REVIEW_STATUS_CANDIDATE:
            rule_id = latest["id"]
            self._client.table("zoning_rules").update(payload).eq("id", rule_id).execute()
            return rule_id

        # Reviewed row exists: add a new version rather than overwrite it.
        payload["version"] = int(latest.get("version") or 1) + 1
        return (self._client.table("zoning_rules").insert(payload).execute()).data[0]["id"]

    def replace_rule_attributes(
        self, zoning_rule_id: str, attributes: list[dict[str, Any]]
    ) -> int:
        """Replace all rule_attributes for a candidate rule. Returns count written."""
        self._client.table("rule_attributes").delete().eq(
            "zoning_rule_id", zoning_rule_id
        ).execute()
        if not attributes:
            return 0
        rows = [dict(a, zoning_rule_id=zoning_rule_id) for a in attributes]
        self._client.table("rule_attributes").insert(rows).execute()
        return len(rows)

    def get_candidate_rules(self, jurisdiction_id: str) -> list[dict[str, Any]]:
        return (
            self._client.table("zoning_rules")
            .select("id, zone_code, zone_name, project_type, review_status, version")
            .eq("jurisdiction_id", jurisdiction_id)
            .eq("review_status", REVIEW_STATUS_CANDIDATE)
            .execute()
        ).data or []

    def get_rule_attributes(self, zoning_rule_id: str) -> list[dict[str, Any]]:
        return (
            self._client.table("rule_attributes")
            .select("*")
            .eq("zoning_rule_id", zoning_rule_id)
            .execute()
        ).data or []

    def update_rule_attribute(self, attribute_id: str, fields: dict[str, Any]) -> None:
        self._client.table("rule_attributes").update(fields).eq(
            "id", attribute_id
        ).execute()

    def update_zoning_rule(self, rule_id: str, fields: dict[str, Any]) -> None:
        self._client.table("zoning_rules").update(fields).eq("id", rule_id).execute()

    # ------------------------------------------------------------------
    # state_rule_baselines (read)
    # ------------------------------------------------------------------
    def get_state_baselines(self) -> list[dict[str, Any]]:
        return (
            self._client.table("state_rule_baselines")
            .select(
                "id, field_name, applies_to, operator, baseline_value_json, unit, "
                "legal_citation, source_url, source_title, effective_to"
            )
            .is_("effective_to", "null")
            .execute()
        ).data or []

    # ------------------------------------------------------------------
    # qa_issues
    # ------------------------------------------------------------------
    def create_qa_issue(self, payload: dict[str, Any]) -> str:
        row = dict(payload)
        row.setdefault("created_at", _now_iso())
        return (self._client.table("qa_issues").insert(row).execute()).data[0]["id"]

    def find_open_qa_issue(
        self, *, zoning_rule_id: str, field_name: str, issue_type: str
    ) -> dict[str, Any] | None:
        res = (
            self._client.table("qa_issues")
            .select("id, status")
            .eq("zoning_rule_id", zoning_rule_id)
            .eq("field_name", field_name)
            .eq("issue_type", issue_type)
            .in_("status", ["open", "in_review"])
            .limit(1)
            .execute()
        ).data or []
        return res[0] if res else None

    # ------------------------------------------------------------------
    # ingest_runs
    # ------------------------------------------------------------------
    def start_ingest_run(
        self,
        *,
        jurisdiction_id: str | None,
        source_registry_id: str | None,
        run_type: str,
        triggered_by: str,
    ) -> str:
        payload = {
            "jurisdiction_id": jurisdiction_id,
            "source_registry_id": source_registry_id,
            "run_type": run_type,
            "status": "running",
            "triggered_by": triggered_by,
            "started_at": _now_iso(),
        }
        return (self._client.table("ingest_runs").insert(payload).execute()).data[0]["id"]

    def finish_ingest_run(
        self,
        run_id: str,
        *,
        status: str,
        processed: int = 0,
        inserted: int = 0,
        updated: int = 0,
        failed: int = 0,
        error_message: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        self._client.table("ingest_runs").update(
            {
                "status": status,
                "finished_at": _now_iso(),
                "records_processed": processed,
                "records_inserted": inserted,
                "records_updated": updated,
                "records_failed": failed,
                "error_message": error_message,
                "stats": stats or {},
            }
        ).eq("id", run_id).execute()


_KNOWN_PROVIDERS = {
    "american_legal",
    "municode",
    "arcgis",
    "fema",
    "cal_fire",
    "hcd",
    "ca_open_data",
    "census",
    "other",
}
