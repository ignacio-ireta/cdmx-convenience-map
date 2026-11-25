"""Unit tests for the ``city_statistics`` crime reader/aggregation, its min-max safety
scaling, and the per-city notes."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cdmxmap.citycontext import CityContext, TransitSystemSpec, load_city_context
from cdmxmap.errors import ConfigError, ScoringError
from cdmxmap.scoring.crime import (
    STATISTICS_SCORE_METHOD,
    CrimeStatisticsSettings,
    aggregate_crime_statistics,
    incident_crime_metadata,
    incident_crime_source,
    read_crime_statistics,
)
from cdmxmap.scoring.metrics import min_max_inverse_score, round_score
from cdmxmap.scoring.notes import (
    CDMX_SAFETY_NOTE,
    CDMX_TRANSIT_NOTE,
    SAFETY_NOT_SCORED_NOTE,
    safety_score_note,
    transit_score_note,
)

HEADER = (
    "unit_key,unit_name,population,population_source,period_start,period_end,"
    "incidents_12m,scored_incidents_12m,top_category_12m,source"
)
ROW_A = "09002,Unidad A,1000,Censo,2025-11-01,2026-10-31,50,10,Robo,sesnsp_municipal"
ROW_B = "09003,Unidad B,2000,Censo,2025-11-01,2026-10-31,30,5,Fraude,"


def _write(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "crime_statistics.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


class TestReadCrimeStatistics:
    def test_keys_stay_strings_and_counts_become_ints(self, tmp_path: Path) -> None:
        frame = read_crime_statistics(_write(tmp_path, ROW_A, ROW_B))
        assert frame["unit_key"].tolist() == ["09002", "09003"]  # leading zero kept
        assert frame["population"].tolist() == [1000, 2000]
        assert str(frame["incidents_12m"].dtype) == "int64"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="city_statistics"):
            read_crime_statistics(tmp_path / "crime_statistics.csv")

    def test_optional_columns_default_to_empty(self, tmp_path: Path) -> None:
        header = (
            "unit_key,unit_name,population,period_start,period_end,"
            "incidents_12m,scored_incidents_12m"
        )
        frame = read_crime_statistics(
            _write(tmp_path, "1,U,10,2025-11-01,2026-10-31,1,1", header=header)
        )
        assert frame.loc[0, "source"] == "" and frame.loc[0, "top_category_12m"] == ""

    @pytest.mark.parametrize(
        ("rows", "message"),
        [
            ((ROW_A, ROW_A), "repeats unit_key"),
            ((ROW_A.replace("Unidad A", ""),), "empty unit_key or unit_name"),
            ((ROW_A.replace(",50,", ",-1,"),), "non-negative integers"),
            ((ROW_A.replace(",50,", ",5.5,"),), "non-negative integers"),
            ((ROW_A.replace(",1000,", ",many,"),), "non-negative integers"),
            ((ROW_A.replace("2026-10-31", "Oct 2026"),), "YYYY-MM-DD"),
            ((), "no rows"),
        ],
    )
    def test_contract_violations_raise(
        self, tmp_path: Path, rows: tuple[str, ...], message: str
    ) -> None:
        with pytest.raises(ScoringError, match=message):
            read_crime_statistics(_write(tmp_path, *rows))

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ScoringError, match="missing columns"):
            read_crime_statistics(_write(tmp_path, "1,U", header="unit_key,unit_name"))


class TestAggregateCrimeStatistics:
    SETTINGS = CrimeStatisticsSettings(source="profile_source")

    def _areas(self, keys: list[object]) -> pd.DataFrame:
        return pd.DataFrame({"area_id": [f"a{i}" for i in range(len(keys))], "mun_code": keys})

    def test_rates_and_source_fallback(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A, ROW_B))
        result = aggregate_crime_statistics(
            self._areas(["09002", "09003", "09002"]), stats, self.SETTINGS
        )
        props = result.properties
        assert props["crime_rate_per_100k_12m"] == [1000.0, 250.0, 1000.0]
        assert props["crime_total_rate_per_100k_12m"] == [5000.0, 1500.0, 5000.0]
        # Row source wins; an empty row source falls back to the profile source.
        assert props["crime_source"] == ["sesnsp_municipal", "profile_source", "sesnsp_municipal"]
        assert result.scored_rates.tolist() == [1000.0, 250.0, 1000.0]
        assert [unit["areas"] for unit in result.metadata["units"]] == [2, 1]
        assert result.metadata["records_total"] == 80

    def test_numeric_keys_match_string_unit_keys(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A.replace("09002", "19039")))
        result = aggregate_crime_statistics(self._areas([19039.0]), stats, self.SETTINGS)
        assert result.properties["crime_statistics_area"] == ["Unidad A"]

    def test_unmatched_area_raises(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A))
        with pytest.raises(ScoringError, match=r"1 area\(s\).*a1 \(empty\)"):
            aggregate_crime_statistics(self._areas(["09002", None]), stats, self.SETTINGS)

    def test_zero_population_raises(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A.replace(",1000,", ",0,")))
        with pytest.raises(ScoringError, match="no population"):
            aggregate_crime_statistics(self._areas(["09002"]), stats, self.SETTINGS)

    def test_missing_statistics_raises(self) -> None:
        with pytest.raises(ScoringError, match="needs crime_statistics.csv"):
            aggregate_crime_statistics(self._areas(["09002"]), None, self.SETTINGS)

    def test_unmatched_units_do_not_set_the_scale(self, tmp_path: Path) -> None:
        # A unit with no area (and an extreme rate) is not part of the min-max range.
        extreme = "09004,Unidad C,10,Censo,2025-11-01,2026-10-31,9,9,Robo,"
        stats = read_crime_statistics(_write(tmp_path, ROW_A, ROW_B, extreme))
        result = aggregate_crime_statistics(self._areas(["09002", "09003"]), stats, self.SETTINGS)
        assert min_max_inverse_score(result.scored_rates).tolist() == [0.0, 100.0]

    def test_metadata_records_the_score_method(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A, ROW_B))
        crime = aggregate_crime_statistics(self._areas(["09002"]), stats, self.SETTINGS).metadata
        assert crime["score_method"] == STATISTICS_SCORE_METHOD == "min_max_across_units"
        # Nothing declared -> no definition/offense keys (no invented provenance).
        assert "scored_definition" not in crime and "scored_offenses" not in crime

    def test_metadata_copies_the_declared_definition(self, tmp_path: Path) -> None:
        stats = read_crime_statistics(_write(tmp_path, ROW_A))
        settings = CrimeStatisticsSettings(
            scored_label="robbery and violent crime",
            scored_definition="All robbery and violent crime",
            scored_offenses=("Robo", "Lesiones dolosas"),
        )
        crime = aggregate_crime_statistics(self._areas(["09002"]), stats, settings).metadata
        keys = list(crime)
        assert keys[keys.index("scored_label") :][:4] == [
            "scored_label",
            "scored_definition",
            "scored_offenses",
            "score_method",
        ]
        assert crime["scored_definition"] == "All robbery and violent crime"
        assert crime["scored_offenses"] == ["Robo", "Lesiones dolosas"]  # JSON list


class TestMinMaxInverseScore:
    def test_lowest_rate_scores_100_and_highest_0_linearly(self) -> None:
        scores = min_max_inverse_score(np.array([300.0, 300.0, 150.0, 175.0, 112.5]))
        assert round_score(scores) == [0.0, 0.0, 80.0, 66.7, 100.0]

    def test_duplicated_unit_rates_do_not_move_the_scale(self) -> None:
        # Every area repeats its unit's rate; only the distinct extremes matter.
        once = min_max_inverse_score(np.array([10.0, 25.0, 40.0]))
        repeated = min_max_inverse_score(np.array([10.0, 25.0, 25.0, 25.0, 40.0]))
        assert once.tolist() == [100.0, 50.0, 0.0]
        assert repeated.tolist() == [100.0, 50.0, 50.0, 50.0, 0.0]

    def test_no_percentile_cap(self) -> None:
        # inverse_density_score would clip the top value at p95; min-max does not.
        rates = np.array([float(rate) for rate in range(100, 1300, 100)])  # 12 units
        scores = min_max_inverse_score(rates)
        assert scores[0] == 100.0 and scores[-1] == 0.0
        assert (np.diff(scores) < 0).all()  # strictly ranked, no tie at the bottom

    def test_equal_rates_all_score_100(self) -> None:
        assert min_max_inverse_score(np.array([42.0, 42.0])).tolist() == [100.0, 100.0]

    def test_non_finite_scores_zero_and_empty_is_empty(self) -> None:
        assert min_max_inverse_score(np.array([np.nan, 1.0, 3.0])).tolist() == [0.0, 100.0, 0.0]
        assert min_max_inverse_score(np.array([np.nan])).tolist() == [0.0]
        assert min_max_inverse_score(np.array([])).tolist() == []


class TestSettings:
    def test_defaults(self) -> None:
        settings = CrimeStatisticsSettings.from_profile({})
        assert settings.scope == "municipality"
        assert settings.area_key_field == "mun_code"
        assert settings.scored_label == "scored incidents"
        assert settings.scored_definition == "" and settings.scored_offenses == ()

    def test_monterrey_profile(self) -> None:
        settings = CrimeStatisticsSettings.from_profile(load_city_context("monterrey").profile)
        assert settings.area_key_field == "mun_code"
        assert settings.source == "sesnsp_municipal"
        assert settings.scored_label == "robbery and violent crime"
        assert settings.scored_definition.startswith("All robbery")
        assert settings.scored_offenses[:2] == ("Robo", "Homicidio doloso")
        assert "Violación equiparada" in settings.scored_offenses
        assert settings.population_source == "INEGI Censo de Población y Vivienda 2020"

    @pytest.mark.parametrize("offenses", ["Robo", ["Robo", 3], {"Robo": 1}])
    def test_malformed_scored_offenses_raise(self, offenses: object) -> None:
        with pytest.raises(ConfigError, match="scored_offenses"):
            CrimeStatisticsSettings.from_profile(
                {"crime_statistics": {"scored_offenses": offenses}}
            )


class TestIncidentSource:
    def test_cdmx_keeps_its_label_and_metadata(self) -> None:
        ctx = load_city_context("cdmx")
        assert incident_crime_source(ctx) == "fgj_cdmx_victimas"
        metadata = {"records_total": 0}
        assert incident_crime_metadata(ctx, metadata) is metadata

    def test_guadalajara_uses_its_declared_source(self) -> None:
        ctx = load_city_context("guadalajara")
        assert incident_crime_source(ctx) == "iieg_jalisco_fge"
        metadata = incident_crime_metadata(ctx, {"records_total": 1})
        # The profile buffers its incident density (crime_source.density_buffer_m).
        assert list(metadata) == ["records_total", "source", "source_label", "density_buffer_m"]
        assert metadata["source_label"].startswith("IIEG Jalisco")
        assert metadata["density_buffer_m"] == 250

    def test_profile_without_crime_source_keeps_todays_value(self) -> None:
        ctx = load_city_context("morelia")
        assert incident_crime_source(ctx) == "fgj_cdmx_victimas"
        metadata = {"records_total": 0}
        assert incident_crime_metadata(ctx, metadata) is metadata


class TestNotes:
    def test_cdmx_notes_are_verbatim(self) -> None:
        ctx = load_city_context("cdmx")
        assert transit_score_note(ctx) == CDMX_TRANSIT_NOTE
        assert safety_score_note(ctx) == CDMX_SAFETY_NOTE
        assert CDMX_TRANSIT_NOTE == (
            "Transit score is 70% nearest Metro/Metrobus/Trolebus and 30% nearest "
            "RTP/Corredor Concesionado."
        )

    def test_morelia_notes_are_generated(self) -> None:
        ctx = load_city_context("morelia")
        assert transit_score_note(ctx) == "Transit score is 70% nearest RAIL and 30% nearest BUS."
        assert safety_score_note(ctx) == SAFETY_NOT_SCORED_NOTE

    def test_monterrey_notes(self) -> None:
        ctx = load_city_context("monterrey")
        assert transit_score_note(ctx) == (
            "Transit score is 70% nearest Metrorrey / TransMetro BRT and 30% nearest "
            "TransMetro / Rutas urbanas."
        )
        assert safety_score_note(ctx) == (
            "Safety score ranks the municipalities within the metro by robbery and violent "
            "crime per 100k residents (SESNSP · incidencia delictiva municipal (fuero común)): "
            "the lowest rate scores 100 and the highest 0, linearly; every area in a "
            "municipality shares its municipality's score."
        )

    def test_guadalajara_buffered_incident_note(self) -> None:
        ctx = load_city_context("guadalajara")
        assert safety_score_note(ctx) == (
            "Safety score is lower-is-better incident density per km² over each area plus a "
            "250 m buffer, latest 12 months in the IIEG Jalisco · Fiscalía del Estado, "
            "incidencia delictiva (Región Centro) data."
        )

    def test_unbuffered_profile_incident_note(self) -> None:
        base = load_city_context("guadalajara")
        crime_source = {
            k: v for k, v in base.profile["crime_source"].items() if k != "density_buffer_m"
        }
        ctx = dataclasses.replace(base, profile={**base.profile, "crime_source": crime_source})
        assert safety_score_note(ctx) == (
            "Safety score is lower-is-better incident density per km² over the latest 12 "
            "months in the IIEG Jalisco · Fiscalía del Estado, incidencia delictiva "
            "(Región Centro) data."
        )

    def test_empty_group_and_fractional_weights(self) -> None:
        base: CityContext = load_city_context("morelia")
        ctx = dataclasses.replace(
            base,
            transit_systems=(TransitSystemSpec("BUS", "bus", "surface", "Buses"),),
            core_weight=0.655,
            surface_weight=0.345,
        )
        assert transit_score_note(ctx) == (
            "Transit score is 65.5% nearest any transit stop and 34.5% nearest Buses."
        )


def test_score_scaling_note_is_qualified_only_for_statistics_mode() -> None:
    from cdmxmap.citycontext import load_city_context
    from cdmxmap.scoring.notes import (
        CLIPPED_SCORES_NOTE,
        STATISTICS_CLIPPED_SCORES_NOTE,
        score_scaling_note,
    )

    assert score_scaling_note(load_city_context("monterrey")) == STATISTICS_CLIPPED_SCORES_NOTE
    for city in ("cdmx", "guadalajara", "morelia", "oslo"):
        assert score_scaling_note(load_city_context(city)) == CLIPPED_SCORES_NOTE
