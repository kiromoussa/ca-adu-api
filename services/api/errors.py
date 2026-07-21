"""Consistent error envelope and typed API errors.

Every non-2xx response uses the OpenAPI ``ErrorEnvelope`` shape:

    {"error": {"code", "message", "details"?, "request_id"?}}

Internal exceptions are never leaked: unexpected errors are mapped to a generic
``internal_error`` message. The envelope builder and :class:`ApiError` are pure
(no FastAPI import); ``register_exception_handlers`` wires them into an app.
"""

from __future__ import annotations

from typing import Any, Optional

# Allowed error codes (mirrors ErrorEnvelope.error.code enum in the OpenAPI).
CODE_VALIDATION = "validation_error"
CODE_UNAUTHORIZED = "unauthorized"
CODE_FORBIDDEN = "forbidden"
CODE_NOT_FOUND = "not_found"
CODE_IDEMPOTENCY_CONFLICT = "idempotency_key_conflict"
CODE_UNSUPPORTED_COVERAGE = "unsupported_coverage"
CODE_QUOTA_EXCEEDED = "quota_exceeded"
CODE_RATE_LIMITED = "rate_limited"
CODE_INTERNAL = "internal_error"

_CODE_TO_STATUS = {
    CODE_VALIDATION: 400,
    CODE_UNAUTHORIZED: 401,
    CODE_FORBIDDEN: 403,
    CODE_NOT_FOUND: 404,
    CODE_IDEMPOTENCY_CONFLICT: 409,
    CODE_UNSUPPORTED_COVERAGE: 422,
    CODE_QUOTA_EXCEEDED: 429,
    CODE_RATE_LIMITED: 429,
    CODE_INTERNAL: 500,
}


def build_envelope(
    code: str,
    message: str,
    *,
    details: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build the error envelope dict."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    if request_id is not None:
        error["request_id"] = request_id
    return {"error": error}


class ApiError(Exception):
    """A typed, client-safe API error carrying an envelope code + status."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.http_status = http_status or _CODE_TO_STATUS.get(code, 500)

    def envelope(self, request_id: Optional[str] = None) -> dict[str, Any]:
        return build_envelope(
            self.code, self.message, details=self.details, request_id=request_id
        )


# --- Factory helpers --------------------------------------------------------
def unauthorized(message: str = "Missing or invalid API credentials.") -> ApiError:
    return ApiError(CODE_UNAUTHORIZED, message)


def forbidden(message: str = "You are not permitted to access this resource.") -> ApiError:
    return ApiError(CODE_FORBIDDEN, message)


def not_found(message: str) -> ApiError:
    return ApiError(CODE_NOT_FOUND, message)


def validation_error(message: str, *, details: Optional[dict[str, Any]] = None) -> ApiError:
    return ApiError(CODE_VALIDATION, message, details=details)


def unsupported_coverage(slug: str, coverage_status: str) -> ApiError:
    return ApiError(
        CODE_UNSUPPORTED_COVERAGE,
        f"The jurisdiction '{slug}' is registered but not yet production "
        f"(coverage_status={coverage_status}). No feasibility result is available "
        "and you were not billed.",
        details={"jurisdiction_slug": slug, "coverage_status": coverage_status},
    )


def quota_exceeded(plan: str, quota: int, used: int) -> ApiError:
    return ApiError(
        CODE_QUOTA_EXCEEDED,
        "Monthly quota exceeded for your plan. Upgrade or wait for the next "
        "billing cycle. There are no paid overages in v1.",
        details={"plan": plan, "monthly_quota": quota, "used_this_month": used},
    )


def rate_limited(limit_per_minute: int) -> ApiError:
    return ApiError(
        CODE_RATE_LIMITED,
        "Too many requests in a short window. Slow down and retry shortly.",
        details={"rate_limit_per_minute": limit_per_minute},
        http_status=429,
    )


def idempotency_conflict() -> ApiError:
    return ApiError(
        CODE_IDEMPOTENCY_CONFLICT,
        "This Idempotency-Key was already used with a different request body.",
    )


def internal_error() -> ApiError:
    return ApiError(CODE_INTERNAL, "An unexpected error occurred. Please retry.")


def register_exception_handlers(app) -> None:
    """Attach handlers so every error path emits the envelope. Imports FastAPI lazily."""
    import logging

    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    logger = logging.getLogger("aduatlas.api")

    def _request_id(request: Request) -> Optional[str]:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.envelope(request_id=_request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        details = {"errors": exc.errors()[:10]}
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                CODE_VALIDATION,
                "The request body or parameters were malformed.",
                details=details,
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException):
        code = {
            401: CODE_UNAUTHORIZED,
            403: CODE_FORBIDDEN,
            404: CODE_NOT_FOUND,
            429: CODE_RATE_LIMITED,
        }.get(exc.status_code, CODE_INTERNAL if exc.status_code >= 500 else CODE_VALIDATION)
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be processed."
        return JSONResponse(
            status_code=exc.status_code,
            content=build_envelope(code, message, request_id=_request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _unexpected_handler(request: Request, exc: Exception):
        # Never leak internal detail; log server-side for correlation.
        logger.exception("Unhandled error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content=build_envelope(
                CODE_INTERNAL,
                "An unexpected error occurred. Please retry.",
                request_id=_request_id(request),
            ),
        )
