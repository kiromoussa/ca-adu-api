"""Strict JSON schema for LLM extraction of adu_rules from raw section text.

The schema mirrors the adu_rules columns (see 0001_initial_schema.sql) and is
built directly from baselines.RULE_FIELDS so the two never drift. Every field is
required and nullable (["number","null"] / ["boolean","null"]) so the model must
emit each key and use null - not omission - when a value is not stated in the
text. additionalProperties is false so the model cannot invent columns.

Both the Anthropic (output_config.format) and Azure OpenAI (response_format
json_schema, strict) code paths in extract.py feed this same schema.
"""

from __future__ import annotations

from baselines import BASELINES, DTYPE_NUMERIC, RULE_FIELDS

# Human-facing name of the schema (used by Azure OpenAI's json_schema wrapper).
SCHEMA_NAME = "adu_rules_extraction"


def _field_property(field: str) -> dict:
    """JSON-schema fragment for one adu_rules field, nullable, with description."""
    baseline = BASELINES[field]
    json_type = "number" if baseline.dtype == DTYPE_NUMERIC else "boolean"
    return {
        "type": [json_type, "null"],
        "description": baseline.description,
    }


def _build_zone_schema() -> dict:
    """Schema for a single zone-district row of extracted ADU rules."""
    properties: dict[str, dict] = {
        "zone_district": {
            "type": "string",
            "description": (
                "The zoning district / designation these rules apply to, exactly as "
                "written in the code (e.g. 'R-1', 'RS', 'R1', 'RM'). Use the most "
                "specific district label available."
            ),
        }
    }
    for field in RULE_FIELDS:
        properties[field] = _field_property(field)

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["zone_district", *RULE_FIELDS],
        "properties": properties,
    }


# Schema for one zone-district object.
ZONE_SCHEMA: dict = _build_zone_schema()

# Top-level extraction schema: a list of zone-district rule objects.
EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["zones"],
    "properties": {
        "zones": {
            "type": "array",
            "description": (
                "One object per residential zoning district for which ADU / SB 9 "
                "standards can be determined from the provided text. Empty array if "
                "no ADU-relevant standards are present."
            ),
            "items": ZONE_SCHEMA,
        }
    },
}


if __name__ == "__main__":  # simple self-check
    import json

    # Every rule field plus zone_district must be present and required.
    props = ZONE_SCHEMA["properties"]
    assert set(props) == {"zone_district", *RULE_FIELDS}
    assert set(ZONE_SCHEMA["required"]) == set(props)
    assert ZONE_SCHEMA["additionalProperties"] is False
    # Must be JSON-serializable.
    json.dumps(EXTRACTION_SCHEMA)
    print(f"schema OK: {len(RULE_FIELDS) + 1} properties per zone")
