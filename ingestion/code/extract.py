"""OFFLINE LLM extraction of ADU rule CANDIDATES from zoning_sections.

This runs OFFLINE only, never on the API request path. For each zoning_section
it asks an LLM to read the raw code text and emit structured per-zone-district
standards (value + per-field confidence + verbatim evidence), strictly conforming
to schema.EXTRACTION_SCHEMA. Each extracted zone is split into per-project_type
candidate zoning_rules rows (review_status='pending' - NEVER auto-verified) with
one rule_attributes row per field, each carrying full provenance.

Provider: Azure OpenAI via the v1 endpoint (AZURE_OPENAI_ENDPOINT ending in
/openai/v1) using the OpenAI client with base_url + bearer key,
AZURE_OPENAI_DEPLOYMENT as the model, and max_completion_tokens. A classic Azure
surface and an optional Anthropic path are supported as fallbacks. The model is
NEVER consulted at request time and its output is always a review candidate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema

import baselines
from baselines import DTYPE_NUMERIC, FIELDS, Field
from db import FLAG_NEEDS_REVIEW
from schema import EXTRACTION_SCHEMA, SCHEMA_NAME

logger = logging.getLogger(__name__)

PROVIDER_AZURE = "azure_openai"
PROVIDER_ANTHROPIC = "anthropic"

_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


class ExtractionError(RuntimeError):
    """Raised when extraction fails or returns unusable output."""


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------
def _field_guide() -> str:
    lines = []
    for name in baselines.FIELD_NAMES:
        f = FIELDS[name]
        unit = "number" if f.dtype == DTYPE_NUMERIC else "true/false"
        lines.append(f"- {name} ({unit}): {f.description}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a California land-use paralegal extracting Accessory Dwelling Unit "
    "(ADU), Junior ADU (JADU), and SB 9 lot-split / duplex standards from raw "
    "municipal zoning code text. You produce REVIEW CANDIDATES for a human to "
    "verify; you never assert a final determination.\n\n"
    "Rules:\n"
    "1. Extract standards per residential zoning district. Emit one object per "
    "district for which the text states or implies ADU/SB 9 standards. If the "
    "text gives a single set of ADU standards applying citywide to all "
    "residential districts, emit one object with zone_district='ALL_RESIDENTIAL'.\n"
    "2. Use ONLY the provided text. Never infer, guess, or fill a value from "
    "general knowledge of California law. If a value is not stated in this text, "
    "return value=null for that field (do not omit the key).\n"
    "3. Numbers are plain magnitudes in the field's unit: heights/setbacks in "
    "feet, sizes in square feet, review time in days, ratios as decimals "
    "(60/40 -> 0.4). No units in the value.\n"
    "4. Booleans capture whether the described restriction/permission is present "
    "(e.g. owner_occupancy_required_adu is true only if the text requires owner "
    "occupancy for a standalone ADU).\n"
    "5. For every field give a confidence (high|medium|low) reflecting how "
    "clearly THIS TEXT states the value, and an evidence string quoting the "
    "supporting phrase (empty string when value is null).\n"
    "6. Return every field key for every zone object. Do not add keys not in the "
    "schema."
)


def _user_prompt(raw_text: str, jurisdiction_name: str, section_label: str) -> str:
    return (
        f"Jurisdiction: {jurisdiction_name}\n"
        f"Section: {section_label}\n\n"
        "Field guide (what each field means):\n"
        f"{_field_guide()}\n\n"
        "Extract the ADU / JADU / SB 9 standards from the following municipal code "
        "text. Return them as the structured object of zone-district rules.\n\n"
        "--- BEGIN SECTION TEXT ---\n"
        f"{raw_text}\n"
        "--- END SECTION TEXT ---"
    )


# ---------------------------------------------------------------------------
# provider selection + calls
# ---------------------------------------------------------------------------
def _select_provider(settings: Any) -> str:
    if settings.has_azure_openai:
        return PROVIDER_AZURE
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return PROVIDER_ANTHROPIC
    raise ExtractionError(
        "No LLM provider configured. Set AZURE_OPENAI_ENDPOINT (ending /openai/v1) "
        "+ AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT, or ANTHROPIC_API_KEY."
    )


def _extract_azure(settings: Any, raw_text: str, name: str, label: str) -> str:
    endpoint = settings.azure_openai_endpoint
    deployment = settings.azure_openai_deployment

    if "/openai/v1" in endpoint:
        # AI Foundry v1 surface: plain OpenAI client, base_url + bearer key,
        # deployment name as the model.
        from openai import OpenAI

        client = OpenAI(base_url=endpoint, api_key=settings.azure_openai_api_key)
    else:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )

    kwargs: dict[str, Any] = dict(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(raw_text, name, label)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": SCHEMA_NAME,
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            },
        },
    )
    try:
        response = client.chat.completions.create(
            max_completion_tokens=settings.extraction_max_tokens, **kwargs
        )
    except Exception as exc:  # older models want max_tokens
        if "max_completion_tokens" not in str(exc):
            raise
        response = client.chat.completions.create(
            max_tokens=settings.extraction_max_tokens, **kwargs
        )
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise ExtractionError(f"Azure model refused: {choice.message.refusal}")
    text = choice.message.content or ""
    if not text.strip():
        raise ExtractionError("Azure OpenAI returned an empty response")
    return text


def _extract_anthropic(settings: Any, raw_text: str, name: str, label: str) -> str:
    import os

    import anthropic

    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
    with client.messages.stream(
        model=model,
        max_tokens=settings.extraction_max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(raw_text, name, label)}],
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
    ) as stream:
        message = stream.get_final_message()
    if getattr(message, "stop_reason", None) == "refusal":
        raise ExtractionError("Anthropic model refused the extraction request")
    text = "".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    )
    if not text.strip():
        raise ExtractionError("Anthropic returned an empty response")
    return text


def extract_section_candidates(
    settings: Any,
    raw_text: str,
    jurisdiction_name: str,
    section_label: str = "",
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return validated zone-district candidate objects for one section."""
    if not raw_text or not raw_text.strip():
        return []
    provider = provider or _select_provider(settings)
    if provider == PROVIDER_AZURE:
        raw_json = _extract_azure(settings, raw_text, jurisdiction_name, section_label)
    elif provider == PROVIDER_ANTHROPIC:
        raw_json = _extract_anthropic(settings, raw_text, jurisdiction_name, section_label)
    else:
        raise ExtractionError(f"Unknown provider: {provider}")

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Extraction output was not valid JSON: {exc}") from exc
    try:
        jsonschema.validate(instance=parsed, schema=EXTRACTION_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ExtractionError(
            f"Extraction output failed schema validation: {exc.message}"
        ) from exc
    return parsed.get("zones", [])


# ---------------------------------------------------------------------------
# candidate -> DB payload mapping (pure, offline-testable)
# ---------------------------------------------------------------------------
def _cap_confidence(conf: str, ceiling: str = "medium") -> str:
    """Clamp a confidence label so unverified candidates never claim 'high'."""
    conf = conf if conf in _CONFIDENCE_ORDER else "low"
    if _CONFIDENCE_ORDER[conf] > _CONFIDENCE_ORDER[ceiling]:
        return ceiling
    return conf


def _attribute_payload(field: Field, fobj: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    value = fobj.get("value")
    conf = fobj.get("confidence") or "low"
    evidence = (fobj.get("evidence") or "").strip()
    value_numeric = None
    if field.dtype == DTYPE_NUMERIC and isinstance(value, (int, float)) and not isinstance(value, bool):
        value_numeric = value
    return {
        "field_name": field.name,
        "value_json": value,
        "value_numeric": value_numeric,
        "unit": field.unit,
        "operator": field.operator,
        "compliance_flag": FLAG_NEEDS_REVIEW,  # validate.py refines this
        "source_url": section.get("section_url"),
        "source_title": section.get("code_title") or section.get("heading"),
        "source_section": section.get("section_label") or section.get("section_number"),
        "source_layer": None,
        "retrieved_at": None,
        "last_verified_at": None,  # never auto-verified
        "confidence": conf if conf in _CONFIDENCE_ORDER else "low",
        "data_status": "current",
        "notes": evidence or None,
    }


def build_candidate_payloads(
    zone: dict[str, Any],
    supported_project_types: list[str],
    section: dict[str, Any],
) -> list[dict[str, Any]]:
    """Split one extracted zone into per-project_type candidate rule payloads.

    Returns a list of {rule: {...kwargs for upsert_candidate_rule...},
    attributes: [rule_attribute payloads]}. A project_type is emitted only when
    the zone has at least one non-null extracted field governing it.
    """
    zone_code = str(zone.get("zone_district") or "").strip()
    fields = zone.get("fields") or {}
    if not zone_code:
        return []

    out: list[dict[str, Any]] = []
    for project_type in supported_project_types:
        attributes: list[dict[str, Any]] = []
        confidences: list[str] = []
        for field_name in baselines.fields_for_project_type(project_type):
            fobj = fields.get(field_name)
            if not isinstance(fobj, dict):
                continue
            if fobj.get("value") is None:
                continue
            field = FIELDS[field_name]
            attributes.append(_attribute_payload(field, fobj, section))
            confidences.append(fobj.get("confidence") or "low")
        if not attributes:
            continue
        rule_conf = "low"
        if confidences:
            lowest = min(confidences, key=lambda c: _CONFIDENCE_ORDER.get(c, 0))
            rule_conf = _cap_confidence(lowest)
        out.append(
            {
                "rule": {
                    "zone_code": zone_code,
                    "zone_name": None,
                    "project_type": project_type,
                    "zoning_section_id": section.get("id"),
                    "source_registry_id": section.get("source_registry_id"),
                    "source_snapshot_id": section.get("source_snapshot_id"),
                    "summary": (
                        f"Extracted candidate ADU/JADU/SB9 standards for zone "
                        f"{zone_code} ({project_type}) from "
                        f"{section.get('section_label') or section.get('section_url')}."
                    ),
                    "confidence": rule_conf,
                },
                "attributes": attributes,
            }
        )
    return out


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def extract_jurisdiction(
    slug: str,
    settings: Any,
    store: Any,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    provider: str | None = None,
) -> dict[str, int]:
    """Extract candidates for a jurisdiction's zoning_sections. Returns counts."""
    jurisdiction = store.get_jurisdiction(slug)
    if jurisdiction is None:
        raise ExtractionError(f"jurisdiction '{slug}' not found in the database")
    supported = list(jurisdiction.get("supported_project_types") or baselines.PROJECT_TYPES)

    sections = store.get_zoning_sections(jurisdiction["id"])
    if limit is not None:
        sections = sections[:limit]

    run_id = None
    if not dry_run:
        run_id = store.start_ingest_run(
            jurisdiction_id=jurisdiction["id"],
            source_registry_id=None,
            run_type="code",
            triggered_by="extract",
        )

    counts = {"sections": 0, "zones": 0, "rules": 0, "attributes": 0, "failed": 0}
    try:
        for section in sections:
            counts["sections"] += 1
            try:
                zones = extract_section_candidates(
                    settings,
                    section.get("raw_text") or "",
                    jurisdiction_name=jurisdiction.get("name", slug),
                    section_label=section.get("section_label") or section.get("section_url", ""),
                    provider=provider,
                )
            except ExtractionError as exc:
                counts["failed"] += 1
                logger.warning("[%s] extraction failed for %s: %s", slug, section.get("section_url"), exc)
                continue

            for zone in zones:
                counts["zones"] += 1
                payloads = build_candidate_payloads(zone, supported, section)
                for item in payloads:
                    if dry_run:
                        counts["rules"] += 1
                        counts["attributes"] += len(item["attributes"])
                        logger.info(
                            "[dry-run] %s %s/%s -> %d attribute(s)",
                            slug,
                            item["rule"]["zone_code"],
                            item["rule"]["project_type"],
                            len(item["attributes"]),
                        )
                        continue
                    rule_id = store.upsert_candidate_rule(
                        jurisdiction_id=jurisdiction["id"], **item["rule"]
                    )
                    written = store.replace_rule_attributes(rule_id, item["attributes"])
                    counts["rules"] += 1
                    counts["attributes"] += written
        if run_id is not None:
            store.finish_ingest_run(
                run_id,
                status="success",
                processed=counts["sections"],
                inserted=counts["rules"],
                failed=counts["failed"],
                stats=counts,
            )
    except Exception as exc:
        if run_id is not None:
            store.finish_ingest_run(
                run_id, status="failed", processed=counts["sections"], error_message=str(exc)
            )
        raise

    logger.info(
        "[%s] extraction done: %d sections, %d zones, %d candidate rules, %d attributes, %d failed",
        slug, counts["sections"], counts["zones"], counts["rules"], counts["attributes"], counts["failed"],
    )
    return counts


if __name__ == "__main__":  # offline self-check (no provider called)
    guide = _field_guide()
    assert all(name in guide for name in baselines.FIELD_NAMES)
    prompt = _user_prompt("Sample ADU text.", "Testville", "Sec. 1.1")
    assert "Testville" in prompt and "Sample ADU text." in prompt

    sample_zone = {
        "zone_district": "R1",
        "fields": {
            name: {"value": None, "confidence": "low", "evidence": ""}
            for name in baselines.FIELD_NAMES
        },
    }
    # Set a couple of ADU-build fields and a JADU field.
    sample_zone["fields"]["max_height_detached_standard_ft"] = {
        "value": 16, "confidence": "high", "evidence": "up to 16 feet"
    }
    sample_zone["fields"]["side_rear_setback_min_ft"] = {
        "value": 5, "confidence": "medium", "evidence": "5 foot side and rear"
    }
    sample_zone["fields"]["jadu_allowed"] = {
        "value": True, "confidence": "high", "evidence": "one JADU permitted"
    }
    section = {
        "id": "sec-1",
        "section_url": "https://example/lamc/12.22",
        "section_label": "12 / 12.22 / 12.22",
        "code_title": "LAMC",
        "source_registry_id": "sr-1",
        "source_snapshot_id": "snap-1",
    }
    payloads = build_candidate_payloads(
        sample_zone, list(baselines.PROJECT_TYPES), section
    )
    by_pt = {p["rule"]["project_type"] for p in payloads}
    assert "detached_adu" in by_pt, by_pt
    assert "jadu" in by_pt, by_pt
    # SB9 project types have no extracted values here -> not emitted.
    assert "sb9_duplex" not in by_pt, by_pt
    # confidence is capped at medium even though a field was 'high'
    for p in payloads:
        assert p["rule"]["confidence"] in {"low", "medium"}, p["rule"]["confidence"]
        for a in p["attributes"]:
            assert a["compliance_flag"] == FLAG_NEEDS_REVIEW
            assert a["last_verified_at"] is None
    print(f"extract OK ({len(payloads)} candidate rules from sample zone)")
