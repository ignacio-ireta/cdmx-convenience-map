"""cdmxmap — geo data pipeline for city-area convenience scoring.

Fetches open-data sources for a city, scores every area unit (postal code /
colonia) on convenience metrics, and writes ``scores_*.geojson`` +
``score_metadata_*.json`` for the static map frontend.

The pipeline is organized as: sources (fetch) -> scoring (engine over a typed
intermediate model) -> output (geojson/metadata/manifest), driven by the CLI.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
