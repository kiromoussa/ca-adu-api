"""Shared minimal client helper for the ADU Atlas API, used by the other
examples in this directory.

Uses httpx (async-friendly, HTTP/2 capable):
    pip install httpx

A drop-in requests-based equivalent is included at the bottom of each example
file's docstring; requests works identically for these synchronous calls
(swap `httpx.Client()` for `requests.Session()` and `client.get/post(...)`
stays the same, since both expose the same basic call signature).

Pick ONE auth mode. Never send RapidAPI headers and X-API-Key together.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx

AuthMode = Literal["rapidapi", "direct"]

# The RapidAPI Hub endpoint paths were registered WITHOUT the /v1 prefix (the
# origin's /v1 base path lives in the provider's Base URL setting on the Hub,
# invisible to consumers). property-feasibility4.p.rapidapi.com/feasibility
# maps to https://adu-atlas-api.onrender.com/v1/feasibility on the origin.
RAPIDAPI_BASE_URL = "https://property-feasibility4.p.rapidapi.com"
DIRECT_BASE_URL = "https://api.aduatlas.example.com"
DEFAULT_RAPIDAPI_HOST = "property-feasibility4.p.rapidapi.com"


@dataclass
class AduAtlasConfig:
    mode: AuthMode
    rapidapi_key: Optional[str] = None
    rapidapi_host: str = DEFAULT_RAPIDAPI_HOST
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    def headers(self) -> dict[str, str]:
        if self.mode == "rapidapi":
            if not self.rapidapi_key:
                raise ValueError("rapidapi_key is required when mode='rapidapi'")
            return {
                "Content-Type": "application/json",
                "X-RapidAPI-Key": self.rapidapi_key,
                "X-RapidAPI-Host": self.rapidapi_host,
            }
        if not self.api_key:
            raise ValueError("api_key is required when mode='direct'")
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def url(self) -> str:
        if self.base_url:
            return self.base_url
        return RAPIDAPI_BASE_URL if self.mode == "rapidapi" else DIRECT_BASE_URL


class AduAtlasApiError(Exception):
    """Raised for any non-2xx response. Mirrors the ErrorEnvelope schema."""

    def __init__(self, status_code: int, body: dict[str, Any]):
        error = body.get("error", {})
        self.status_code = status_code
        self.code = error.get("code", "unknown_error")
        self.message = error.get("message", "Unknown error")
        self.details = error.get("details")
        self.request_id = error.get("request_id")
        super().__init__(f"[{status_code} {self.code}] {self.message}")


def _consumer_path(config: AduAtlasConfig, path: str) -> str:
    """Every example in this directory writes paths with the /v1 prefix (the
    origin's real path). RapidAPI's Hub-registered endpoint paths omit that
    prefix, so this strips it automatically when mode='rapidapi'.
    """
    if config.mode == "rapidapi" and path.startswith("/v1/"):
        return path[len("/v1"):]
    return path


def request(
    config: AduAtlasConfig,
    method: str,
    path: str,
    *,
    json: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    extra_headers: Optional[dict[str, str]] = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    headers = config.headers()
    if extra_headers:
        headers.update(extra_headers)

    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            f"{config.url()}{_consumer_path(config, path)}",
            headers=headers,
            json=json,
            params=params,
        )

    body = response.json()
    if response.status_code >= 400:
        raise AduAtlasApiError(response.status_code, body)
    return body


def rapidapi_config_from_env() -> AduAtlasConfig:
    return AduAtlasConfig(mode="rapidapi", rapidapi_key=os.environ["RAPIDAPI_KEY"])


def direct_config_from_env() -> AduAtlasConfig:
    return AduAtlasConfig(mode="direct", api_key=os.environ["ADU_ATLAS_API_KEY"])
