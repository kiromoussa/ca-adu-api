"""Idempotency-Key handling for POST /v1/feasibility.

A repeated key with an identical request body replays the stored response; a
repeated key with a different body is a 409 conflict. "Identical body" is
determined by the request fingerprint (a hash of the normalized inputs), so the
comparison is robust to insignificant formatting differences.
"""

from __future__ import annotations

from typing import Any, Optional

from . import errors
from ..core.repository import FeasibilityRepository


def check_idempotency(
    repo: FeasibilityRepository,
    *,
    consumer_id: Optional[str],
    idempotency_key: Optional[str],
    request_fingerprint: str,
) -> Optional[dict[str, Any]]:
    """Return a stored analysis to replay, or ``None`` if this is a fresh key.

    Raises :class:`errors.ApiError` (409) when the key was used with a different
    body. The returned dict (when present) carries ``result_json`` and
    ``feasibility_status`` for replay without recomputation or billing.
    """
    if not idempotency_key:
        return None
    stored = repo.find_by_idempotency_key(consumer_id, idempotency_key)
    if stored is None:
        return None
    if stored.get("request_fingerprint") != request_fingerprint:
        raise errors.idempotency_conflict()
    return stored
