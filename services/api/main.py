"""ADU Atlas FastAPI application (the deterministic request path).

Exposes the ``/v1`` surface from ``openapi/openapi.yaml``. The only billable
endpoint is ``POST /v1/feasibility``; it meters exactly one unit per completed,
non-cached, terminal analysis. All other endpoints are read-only metadata.

No LLM is invoked anywhere in this module or anything it calls.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from ..core import constants
from ..core.constants import ANALYSIS_VERSION, RULES_VERSION, db_compliance_to_api
from ..core.feasibility import (
    FeasibilityInput,
    compute_request_fingerprint,
    run_feasibility,
)
from ..core.geocode import normalize_address
from . import errors, idempotency
from .deps import (
    AuthContext,
    authenticate,
    get_catalog,
    get_geocoder,
    get_repository,
)
from .rapidapi import check_monthly_quota, decide_metering
from .schemas import (
    ChangelogEntry,
    ChangelogResponse,
    FeasibilityRequest,
    FeasibilityResponse,
    HealthResponse,
    Jurisdiction,
    JurisdictionList,
    JurisdictionRulesResponse,
    Provenance,
    RuleAttribute,
    SourceFreshness,
    ZoneRuleSet,
)
from .settings import get_settings

_START_TIME = time.monotonic()

app = FastAPI(
    title="ADU Atlas API",
    version="1.0.0",
    summary="Deterministic, source-cited, address-level preliminary feasibility "
    "for California ADUs, JADUs, and SB 9 projects.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

errors.register_exception_handlers(app)


@app.middleware("http")
async def _request_context(request: Request, call_next):
    request.state.request_id = "req_" + uuid.uuid4().hex[:20]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _record_usage(
    repo,
    *,
    auth: AuthContext,
    endpoint: str,
    method: str,
    status_code: int,
    billable: bool,
    cache_hit: bool,
    analysis_id: Optional[str] = None,
    project_type: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    request_fingerprint: Optional[str] = None,
    response_time_ms: Optional[int] = None,
) -> None:
    """Best-effort metering write; never fails the request."""
    try:
        repo.record_usage_event(
            {
                "consumer_id": auth.consumer_id,
                "provider": auth.provider,
                "plan": auth.plan_name,
                "endpoint": endpoint,
                "method": method,
                "project_type": project_type,
                "jurisdiction_slug": jurisdiction_slug,
                "analysis_id": analysis_id,
                "request_fingerprint": request_fingerprint,
                "status_code": status_code,
                "billable": billable,
                "billed": billable,
                "cache_hit": cache_hit,
                "response_time_ms": response_time_ms,
            }
        )
    except Exception:
        pass


# ===========================================================================
# POST /v1/feasibility  (the only billable endpoint)
# ===========================================================================
@app.post("/v1/feasibility", response_model=FeasibilityResponse, tags=["feasibility"])
def create_feasibility(
    body: FeasibilityRequest,
    response: Response,
    request: Request,
    auth: AuthContext = Depends(authenticate),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> FeasibilityResponse:
    repo = get_repository()
    geocoder = get_geocoder()
    catalog = get_catalog()
    started = time.perf_counter()

    inp = FeasibilityInput(
        address=body.address,
        project_type=body.project_type,
        target_sqft=body.target_sqft,
        bedrooms=body.bedrooms,
        proposed_height_ft=body.proposed_height_ft,
        existing_structure=(body.existing_structure.model_dump() if body.existing_structure else None),
        options=(body.options.model_dump(exclude_none=True) if body.options else {}),
    )
    normalized = normalize_address(inp.address)
    fingerprint = compute_request_fingerprint(auth.consumer_id, normalized, inp)

    # 1) Idempotency replay (identical body + key -> stored response; not billed).
    stored = idempotency.check_idempotency(
        repo,
        consumer_id=auth.consumer_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    if stored is not None and stored.get("result_json"):
        response.headers["X-Billable"] = "false"
        if idempotency_key:
            response.headers["Idempotency-Key"] = idempotency_key
        _record_usage(
            repo, auth=auth, endpoint="POST /v1/feasibility", method="POST",
            status_code=200, billable=False, cache_hit=True,
            analysis_id=stored.get("id"), project_type=body.project_type,
            request_fingerprint=fingerprint,
        )
        return FeasibilityResponse.model_validate(stored["result_json"])

    # 2) 24h dedupe cache (same consumer + identical inputs -> not billed).
    window = catalog.dedupe_window_hours()
    cached = repo.find_cached_analysis(fingerprint, within_hours=window)
    if cached is not None and cached.get("result_json"):
        response.headers["X-Billable"] = "false"
        if idempotency_key:
            response.headers["Idempotency-Key"] = idempotency_key
        _record_usage(
            repo, auth=auth, endpoint="POST /v1/feasibility", method="POST",
            status_code=200, billable=False, cache_hit=True,
            analysis_id=cached.get("id"), project_type=body.project_type,
            jurisdiction_slug=cached.get("jurisdiction_slug"),
            request_fingerprint=fingerprint,
        )
        return FeasibilityResponse.model_validate(cached["result_json"])

    # 3) Monthly quota (hard cap; no overages). Only billable analyses count.
    quota = catalog.monthly_quota(auth.plan_name)
    used = repo.count_billable_this_month(auth.consumer_id)
    qc = check_monthly_quota(used, quota)
    if not qc.allowed:
        _record_usage(
            repo, auth=auth, endpoint="POST /v1/feasibility", method="POST",
            status_code=429, billable=False, cache_hit=False,
            project_type=body.project_type, request_fingerprint=fingerprint,
        )
        raise errors.quota_exceeded(auth.plan_name, qc.quota or 0, qc.used)

    # 4) Compute (deterministic; persists the analysis + findings).
    outcome = run_feasibility(
        repo,
        geocoder,
        inp,
        consumer_id=auth.consumer_id,
        provider=auth.provider,
        plan=auth.plan_name,
        idempotency_key=idempotency_key,
        allow_share_token=auth.feature("shareable_analysis_token"),
        persist=True,
    )

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # 5) Unsupported coverage -> 422, not billed.
    if outcome.kind == "unsupported_coverage":
        detail = outcome.unsupported_detail or {}
        _record_usage(
            repo, auth=auth, endpoint="POST /v1/feasibility", method="POST",
            status_code=422, billable=False, cache_hit=False,
            project_type=body.project_type,
            jurisdiction_slug=detail.get("jurisdiction_slug"),
            request_fingerprint=fingerprint, response_time_ms=elapsed_ms,
        )
        raise errors.unsupported_coverage(
            detail.get("jurisdiction_slug", "unknown"),
            detail.get("coverage_status", "planned"),
        )

    # 6) Completed. Decide metering and record it.
    decision = decide_metering(
        status_code=200,
        feasibility_status=outcome.feasibility_status,
        cache_hit=outcome.cache_hit,
    )
    response.headers["X-Billable"] = "true" if decision.billable else "false"
    if idempotency_key:
        response.headers["Idempotency-Key"] = idempotency_key
    _record_usage(
        repo, auth=auth, endpoint="POST /v1/feasibility", method="POST",
        status_code=200, billable=decision.billable, cache_hit=outcome.cache_hit,
        analysis_id=outcome.analysis_id, project_type=body.project_type,
        jurisdiction_slug=outcome.jurisdiction_slug, request_fingerprint=fingerprint,
        response_time_ms=elapsed_ms,
    )
    return FeasibilityResponse.model_validate(outcome.result)


# ===========================================================================
# GET /v1/jurisdictions
# ===========================================================================
@app.get("/v1/jurisdictions", response_model=JurisdictionList, tags=["jurisdictions"])
def list_jurisdictions(auth: AuthContext = Depends(authenticate)) -> JurisdictionList:
    repo = get_repository()
    rows = repo.list_jurisdictions()
    data = [
        Jurisdiction(
            slug=r["slug"],
            name=r["name"],
            display_name=r.get("display_name") or r["name"],
            state=r.get("state"),
            county=r.get("county"),
            coverage_status=r["coverage_status"],
            supported_project_types=list(r.get("supported_project_types") or []),
            sources_last_updated_at=_iso(r.get("last_source_refresh_at") or r.get("source_update_date")),
        )
        for r in rows
    ]
    return JurisdictionList(data=data, count=len(data))


# ===========================================================================
# GET /v1/jurisdictions/{slug}/rules
# ===========================================================================
def _provenance_from_attr(row: dict[str, Any]) -> Provenance:
    return Provenance(
        source_url=row.get("source_url") or "urn:aduatlas:unknown-source",
        source_title=row.get("source_title") or "Local zoning ordinance",
        source_section=row.get("source_section"),
        source_layer=row.get("source_layer"),
        retrieved_at=_iso(row.get("retrieved_at")) or datetime.now(timezone.utc).isoformat(),
        last_verified_at=_iso(row.get("last_verified_at")),
        confidence=row.get("confidence") or "medium",
        data_status=row.get("data_status") or "current",
    )


@app.get(
    "/v1/jurisdictions/{slug}/rules",
    response_model=JurisdictionRulesResponse,
    tags=["jurisdictions"],
)
def get_jurisdiction_rules(
    slug: str,
    zone: Optional[str] = Query(default=None),
    project_type: Optional[str] = Query(default=None),
    auth: AuthContext = Depends(authenticate),
) -> JurisdictionRulesResponse:
    repo = get_repository()
    payload = repo.get_jurisdiction_rules(slug, zone, project_type)
    if payload is None:
        raise errors.not_found(f"No jurisdiction with slug '{slug}'.")
    j = payload["jurisdiction"]
    jurisdiction = Jurisdiction(
        slug=j["slug"],
        name=j["name"],
        display_name=j["name"],
        state=j.get("state_code"),
        county=j.get("county"),
        coverage_status=j["coverage_status"],
        supported_project_types=list(j.get("supported_project_types") or []),
        sources_last_updated_at=_iso(j.get("last_source_refresh_at")),
    )
    zones: list[ZoneRuleSet] = []
    citations: list[Provenance] = []
    for z in payload.get("zones", []):
        attributes = []
        for a in z.get("attributes", []):
            prov = _provenance_from_attr(a)
            citations.append(prov)
            value = a.get("value_json")
            if a.get("value_numeric") is not None:
                value = float(a["value_numeric"])
            attributes.append(
                RuleAttribute(
                    key=a["field_name"],
                    value=value,
                    unit=a.get("unit"),
                    compliance_flag=db_compliance_to_api(a.get("compliance_flag")),
                    provenance=prov,
                )
            )
        zones.append(
            ZoneRuleSet(
                zone_code=z["zone_code"],
                zone_name=z.get("zone_name"),
                project_type=z.get("project_type"),
                attributes=attributes,
            )
        )
    return JurisdictionRulesResponse(
        jurisdiction=jurisdiction,
        citywide=[],
        zones=zones,
        citations=citations,
        version_history=[],
    )


# ===========================================================================
# GET /v1/analyses/{analysis_id}
# ===========================================================================
@app.get("/v1/analyses/{analysis_id}", response_model=FeasibilityResponse, tags=["analyses"])
def get_analysis(
    analysis_id: str,
    request: Request,
    token: Optional[str] = Query(default=None),
) -> FeasibilityResponse:
    repo = get_repository()

    # Public share-token path: no originating API key required.
    if token:
        row = repo.get_analysis_by_share_token(token)
        if row is None or row.get("share_token") != token or str(row.get("id")) != str(analysis_id):
            raise errors.not_found("No shareable analysis matches that id and token.")
        if not row.get("result_json"):
            raise errors.not_found("Analysis result is unavailable.")
        return FeasibilityResponse.model_validate(row["result_json"])

    # Private path: requires credentials and consumer ownership.
    auth = authenticate(request)
    row = repo.get_analysis(analysis_id)
    if row is None:
        raise errors.not_found(f"No analysis with id '{analysis_id}'.")
    if (row.get("consumer_id") or "") != auth.consumer_id:
        raise errors.forbidden("This analysis is private to another consumer.")
    if not row.get("result_json"):
        raise errors.not_found("Analysis result is unavailable.")
    return FeasibilityResponse.model_validate(row["result_json"])


# ===========================================================================
# GET /v1/changelog
# ===========================================================================
@app.get("/v1/changelog", response_model=ChangelogResponse, tags=["meta"])
def get_changelog(
    jurisdiction: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(authenticate),
) -> ChangelogResponse:
    repo = get_repository()
    rows = repo.get_changelog(jurisdiction, limit)
    _map = {
        "coverage": "coverage_change",
        "rule_update": "rule_update",
        "source_update": "source_refreshed",
        "correction": "correction",
        "release": "source_ingested",
        "other": "correction",
    }
    data = [
        ChangelogEntry(
            id=str(r["id"]),
            jurisdiction_slug=r.get("jurisdiction_slug") or "unknown",
            change_type=_map.get(r.get("entry_type"), "correction"),
            summary=r.get("summary") or r.get("title") or "",
            occurred_at=_iso(r.get("published_at")) or datetime.now(timezone.utc).isoformat(),
        )
        for r in rows
    ]
    return ChangelogResponse(data=data, count=len(data))


# ===========================================================================
# GET /v1/health  (no auth)
# ===========================================================================
@app.get("/v1/health", response_model=HealthResponse, tags=["meta"])
def health() -> Response:
    uptime = time.monotonic() - _START_TIME
    settings = get_settings()
    sources: list[SourceFreshness] = []
    status = "ok"
    if settings.has_db:
        try:
            repo = get_repository()
            for r in repo.get_source_freshness():
                sources.append(
                    SourceFreshness(
                        key=r.get("key") or r.get("name") or "source",
                        name=r.get("name"),
                        data_status=r.get("data_status") or "unavailable",
                        last_refreshed_at=_iso(r.get("last_refreshed_at")),
                    )
                )
            if any(s.data_status == "unavailable" for s in sources):
                status = "degraded"
        except Exception:
            status = "degraded"
    else:
        status = "degraded"

    payload = HealthResponse(
        status=status,
        uptime_seconds=round(uptime, 3),
        api_version=ANALYSIS_VERSION,
        rules_version=RULES_VERSION,
        sources=sources,
    )
    code = 200 if status == "ok" else 503
    return JSONResponse(status_code=code, content=payload.model_dump())
