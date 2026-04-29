from __future__ import annotations

import argparse

from common import DATA_PROCESSED, city_bbox, copy_seed, element_center, retry_overpass, write_csv


def build_query(city: str) -> str:
    bbox_data = city_bbox(city)
    bbox = (
        f'{bbox_data["south"]},{bbox_data["west"]},'
        f'{bbox_data["north"]},{bbox_data["east"]}'
    )
    return f"""
[out:json][timeout:45];
(
  nwr["leisure"="fitness_centre"]({bbox});
  nwr["amenity"="gym"]({bbox});
);
out tags center;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch gyms from OSM Overpass by city profile.")
    parser.add_argument("--city", default="cdmx", help="City profile id (default: cdmx).")
    parser.add_argument("--seed-only", action="store_true", help="Skip Overpass and use seed CSV.")
    args = parser.parse_args()

    target = DATA_PROCESSED / "gyms.csv"
    if args.seed_only:
        copy_seed("gyms_seed.csv", target)
        return

    try:
        payload = retry_overpass(build_query(args.city), attempts=2, timeout=75)
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for element in payload.get("elements", []):
            center = element_center(element)
            if not center:
                continue
            tags = element.get("tags", {})
            key = (element.get("type", ""), str(element.get("id", "")))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "name": tags.get("name", "Unnamed gym"),
                    "latitude": center[0],
                    "longitude": center[1],
                    "source": "openstreetmap",
                }
            )
        if len(rows) < 5:
            raise ValueError(f"Only found {len(rows)} gym rows")
        write_csv(target, rows, ["name", "latitude", "longitude", "source"])
        print(f"Fetched {len(rows)} gyms")
    except Exception as exc:
        print(f"Falling back to seed gyms because Overpass failed: {exc}")
        copy_seed("gyms_seed.csv", target)


if __name__ == "__main__":
    main()
