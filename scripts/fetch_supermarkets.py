from __future__ import annotations

import argparse
import re

from common import CDMX_BBOX, DATA_PROCESSED, copy_seed, element_center, retry_overpass, write_csv


BRAND_PATTERN = re.compile(r"(costco|walmart)", re.IGNORECASE)
ALLOWED_SHOPS = {"supermarket", "wholesale", "department_store"}


def build_query() -> str:
    bbox = (
        f'{CDMX_BBOX["south"]},{CDMX_BBOX["west"]},'
        f'{CDMX_BBOX["north"]},{CDMX_BBOX["east"]}'
    )
    return f"""
[out:json][timeout:45];
(
  nwr["brand"~"Costco|Walmart",i]({bbox});
  nwr["operator"~"Costco|Walmart",i]({bbox});
  nwr["name"~"Costco|Walmart",i]({bbox});
);
out tags center;
"""


def infer_brand(tags: dict) -> str:
    haystack = " ".join(
        str(tags.get(key, "")) for key in ["brand", "operator", "name"]
    )
    match = BRAND_PATTERN.search(haystack)
    return match.group(1).title() if match else "Unknown"


def is_store(tags: dict) -> bool:
    shop = str(tags.get("shop", "")).lower()
    name = str(tags.get("name", "")).lower()
    if shop in ALLOWED_SHOPS:
        return True
    if "costco" in name:
        return True
    if "walmart" in name and not any(
        blocked in name for blocked in ["banco", "farmacia"]
    ):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CDMX Costco/Walmart points from OSM.")
    parser.add_argument("--seed-only", action="store_true", help="Skip Overpass and use seed CSV.")
    args = parser.parse_args()

    target = DATA_PROCESSED / "supermarkets.csv"
    if args.seed_only:
        copy_seed("supermarkets_seed.csv", target)
        return

    try:
        payload = retry_overpass(build_query(), attempts=2, timeout=75)
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for element in payload.get("elements", []):
            center = element_center(element)
            if not center:
                continue
            tags = element.get("tags", {})
            brand = infer_brand(tags)
            if brand == "Unknown" or not is_store(tags):
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
            raise ValueError(f"Only found {len(rows)} Costco/Walmart rows")
        write_csv(target, rows, ["name", "brand", "latitude", "longitude", "source"])
        print(f"Fetched {len(rows)} Costco/Walmart points")
    except Exception as exc:
        print(f"Falling back to seed supermarkets because Overpass failed: {exc}")
        copy_seed("supermarkets_seed.csv", target)


if __name__ == "__main__":
    main()
