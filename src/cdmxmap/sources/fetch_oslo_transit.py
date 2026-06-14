from __future__ import annotations

import argparse

from .io import (
    DATA_PROCESSED,
    city_bbox,
    city_data_dir,
    element_center,
    retry_overpass,
    write_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Oslo public-transport stops from OSM.")
    parser.add_argument("--city", required=True)
    args = parser.parse_args()
    if args.city != "oslo":
        raise ValueError("This fetcher only supports the Oslo profile")
    bbox_data = city_bbox(args.city)
    bbox = ",".join(str(bbox_data[key]) for key in ["south", "west", "north", "east"])
    query = f"""
[out:json][timeout:90];
(
  nwr["highway"="bus_stop"]({bbox});
  nwr["railway"~"station|halt|tram_stop|subway_entrance"]({bbox});
  nwr["public_transport"~"platform|station"]({bbox});
);
out tags center;
"""
    payload = retry_overpass(query, attempts=3, timeout=120)
    rows = []
    seen = set()
    for element in payload.get("elements", []):
        center = element_center(element)
        if not center:
            continue
        tags = element.get("tags") or {}
        key = (element.get("type"), element.get("id"))
        if key in seen:
            continue
        seen.add(key)
        railway = str(tags.get("railway", ""))
        mode = str(tags.get("station", "") or tags.get("tram", ""))
        system = "RAIL" if railway or mode in {"subway", "light_rail", "tram"} else "BUS"
        rows.append(
            {
                "id": f"osm:{key[0]}:{key[1]}",
                "name": tags.get("name", "Unnamed stop"),
                "system": system,
                "line": "",
                "hierarchy": tags.get("public_transport", ""),
                "latitude": center[0],
                "longitude": center[1],
                "source": "openstreetmap",
            }
        )
    if not rows:
        raise ValueError("OSM returned no Oslo public-transport stops")
    target = city_data_dir(DATA_PROCESSED, args.city) / "transit_stops.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_csv(
        target,
        rows,
        ["id", "name", "system", "line", "hierarchy", "latitude", "longitude", "source"],
    )
    print(f"Wrote {len(rows)} Oslo public-transport stops")


if __name__ == "__main__":
    main()
