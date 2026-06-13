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
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.output import build_metadata, write_geojson
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.points import load_point_datasets
from cdmxmap.sources.io import DATA_PROCESSED, DATA_RAW, FRONTEND_PUBLIC_DATA, ensure_dirs

logger = logging.getLogger(__name__)

# Source fetchers run as modules, in order, each producing one primary file.
SOURCE_OUTPUTS = {
    "fetch_postal_codes": DATA_RAW / "correos-postales.json",
    "fetch_colonias": DATA_RAW / "colonias.geojson",
    "fetch_transit": DATA_PROCESSED / "transit_stops.csv",
    "fetch_supermarkets": DATA_PROCESSED / "supermarkets.csv",
    "fetch_gyms": DATA_PROCESSED / "gyms.csv",
    "fetch_crime": DATA_PROCESSED / "crime_points.csv",
}
FETCH_SEQUENCE = list(SOURCE_OUTPUTS)
CITY_AWARE_FETCHERS = {"fetch_supermarkets", "fetch_gyms"}


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
    input_path: Path | None = None,
    output_path: Path | None = None,
    skip_legacy: bool = False,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
) -> Path:
    """Score one area unit and write its GeoJSON + metadata. Returns the output path."""
    ensure_dirs()
    config = AREA_CONFIGS[area_unit]
    resolved_input = input_path or config.default_input_path
    resolved_output = output_path or DATA_PROCESSED / config.output_name
    public_output_path = FRONTEND_PUBLIC_DATA / resolved_output.name

    places_config = load_places_config()
    point_datasets = load_point_datasets(places_config)
    scored = score_areas(
        config=config,
        input_path=resolved_input,
        point_datasets=point_datasets,
        places_config=places_config,
        transit_router=transit_router,
    )

    write_geojson(scored.output, resolved_output)
    shutil.copyfile(resolved_output, public_output_path)
    logger.info("Copied frontend asset to %s", public_output_path)

    legacy_output_paths: list[Path] = []
    public_legacy_output_paths: list[Path] = []
    if not skip_legacy:
        for legacy_name in config.legacy_output_names:
            legacy_path = DATA_PROCESSED / legacy_name
            public_legacy_path = FRONTEND_PUBLIC_DATA / legacy_name
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
    )
    metadata_path = DATA_PROCESSED / f"score_metadata_{config.area_unit}.json"
    public_metadata_path = FRONTEND_PUBLIC_DATA / metadata_path.name
    _atomic_write_text(metadata_path, json.dumps(metadata, indent=2))
    shutil.copyfile(metadata_path, public_metadata_path)

    legacy_metadata_path = DATA_PROCESSED / "score_metadata.json"
    legacy_public_metadata_path = FRONTEND_PUBLIC_DATA / "score_metadata.json"
    shutil.copyfile(metadata_path, legacy_metadata_path)
    shutil.copyfile(metadata_path, legacy_public_metadata_path)

    logger.info("Wrote %s", metadata_path)
    return resolved_output


def _fetch_one(
    module: str, city: str, manifest: RunManifest, *, resume: bool, fail_fast: bool
) -> None:
    name = module.removeprefix("fetch_")
    entry = manifest.entry(name, "source")
    output = SOURCE_OUTPUTS[module]

    if resume and output.exists():
        entry.status = SKIPPED
        entry.output = repo_relative(output)
        entry.sha256 = sha256_file(output)
        logger.info("source %s skipped (resume; %s exists)", name, output.name)
        return

    entry.status = RUNNING
    entry.started_at = _now_iso()
    cmd = [sys.executable, "-m", f"cdmxmap.sources.{module}"]
    if module in CITY_AWARE_FETCHERS:
        cmd.extend(["--city", city])
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
    area_unit: str, manifest: RunManifest, *, transit_router: str, fail_fast: bool
) -> None:
    entry = manifest.entry(area_unit, "area")
    entry.status = RUNNING
    entry.started_at = _now_iso()
    try:
        output = build_area(area_unit, transit_router=transit_router)
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
) -> int:
    """Fetch sources (unless skipped) and build the requested area units.

    Returns a process exit code (0 ok, 1 partial, 3 no output, 130 interrupted).
    """
    units = area_units or []
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
            for module in FETCH_SEQUENCE:
                _fetch_one(module, city, manifest, resume=resume, fail_fast=fail_fast)
        for area_unit in units:
            _build_one(area_unit, manifest, transit_router=transit_router, fail_fast=fail_fast)
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
