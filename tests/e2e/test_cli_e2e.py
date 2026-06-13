"""End-to-end tests: drive the build + CLI over the fixture city (standards §K)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cdmxmap import manifest as mf
from cdmxmap.pipeline import build_area, run_pipeline
from cdmxmap.validate import validate_geojson

FIXTURE_CITY = Path(__file__).parents[1] / "fixtures" / "fixture_city"


@pytest.mark.e2e
def test_build_area_writes_and_validates(
    fixture_places: dict, fixture_data_dir: Path, tmp_path: Path
) -> None:
    public_dir = tmp_path / "public"
    out = build_area(
        "colonia",
        input_path=FIXTURE_CITY / "areas.geojson",
        places_config=fixture_places,
        data_dir=fixture_data_dir,
        public_dir=public_dir,
        skip_legacy=True,
    )
    assert out.exists()
    assert (public_dir / "scores_colonia.geojson").exists()
    assert (fixture_data_dir / "score_metadata_colonia.json").exists()
    assert validate_geojson(out) == 3


@pytest.mark.e2e
def test_run_pipeline_skip_fetch_writes_manifest(
    fixture_places: dict, fixture_data_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(mf, "RUNS_DIR", tmp_path / "runs")
    code = run_pipeline(
        "fixture",
        area_units=["colonia"],
        skip_fetch=True,
        places_config=fixture_places,
        data_dir=fixture_data_dir,
        public_dir=tmp_path / "public",
        run_id="testrun",
        log_level="warning",
    )
    assert code == 0
    run_dir = tmp_path / "runs" / "testrun"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "run.log").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    area_entries = [e for e in manifest["entries"] if e["kind"] == "area"]
    assert area_entries and all(e["status"] == "success" for e in area_entries)


@pytest.mark.e2e
def test_cli_help_and_validate(
    fixture_places: dict, fixture_data_dir: Path, tmp_path: Path
) -> None:
    out = build_area(
        "colonia",
        input_path=FIXTURE_CITY / "areas.geojson",
        places_config=fixture_places,
        data_dir=fixture_data_dir,
        public_dir=tmp_path / "public",
        skip_legacy=True,
    )

    def cdmxmap(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "cdmxmap", *args], capture_output=True, text=True
        )

    help_result = cdmxmap("--help")
    assert help_result.returncode == 0
    assert "score" in help_result.stdout

    assert cdmxmap("validate", "--path", str(out)).returncode == 0

    broken = tmp_path / "broken.geojson"
    broken.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    assert cdmxmap("validate", "--path", str(broken)).returncode != 0
