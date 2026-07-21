"""Shared pytest configuration for the CA ADU Zoning API test suite.

Puts two directories on sys.path so the scraper and pipeline modules import the
same way they do in production:

  - the repo root, so ``import scraper.adapters.alp`` resolves the package.
  - ``scraper/pipeline``, so ``import baselines`` / ``import validate`` resolve
    as top-level modules (validate.py does ``from baselines import ...``, i.e.
    it expects the pipeline dir to be on the path, which is how run.py invokes
    it on Render).

No network, no real Supabase, and no environment secrets are required to import
anything the tests touch.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
PIPELINE_DIR = REPO_ROOT / "scraper" / "pipeline"

for _path in (str(REPO_ROOT), str(PIPELINE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
