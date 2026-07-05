"""Backward-compatible alias for the generic OpenStreetMap transit fetcher.

The Norwegian city profiles (``oslo``/``bergen``/``trondheim``/``stavanger``/
``drammen``) reference this module by name in their ``fetchers`` list. The
implementation is country-neutral and now lives in :mod:`fetch_osm_transit`;
this shim preserves the ``python -m cdmxmap.sources.fetch_no_transit`` entry
point so those profiles keep working byte-for-byte.
"""

from __future__ import annotations

from .fetch_osm_transit import main

if __name__ == "__main__":
    main()
