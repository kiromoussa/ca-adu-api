"""RapidAPI gateway, plan resolution, metering, and limiter tests (mocked)."""

from __future__ import annotations

from services.api.rapidapi import (
    InMemoryRateLimiter,
    check_monthly_quota,
    decide_metering,
    parse_credentials,
    resolve_plan_name,
    verify_rapidapi_host,
)
from services.api.settings import PlanCatalog

EXPECTED_HOST = "aduatlas.p.rapidapi.com"

CATALOG = PlanCatalog(
    {
        "plans": {
            "BASIC": {"monthly_quota": 3, "rate_limit_per_minute": 10, "rapidapi_plan_slug": "basic"},
            "PRO": {"monthly_quota": 50, "rate_limit_per_minute": 30, "rapidapi_plan_slug": "pro"},
        },
        "metering": {"burst_limiter": {"default_requests_per_minute": 60}},
    }
)


# --- host verification -----------------------------------------------------
def test_verify_host():
    assert verify_rapidapi_host("aduatlas.p.rapidapi.com", EXPECTED_HOST) is True
    assert verify_rapidapi_host("ADUATLAS.P.RAPIDAPI.COM", EXPECTED_HOST) is True
    assert verify_rapidapi_host("evil.example.com", EXPECTED_HOST) is False
    assert verify_rapidapi_host(None, EXPECTED_HOST) is False


# --- credential parsing ----------------------------------------------------
def test_rapidapi_credentials_valid():
    creds = parse_credentials(
        {
            "X-RapidAPI-Key": "consumer-key-123",
            "X-RapidAPI-Host": EXPECTED_HOST,
            "X-RapidAPI-User": "user-abc",
            "X-RapidAPI-Subscription": "pro",
        },
        expected_host=EXPECTED_HOST,
    )
    assert creds.valid is True
    assert creds.kind == "rapidapi"
    assert creds.plan_slug == "pro"
    assert creds.consumer_id.startswith("c_")


def test_rapidapi_host_mismatch_is_invalid():
    creds = parse_credentials(
        {"X-RapidAPI-Key": "k", "X-RapidAPI-Host": "evil.example.com"},
        expected_host=EXPECTED_HOST,
    )
    assert creds.valid is False
    assert "host" in (creds.error or "").lower()


def test_proxy_secret_enforced_when_configured():
    headers = {"X-RapidAPI-Key": "k", "X-RapidAPI-Host": EXPECTED_HOST}
    bad = parse_credentials(headers, expected_host=EXPECTED_HOST, proxy_secret="s3cr3t")
    assert bad.valid is False
    good = parse_credentials(
        {**headers, "X-RapidAPI-Proxy-Secret": "s3cr3t"},
        expected_host=EXPECTED_HOST,
        proxy_secret="s3cr3t",
    )
    assert good.valid is True


def test_direct_key_credentials():
    creds = parse_credentials({"X-API-Key": "raw-secret"}, expected_host=EXPECTED_HOST)
    assert creds.valid is True
    assert creds.kind == "direct"
    assert creds.consumer_id.startswith("c_")
    # The raw key never appears in the opaque consumer id.
    assert "raw-secret" not in creds.consumer_id


def test_mixed_and_missing_credentials_invalid():
    mixed = parse_credentials(
        {"X-RapidAPI-Key": "k", "X-RapidAPI-Host": EXPECTED_HOST, "X-API-Key": "d"},
        expected_host=EXPECTED_HOST,
    )
    assert mixed.valid is False
    missing = parse_credentials({}, expected_host=EXPECTED_HOST)
    assert missing.valid is False


# --- plan resolution -------------------------------------------------------
def test_resolve_plan_from_subscription_slug():
    creds = parse_credentials(
        {"X-RapidAPI-Key": "k", "X-RapidAPI-Host": EXPECTED_HOST, "X-RapidAPI-Subscription": "pro"},
        expected_host=EXPECTED_HOST,
    )
    assert resolve_plan_name(creds, CATALOG) == "PRO"


def test_resolve_plan_defaults_to_basic_when_unknown_slug():
    creds = parse_credentials(
        {"X-RapidAPI-Key": "k", "X-RapidAPI-Host": EXPECTED_HOST, "X-RapidAPI-Subscription": "mystery"},
        expected_host=EXPECTED_HOST,
    )
    assert resolve_plan_name(creds, CATALOG) == "BASIC"


# --- metering decision -----------------------------------------------------
def test_meter_only_completed_terminal_non_cached():
    assert decide_metering(status_code=200, feasibility_status="likely_feasible", cache_hit=False).billable is True
    assert decide_metering(status_code=200, feasibility_status="likely_constrained", cache_hit=False).billable is True
    assert decide_metering(status_code=200, feasibility_status="needs_professional_review", cache_hit=False).billable is True


def test_do_not_meter_non_billable_outcomes():
    assert decide_metering(status_code=200, feasibility_status="insufficient_data", cache_hit=False).billable is False
    assert decide_metering(status_code=200, feasibility_status="likely_feasible", cache_hit=True).billable is False
    assert decide_metering(status_code=422, feasibility_status=None, cache_hit=False).billable is False
    assert decide_metering(status_code=429, feasibility_status=None, cache_hit=False).billable is False
    assert decide_metering(status_code=400, feasibility_status=None, cache_hit=False).billable is False
    assert decide_metering(status_code=500, feasibility_status=None, cache_hit=False).billable is False


# --- monthly quota ---------------------------------------------------------
def test_monthly_quota_hard_cap():
    assert check_monthly_quota(0, 3).allowed is True
    assert check_monthly_quota(2, 3).allowed is True
    assert check_monthly_quota(3, 3).allowed is False
    assert check_monthly_quota(10, 3).allowed is False
    # No quota configured -> always allowed.
    assert check_monthly_quota(1000, None).allowed is True


# --- burst limiter ---------------------------------------------------------
def test_rate_limiter_blocks_over_limit_and_resets_next_window():
    limiter = InMemoryRateLimiter()
    # 3 per minute, fixed window anchored at now=0.
    assert limiter.allow("c_1", 3, now=0) is True
    assert limiter.allow("c_1", 3, now=1) is True
    assert limiter.allow("c_1", 3, now=2) is True
    assert limiter.allow("c_1", 3, now=3) is False  # 4th in same minute
    # Next minute window resets.
    assert limiter.allow("c_1", 3, now=61) is True
    # A different consumer is independent.
    assert limiter.allow("c_2", 3, now=3) is True
