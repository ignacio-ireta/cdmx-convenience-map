"""Crime ingestion and aggregation (aggregate-only, see §P).

Two modes, chosen by the city context's ``crime_mode``:

- ``incident_points`` (CDMX, Guadalajara): geocoded incidents joined to areas and
  scored by recent incident density per km² (``aggregate_crime``). A profile city
  may declare ``crime_source.density_buffer_m`` to count incidents over each area
  plus a buffer, which steadies the density of tiny polygons (Guadalajara).
- ``city_statistics`` (Monterrey): one aggregate row per administrative unit
  (municipality) from ``crime_statistics.csv``; every area inherits its unit's
  per-100k rate (``aggregate_crime_statistics``). No per-area counts are invented.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.citycontext import CDMX_CITY_ID, CRIME_MODE_CITY_STATISTICS, CityContext
from cdmxmap.config import METRIC_CRS, WGS84_CRS
from cdmxmap.errors import ConfigError, ScoringError

CDMX_CRIME_SOURCE = "fgj_cdmx_victimas"
CRIME_STATISTICS_REQUIRED_COLUMNS = (
    "unit_key",
    "unit_name",
    "population",
    "period_start",
    "period_end",
    "incidents_12m",
    "scored_incidents_12m",
)
CRIME_STATISTICS_OPTIONAL_COLUMNS = ("population_source", "top_category_12m", "source")
CRIME_STATISTICS_COUNT_COLUMNS = ("population", "incidents_12m", "scored_incidents_12m")
PER_100K = 100_000
# Statistics-mode safety: linear min-max over the matched units' scored rates.
STATISTICS_SCORE_METHOD = "min_max_across_units"


def read_crimes(
    path: Path, *, metric_crs: str = METRIC_CRS, source: str = CDMX_CRIME_SOURCE
) -> gpd.GeoDataFrame:
    if not path.exists():
        return gpd.GeoDataFrame(
            columns=[
                "date",
                "category",
                "offense",
                "borough",
                "latitude",
                "longitude",
                "source",
            ],
            geometry=[],
            crs=WGS84_CRS,
        ).to_crs(metric_crs)

    df = pd.read_csv(path)
    if df.empty:
        return gpd.GeoDataFrame(df, geometry=[], crs=WGS84_CRS).to_crs(metric_crs)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["date", "latitude", "longitude"]).copy()
    if "category" not in df.columns:
        df["category"] = "Sin categoria"
    if "offense" not in df.columns:
        df["offense"] = "Sin delito"
    if "source" not in df.columns:
        df["source"] = source

    crimes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84_CRS,
    )
    return crimes.to_crs(metric_crs)


def aggregate_crime(
    areas_metric: gpd.GeoDataFrame,
    crimes: gpd.GeoDataFrame,
    *,
    source: str = CDMX_CRIME_SOURCE,
    buffer_m: int = 0,
) -> tuple[pd.DataFrame, dict]:
    """Per-area incident counts, recent density and top category.

    With ``buffer_m > 0`` every field is computed over the area polygon buffered by
    that many meters (metric CRS): an incident may count toward several overlapping
    buffers, the density divides by the buffered area, and the metadata record
    counts stay unique incidents. ``buffer_m == 0`` is the historical polygon join.
    """
    columns = [
        "area_id",
        "crime_incidents_total",
        "crime_incidents_recent_12m",
        "crime_density_recent_12m_per_km2",
        "crime_top_category_recent_12m",
        "crime_source",
    ]
    empty = pd.DataFrame(
        {
            "area_id": areas_metric["area_id"],
            "crime_incidents_total": 0,
            "crime_incidents_recent_12m": 0,
            "crime_density_recent_12m_per_km2": 0.0,
            "crime_top_category_recent_12m": "",
            "crime_source": "",
        },
        columns=columns,
    )
    if crimes.empty:
        return empty, {
            "records_total": 0,
            "records_recent_12m": 0,
            "latest_date": None,
            "recent_start_date": None,
        }

    area_lookup = areas_metric[["area_id", "geometry"]].copy()
    if buffer_m > 0:
        area_lookup["geometry"] = area_lookup.geometry.buffer(buffer_m)
        # A unique row label per incident, so overlapping buffers can be de-duplicated.
        crimes = crimes.reset_index(drop=True)
    joined = gpd.sjoin(
        crimes,
        area_lookup,
        how="inner",
        predicate="within",
    )
    if joined.empty:
        return empty, {
            "records_total": int(len(crimes)),
            "records_recent_12m": 0,
            "latest_date": None,
            "recent_start_date": None,
        }

    latest_date = joined["date"].max()
    recent_start = latest_date - pd.DateOffset(months=12)
    recent = joined[joined["date"] >= recent_start].copy()

    totals = joined.groupby("area_id").size().rename("crime_incidents_total")
    recent_counts = recent.groupby("area_id").size().rename("crime_incidents_recent_12m")
    if recent.empty:
        top_categories = pd.Series(dtype=str, name="crime_top_category_recent_12m")
    else:
        top_categories = (
            recent.groupby("area_id")["category"]
            .agg(lambda series: series.value_counts().idxmax())
            .rename("crime_top_category_recent_12m")
        )

    area_km2 = area_lookup.set_index("area_id").geometry.area / 1_000_000
    aggregated = (
        pd.DataFrame({"area_id": areas_metric["area_id"]})
        .merge(totals, on="area_id", how="left")
        .merge(recent_counts, on="area_id", how="left")
        .merge(top_categories, on="area_id", how="left")
    )
    aggregated["crime_incidents_total"] = aggregated["crime_incidents_total"].fillna(0).astype(int)
    aggregated["crime_incidents_recent_12m"] = (
        aggregated["crime_incidents_recent_12m"].fillna(0).astype(int)
    )
    aggregated["crime_density_recent_12m_per_km2"] = (
        aggregated["crime_incidents_recent_12m"]
        / aggregated["area_id"].map(area_km2).replace(0, np.nan)
    ).fillna(0.0)
    aggregated["crime_top_category_recent_12m"] = aggregated[
        "crime_top_category_recent_12m"
    ].fillna("")
    aggregated["crime_source"] = source

    if buffer_m > 0:
        records_total = int(joined.index.nunique())
        records_recent = int(recent.index.nunique())
    else:
        records_total = int(len(joined))
        records_recent = int(len(recent))
    return aggregated[columns], {
        "records_total": records_total,
        "records_recent_12m": records_recent,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "recent_start_date": recent_start.strftime("%Y-%m-%d"),
    }


def incident_crime_source(ctx: CityContext) -> str:
    """Per-feature ``crime_source`` for the incident mode.

    CDMX keeps its historical label exactly; a profile city uses its declared
    ``crime_source.source`` and otherwise keeps the historical label too.
    """
    if ctx.city_id != CDMX_CITY_ID:
        declared = (ctx.profile.get("crime_source") or {}).get("source")
        if declared:
            return str(declared)
    return CDMX_CRIME_SOURCE


def incident_density_buffer_m(ctx: CityContext) -> int:
    """Meters each area is buffered by before counting incidents (0 = the polygon).

    Only a profile city's ``crime_source.density_buffer_m`` turns it on; CDMX and
    every profile without the key keep the unbuffered polygon join.
    """
    if ctx.city_id == CDMX_CITY_ID:
        return 0
    value = (ctx.profile.get("crime_source") or {}).get("density_buffer_m")
    if value is None:
        return 0
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
        or value != int(value)
    ):
        raise ConfigError(
            "crime_source.density_buffer_m must be a non-negative whole number of meters, "
            f"got {value!r}"
        )
    return int(value)


def incident_crime_metadata(ctx: CityContext, metadata: dict) -> dict:
    """Add a profile city's declared ``source``/``source_label`` (CDMX unchanged),
    plus ``density_buffer_m`` when its incident density is buffered."""
    declared = ctx.profile.get("crime_source") if ctx.city_id != CDMX_CITY_ID else None
    if not declared:
        return metadata
    buffer_m = incident_density_buffer_m(ctx)
    return {
        **metadata,
        "source": incident_crime_source(ctx),
        "source_label": str(declared.get("source_label") or incident_crime_source(ctx)),
        **({"density_buffer_m": buffer_m} if buffer_m > 0 else {}),
    }


@dataclass(frozen=True)
class CrimeStatisticsSettings:
    """The profile's ``crime_statistics`` block, with defaults."""

    scope: str = "municipality"
    area_key_field: str = "mun_code"
    source: str = ""
    source_label: str = ""
    scored_label: str = "scored incidents"
    population_source: str = ""
    # Optional provenance copied into the metadata crime block when declared.
    scored_definition: str = ""
    scored_offenses: tuple[str, ...] = ()

    @classmethod
    def from_profile(cls, profile: dict) -> CrimeStatisticsSettings:
        block = profile.get("crime_statistics") or {}
        defaults = cls()

        def text(key: str, default: str) -> str:
            return str(block.get(key) or default).strip()

        offenses = block.get("scored_offenses") or []
        if not isinstance(offenses, list) or not all(isinstance(o, str) for o in offenses):
            raise ConfigError("crime_statistics.scored_offenses must be a list of strings")
        return cls(
            scope=text("scope", defaults.scope),
            area_key_field=text("area_key_field", defaults.area_key_field),
            source=text("source", defaults.source),
            source_label=text("source_label", defaults.source_label),
            scored_label=text("scored_label", defaults.scored_label),
            population_source=text("population_source", defaults.population_source),
            scored_definition=text("scored_definition", defaults.scored_definition),
            scored_offenses=tuple(o.strip() for o in offenses if o.strip()),
        )


