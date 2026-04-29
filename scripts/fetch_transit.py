from __future__ import annotations

import argparse
import json
import urllib.request

from common import DATA_PROCESSED, DATA_RAW, USER_AGENT, ensure_dirs, write_csv


APIMETRO_SYSTEMS = ["METRO", "MB", "RTP", "TROLE", "CC"]
APIMETRO_STATIONS_URL = (
    "https://apimetro.dev/movilidad/mapas/geojsonEstacion"
    f"?sistema={','.join(APIMETRO_SYSTEMS)}&existe=true"
)


def fetch_geojson(force: bool) -> dict:
    ensure_dirs()
    raw_path = DATA_RAW / "apimetro_transit_stations.geojson"
    if raw_path.exists() and not force:
        print(f"Using cached {raw_path}")
        return json.loads(raw_path.read_text(encoding="utf-8"))

    print(f"Downloading {APIMETRO_STATIONS_URL}")
    request = urllib.request.Request(
        APIMETRO_STATIONS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {raw_path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch transit station/stop points from Apimetro GeoJSON."
    )
    parser.add_argument("--force", action="store_true", help="Redownload even if cached.")
    args = parser.parse_args()

    payload = fetch_geojson(args.force)
    rows: list[dict] = []
    seen: set[tuple[str, str, float, float]] = set()

    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (TypeError, ValueError):
            continue

        properties = feature.get("properties") or {}
        system = str(properties.get("sistema") or "").upper()
        if system not in APIMETRO_SYSTEMS:
            continue
        stop_name = str(properties.get("nombre") or "Unnamed stop").strip()
        line = str(properties.get("num_comercial") or "").strip()
        hierarchy = str(properties.get("jerarquia_transporte") or "").strip()
        key = (system, stop_name.casefold(), round(lon, 6), round(lat, 6))
        if key in seen:
            continue
        seen.add(key)

        display_name = f"{system} · {stop_name}"

        rows.append(
            {
                "id": f"{system}-{len(rows) + 1}",
                "name": display_name,
                "system": system,
                "line": line,
                "hierarchy": hierarchy,
                "latitude": lat,
                "longitude": lon,
                "source": "apimetro",
            }
        )

    if not rows:
        raise ValueError("No Apimetro transit points were extracted")

    rows.sort(key=lambda row: (row["system"], row["name"], row["latitude"], row["longitude"]))
    write_csv(
        DATA_PROCESSED / "transit_stops.csv",
        rows,
        ["id", "name", "system", "line", "hierarchy", "latitude", "longitude", "source"],
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["system"]] = counts.get(row["system"], 0) + 1
    print(f"Extracted {len(rows)} Apimetro transit points: {counts}")


if __name__ == "__main__":
    main()
