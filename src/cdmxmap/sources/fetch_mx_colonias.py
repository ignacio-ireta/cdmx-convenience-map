"""Fetch INEGI DCAH 2025 colonia polygons for a Mexican profile city.

The city profile's ``mx_area`` block names the INEGI state and the member
municipalities (3-digit ``cve_mun``). The state-wide DCAH 2025 shapefile
("Delimitación de colonias y otros asentamientos humanos", INEGI free-use terms
with attribution) is cached once under ``data/raw/`` by ``mx_common.load_dcah``;
this fetcher keeps the polygons of the member municipalities that carry a real
name and writes ``data/raw/<city>/colonias.geojson`` with the normalized
properties of spec §3:

``area_unit`` ("colonia"), ``area_id`` (13-char ``cvegeo``), ``area_name`` =
``display_name`` = ``colonia_name`` (title-cased ``nom_asen``), ``municipio``
(INEGI municipality name), ``mun_code`` (``cve_ent`` + ``cve_mun``), ``col_code``
(``cve_asen``), ``col_type`` (title-cased ``tipo``), ``postal_code`` (DCAH ``cp``
unless it is the "00000" placeholder, else the open-mexico SEPOMEX polygon that
holds the colonia's representative point, else ""), ``year`` (from
``fecha_act``) and ``source`` ("inegi_dcah_2025").

The helpers that pick member colonias and place them in postal polygons are
shared with ``fetch_mx_postal_codes`` (its ``colonias_label``), so both outputs
agree on which colonias exist and where they sit.
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.errors import ConfigError, FetchError

from . import mx_common
from .io import DATA_RAW, city_data_dir, load_city_profile

SOURCE = "inegi_dcah_2025"
OUTPUT_NAME = "colonias.geojson"
AREA_UNIT = "colonia"
CVEGEO_LENGTH = 13
# DCAH writes "00000" when the municipality supplied no postal code (every
# Jalisco row in the 2025 edition).
DCAH_NO_POSTAL_CODE = "00000"
COLONIA_PROPERTIES = (
    "area_unit",
    "area_id",
    "area_name",
    "display_name",
    "colonia_name",
    "municipio",
    "mun_code",
    "col_code",
    "col_type",
    "postal_code",
    "year",
    "source",
)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def metric_crs(profile: dict, city: str) -> str:
    """The profile's metric CRS (``crs_metric_epsg``) as an ``EPSG:<code>`` string."""
    epsg = profile.get("crs_metric_epsg")
    if not isinstance(epsg, int) or isinstance(epsg, bool) or epsg <= 0:
        raise ConfigError(f"City profile '{city}' must declare an integer crs_metric_epsg")
    return f"EPSG:{epsg}"


def source_url(profile: dict, key: str, city: str) -> str:
    """``profile["sources"][key]`` as a non-empty string, else ``ConfigError``."""
    url = (profile.get("sources") or {}).get(key)
    if not isinstance(url, str) or not url.strip():
        raise ConfigError(f"City profile '{city}' must declare sources.{key}")
    return url.strip()


# ---------------------------------------------------------------------------
# Selection and normalization (pure: frames in, frames out)
# ---------------------------------------------------------------------------


def member_municipalities(
    municipalities: gpd.GeoDataFrame, members: list[str], city: str
) -> gpd.GeoDataFrame:
    """The INEGI municipalities listed in ``mx_area.municipalities``.

    Raises ``ConfigError`` when a declared ``cve_mun`` is not in the state file,
    so a typo in the profile can never silently shrink the city.
    """
    codes = municipalities["cve_mun"].astype(str)
    missing = [code for code in members if code not in set(codes)]
    if missing:
        raise ConfigError(
            f"City profile '{city}' mx_area.municipalities lists {missing}, "
            "which the INEGI municipal file for its state does not contain"
        )
    return municipalities[codes.isin(members)].copy()


def member_colonias(
    dcah: gpd.GeoDataFrame, state_code: str, members: list[str]
) -> tuple[gpd.GeoDataFrame, int]:
    """DCAH polygons of the member municipalities that carry a real name.

    Returns the kept rows (with ``cve_mun`` normalized to 3 digits and a new
    title-cased ``colonia_name`` column) and the number of member polygons
    dropped because their ``nom_asen`` is a placeholder (NINGUNO, SIN NOMBRE, ...).
    """
    cve_ent = dcah["cve_ent"].astype(str).str.strip()
    cve_mun = dcah["cve_mun"].astype(str).str.strip().str.zfill(3)
    in_area = (cve_ent == state_code) & cve_mun.isin(members)
    frame = dcah[in_area].copy()
    frame["cve_mun"] = cve_mun[in_area]
    unnamed = frame["nom_asen"].map(mx_common.is_unnamed_colonia).astype(bool)
    dropped = int(unnamed.sum())
    frame = frame[~unnamed].copy()
    frame["colonia_name"] = [
        mx_common.spanish_title_case(" ".join(str(name).split())) for name in frame["nom_asen"]
    ]
    return frame, dropped


