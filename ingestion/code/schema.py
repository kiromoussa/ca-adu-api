"""Strict JSON schema for OFFLINE LLM extraction of ADU rule candidates.

Built directly from baselines.FIELDS so the schema and the validator never
drift. Each field is emitted as an object carrying:
  - value       : the extracted magnitude / boolean, or null if the text is
                  silent (null is required, not omission),
  - confidence  : the model's per-field confidence (high|medium|low), and
  - evidence    : a short verbatim quote / phrase from the section text that
                  supports the value (empty string when value is null).

This gives every rule_attribute row per-field provenance (confidence +
explanation), as the trust non-negotiables require. additionalProperties is
false everywhere so the model cannot invent fields. Both the Azure OpenAI v1
(response_format json_schema, strict) path in extract.py and any structured
Anthropic path feed this same schema.
"""

from __future__ import annotations

from baselines import DTYPE_NUMERIC, FIELD_NAMES, FIELDS

SCHEMA_NAME = "adu_rule_extraction"


def _field_object(field_name: str) -> dict:
    """Schema fragment for one extracted field: {value, confidence, evidence}."""
    f = FIELDS[field_name]
    json_type = "number" if f.dtype == DTYPE_NUMERIC else "boolean"
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "confidence", "evidence"],
        "properties": {
            "value": {
                "type": [json_type, "null"],
                "description": f.description,
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": (
                    "Confidence that this value is correctly read FROM THIS TEXT "
                    "(not confidence in general CA law)."
                ),
            },
            "evidence": {
                "type": "string",
                "description": (
                    "Short verbatim quote or phrase from the section text that "
                    "supports the value. Empty string if value is null."
                ),
            },
        },
    }


def _zone_object() -> dict:
    properties: dict[str, dict] = {
        "zone_district": {
            "type": "string",
            "description": (
                "The zoning district / designation these standards apply to, "
                "exactly as written in the code (e.g. 'R1', 'RS', 'RD1.5', 'RM'). "
                "Use the most specific label available; if the text states a single "
                "set of ADU standards applying citywide to all residential "
                "districts, use 'ALL_RESIDENTIAL'."
            ),
        },
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FIELD_NAMES),
            "properties": {name: _field_object(name) for name in FIELD_NAMES},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["zone_district", "fields"],
        "properties": properties,
    }


ZONE_SCHEMA: dict = _zone_object()

EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zones"],
    "properties": {
        "zones": {
            "type": "array",
            "description": (
                "One object per residential zoning district for which ADU / JADU / "
                "SB 9 standards can be determined from the provided text. Empty "
                "array if no relevant standards are present."
            ),
            "items": ZONE_SCHEMA,
        }
    },
}


if __name__ == "__main__":  # offline self-check
    import json

    field_props = ZONE_SCHEMA["properties"]["fields"]
    assert set(field_props["properties"]) == set(FIELD_NAMES)
    assert field_props["additionalProperties"] is False
    for name in FIELD_NAMES:
        obj = field_props["properties"][name]
        assert set(obj["required"]) == {"value", "confidence", "evidence"}, name
    json.dumps(EXTRACTION_SCHEMA)  # must be serializable
    print(f"schema OK: {len(FIELD_NAMES)} fields per zone")