@dataclass(frozen=True)
class CrimeStatisticsResult:
    """Per-area statistics fields (output order), scoring input, and metadata."""

    properties: dict[str, list]
    scored_rates: np.ndarray
    metadata: dict


def read_crime_statistics(path: Path) -> pd.DataFrame:
    """Read and validate ``crime_statistics.csv`` (one aggregate row per unit).

    Keys stay strings (no lost leading zeros); counts must be non-negative
    integers and periods ``YYYY-MM-DD`` dates. Raises ``FileNotFoundError`` when
    the file is missing and ``ScoringError`` when it breaks the contract.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing crime statistics file (crime_mode '{CRIME_MODE_CITY_STATISTICS}'): {path}"
        )
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in CRIME_STATISTICS_REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise ScoringError(f"{path.name} is missing columns {missing}")
    if frame.empty:
        raise ScoringError(f"{path.name} has no rows")
    for column in CRIME_STATISTICS_OPTIONAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    for column in frame.columns:
        frame[column] = frame[column].astype(str).str.strip()
    if (frame["unit_key"] == "").any() or (frame["unit_name"] == "").any():
        raise ScoringError(f"{path.name} has rows with an empty unit_key or unit_name")
    duplicated = sorted(set(frame.loc[frame["unit_key"].duplicated(), "unit_key"]))
    if duplicated:
        raise ScoringError(f"{path.name} repeats unit_key values {duplicated[:5]}")
    for column in CRIME_STATISTICS_COUNT_COLUMNS:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or (values < 0).any() or (values % 1 != 0).any():
            raise ScoringError(f"{path.name} column {column} must hold non-negative integers")
        frame[column] = values.astype("int64")
    for column in ("period_start", "period_end"):
        parsed = pd.to_datetime(frame[column], format="%Y-%m-%d", errors="coerce")
        if parsed.isna().any():
            raise ScoringError(f"{path.name} column {column} must hold YYYY-MM-DD dates")
    return frame


def _unit_key(value: object) -> str:
    """Normalize an area's join-key property to the CSV's string ``unit_key``."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _rate_1dp(count: float, population: float) -> float:
    """Incidents per 100k residents, rounded to 1 dp (features and metadata agree)."""
    return round(float(count) / float(population) * PER_100K, 1)


