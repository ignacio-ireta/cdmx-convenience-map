"""Shared pytest configuration.

The production pipeline currently lives under ``scripts/`` (it moves into
``src/cdmxmap/`` in Phase 2). Put that directory on the import path so tests can
exercise the existing modules directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
