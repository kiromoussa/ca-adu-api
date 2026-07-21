"""Unit tests for the scraper adapters (ALP + Municode).

Everything here is offline. No Playwright browser is launched and no HTTP request
is made: the link-harvesting logic is exercised with a fake Page whose anchors
come from in-test fixtures, section parsing runs against the checked-in HTML
fixtures, the Municode API-discovery path runs against a monkeypatched httpx
response, and the Supabase upsert is captured with a fake client so we can assert
the payload shape against the zoning_sections columns.

Two things are asserted, per the test plan:
  1. Each adapter can locate at least one ADU section for every seed city.
  2. The upsert payload shape matches the zoning_sections columns (migration 0001).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

# The adapters import bs4 / playwright / httpx / tenacity at import time; skip the
# whole module cleanly if the scraper runtime deps are not installed (they are in
# tests/requirements-dev.txt). supabase is needed for the upsert-shape test.
pytest.importorskip("bs4")
pytest.importorskip("playwright")
pytest.importorskip("httpx")
pytest.importorskip("tenacity")

from scraper.adapters.alp import ALPScraper  # noqa: E402
from scraper.adapters.municode import MunicodeApiClient, MunicodeScraper  # noqa: E402
from scraper.base import ScrapedSection  # noqa: E402
from scraper.config import Settings  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The columns of zoning_sections, from supabase/migrations/0001_initial_schema.sql.
ZONING_SECTIONS_COLUMNS = {
    "id",
    "city_id",
    "title_number",
    "chapter_number",
    "section_number",
    "section_url",
    "raw_text",
    "content_hash",
    "last_updated",
    "created_at",
}

# The 8 seed cities (supabase/seed.sql): slug, publisher, and base_url.
SEED_CITIES = [
    ("los_angeles", "alp", "https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-422835"),
    ("san_diego", "alp", "https://codelibrary.amlegal.com/codes/san_diego/latest"),
    ("san_francisco", "alp", "https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-17747"),
    ("sacramento", "alp", "https://codelibrary.amlegal.com/codes/sacramentoca/latest/sacramento_ca/0-0-0-32996"),
    ("san_jose", "municode", "https://library.municode.com/ca/san_jose/codes/code_of_ordinances"),
    ("irvine", "municode", "https://library.municode.com/ca/irvine/ordinances/code_of_ordinances"),
    ("long_beach", "municode", "https://library.municode.com/ca/long_beach/codes/municipal_code"),
    ("oakland", "municode", "https://library.municode.com/ca/oakland/codes/planning_code"),
]


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class FakeAnchor:
    """Stand-in for a Playwright element handle returned by query_selector_all."""

    def __init__(self, href: str, text: str) -> None:
        self._href = href
        self._text = text

    def get_attribute(self, name: str):
        return self._href if name == "href" else None

    def inner_text(self) -> str:
        return self._text


class FakePage:
    def __init__(self, anchors: list[FakeAnchor]) -> None:
        self._anchors = anchors

    def query_selector_all(self, selector: str):
        return list(self._anchors) if selector == "a[href]" else []


def _settings() -> Settings:
    # Construct directly (bypassing from_env) so no environment secrets are needed.
    return Settings(
        supabase_url="http://localhost",
        supabase_service_role_key="test-service-role-key",
        save_snapshots=False,
    )


def _make_adapter(slug: str, publisher: str, base_url: str):
    city = {"id": "00000000-0000-0000-0000-000000000001", "name": slug.replace("_", " ").title(), "slug": slug, "base_url": base_url}
    cls = ALPScraper if publisher == "alp" else MunicodeScraper
    # db and browser are never touched by the code paths under test.
    return cls(city=city, db=object(), browser=object(), settings=_settings())


# ---------------------------------------------------------------------------
# 1. each adapter locates at least one ADU section per city
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("slug,publisher,base_url", SEED_CITIES, ids=[c[0] for c in SEED_CITIES])
def test_adapter_harvests_at_least_one_adu_section(slug, publisher, base_url):
    adapter = _make_adapter(slug, publisher, base_url)

    if publisher == "alp":
        # A real ALP node-id link under this city's code path.
        section_href = f"https://codelibrary.amlegal.com/codes/{adapter._city_path}/latest/0-0-0-4001"
    else:
        # A real Municode node link carrying ?nodeId= for this city's code path.
        section_href = f"{adapter.base_url}?nodeId=TIT20ZO_CH20.30REZODI_20.30.460ACDWUN"

    anchors = [
        FakeAnchor(section_href, "Accessory Dwelling Units"),
        # An irrelevant link that must be filtered out.
        FakeAnchor("https://example.com/contact", "Contact Us"),
    ]
    found = adapter._harvest_links(FakePage(anchors))

    assert len(found) >= 1, f"{slug}: expected to locate at least one ADU section"
    assert section_href in found
    assert "https://example.com/contact" not in found


# ---------------------------------------------------------------------------
# section parsing produces a well-formed ScrapedSection
# ---------------------------------------------------------------------------
def test_alp_parse_section_extracts_text_and_numbering():
    adapter = _make_adapter(*SEED_CITIES[0])  # los_angeles / alp
    html = (FIXTURES / "alp_section.html").read_text(encoding="utf-8")
    url = f"https://codelibrary.amlegal.com/codes/{adapter._city_path}/latest/0-0-0-422835"

    section = adapter.parse_section(url, html)

    assert isinstance(section, ScrapedSection)
    assert section.section_url == url
    assert "accessory dwelling unit" in section.raw_text.lower()
    assert section.section_number == "12.22.1"
    assert section.chapter_number == "12.22"
    assert section.title_number == "12"


def test_municode_parse_section_uses_node_id_numbering():
    adapter = _make_adapter(*SEED_CITIES[4])  # san_jose / municode
    html = (FIXTURES / "municode_section.html").read_text(encoding="utf-8")
    url = f"{adapter.base_url}?nodeId=TIT20ZO_CH20.30REZODI_20.30.460ACDWUN"

    section = adapter.parse_section(url, html)

    assert isinstance(section, ScrapedSection)
    assert "accessory dwelling unit" in section.raw_text.lower()
    assert section.section_number == "20.30.460"
    assert section.title_number == "20"
    assert section.chapter_number == "20.30"


def test_content_hash_is_stable_sha256():
    a = ScrapedSection(section_url="u", raw_text="  Accessory   Dwelling\n Unit ")
    b = ScrapedSection(section_url="u", raw_text="Accessory Dwelling Unit")
    # Whitespace is normalized before hashing, so the two hashes match.
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 64
    assert all(ch in "0123456789abcdef" for ch in a.content_hash)


# ---------------------------------------------------------------------------
# Municode API discovery locates node ids without touching the network
# ---------------------------------------------------------------------------
def test_municode_api_client_extracts_node_ids(monkeypatch):
    client = MunicodeApiClient(user_agent="test-agent")

    fake_payload = {
        "Hits": [
            {"NodeId": "TIT20ZO_CH20.30REZODI_20.30.460ACDWUN", "Title": "Accessory Dwelling Units"},
            {"Url": "/ca/san_jose/codes/code_of_ordinances?nodeId=TIT20ZO_CH20.30REZODI_20.30.470ADUSTD"},
        ]
    }

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_payload

    monkeypatch.setattr(client._client, "get", lambda *a, **k: FakeResp())

    node_ids = client.search_node_ids(client_id=123, search_text="accessory dwelling unit")
    client.close()

    assert any("20.30.460" in n for n in node_ids)
    assert any("20.30.470" in n for n in node_ids)


# ---------------------------------------------------------------------------
# 2. upsert payload shape matches the zoning_sections columns
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self) -> None:
        self.payload = None
        self.on_conflict = None


class _FakeQuery:
    def __init__(self, recorder: _Recorder) -> None:
        self._rec = recorder

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def upsert(self, payload, on_conflict=None):
        self._rec.payload = payload
        self._rec.on_conflict = on_conflict
        return self

    def execute(self):
        # get_section_hash select returns no rows -> the section is treated as new.
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, recorder: _Recorder) -> None:
        self._rec = recorder

    def table(self, _name: str):
        return _FakeQuery(self._rec)


def test_upsert_payload_shape_matches_zoning_sections_columns(monkeypatch):
    import scraper.db as db

    recorder = _Recorder()
    monkeypatch.setattr(db, "create_client", lambda url, key: _FakeClient(recorder))

    writer = db.SupabaseWriter(url="http://localhost", service_role_key="k")
    outcome = writer.upsert_zoning_section(
        city_id="00000000-0000-0000-0000-000000000001",
        section_url="https://codelibrary.amlegal.com/codes/los_angeles/latest/0-0-0-4001",
        raw_text="Accessory dwelling unit standards.",
        content_hash="a" * 64,
        title_number="12",
        chapter_number="12.22",
        section_number="12.22.1",
    )

    assert outcome == "inserted"
    assert recorder.on_conflict == "city_id,section_url"

    payload = recorder.payload
    assert payload is not None
    # Every key written must be a real zoning_sections column.
    assert set(payload).issubset(ZONING_SECTIONS_COLUMNS), (
        f"payload has unknown columns: {set(payload) - ZONING_SECTIONS_COLUMNS}"
    )
    # The not-null / natural-key columns must be present.
    for required in ("city_id", "section_url", "raw_text", "content_hash", "last_updated"):
        assert required in payload
    assert payload["title_number"] == "12"
    assert payload["chapter_number"] == "12.22"
    assert payload["section_number"] == "12.22.1"


def test_upsert_skips_unchanged_content(monkeypatch):
    import scraper.db as db

    recorder = _Recorder()

    class _UnchangedQuery(_FakeQuery):
        def execute(self):
            # Existing row with the same hash -> unchanged.
            return SimpleNamespace(data=[{"content_hash": "b" * 64}])

    class _UnchangedClient:
        def table(self, _name):
            return _UnchangedQuery(recorder)

    monkeypatch.setattr(db, "create_client", lambda url, key: _UnchangedClient())

    writer = db.SupabaseWriter(url="http://localhost", service_role_key="k")
    outcome = writer.upsert_zoning_section(
        city_id="c1",
        section_url="https://example.com/s",
        raw_text="x",
        content_hash="b" * 64,
    )
    assert outcome == "unchanged"
    assert recorder.payload is None  # no write attempted
