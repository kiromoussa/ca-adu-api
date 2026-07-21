"""LLM extraction of structured ADU rules from raw zoning-section text.

Supports two providers, chosen from the environment (Azure OpenAI takes
precedence when both are configured):

  - Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_DEPLOYMENT (+ optional AZURE_OPENAI_API_VERSION)
  - Anthropic: ANTHROPIC_API_KEY

Both force structured JSON output against schema.EXTRACTION_SCHEMA. The result
is validated with jsonschema before being returned, so callers get well-formed
rows or a clear error - never silently malformed data.
"""

from __future__ import annotations

import json
import os

import jsonschema

from baselines import BASELINES, RULE_FIELDS
from schema import EXTRACTION_SCHEMA, SCHEMA_NAME

# Default models / versions (overridable via env).
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
MAX_OUTPUT_TOKENS = int(os.environ.get("EXTRACTION_MAX_TOKENS", "16000"))

PROVIDER_AZURE = "azure_openai"
PROVIDER_ANTHROPIC = "anthropic"


class ExtractionError(RuntimeError):
    """Raised when extraction fails or returns unusable output."""


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------
def _field_guide() -> str:
    """Bulleted guide of every field the model must populate."""
    lines = []
    for field in RULE_FIELDS:
        b = BASELINES[field]
        unit = "number" if b.dtype == "numeric" else "true/false"
        lines.append(f"- {field} ({unit}): {b.description}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a California land-use paralegal extracting Accessory Dwelling Unit "
    "(ADU), Junior ADU (JADU), and SB 9 lot-split / duplex standards from raw "
    "municipal zoning code text.\n\n"
    "Rules:\n"
    "1. Extract standards per residential zoning district. Emit one object per "
    "district for which the text states or implies ADU/SB 9 standards. If the "
    "text gives a single set of ADU standards that apply citywide to all "
    "residential districts, emit a single object with zone_district set to the "
    "broadest label used (e.g. 'ALL_RESIDENTIAL').\n"
    "2. Use ONLY the provided text. Never infer, guess, or fill in a value from "
    "general knowledge of California law. If a value is not stated in this text, "
    "return null for that field.\n"
    "3. Numbers are plain magnitudes in the field's unit: heights and setbacks in "
    "feet, sizes in square feet, review time in days, ratios as decimals "
    "(60/40 -> 0.4). Do not include units in the value.\n"
    "4. Booleans capture whether the described restriction/permission is present: "
    "e.g. owner_occupancy_required_adu is true only if the text requires owner "
    "occupancy for a standalone ADU.\n"
    "5. Do not confuse a maximum ADU size with a bedroom-specific cap; only fill "
    "max_size_sqft_1br / max_size_sqft_2br when the text ties the cap to bedroom "
    "count.\n"
    "6. Return every field key for every zone object, using null where the text "
    "is silent. Do not add keys that are not in the schema."
)


def _user_prompt(raw_text: str, city_name: str, section_label: str) -> str:
    return (
        f"City: {city_name}\n"
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
# provider selection
# ---------------------------------------------------------------------------
def _select_provider() -> str:
    if (
        os.environ.get("AZURE_OPENAI_ENDPOINT")
        and os.environ.get("AZURE_OPENAI_API_KEY")
        and os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    ):
        return PROVIDER_AZURE
    if os.environ.get("ANTHROPIC_API_KEY"):
        return PROVIDER_ANTHROPIC
    raise ExtractionError(
        "No LLM provider configured. Set AZURE_OPENAI_ENDPOINT + "
        "AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT, or ANTHROPIC_API_KEY."
    )


# ---------------------------------------------------------------------------
# Anthropic path
# ---------------------------------------------------------------------------
def _extract_anthropic(raw_text: str, city_name: str, section_label: str) -> str:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / profile from env
    # Stream so a large structured payload never hits the request timeout, and
    # force the response to match the extraction schema exactly.
    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _user_prompt(raw_text, city_name, section_label)}
        ],
        output_config={
            "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}
        },
    ) as stream:
        message = stream.get_final_message()

    if getattr(message, "stop_reason", None) == "refusal":
        raise ExtractionError("Anthropic model refused the extraction request")

    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    if not text.strip():
        raise ExtractionError("Anthropic returned an empty response")
    return text


# ---------------------------------------------------------------------------
# Azure OpenAI path
# ---------------------------------------------------------------------------
def _extract_azure(raw_text: str, city_name: str, section_label: str) -> str:
    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=AZURE_API_VERSION,
    )
    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(raw_text, city_name, section_label)},
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
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise ExtractionError(f"Azure model refused: {choice.message.refusal}")
    text = choice.message.content or ""
    if not text.strip():
        raise ExtractionError("Azure OpenAI returned an empty response")
    return text


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def extract_rules(
    raw_text: str,
    city_name: str,
    section_label: str = "",
    provider: str | None = None,
) -> list[dict]:
    """Extract structured ADU rule rows from one section's raw text.

    Args:
        raw_text: the scraped municipal code text for a zoning section.
        city_name: human-readable city name (for prompt context).
        section_label: optional section identifier (title/chapter/section).
        provider: force a provider ("azure_openai" | "anthropic"); default auto.

    Returns:
        A list of zone-district dicts, each containing zone_district plus every
        field in RULE_FIELDS (values may be null).

    Raises:
        ExtractionError: on provider/config failure, refusal, empty output, or
            output that does not conform to EXTRACTION_SCHEMA.
    """
    if not raw_text or not raw_text.strip():
        return []

    provider = provider or _select_provider()
    if provider == PROVIDER_AZURE:
        raw_json = _extract_azure(raw_text, city_name, section_label)
    elif provider == PROVIDER_ANTHROPIC:
        raw_json = _extract_anthropic(raw_text, city_name, section_label)
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


if __name__ == "__main__":  # offline self-check (no network / no API key needed)
    # Verify prompt + schema wiring without calling any provider.
    guide = _field_guide()
    assert all(field in guide for field in RULE_FIELDS)
    prompt = _user_prompt("Sample ADU text.", "Testville", "Sec. 1.1")
    assert "Testville" in prompt and "Sample ADU text." in prompt
    # Empty input short-circuits to no rows.
    assert extract_rules("", "Testville") == []
    print("extract OK (prompt/schema wiring verified; providers not called)")
