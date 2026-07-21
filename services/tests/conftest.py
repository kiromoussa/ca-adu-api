"""Pytest bootstrap for the services test suite.

Ensures the repository root is importable so ``import services...`` works no
matter where pytest is invoked from. These tests use fakes only; they never
touch a live database or the network and never import the psycopg-backed
``services.core.db`` or the FastAPI app.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
