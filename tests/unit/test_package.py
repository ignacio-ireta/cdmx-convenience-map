"""The cdmxmap package is importable and exposes a version."""

from __future__ import annotations

import cdmxmap


def test_version_is_exposed() -> None:
    assert isinstance(cdmxmap.__version__, str)
    assert cdmxmap.__version__.count(".") >= 1
