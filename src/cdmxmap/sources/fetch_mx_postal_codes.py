"""Fetch Mexican postal-code (SEPOMEX) area polygons for one city profile.

Two modes, chosen by the profile:

- **Municipality mode** (the profile declares ``mx_area``; Monterrey, Guadalajara):
  every open-mexico SEPOMEX polygon of the state is assigned the INEGI
  municipality it overlaps most (``mx_common.assign_largest_overlap``) and kept
  when that municipality is in ``mx_area.municipalities``. Each polygon gets a
  ``colonias_label`` built from INEGI DCAH 2025 colonia names (free-use terms
  with attribution). The SEPOMEX/Correos asentamiento catalog is deliberately
  not used: its terms forbid redistribution.
- **Legacy range mode** (``postal_code_range``; Morelia): the state file is
  trimmed to the profile bbox and the inclusive code range. This path is kept
  byte-for-byte as it was.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable

import geopandas as gpd
import pandas as pd

from cdmxmap.errors import FetchError

from . import mx_common
from .fetch_mx_colonias import (
    fold_name,
    member_colonias,
    member_municipalities,
    metric_crs,
    outside_bbox,
    point_postal_codes,
    representative_points,
    source_url,
    write_geojson,
)
from .io import DATA_RAW, city_bbox, city_data_dir, load_city_profile
from .mx_common import cached_state_file

SOURCE = "open_mexico_sepomex"
LABEL_NAMES = 2
POSTAL_PROPERTIES = (
    "d_codigo",
    "mun_code",
    "municipio",
    "colonias_label",
    "colonias_count",
    "source",
)


def _state_source_url(profile: dict, city: str) -> str:
    url = (profile.get("sources") or {}).get("postal_codes")
    if not url:
        raise ValueError(
            f"City profile '{city}' must declare sources.postal_codes "
            "(the state GeoJSON URL of postal-code polygons)"
        )
    return str(url)


def _postal_range(profile: dict, city: str) -> tuple[int, int]:
    """Inclusive ``[min, max]`` postal-code range that defines the municipality."""
    values = profile.get("postal_code_range")
    if not values or len(values) != 2:
        raise ValueError(
            f"City profile '{city}' must declare postal_code_range [min, max] "
            "to select its municipality from the state file"
        )
    low, high = int(values[0]), int(values[1])
    return (low, high) if low <= high else (high, low)


# The state-file cache moved to ``mx_common`` (shared with the other Mexican
# fetchers); the alias keeps this module's call sites and cache path unchanged.
_cached_state_file = cached_state_file


# ---------------------------------------------------------------------------
# Municipality mode (profile declares ``mx_area``)
# ---------------------------------------------------------------------------


def colonias_label(names: Iterable[str]) -> tuple[str, int]:
    """``("First, Second +N", distinct_count)`` from names in display order.

    Names are de-duplicated case-, accent- and whitespace-insensitively, keeping
    the first spelling; the label shows the first two and counts the rest.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = fold_name(name)
        if key and key not in seen:
            seen.add(key)
            unique.append(name)
    label = ", ".join(unique[:LABEL_NAMES])
    extra = len(unique) - LABEL_NAMES
    return (f"{label} +{extra}" if extra > 0 else label), len(unique)


def postal_colonia_labels(
    areas: gpd.GeoDataFrame, colonias: gpd.GeoDataFrame, crs: str
) -> tuple[list[str], list[int]]:
    """``colonias_label`` and ``colonias_count`` for each row of ``areas``.

    A colonia belongs to the postal polygon holding its representative point;
    within a polygon, colonias are listed by area (largest first), ties broken
    by name then ``cvegeo``.
    """
    codes = point_postal_codes(representative_points(colonias, crs), areas, crs)
    members = pd.DataFrame(
        {
            "d_codigo": codes.to_numpy(),
            "area": colonias.geometry.to_crs(crs).area.to_numpy(),
            "name": colonias["colonia_name"].astype(str).to_numpy(),
            "cvegeo": colonias["cvegeo"].astype(str).to_numpy(),
        }
    )
    members = members[members["d_codigo"] != ""].sort_values(
        ["d_codigo", "area", "name", "cvegeo"],
        ascending=[True, False, True, True],
        kind="mergesort",
    )
    by_code = {
        str(code): colonias_label(group["name"].tolist())
        for code, group in members.groupby("d_codigo", sort=False)
    }
    labels = [by_code.get(str(code), ("", 0)) for code in areas["d_codigo"]]
    return [label for label, _ in labels], [count for _, count in labels]


