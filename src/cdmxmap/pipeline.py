"""Pipeline orchestration: build one area unit, or run a full city.

``build_area`` is the pure, behavior-preserving build (used by ``cdmxmap score``).
``run_pipeline`` wraps fetch + build with a run manifest, per-source failure
isolation, resume, interruption handling, and meaningful exit codes (§H/§J/§R/§S).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.config import TRANSIT_ROUTER_APIMETRO, load_places_config
from cdmxmap.errors import FetchError
from cdmxmap.logging_config import setup_logging
from cdmxmap.manifest import (
    FAILED,
    INTERRUPTED,
    RUNNING,
    SKIPPED,
    SUCCESS,
    RunManifest,
    latest_manifest,
    repo_relative,
    sha256_file,
)
from cdmxmap.output import build_metadata, write_geojson
from cdmxmap.routing.base import Router
from cdmxmap.routing.cache import RoutingCache
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.points import load_point_datasets
from cdmxmap.sources.io import DATA_PROCESSED, DATA_RAW, ensure_dirs

logger = logging.getLogger(__name__)

# CDMX's source fetchers and their flat output paths (the historical layout).
# Each fetcher runs as a module, in order, producing one primary file.
CDMX_SOURCE_OUTPUTS = {
    "fetch_postal_codes": DATA_RAW / "correos-postales.json",
    "fetch_colonias": DATA_RAW / "colonias.geojson",
    "fetch_transit": DATA_PROCESSED / "transit_stops.csv",
    "fetch_supermarkets": DATA_PROCESSED / "supermarkets.csv",
    "fetch_gyms": DATA_PROCESSED / "gyms.csv",
    "fetch_crime": DATA_PROCESSED / "crime_points.csv",
}
# Only CDMX's OSM amenity fetchers accept --city; its source-specific fetchers are
# hardwired to CDMX open data. Other cities declare city-aware fetchers in profile.
CDMX_CITY_AWARE_FETCHERS = {"fetch_supermarkets", "fetch_gyms"}


def source_outputs(ctx: CityContext) -> dict[str, Path]:
    """Map each fetcher module to its primary output path, per city.

    CDMX keeps the flat historical layout. Other cities declare their fetchers in
    ``city.json`` as ``fetchers: [{module, output, dir}]`` (``dir`` is "raw" or
    "processed", default processed), resolved under the per-city raw/processed dirs.
    """
    if ctx.city_id == "cdmx":
        return dict(CDMX_SOURCE_OUTPUTS)
    outputs: dict[str, Path] = {}
    for entry in ctx.profile.get("fetchers", []):
        base = ctx.raw_dir if entry.get("dir") == "raw" else ctx.data_dir
        outputs[entry["module"]] = base / entry["output"]
    return outputs


def fetch_sequence(ctx: CityContext) -> list[str]:
    return list(source_outputs(ctx))


def city_aware_fetchers(ctx: CityContext) -> set[str]:
    """Fetchers that receive --city. CDMX: only OSM amenities; others: all."""
    if ctx.city_id == "cdmx":
        return set(CDMX_CITY_AWARE_FETCHERS)
    return set(source_outputs(ctx))


def _resolve_context(city: str, ctx: CityContext | None) -> CityContext:
    """Resolve the city context, falling back to CDMX defaults when a city has no
    profile (e.g. the synthetic test 'fixture' city), which reproduces the
    pre-multi-city behavior where everything used CDMX configuration."""
    if ctx is not None:
        return ctx
    try:
        return load_city_context(city)
    except FileNotFoundError:
        if city != "cdmx":
            logger.warning("No city profile for %r; using CDMX defaults.", city)
        return load_city_context("cdmx")


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def build_area(
    area_unit: str,
    *,
    city: str = "cdmx",
    ctx: CityContext | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
    skip_legacy: bool = False,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
    places_config: dict | None = None,
    data_dir: Path | None = None,
    public_dir: Path | None = None,
    router: Router | None = None,
    routing_cache: RoutingCache | None = None,
) -> Path:
    """Score one area unit and write its GeoJSON + metadata. Returns the output path.

    ``data_dir`` / ``public_dir`` / ``places_config`` default to the per-city
    pipeline locations; they exist so tests can drive the build over a fixture. For
    CDMX (the default city) all defaults leave production behavior (and the
    byte-for-byte output) unchanged.
    """
    ensure_dirs()
    resolved_ctx = _resolve_context(city, ctx)
    resolved_data_dir = data_dir or resolved_ctx.data_dir
    resolved_public_dir = public_dir or resolved_ctx.public_dir
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    resolved_public_dir.mkdir(parents=True, exist_ok=True)

    config = resolved_ctx.area_configs[area_unit]
    resolved_input = input_path or config.default_input_path
    resolved_output = output_path or resolved_data_dir / config.output_name
    public_output_path = resolved_public_dir / resolved_output.name

    if places_config is None:
        places_config = load_places_config(resolved_ctx.city_id)
    point_datasets = load_point_datasets(
        places_config, ctx=resolved_ctx, data_dir=resolved_data_dir
    )
    scored = score_areas(
        config=config,
        input_path=resolved_input,
        point_datasets=point_datasets,
        places_config=places_config,
        ctx=resolved_ctx,
        transit_router=transit_router,
        router=router,
        routing_cache=routing_cache,
    )

    write_geojson(scored.output, resolved_output)
    shutil.copyfile(resolved_output, public_output_path)
    logger.info("Copied frontend asset to %s", public_output_path)

    legacy_output_paths: list[Path] = []
    public_legacy_output_paths: list[Path] = []
    if not skip_legacy:
        for legacy_name in config.legacy_output_names:
            legacy_path = resolved_data_dir / legacy_name
            public_legacy_path = resolved_public_dir / legacy_name
            shutil.copyfile(resolved_output, legacy_path)
            shutil.copyfile(resolved_output, public_legacy_path)
            legacy_output_paths.append(legacy_path)
            public_legacy_output_paths.append(public_legacy_path)
            logger.info("Copied legacy asset to %s", legacy_path)

    metadata = build_metadata(
        config=config,
        input_path=resolved_input,
        output_path=resolved_output,
        public_output_path=public_output_path,
        legacy_output_paths=legacy_output_paths,
        public_legacy_output_paths=public_legacy_output_paths,
        point_datasets=point_datasets,
        score_metadata=scored.metadata,
        places_config=places_config,
        ctx=resolved_ctx,
    )
    metadata_path = resolved_data_dir / f"score_metadata_{config.area_unit}.json"
    public_metadata_path = resolved_public_dir / metadata_path.name
    _atomic_write_text(metadata_path, json.dumps(metadata, indent=2))
    shutil.copyfile(metadata_path, public_metadata_path)

    legacy_metadata_path = resolved_data_dir / "score_metadata.json"
    legacy_public_metadata_path = resolved_public_dir / "score_metadata.json"
    shutil.copyfile(metadata_path, legacy_metadata_path)
    shutil.copyfile(metadata_path, legacy_public_metadata_path)

    logger.info("Wrote %s", metadata_path)
    return resolved_output


def _fetch_one(
    module: str,
    ctx: CityContext,
    manifest: RunManifest,
    *,
    outputs: dict[str, Path],
    aware: set[str],
    resume: bool,
    fail_fast: bool,
) -> None:
    name = module.removeprefix("fetch_")
    entry = manifest.entry(name, "source")
    output = outputs[module]

    if resume and output.exists():
        entry.status = SKIPPED
        entry.output = repo_relative(output)
        entry.sha256 = sha256_file(output)
        logger.info("source %s skipped (resume; %s exists)", name, output.name)
        return

    entry.status = RUNNING
    entry.started_at = _now_iso()
    cmd = [sys.executable, "-m", f"cdmxmap.sources.{module}"]
    if module in aware:
        cmd.extend(["--city", ctx.city_id])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        for line in proc.stdout.splitlines():
            logger.info("[%s] %s", name, line)
        if proc.returncode != 0:
            reason = (
                proc.stderr.strip().splitlines()[-1]
                if proc.stderr.strip()
                else f"exit code {proc.returncode}"
            )
            entry.status = FAILED
            entry.error = reason
            logger.error("source %s failed: %s", name, reason)
            if fail_fast:
                raise FetchError(f"{name}: {reason}")
        else:
            entry.status = SUCCESS
            entry.output = repo_relative(output)
            entry.sha256 = sha256_file(output)
            logger.info("source %s ok", name)
    except KeyboardInterrupt:
        entry.status = INTERRUPTED
        raise
    finally:
        entry.finished_at = _now_iso()


def _build_one(
    area_unit: str,
    manifest: RunManifest,
    *,
    ctx: CityContext,
    transit_router: str,
    fail_fast: bool,
    places_config: dict | None = None,
    data_dir: Path | None = None,
    public_dir: Path | None = None,
    router: Router | None = None,
    routing_cache: RoutingCache | None = None,
) -> None:
    entry = manifest.entry(area_unit, "area")
    entry.status = RUNNING
    entry.started_at = _now_iso()
    try:
        output = build_area(
            area_unit,
            ctx=ctx,
            transit_router=transit_router,
            places_config=places_config,
            data_dir=data_dir,
            public_dir=public_dir,
            router=router,
            routing_cache=routing_cache,
        )
        entry.status = SUCCESS
        entry.output = repo_relative(output)
        entry.sha256 = sha256_file(output)
        logger.info("area %s scored", area_unit)
    except KeyboardInterrupt:
        entry.status = INTERRUPTED
        raise
    except Exception as exc:  # noqa: BLE001 - isolate one area's failure.
        entry.status = FAILED
        entry.error = str(exc)
        logger.error("area %s failed: %s", area_unit, exc)
        if fail_fast:
            raise
    finally:
        entry.finished_at = _now_iso()


def _exit_code(manifest: RunManifest, *, built_requested: bool) -> int:
    interrupted = manifest.status == INTERRUPTED or any(
        e.status == INTERRUPTED for e in manifest.entries
    )
    if interrupted:
        return 130
    area_success = any(e.kind == "area" and e.status == SUCCESS for e in manifest.entries)
    if built_requested and not area_success:
        return 3  # build requested but produced no output
    if any(e.status == FAILED for e in manifest.entries):
        return 1  # partial: something failed but output was produced
    return 0


def run_pipeline(
    city: str = "cdmx",
    *,
    area_units: list[str] | None = None,
    skip_fetch: bool = False,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
    fail_fast: bool = False,
    resume: bool = False,
    log_level: str | None = None,
    run_id: str | None = None,
    ctx: CityContext | None = None,
    places_config: dict | None = None,
    data_dir: Path | None = None,
    public_dir: Path | None = None,
    router: Router | None = None,
    routing_cache: RoutingCache | None = None,
) -> int:
    """Fetch sources (unless skipped) and build the requested area units.

    Returns a process exit code (0 ok, 1 partial, 3 no output, 130 interrupted).
    ``places_config`` / ``data_dir`` / ``public_dir`` default to the per-city
    pipeline locations and exist so an offline test can drive a full run over a
    fixture.
    """
    units = area_units or []
    resolved_ctx = _resolve_context(city, ctx)
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    command = "cdmxmap " + " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "run_pipeline"
    manifest = RunManifest(
        run_id=resolved_run_id, command=command, city=city, started_at=_now_iso()
    )
    setup_logging(log_level, log_file=manifest.run_dir / "run.log")
    logger.info(
        "run start run_id=%s city=%s area_units=%s fetch=%s",
        resolved_run_id,
        city,
        units or "-",
        not skip_fetch,
    )

    if resume and latest_manifest() is None:
        logger.info("resume requested but no prior manifest found; running fresh")

    try:
        if not skip_fetch:
            outputs = source_outputs(resolved_ctx)
            aware = city_aware_fetchers(resolved_ctx)
            for module in fetch_sequence(resolved_ctx):
                _fetch_one(
                    module,
                    resolved_ctx,
                    manifest,
                    outputs=outputs,
                    aware=aware,
                    resume=resume,
                    fail_fast=fail_fast,
                )
        for area_unit in units:
            _build_one(
                area_unit,
                manifest,
                ctx=resolved_ctx,
                transit_router=transit_router,
                fail_fast=fail_fast,
                places_config=places_config,
                data_dir=data_dir,
                public_dir=public_dir,
                router=router,
                routing_cache=routing_cache,
            )
        manifest.status = (
            "success" if not any(e.status == FAILED for e in manifest.entries) else "partial"
        )
    except KeyboardInterrupt:
        manifest.status = INTERRUPTED
        for entry in manifest.entries:
            if entry.status == RUNNING:
                entry.status = INTERRUPTED
        logger.warning("Interrupted by user.")
    except FetchError as exc:
        manifest.status = "failed"
        logger.error("Aborting (fail-fast): %s", exc)
    finally:
        if routing_cache is not None:
            routing_cache.save()
        manifest.finished_at = _now_iso()
        manifest.write()
        manifest.write_errors()
        counts = manifest.summary()
        logger.info(
            "run done run_id=%s %s",
            resolved_run_id,
            " ".join(f"{status}={count}" for status, count in sorted(counts.items())),
        )
        if manifest.status == INTERRUPTED:
            resume_unit = f" --area-unit {units[0]}" if units else ""
            logger.warning("Resume with: cdmxmap run --city %s%s --resume", city, resume_unit)

    return _exit_code(manifest, built_requested=bool(units))
