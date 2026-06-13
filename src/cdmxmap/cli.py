"""The ``cdmxmap`` command-line interface (engineering standards §E)."""

from __future__ import annotations

from pathlib import Path

import typer

from cdmxmap import validate as validate_mod
from cdmxmap.config import TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY
from cdmxmap.errors import CdmxmapError
from cdmxmap.logging_config import setup_logging
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.pipeline import build_area, run_pipeline

app = typer.Typer(
    help="CDMX convenience map pipeline: fetch open data, score areas, validate.",
    no_args_is_help=True,
    add_completion=False,
)

AREA_UNITS = sorted(AREA_CONFIGS)
ROUTERS = [TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY]
LOG_LEVEL_OPTION = typer.Option(
    None, "--log-level", help="debug|info|warning|error (or CDMXMAP_LOG_LEVEL)."
)


def _validate_area_unit(value: str) -> str:
    if value not in AREA_CONFIGS:
        raise typer.BadParameter(f"must be one of {AREA_UNITS}")
    return value


def _validate_router(value: str) -> str:
    if value not in ROUTERS:
        raise typer.BadParameter(f"must be one of {ROUTERS}")
    return value


@app.command()
def fetch(
    city: str = typer.Option("cdmx", help="City profile id."),
    fail_fast: bool = typer.Option(False, help="Stop at the first source failure."),
    resume: bool = typer.Option(False, help="Skip sources whose output already exists."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Download and normalize every open-data source for a city."""
    code = run_pipeline(
        city,
        area_units=[],
        skip_fetch=False,
        fail_fast=fail_fast,
        resume=resume,
        log_level=log_level,
    )
    raise typer.Exit(code)


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
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Score one area unit into scores_<unit>.geojson + score_metadata."""
    setup_logging(log_level)
    try:
        build_area(
            area_unit,
            input_path=input_area_geojson,
            output_path=output,
            skip_legacy=skip_legacy,
            transit_router=transit_router,
        )
    except CdmxmapError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc


@app.command("validate")
def validate_outputs(
    path: list[Path] = typer.Option(  # noqa: B008 - typer option factory
        [], "--path", help="GeoJSON path(s) to validate; defaults to processed outputs."
    ),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Validate processed scored GeoJSON against the data contract."""
    setup_logging(log_level)
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
    fail_fast: bool = typer.Option(False, help="Stop at the first source/area failure."),
    resume: bool = typer.Option(False, help="Skip sources whose output already exists."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Fetch sources (unless skipped) and build scores for one area unit."""
    code = run_pipeline(
        city,
        area_units=[area_unit],
        skip_fetch=skip_fetch,
        transit_router=transit_router,
        fail_fast=fail_fast,
        resume=resume,
        log_level=log_level,
    )
    raise typer.Exit(code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
