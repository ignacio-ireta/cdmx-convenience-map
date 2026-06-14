from __future__ import annotations

import argparse

from .io import (
    DATA_PROCESSED,
    city_bbox,
    city_data_dir,
    copy_seed,
    element_center,
    load_city_profile,
    retry_overpass,
    write_csv,
)

ALLOWED_SHOPS = {"supermarket", "wholesale", "department_store"}


def build_query(city: str, brands: set[str]) -> str:
    bbox_data = city_bbox(city)
    bbox = f"{bbox_data['south']},{bbox_data['west']},{bbox_data['north']},{bbox_data['east']}"
    pattern = "|".join(sorted(brands))
    return f"""
[out:json][timeout:45];
(
  nwr["shop"~"supermarket|wholesale|department_store"]["brand"~"{pattern}",i]({bbox});
  nwr["shop"~"supermarket|wholesale|department_store"]["operator"~"{pattern}",i]({bbox});
  nwr["shop"~"supermarket|wholesale|department_store"]["name"~"{pattern}",i]({bbox});
);
out tags center;
"""


def infer_brand(tags: dict, brands: set[str]) -> str:
    haystack = " ".join(str(tags.get(key, "")).lower() for key in ["brand", "operator", "name"])
    match = next(
        (brand for brand in sorted(brands, key=len, reverse=True) if brand in haystack),
        None,
    )
    return match.title() if match else "Unknown"


def is_store(tags: dict) -> bool:
    shop = str(tags.get("shop", "")).lower()
    name = str(tags.get("name", "")).lower()
    if shop in ALLOWED_SHOPS:
        return True
    if "costco" in name:
        return True
    if "walmart" in name and not any(blocked in name for blocked in ["banco", "farmacia"]):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch supermarket points from OSM by city profile."
    )
    parser.add_argument("--city", default="cdmx", help="City profile id (default: cdmx).")
    parser.add_argument("--seed-only", action="store_true", help="Skip Overpass and use seed CSV.")
    args = parser.parse_args()

    target = city_data_dir(DATA_PROCESSED, args.city) / "supermarkets.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.seed_only:
        if args.city != "cdmx":
            raise ValueError("Seed data is only valid for CDMX")
        copy_seed("supermarkets_seed.csv", target)
        return

    try:
        profile = load_city_profile(args.city)
        brands = {
            brand.lower()
            for brand in profile.get("amenity_brands", {}).get(
                "supermarkets", ["costco", "walmart"]
            )
        }
        payload = retry_overpass(build_query(args.city, brands), attempts=2, timeout=75)
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for element in payload.get("elements", []):
            center = element_center(element)
            if not center:
                continue
            tags = element.get("tags", {})
            brand = infer_brand(tags, brands)
            if brand == "Unknown" or brand.lower() not in brands or not is_store(tags):
                continue
            key = (element.get("type", ""), str(element.get("id", "")))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "name": tags.get("name", brand),
                    "brand": brand,
                    "latitude": center[0],
                    "longitude": center[1],
                    "source": "openstreetmap",
                }
            )
        if len(rows) < 5:
            raise ValueError(f"Only found {len(rows)} matching supermarket rows")
        write_csv(target, rows, ["name", "brand", "latitude", "longitude", "source"])
        print(f"Fetched {len(rows)} matching supermarket points")
    except Exception as exc:
        if args.city != "cdmx":
            raise RuntimeError(f"Could not fetch supermarkets for {args.city}: {exc}") from exc
        print(f"Falling back to seed supermarkets because Overpass failed: {exc}")
        copy_seed("supermarkets_seed.csv", target)


if __name__ == "__main__":
    main()
