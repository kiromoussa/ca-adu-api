"""Municipal-code ingestion orchestrator (OFFLINE).

For one jurisdiction: resolve its config + DB rows, register the code source,
then stream sections from the publisher fetcher. Each section is captured as an
immutable content-hashed source_snapshot and written to zoning_sections with a
provenance link to that snapshot. No LLM here - this is pure retrieval + storage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import registry
from config import Settings
from db import CodeStore
from fetchers import FetchedSection, fetcher_for

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    slug: str
    discovered: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    snapshots_created: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def sections_written(self) -> int:
        return self.inserted + self.updated

    @property
    def ok(self) -> bool:
        return (self.inserted + self.updated + self.unchanged) > 0


def _save_local_snapshot(
    settings: Settings, slug: str, section: FetchedSection
) -> None:
    """Best-effort local copy of the raw capture (resilience beside Storage)."""
    if not settings.save_local_snapshots:
        return
    try:
        from normalize import sha256_bytes

        directory = Path(settings.snapshot_dir) / slug
        directory.mkdir(parents=True, exist_ok=True)
        digest = sha256_bytes(section.raw_bytes)[:12]
        tail = section.section_url.rstrip("/").split("/")[-1][:60] or "index"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tail)
        (directory / f"{safe}.{digest}.html").write_bytes(section.raw_bytes)
    except OSError as exc:  # pragma: no cover - best-effort
        logger.warning("[%s] local snapshot failed: %s", slug, exc)


def ingest_jurisdiction(
    slug: str,
    settings: Settings,
    store: CodeStore,
    *,
    triggered_by: str = "manual",
) -> IngestResult:
    """Ingest municipal code for one jurisdiction slug."""
    result = IngestResult(slug=slug)

    jurisdiction = store.get_jurisdiction(slug)
    if jurisdiction is None:
        msg = (
            f"jurisdiction '{slug}' not found in the database. Seed jurisdictions "
            f"first (config/jurisdictions.yaml)."
        )
        logger.error("[%s] %s", slug, msg)
        result.errors.append(msg)
        return result

    try:
        source_cfg = registry.municipal_code_source(settings.config_dir, slug)
    except registry.RegistryError as exc:
        logger.error("[%s] %s", slug, exc)
        result.errors.append(str(exc))
        return result

    publisher = str(source_cfg.get("publisher") or "")
    fetcher_cls = fetcher_for(publisher)
    if fetcher_cls is None:
        msg = f"unknown publisher '{publisher}' for {slug}"
        logger.error("[%s] %s", slug, msg)
        result.errors.append(msg)
        return result

    source_row = store.ensure_source_registry(jurisdiction["id"], source_cfg)
    run_id = store.start_ingest_run(
        jurisdiction_id=jurisdiction["id"],
        source_registry_id=source_row["id"],
        run_type="code",
        triggered_by=triggered_by,
    )

    coverage = jurisdiction.get("coverage_status")
    if coverage == "planned":
        logger.info(
            "[%s] coverage_status=planned; ingesting into staging (not yet "
            "production-served).",
            slug,
        )

    fetcher = fetcher_cls(jurisdiction=jurisdiction, source=source_cfg, settings=settings)
    last_etag: str | None = None
    last_modified: str | None = None

    try:
        for section in fetcher.run():
            result.discovered += 1
            last_etag = section.etag or last_etag
            last_modified = section.last_modified or last_modified
            try:
                _save_local_snapshot(settings, slug, section)
                snapshot_id, created = store.create_snapshot(
                    source_registry_id=source_row["id"],
                    jurisdiction_id=jurisdiction["id"],
                    raw_bytes=section.raw_bytes,
                    content_type=section.content_type,
                    http_status=section.http_status,
                    etag=section.etag,
                    last_modified=section.last_modified,
                    retrieved_at=section.retrieved_at,
                    metadata={
                        "section_url": section.section_url,
                        "section_label": section.section_label,
                        "publisher": publisher,
                    },
                )
                if created:
                    result.snapshots_created += 1

                outcome, _section_id = store.upsert_zoning_section(
                    jurisdiction_id=jurisdiction["id"],
                    source_registry_id=source_row["id"],
                    source_snapshot_id=snapshot_id,
                    section_url=section.section_url,
                    raw_text=section.text,
                    content_hash=section.content_hash,
                    code_title=section.code_title,
                    title_number=section.title_number,
                    chapter_number=section.chapter_number,
                    section_number=section.section_number,
                    section_label=section.section_label,
                    heading=section.title,
                    confidence="medium",
                    retrieved_at=section.retrieved_at,
                )
                if outcome == "inserted":
                    result.inserted += 1
                elif outcome == "updated":
                    result.updated += 1
                else:
                    result.unchanged += 1
                logger.info("[%s] %s %s", slug, outcome, section.section_url)
            except Exception as exc:  # one bad section never aborts the run
                result.failed += 1
                result.errors.append(f"{section.section_url}: {exc}")
                logger.exception("[%s] failed writing %s", slug, section.section_url)

        try:
            store.touch_source_checked(
                source_row["id"], etag=last_etag, last_modified=last_modified
            )
        except Exception:  # pragma: no cover - non-fatal
            logger.warning("[%s] could not stamp source_registry", slug)

        status = "success" if result.ok else ("partial" if result.failed else "success")
        if not result.ok and result.discovered == 0:
            status = "failed"
        store.finish_ingest_run(
            run_id,
            status=status,
            processed=result.discovered,
            inserted=result.inserted,
            updated=result.updated,
            failed=result.failed,
            stats={
                "unchanged": result.unchanged,
                "snapshots_created": result.snapshots_created,
            },
        )
    except Exception as exc:
        logger.exception("[%s] ingestion aborted", slug)
        result.errors.append(str(exc))
        store.finish_ingest_run(
            run_id,
            status="failed",
            processed=result.discovered,
            inserted=result.inserted,
            updated=result.updated,
            failed=result.failed,
            error_message=str(exc),
        )

    logger.info(
        "[%s] ingest done: discovered=%d inserted=%d updated=%d unchanged=%d "
        "failed=%d snapshots=%d",
        slug,
        result.discovered,
        result.inserted,
        result.updated,
        result.unchanged,
        result.failed,
        result.snapshots_created,
    )
    return result
