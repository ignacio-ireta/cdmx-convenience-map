"""The ``cdmxmap`` command-line interface (engineering standards §E)."""

from __future__ import annotations

from pathlib import Path

import typer

from cdmxmap import validate as validate_mod
from cdmxmap.config import TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.pipeline import build_area, fetch_sources, run_city

app = typer.Typer(
    help="CDMX convenience map pipeline: fetch open data, score areas, validate.",
    no_args_is_help=True,
    add_completion=False,
)

AREA_UNITS = sorted(AREA_CONFIGS)
ROUTERS = [TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY]


def _validate_area_unit(value: str) -> str:
    if value not in AREA_CONFIGS:
        raise typer.BadParameter(f"must be one of {AREA_UNITS}")
    return value


def _validate_router(value: str) -> str:
    if value not in ROUTERS:
        raise typer.BadParameter(f"must be one of {ROUTERS}")
    return value


@app.command()
def fetch(city: str = typer.Option("cdmx", help="City profile id.")) -> None:
    """Download and normalize every open-data source for a city."""
    fetch_sources(city)


@app.command()
def score(
    area_unit: str = typer.Option(
        "postal_code", callback=_validate_area_unit, help=f"Area unit ({AREA_UNITS})."
    ),
    transit_router: str = typer.Option(
        TRANSIT_ROUTER_APIMETRO, callback=_validate_router, help=f"Transit router ({ROUTERS})."
    ),
    input_area_geojson: Path | None = typer.Option(None, help="Override the area GeoJSON input."),
    output: Path | None = typer.Option(None, help="Override the processed output path."),
    skip_legacy: bool = typer.Option(False, help="Do not write legacy output aliases."),
) -> None:
    """Score one area unit into scores_<unit>.geojson + score_metadata."""
    build_area(
        area_unit,
        input_path=input_area_geojson,
        output_path=output,
        skip_legacy=skip_legacy,
        transit_router=transit_router,
    )


@app.command("validate")
def validate_outputs(
    path: list[Path] = typer.Option(  # noqa: B008 - typer option factory
        [], "--path", help="GeoJSON path(s) to validate; defaults to processed outputs."
    ),
) -> None:
    """Validate processed scored GeoJSON against the data contract."""
    validate_mod.validate(list(path) or None)


@app.command()
def run(
    city: str = typer.Option("cdmx", help="City profile id."),
    area_unit: str = typer.Option(
        "postal_code", callback=_validate_area_unit, help=f"Area unit ({AREA_UNITS})."
    ),
    skip_fetch: bool = typer.Option(False, help="Skip fetchers; only rebuild scores."),
    transit_router: str = typer.Option(
        TRANSIT_ROUTER_APIMETRO, callback=_validate_router, help=f"Transit router ({ROUTERS})."
    ),
) -> None:
    """Fetch sources (unless skipped) and build scores for one area unit."""
    run_city(city, area_unit=area_unit, skip_fetch=skip_fetch, transit_router=transit_router)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
