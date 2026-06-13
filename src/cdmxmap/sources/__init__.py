"""Open-data source fetchers and shared IO helpers.

Each ``fetch_*`` module downloads and normalizes one source into a processed CSV
(or GeoJSON) under ``data/``. They are runnable as modules, e.g.
``python -m cdmxmap.sources.fetch_postal_codes``, and orchestrated by the CLI.
"""

from __future__ import annotations
