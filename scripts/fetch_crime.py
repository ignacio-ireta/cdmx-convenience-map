from __future__ import annotations

import argparse
import csv

import pandas as pd

from common import DATA_PROCESSED, DATA_RAW, download, write_csv


CRIME_CSV_URL = (
    "https://archivo.datos.cdmx.gob.mx/FGJ/victimas/"
    "victimasFGJ_acumulado_2024_09.csv"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and normalize FGJ victim investigation records."
    )
    parser.add_argument("--force", action="store_true", help="Redownload even if cached.")
    args = parser.parse_args()

    raw_path = DATA_RAW / "victimasFGJ_acumulado_2024_09.csv"
    download(CRIME_CSV_URL, raw_path, force=args.force, timeout=180)

    usecols = [
        "fecha_inicio",
        "delito",
        "categoria_delito",
        "alcaldia_catalogo",
        "latitud",
        "longitud",
    ]
    crimes = pd.read_csv(
        raw_path,
        usecols=usecols,
        dtype=str,
        encoding="utf-8",
        quoting=csv.QUOTE_MINIMAL,
    )
    crimes["latitude"] = pd.to_numeric(crimes["latitud"], errors="coerce")
    crimes["longitude"] = pd.to_numeric(crimes["longitud"], errors="coerce")
    crimes["date"] = pd.to_datetime(crimes["fecha_inicio"], errors="coerce")
    crimes = crimes.dropna(subset=["latitude", "longitude", "date"]).copy()
    crimes = crimes[
        crimes["latitude"].between(19.04, 19.60)
        & crimes["longitude"].between(-99.38, -98.90)
    ].copy()

    crimes["category"] = crimes["categoria_delito"].fillna("Sin categoria")
    crimes["offense"] = crimes["delito"].fillna("Sin delito")
    crimes["borough"] = crimes["alcaldia_catalogo"].fillna("Sin alcaldia")
    crimes["source"] = "fgj_cdmx_victimas"

    rows = crimes[
        [
            "date",
            "offense",
            "category",
            "borough",
            "latitude",
            "longitude",
            "source",
        ]
    ].copy()
    rows["date"] = rows["date"].dt.strftime("%Y-%m-%d")

    write_csv(
        DATA_PROCESSED / "crime_points.csv",
        rows.to_dict(orient="records"),
        ["date", "offense", "category", "borough", "latitude", "longitude", "source"],
    )
    print(
        f"Normalized {len(rows)} geocoded FGJ victim records "
        f"from {rows['date'].min()} to {rows['date'].max()}"
    )


if __name__ == "__main__":
    main()

