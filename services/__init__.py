"""ADU Atlas API service package.

Two subpackages:

- ``services.core`` - the pure, deterministic, unit-testable feasibility core
  (address normalization, PostGIS spatial resolution, the versioned rule engine,
  and the feasibility orchestrator). No LLM is ever used on this path.
- ``services.api`` - the FastAPI request path (routers, Pydantic schemas mirroring
  the OpenAPI contract, the RapidAPI gateway/limiter, idempotency, and the error
  envelope).
"""

__all__ = ["core", "api"]
