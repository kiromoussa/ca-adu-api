"""FastAPI request path for ADU Atlas.

The app (``services.api.main.app``) exposes the ``/v1`` router defined by
``openapi/openapi.yaml``. All request/response shapes are the Pydantic models in
``schemas.py``; the RapidAPI gateway/limiter, idempotency, and the error envelope
live in their own modules. No LLM is invoked on this path.
"""

__all__ = ["main", "schemas", "settings", "errors", "rapidapi", "idempotency", "deps"]