def municipality_postal_areas(
    postal: gpd.GeoDataFrame,
    municipalities: gpd.GeoDataFrame,
    colonias: gpd.GeoDataFrame,
    members: list[str],
    crs: str,
    city: str,
) -> gpd.GeoDataFrame:
    """Spec §3 ``postal_codes.geojson`` frame (EPSG:4326, sorted by ``d_codigo``).

    ``municipalities`` is the whole state (a polygon mostly outside the metro
    must lose to its real municipality); ``colonias`` are the named member
    colonias from ``member_colonias``.
    """
    duplicated = sorted(set(postal["d_codigo"][postal["d_codigo"].duplicated()]))
    if duplicated:
        raise FetchError(f"State postal file repeats d_codigo {duplicated[:5]}")
    assigned = mx_common.assign_largest_overlap(postal, municipalities, "mun_code", metric_crs=crs)
    unassigned = int(assigned.isna().sum())
    if unassigned:
        print(f"{unassigned} postal polygons overlap no INEGI municipality and were skipped")

    member_rows = member_municipalities(municipalities, members, city)
    names_by_code = dict(
        zip(member_rows["mun_code"].astype(str), member_rows["municipio"].astype(str))
    )
    keep = assigned.isin(list(names_by_code)).to_numpy(dtype=bool)
    areas = postal[keep].copy()
    areas["mun_code"] = assigned[keep].astype(str).to_numpy()
    empty = sorted(set(names_by_code) - set(areas["mun_code"]))
    if empty:
        raise FetchError(f"No postal polygons fall in member municipalities {empty} of {city}")

    labels, counts = postal_colonia_labels(areas, colonias, crs)
    frame = gpd.GeoDataFrame(
        {
            "d_codigo": areas["d_codigo"].astype(str).to_numpy(),
            "mun_code": areas["mun_code"].to_numpy(),
            "municipio": [names_by_code[code] for code in areas["mun_code"]],
            "colonias_label": labels,
            "colonias_count": counts,
            "source": SOURCE,
        },
        geometry=areas.geometry.to_crs(mx_common.WGS84).to_numpy(),
        crs=mx_common.WGS84,
    )
    frame = frame[[*POSTAL_PROPERTIES, "geometry"]]
    return frame.sort_values("d_codigo", kind="mergesort").reset_index(drop=True)


def build_municipality_areas(profile: dict, city: str, url: str) -> gpd.GeoDataFrame:
    """Load the cached state inputs and return the city's postal-code areas."""
    state, members = mx_common.profile_mx_area(profile, city)
    crs = metric_crs(profile, city)
    municipalities = mx_common.load_state_municipalities(state)
    postal = mx_common.load_state_postal_polygons(url)
    dcah = mx_common.load_dcah(source_url(profile, "colonias", city), state)
    colonias, _ = member_colonias(dcah, state, members)
    return municipality_postal_areas(postal, municipalities, colonias, members, crs, city)


def _write_municipality_areas(profile: dict, city: str, url: str) -> None:
    areas = build_municipality_areas(profile, city, url)
    unlabelled = int((areas["colonias_label"] == "").sum())
    print(
        f"{len(areas)} postal polygons in {areas['mun_code'].nunique()} municipalities; "
        f"{unlabelled} without a DCAH colonia label"
    )
    for (mun_code, municipio), count in (
        areas.groupby(["mun_code", "municipio"], sort=True).size().items()
    ):
        print(f"  {mun_code} {municipio}: {count}")
    if outside_bbox(areas, profile):
        print(f"WARNING: {city} postal polygons extend beyond the profile bbox {profile['bbox']}")
    target = city_data_dir(DATA_RAW, city) / "postal_codes.geojson"
    write_geojson(areas, target)
    print(f"Wrote {len(areas)} {city} postal-code areas (municipality mode) to {target}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Mexican postal-code area polygons for one city profile."
    )
    parser.add_argument("--city", required=True)
    args = parser.parse_args()

    profile = load_city_profile(args.city)
    url = _state_source_url(profile, args.city)
    if "mx_area" in profile:
        _write_municipality_areas(profile, args.city, url)
        return
    low, high = _postal_range(profile, args.city)
    raw_dir = city_data_dir(DATA_RAW, args.city)
    raw_dir.mkdir(parents=True, exist_ok=True)

    areas = gpd.read_file(_cached_state_file(url)).to_crs("EPSG:4326")
    bbox = city_bbox(args.city)
    areas = areas.cx[bbox["west"] : bbox["east"], bbox["south"] : bbox["north"]].copy()
    codes = areas["d_codigo"].astype(int)
    areas = areas[(codes >= low) & (codes <= high)].copy()
    if areas.empty:
        raise ValueError(
            f"State file returned no postal-code areas for {args.city} "
            f"in range {low}-{high} within its bbox"
        )
    target = raw_dir / "postal_codes.geojson"
    areas.to_file(target, driver="GeoJSON")
    print(f"Wrote {len(areas)} {args.city} postal-code areas ({low}-{high}) to {target}")


if __name__ == "__main__":
    main()
