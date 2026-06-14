"""Crime ingestion and spatial aggregation (aggregate-only, see §P)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.config import METRIC_CRS, WGS84_CRS


def read_crimes(path: Path, *, metric_crs: str = METRIC_CRS) -> gpd.GeoDataFrame:
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
        df["source"] = "fgj_cdmx_victimas"

    crimes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84_CRS,
    )
    return crimes.to_crs(metric_crs)


def aggregate_crime(
    areas_metric: gpd.GeoDataFrame, crimes: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, dict]:
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

    area_km2 = areas_metric.set_index("area_id").geometry.area / 1_000_000
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
    aggregated["crime_source"] = "fgj_cdmx_victimas"

    return aggregated[columns], {
        "records_total": int(len(joined)),
        "records_recent_12m": int(len(recent)),
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "recent_start_date": recent_start.strftime("%Y-%m-%d"),
    }
