# Archived Data

The original MVP used the official CDMX GTFS ZIP directly and scored distance to every stop in `stops.txt`. That made the transit metric noisy because the stop pool was too dense and undifferentiated.

Those generated GTFS artifacts are no longer part of the active pipeline. If present locally, they live under `data/archive/gtfs_legacy/` and can be regenerated with `scripts/archive/fetch_gtfs_transit.py`.

Active transit scoring now uses Apimetro station/stop GeoJSON for Metro, Metrobús, RTP, Trolebús, and Corredor Concesionado.