def aggregate_crime_statistics(
    areas: pd.DataFrame,
    statistics: pd.DataFrame | None,
    settings: CrimeStatisticsSettings,
) -> CrimeStatisticsResult:
    """Give every area its unit's aggregate crime statistics.

    Each area's ``settings.area_key_field`` property is joined to ``unit_key``. An
    area without a matching unit (or a unit with no population) is a hard
    ``ScoringError``, never a silent zero: the score would otherwise read as safest.
    """
    if statistics is None:
        raise ScoringError(
            f"crime_mode '{CRIME_MODE_CITY_STATISTICS}' needs crime_statistics.csv; none was loaded"
        )
    key_field = settings.area_key_field
    if key_field not in areas.columns:
        raise ScoringError(
            f"Areas lack the crime statistics join field {key_field!r} "
            "(crime_statistics.area_key_field)"
        )
    keys = [_unit_key(value) for value in areas[key_field]]
    units = statistics.set_index("unit_key")
    unmatched = [
        f"{area_id} ({key or 'empty'})"
        for area_id, key in zip(areas["area_id"], keys)
        if key not in units.index
    ]
    if unmatched:
        raise ScoringError(
            f"{len(unmatched)} area(s) have no crime_statistics unit for {key_field!r}: "
            + ", ".join(unmatched[:5])
        )
    rows = units.loc[keys]
    if (rows["population"] <= 0).any():
        empty = sorted(set(rows.index[rows["population"] <= 0]))
        raise ScoringError(f"crime_statistics units {empty[:5]} have no population")

    population = rows["population"].to_numpy(dtype=float)
    scored_rates = rows["scored_incidents_12m"].to_numpy(dtype=float) / population * PER_100K
    sources = [row_source or settings.source for row_source in rows["source"]]
    properties: dict[str, list] = {
        "crime_statistics_scope": [settings.scope] * len(rows),
        "crime_statistics_area": rows["unit_name"].tolist(),
        "crime_statistics_period": (rows["period_start"] + "/" + rows["period_end"]).tolist(),
        "crime_scope_population": rows["population"].astype(int).tolist(),
        "crime_scope_incidents_12m": rows["incidents_12m"].astype(int).tolist(),
        "crime_scope_scored_incidents_12m": rows["scored_incidents_12m"].astype(int).tolist(),
        "crime_rate_per_100k_12m": [
            _rate_1dp(count, people)
            for count, people in zip(rows["scored_incidents_12m"], population)
        ],
        "crime_total_rate_per_100k_12m": [
            _rate_1dp(count, people) for count, people in zip(rows["incidents_12m"], population)
        ],
        "crime_top_category_recent_12m": rows["top_category_12m"].tolist(),
        "crime_source": sources,
    }
    return CrimeStatisticsResult(
        properties=properties,
        scored_rates=scored_rates,
        metadata=_crime_statistics_metadata(units, keys, settings),
    )