def representative_points(frame: gpd.GeoDataFrame, crs: str) -> gpd.GeoSeries:
    """Representative points of ``frame``'s polygons, computed in ``crs``."""
    return frame.geometry.to_crs(crs).representative_point()


def point_postal_codes(points: gpd.GeoSeries, postal: gpd.GeoDataFrame, crs: str) -> pd.Series:
    """For each point, the ``d_codigo`` of the postal polygon containing it, else "".

    A point on a shared edge touches two polygons; the lowest ``d_codigo`` wins
    so the result is deterministic. The Series is index-aligned with ``points``.
    """
    values = np.full(len(points), "", dtype=object)
    if len(points) and len(postal):
        left = gpd.GeoDataFrame(
            {"_pos": np.arange(len(points))}, geometry=list(points.to_crs(crs)), crs=crs
        )
        right = gpd.GeoDataFrame(
            {"_cp": postal["d_codigo"].astype(str).to_numpy()},
            geometry=list(postal.geometry.to_crs(crs)),
            crs=crs,
        )
        pairs = gpd.sjoin(left, right, how="inner", predicate="intersects")
        best = pairs.sort_values(["_pos", "_cp"], kind="mergesort").drop_duplicates("_pos")
        values[best["_pos"].to_numpy(dtype=int)] = best["_cp"].to_numpy()
    return pd.Series(values, index=points.index, dtype=object)


def dcah_postal_code(value: object) -> str:
    """The DCAH ``cp`` as a 5-digit code, or "" for the "00000"/empty placeholder."""
    text = str(value if value is not None else "").strip()
    if re.fullmatch(r"\d{5}", text) and text != DCAH_NO_POSTAL_CODE:
        return text
    return ""


def dcah_year(value: object) -> str:
    """The 4-digit year of a DCAH ``fecha_act`` ("11/2025" -> "2025"), else ""."""
    match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(value if value is not None else ""))
    return match.group(1) if match else ""


def colonia_type(value: object) -> str:
    """Title-cased DCAH ``tipo``; the "NINGUNO" placeholder becomes ""."""
    text = " ".join(str(value if value is not None else "").split())
    if mx_common.is_unnamed_colonia(text):
        return ""
    return mx_common.spanish_title_case(text)


def fold_name(name: str) -> str:
    """Case-, accent- and whitespace-insensitive key for de-duplicating names."""
    decomposed = unicodedata.normalize("NFKD", name)
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(bare.casefold().split())


