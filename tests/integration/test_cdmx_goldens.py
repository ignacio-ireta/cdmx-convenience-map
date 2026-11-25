"""CDMX safety-net goldens over the synthetic fixture city.

``test_fixture_pipeline.py`` pins the colonia-unit property *values*. These pin the
rest of what CDMX publishes, so multi-city engine work cannot move CDMX output:

- the full ``score_areas(...).metadata`` dict (minus every ``generated_at``),
  compared by value *and* key order, as it is serialized to the metadata JSON;
- the postal-code unit's properties, scored with CDMX's in-code
  ``AREA_CONFIGS["postal_code"]`` (only the id field is pointed at the fixture's
  ``area_id``, since the fixture has no postal-code column);
- the ordered property keys of the colonia, routed-colonia and postal outputs
  (GeoJSON property order is part of the published bytes).

All runs use the CDMX ``CityContext`` explicitly. Regenerate (and read the diff:
a change here means CDMX output changed) with::

    UPDATE_GOLDEN=1 uv run pytest tests/integration -m golden
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.models import AREA_CONFIGS, AreaConfig, ScoredAreaResult
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.points import load_point_datasets

FIXTURE_CITY = Path(__file__).parents[1] / "fixtures" / "fixture_city"
METADATA_GOLDEN = FIXTURE_CITY / "expected_metadata.json"
POSTAL_GOLDEN = FIXTURE_CITY / "expected_postal_properties.json"
ORDER_GOLDEN = FIXTURE_CITY / "expected_property_order.json"

# CDMX's postal unit exactly as configured in code, except for the id field: the
# fixture areas carry ``area_id`` (C001..) instead of a postal-code column, which
# the postal path zero-pads to 5 digits like a real code.
FIXTURE_POSTAL_CONFIG: AreaConfig = dataclasses.replace(
    AREA_CONFIGS["postal_code"], id_fields=["area_id"]
)


@pytest.fixture
def cdmx_ctx() -> CityContext:
    ctx = load_city_context("cdmx")
    assert ctx.city_id == "cdmx"
    return ctx


def _score(
    places: dict, ctx: CityContext, config: AreaConfig, *, router: Any = None
) -> ScoredAreaResult:
    points = load_point_datasets(places, ctx=ctx, data_dir=FIXTURE_CITY)
    return score_areas(
        config=config,
        input_path=FIXTURE_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
        ctx=ctx,
        router=router,
    )


def _properties(result: ScoredAreaResult) -> list[dict]:
    """Feature properties in serialized order, sorted by area id."""
    features = json.loads(result.output.to_json())["features"]
    props = [feature["properties"] for feature in features]
    props.sort(key=lambda p: p["area_id"])
    return props


def _strip_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_generated_at(v) for k, v in value.items() if k != "generated_at"}
    if isinstance(value, list | tuple):
        return [_strip_generated_at(item) for item in value]
    return value


def _ordered_keys(props: list[dict]) -> list[str]:
    orders = {tuple(p.keys()) for p in props}
    assert len(orders) == 1, "every feature must serialize its properties in one order"
    return list(next(iter(orders)))


def _read_or_update(path: Path, text: str) -> str:
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


@pytest.mark.golden
def test_cdmx_golden_metadata(fixture_places: dict, cdmx_ctx: CityContext) -> None:
    result = _score(fixture_places, cdmx_ctx, AREA_CONFIGS["colonia"])
    metadata = _strip_generated_at(result.metadata)
    # The pipeline serializes metadata with plain json.dumps (no default=), so the
    # dict must stay JSON-native; this also normalizes tuples to lists.
    serialized = json.dumps(metadata, indent=2) + "\n"
    expected_text = _read_or_update(METADATA_GOLDEN, serialized)
    assert json.loads(serialized) == json.loads(expected_text)
    # Same values *and* the same key order as the golden (metadata JSON bytes).
    assert serialized == expected_text


@pytest.mark.golden
def test_cdmx_golden_postal_properties(fixture_places: dict, cdmx_ctx: CityContext) -> None:
    props = _properties(_score(fixture_places, cdmx_ctx, FIXTURE_POSTAL_CONFIG))
    assert [p["area_id"] for p in props] == ["00001", "00002", "00003"]
    assert all(p["area_unit"] == "postal_code" for p in props)
    serialized = json.dumps(props, indent=2, sort_keys=True) + "\n"
    expected = json.loads(_read_or_update(POSTAL_GOLDEN, serialized))
    assert props == expected


@pytest.mark.golden
def test_cdmx_golden_property_order(
    fixture_places: dict, cdmx_ctx: CityContext, stub_router
) -> None:
    order = {
        "colonia": _ordered_keys(
            _properties(_score(fixture_places, cdmx_ctx, AREA_CONFIGS["colonia"]))
        ),
        "colonia_routed": _ordered_keys(
            _properties(
                _score(fixture_places, cdmx_ctx, AREA_CONFIGS["colonia"], router=stub_router)
            )
        ),
        "postal_code": _ordered_keys(
            _properties(_score(fixture_places, cdmx_ctx, FIXTURE_POSTAL_CONFIG))
        ),
    }
    serialized = json.dumps(order, indent=2) + "\n"
    expected = json.loads(_read_or_update(ORDER_GOLDEN, serialized))
    assert order == expected
