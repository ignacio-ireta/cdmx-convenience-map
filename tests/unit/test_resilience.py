"""Tests for Phase 3 resilience: errors, manifest, atomic writes, logging."""

from __future__ import annotations

import hashlib
import json
import logging

import geopandas as gpd
from shapely.geometry import Point

from cdmxmap import errors
from cdmxmap import manifest as mf
from cdmxmap.logging_config import resolve_level, setup_logging
from cdmxmap.output.geojson import write_geojson
from cdmxmap.pipeline import _exit_code


class TestErrors:
    def test_hierarchy_and_exit_codes(self) -> None:
        assert issubclass(errors.ConfigError, errors.CdmxmapError)
        assert errors.ConfigError().exit_code == 2
        assert errors.NoOutputError().exit_code == 3
        assert errors.FetchError().exit_code == 1


class TestManifest:
    def test_entry_dedup_and_summary(self) -> None:
        manifest = mf.RunManifest(run_id="t", command="c", city="cdmx", started_at="now")
        first = manifest.entry("transit", "source")
        first.status = mf.SUCCESS
        assert manifest.entry("transit", "source") is first  # deduplicated
        manifest.entry("crime", "source").status = mf.FAILED
        assert manifest.summary() == {"success": 1, "failed": 1}

    def test_roundtrip_and_errors_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(mf, "RUNS_DIR", tmp_path)
        manifest = mf.RunManifest(
            run_id="run1", command="cdmxmap run", city="cdmx", started_at="t0"
        )
        manifest.entry("transit", "source").status = mf.SUCCESS
        manifest.entry("crime", "source").status = mf.FAILED
        manifest.finished_at = "t1"

        manifest_path = manifest.write()
        errors_path = manifest.write_errors()
        payload = json.loads(manifest_path.read_text())
        assert payload["run_id"] == "run1"
        assert payload["summary"]["failed"] == 1
        assert [e["name"] for e in json.loads(errors_path.read_text())] == ["crime"]

        loaded = mf.latest_manifest()
        assert loaded is not None
        assert loaded.run_id == "run1"
        assert {e.name for e in loaded.entries} == {"transit", "crime"}

    def test_sha256_file(self, tmp_path) -> None:
        target = tmp_path / "x.txt"
        target.write_bytes(b"hello")
        assert mf.sha256_file(target) == hashlib.sha256(b"hello").hexdigest()
        assert mf.sha256_file(tmp_path / "missing") is None


class TestAtomicGeojson:
    def test_name_member_uses_stem_not_tmp(self, tmp_path) -> None:
        gdf = gpd.GeoDataFrame({"area_id": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        out = tmp_path / "scores_test.geojson"
        write_geojson(gdf, out)
        data = json.loads(out.read_text())
        # Regression guard: the embedded layer name is the stem, not "...geojson.tmp".
        assert data["name"] == "scores_test"
        assert not list(tmp_path.glob(".tmp-geojson-*"))  # temp dir cleaned up


class TestLogging:
    def test_resolve_level(self, monkeypatch) -> None:
        monkeypatch.delenv("CDMXMAP_LOG_LEVEL", raising=False)
        assert resolve_level("debug") == logging.DEBUG
        assert resolve_level(None) == logging.INFO
        assert resolve_level("nonsense") == logging.INFO
        monkeypatch.setenv("CDMXMAP_LOG_LEVEL", "error")
        assert resolve_level(None) == logging.ERROR

    def test_setup_logging_is_idempotent(self) -> None:
        setup_logging("warning")
        first = len(logging.getLogger().handlers)
        setup_logging("warning")
        assert len(logging.getLogger().handlers) == first  # cleared, not duplicated


class TestExitCodes:
    def _manifest(self) -> mf.RunManifest:
        return mf.RunManifest(run_id="t", command="c", city="cdmx", started_at="t")

    def test_exit_code_progression(self) -> None:
        manifest = self._manifest()
        manifest.entry("transit", "source").status = mf.SUCCESS
        assert _exit_code(manifest, built_requested=False) == 0
        assert _exit_code(manifest, built_requested=True) == 3  # nothing built
        manifest.entry("postal_code", "area").status = mf.SUCCESS
        assert _exit_code(manifest, built_requested=True) == 0
        manifest.entry("crime", "source").status = mf.FAILED
        assert _exit_code(manifest, built_requested=True) == 1  # partial
        manifest.entry("colonia", "area").status = mf.INTERRUPTED
        assert _exit_code(manifest, built_requested=True) == 130