def normalize_colonias(
    colonias: gpd.GeoDataFrame,
    municipalities: gpd.GeoDataFrame,
    postal: gpd.GeoDataFrame,
    crs: str,
) -> gpd.GeoDataFrame:
    """Spec §3 ``colonias.geojson`` frame (EPSG:4326, sorted by ``area_id``).

    ``colonias`` is the output of ``member_colonias``; ``municipalities`` must
    hold every municipality those colonias belong to; ``postal`` is the
    open-mexico state file used for the postal-code fallback.
    """
    names_by_code = dict(
        zip(municipalities["mun_code"].astype(str), municipalities["municipio"].astype(str))
    )
    mun_codes = colonias["cve_ent"].astype(str).str.strip() + colonias["cve_mun"].astype(str)
    unknown = sorted(set(mun_codes) - set(names_by_code))
    if unknown:
        raise FetchError(
            f"DCAH colonias reference municipalities {unknown} missing from INEGI mgem"
        )

    area_ids = colonias["cvegeo"].astype(str).str.strip()
    bad_ids = sorted(area_ids[area_ids.str.len() != CVEGEO_LENGTH])
    if bad_ids:
        raise FetchError(f"DCAH cvegeo must be {CVEGEO_LENGTH} characters, got {bad_ids[:5]}")
    duplicated = sorted(set(area_ids[area_ids.duplicated()]))
    if duplicated:
        raise FetchError(f"DCAH cvegeo repeats for {duplicated[:5]}")

    dcah_codes = [dcah_postal_code(value) for value in colonias["cp"]]
    postal_codes = list(dcah_codes)
    if any(code == "" for code in dcah_codes):
        fallback = point_postal_codes(representative_points(colonias, crs), postal, crs)
        postal_codes = [code or str(spatial) for code, spatial in zip(dcah_codes, fallback)]
    from_dcah = sum(code != "" for code in dcah_codes)
    missing = sum(code == "" for code in postal_codes)

    names = colonias["colonia_name"].astype(str).tolist()
    frame = gpd.GeoDataFrame(
        {
            "area_unit": AREA_UNIT,
            "area_id": area_ids.to_numpy(),
            "area_name": names,
            "display_name": names,
            "colonia_name": names,
            "municipio": [names_by_code[code] for code in mun_codes],
            "mun_code": mun_codes.to_numpy(),
            "col_code": colonias["cve_asen"].astype(str).str.strip().to_numpy(),
            "col_type": [colonia_type(value) for value in colonias["tipo"]],
            "postal_code": postal_codes,
            "year": [dcah_year(value) for value in colonias["fecha_act"]],
            "source": SOURCE,
        },
        geometry=colonias.geometry.to_crs(mx_common.WGS84).to_numpy(),
        crs=mx_common.WGS84,
    )
    frame = frame[[*COLONIA_PROPERTIES, "geometry"]]
    frame = frame.sort_values("area_id", kind="mergesort").reset_index(drop=True)
    frame.attrs["postal_code_counts"] = {
        "dcah": from_dcah,
        "sepomex_polygon": len(frame) - from_dcah - missing,
        "missing": missing,
    }
    return frame


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_geojson(frame: gpd.GeoDataFrame, target: Path) -> None:
    """Write ``frame`` as GeoJSON via a temp file promoted with ``os.replace``.

    The layer is named after ``target`` (GDAL would otherwise name it after the
    random temp file), so identical inputs give identical bytes.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.stem}.{uuid.uuid4().hex[:12]}.part{target.suffix}")
    try:
        frame.to_file(tmp_path, driver="GeoJSON", layer=target.stem)
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)


def outside_bbox(frame: gpd.GeoDataFrame, profile: dict) -> bool:
    """True when ``frame``'s bounds leave the profile bbox (amenity queries use it)."""
    bbox = profile.get("bbox") or {}
    if not all(key in bbox for key in ("south", "west", "north", "east")):
        return False
    west, south, east, north = (float(value) for value in frame.total_bounds)
    return bool(
        west < float(bbox["west"])
        or south < float(bbox["south"])
        or east > float(bbox["east"])
        or north > float(bbox["north"])
    )


def build_colonias(profile: dict, city: str) -> gpd.GeoDataFrame:
    """Load the cached state inputs and return the city's normalized colonias."""
    state, members = mx_common.profile_mx_area(profile, city)
    crs = metric_crs(profile, city)
    municipalities = member_municipalities(
        mx_common.load_state_municipalities(state), members, city
    )
    dcah = mx_common.load_dcah(source_url(profile, "colonias", city), state)
    colonias, dropped = member_colonias(dcah, state, members)
    print(
        f"Kept {len(colonias)} named DCAH colonias in {len(members)} municipalities; "
        f"dropped {dropped} unnamed polygons (NINGUNO / SIN NOMBRE placeholders)"
    )
    present = set(colonias["cve_mun"])
    empty = [code for code in members if code not in present]
    if empty:
        raise FetchError(f"No named DCAH colonias for member municipalities {empty} of {city}")
    postal = mx_common.load_state_postal_polygons(source_url(profile, "postal_codes", city))
    return normalize_colonias(colonias, municipalities, postal, crs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch INEGI DCAH 2025 colonia polygons for a Mexican city profile (mx_area)."
    )
    parser.add_argument("--city", required=True)
    args = parser.parse_args()

    profile = load_city_profile(args.city)
    colonias = build_colonias(profile, args.city)
    if colonias.empty:
        raise FetchError(f"DCAH produced no named colonias for {args.city}")

    counts = colonias.attrs.get("postal_code_counts", {})
    print(
        f"Postal codes: {counts.get('dcah', 0)} from DCAH cp, "
        f"{counts.get('sepomex_polygon', 0)} from the SEPOMEX polygon at the "
        f"representative point, {counts.get('missing', 0)} left empty"
    )
    for (mun_code, municipio), count in (
        colonias.groupby(["mun_code", "municipio"], sort=True).size().items()
    ):
        print(f"  {mun_code} {municipio}: {count}")
    if outside_bbox(colonias, profile):
        print(f"WARNING: {args.city} colonias extend beyond the profile bbox {profile['bbox']}")

    target = city_data_dir(DATA_RAW, args.city) / OUTPUT_NAME
    write_geojson(colonias, target)
    print(f"Wrote {len(colonias)} {args.city} colonias to {target}")


if __name__ == "__main__":
    main()
