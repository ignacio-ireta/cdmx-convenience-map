"""The ``cdmxmap`` command-line interface (engineering standards §E)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cdmxmap import validate as validate_mod
from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.config import (
    ROAD_ROUTER_NONE,
    ROAD_ROUTER_VALHALLA,
    TRANSIT_ROUTER_APIMETRO,
    TRANSIT_ROUTER_R5PY,
    load_places_config,
    road_routing_config,
)
from cdmxmap.errors import CdmxmapError, ConfigError
from cdmxmap.logging_config import setup_logging
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.pipeline import build_area, run_pipeline
from cdmxmap.routing import Router, RoutingCache, get_road_router
from cdmxmap.sources.io import DATA_PROCESSED, ensure_dirs

app = typer.Typer(
    help="Convenience map pipeline: fetch open data, score areas, validate.",
    no_args_is_help=True,
    add_completion=False,
)

AREA_UNITS = sorted(AREA_CONFIGS)
ROUTERS = [TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY]
ROAD_ROUTERS = [ROAD_ROUTER_NONE, ROAD_ROUTER_VALHALLA]
CITY_OPTION = typer.Option("cdmx", help="City profile id (e.g. cdmx, oslo).")
LOG_LEVEL_OPTION = typer.Option(
    None, "--log-level", help="debug|info|warning|error (or CDMXMAP_LOG_LEVEL)."
)


def _resolve_cli_context(city: str, area_unit: str) -> CityContext:
    """Load the city context and validate the area unit against it (city-aware)."""
    try:
        ctx = load_city_context(city)
    except (FileNotFoundError, CdmxmapError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--city") from exc
    if area_unit not in ctx.area_configs:
        raise typer.BadParameter(
            f"must be one of {sorted(ctx.area_configs)} for city '{city}'",
            param_hint="--area-unit",
        )
    return ctx


def _validate_router(value: str) -> str:
    if value not in ROUTERS:
        raise typer.BadParameter(f"must be one of {ROUTERS}")
    return value


def _validate_road_router(value: str) -> str:
    if value not in ROAD_ROUTERS:
        raise typer.BadParameter(f"must be one of {ROAD_ROUTERS}")
    return value


def _road_router(
    travel_router: str, city: str = "cdmx"
) -> tuple[Router | None, RoutingCache | None]:
    """Build the road router + cache for a CLI run (``none`` -> no routing)."""
    if travel_router == ROAD_ROUTER_NONE:
        return None, None
    ctx = load_city_context(city)
    config = road_routing_config(load_places_config(city))
    router = get_road_router(travel_router, tiles_dir=config["tiles_dir"])
    ensure_dirs()
    cache = RoutingCache(ctx.data_dir / "routing_cache" / "routes.json")
    return router, cache


@app.command()
def fetch(
    city: str = CITY_OPTION,
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
    city: str = CITY_OPTION,
    area_unit: str = typer.Option("postal_code", help=f"Area unit (CDMX: {AREA_UNITS})."),
    transit_router: str = typer.Option(
        TRANSIT_ROUTER_APIMETRO, callback=_validate_router, help=f"Transit router ({ROUTERS})."
    ),
    travel_router: str = typer.Option(
        ROAD_ROUTER_NONE,
        callback=_validate_road_router,
        help=f"Road router for work/amenity times ({ROAD_ROUTERS}).",
    ),
    input_area_geojson: Path | None = typer.Option(None, help="Override the area GeoJSON input."),
    output: Path | None = typer.Option(None, help="Override the processed output path."),
    skip_legacy: bool = typer.Option(False, help="Do not write legacy output aliases."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Score one area unit into scores_<unit>.geojson + score_metadata."""
    setup_logging(log_level)
    ctx = _resolve_cli_context(city, area_unit)
    try:
        router, routing_cache = _road_router(travel_router, city)
        build_area(
            area_unit,
            ctx=ctx,
            input_path=input_area_geojson,
            output_path=output,
            skip_legacy=skip_legacy,
            transit_router=transit_router,
            router=router,
            routing_cache=routing_cache,
        )
        if routing_cache is not None:
            routing_cache.save()
    except CdmxmapError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc


@app.command("validate")
def validate_outputs(
    path: list[Path] = typer.Option(  # noqa: B008 - typer option factory
        [], "--path", help="GeoJSON path(s) to validate; defaults to processed outputs."
    ),
    city: str | None = typer.Option(None, help="Validate a city's outputs (e.g. oslo)."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Validate processed scored GeoJSON against the data contract."""
    setup_logging(log_level)
    validate_mod.validate(list(path) or None, city=city)


@app.command()
def run(
    city: str = CITY_OPTION,
    area_unit: str = typer.Option("postal_code", help=f"Area unit (CDMX: {AREA_UNITS})."),
    skip_fetch: bool = typer.Option(False, help="Skip fetchers; only rebuild scores."),
    transit_router: str = typer.Option(
        TRANSIT_ROUTER_APIMETRO, callback=_validate_router, help=f"Transit router ({ROUTERS})."
    ),
    travel_router: str = typer.Option(
        ROAD_ROUTER_NONE,
        callback=_validate_road_router,
        help=f"Road router for work/amenity times ({ROAD_ROUTERS}).",
    ),
    fail_fast: bool = typer.Option(False, help="Stop at the first source/area failure."),
    resume: bool = typer.Option(False, help="Skip sources whose output already exists."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Fetch sources (unless skipped) and build scores for one area unit."""
    ctx = _resolve_cli_context(city, area_unit)
    try:
        router, routing_cache = _road_router(travel_router, city)
    except CdmxmapError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    code = run_pipeline(
        city,
        ctx=ctx,
        area_units=[area_unit],
        skip_fetch=skip_fetch,
        transit_router=transit_router,
        fail_fast=fail_fast,
        resume=resume,
        log_level=log_level,
        router=router,
        routing_cache=routing_cache,
    )
    raise typer.Exit(code)


@app.command("build-matrix")
def build_matrix(
    city: str = CITY_OPTION,
    area_unit: str = typer.Option("postal_code", help=f"Area unit (CDMX: {AREA_UNITS})."),
    travel_router: str = typer.Option(
        ROAD_ROUTER_VALHALLA,
        callback=_validate_road_router,
        help=f"Road router ({ROAD_ROUTERS}); must not be 'none'.",
    ),
    input_area_geojson: Path | None = typer.Option(None, help="Override the area GeoJSON input."),
    force: bool = typer.Option(False, help="Rebuild even if an up-to-date matrix exists."),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Build the dynamic-workplace area-to-area routed matrix (binary + index)."""
    setup_logging(log_level)
    from cdmxmap.routing.matrix_build import build_area_matrix

    ctx = _resolve_cli_context(city, area_unit)
    try:
        if travel_router == ROAD_ROUTER_NONE:
            raise ConfigError("build-matrix needs a router; pass --travel-router valhalla.")
        router, _ = _road_router(travel_router, city)
        assert router is not None
        config = ctx.area_configs[area_unit]
        rr_config = road_routing_config(load_places_config(city))
        ensure_dirs()
        summary = build_area_matrix(
            config=config,
            input_path=input_area_geojson or config.default_input_path,
            router=router,
            modes=rr_config["modes"],
            output_dir=ctx.data_dir,
            public_dir=ctx.public_dir,
            osm_source=rr_config.get("osm_source"),
            force=force,
        )
        typer.echo(json.dumps(summary, indent=2))
    except CdmxmapError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc


@app.command("build-tiles")
def build_tiles_command(
    pbf: Path = typer.Option(..., help="OSM PBF extract to build Valhalla tiles from."),
    tiles_dir: Path = typer.Option(
        DATA_PROCESSED / "valhalla", help="Output directory for the Valhalla tileset."
    ),
    log_level: str = LOG_LEVEL_OPTION,
) -> None:
    """Build a local Valhalla tileset from an OSM PBF (one-time offline setup)."""
    setup_logging(log_level)
    from cdmxmap.routing.valhalla import build_tiles

    try:
        out = build_tiles(pbf, tiles_dir)
        typer.echo(f"Built Valhalla tiles in {out}")
    except CdmxmapError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(exc.exit_code) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