def _crime_statistics_metadata(
    units: pd.DataFrame, keys: list[str], settings: CrimeStatisticsSettings
) -> dict:
    """The metadata ``crime`` block: matched units only, sorted by key."""
    area_counts = Counter(keys)
    matched = units.loc[sorted(area_counts)]
    period_start = str(matched["period_start"].min())
    period_end = str(matched["period_end"].max())
    incidents = int(matched["incidents_12m"].sum())
    csv_sources = sorted({value for value in matched["source"] if value})
    csv_population_sources = sorted({value for value in matched["population_source"] if value})
    return {
        "mode": CRIME_MODE_CITY_STATISTICS,
        "scope": settings.scope,
        "source": settings.source or "; ".join(csv_sources),
        "source_label": settings.source_label or settings.source or "; ".join(csv_sources),
        "scored_label": settings.scored_label,
        **({"scored_definition": settings.scored_definition} if settings.scored_definition else {}),
        **({"scored_offenses": list(settings.scored_offenses)} if settings.scored_offenses else {}),
        "score_method": STATISTICS_SCORE_METHOD,
        "population_source": settings.population_source or "; ".join(csv_population_sources),
        "period_start": period_start,
        "period_end": period_end,
        "recent_start_date": period_start,
        "latest_date": period_end,
        "records_total": incidents,
        "records_recent_12m": incidents,
        "units": [
            {
                "key": str(key),
                "name": str(row["unit_name"]),
                "population": int(row["population"]),
                "incidents_12m": int(row["incidents_12m"]),
                "scored_incidents_12m": int(row["scored_incidents_12m"]),
                "rate_per_100k": _rate_1dp(row["scored_incidents_12m"], row["population"]),
                "total_rate_per_100k": _rate_1dp(row["incidents_12m"], row["population"]),
                "areas": area_counts[str(key)],
            }
            for key, row in matched.iterrows()
        ],
        "areas_matched": len(keys),
        "areas_unmatched": 0,
    }
