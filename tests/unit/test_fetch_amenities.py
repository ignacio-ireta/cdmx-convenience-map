"""Offline tests for the amenity fetchers: supermarkets (legacy + v2 classifier)
and INEGI DENUE gyms.

Nothing here reaches the network: Overpass is replaced by monkeypatching
``fetch_supermarkets.retry_overpass`` (and ``io.post_overpass`` as a guard), and
DENUE downloads go through ``mx_common.stream_download``, which an autouse
fixture refuses unless a test serves a tiny zip built in ``tmp_path``. The
Overpass payload in ``tests/fixtures/mx_amenities/`` is synthetic.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from cdmxmap.errors import ConfigError, FetchError
from cdmxmap.sources import fetch_denue_gyms as fdg
from cdmxmap.sources import fetch_supermarkets as fs
from cdmxmap.sources import io as sio
from cdmxmap.sources import mx_common as mc
from cdmxmap.sources.io import load_city_profile

FIXTURES = Path(__file__).parents[1] / "fixtures" / "mx_amenities"
MTY_PAYLOAD = FIXTURES / "overpass_monterrey_sample.json"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_download(url: str, path: Path, *, timeout: int = 300) -> None:
        raise AssertionError(f"test tried to download {url}")

    def refuse_overpass(*args: object, **kwargs: object) -> dict:
        raise AssertionError("test tried to reach Overpass")

    monkeypatch.setattr(mc, "stream_download", refuse_download)
    monkeypatch.setattr(sio, "post_overpass", refuse_overpass)
    monkeypatch.setattr(fs, "retry_overpass", refuse_overpass)


@pytest.fixture(scope="module")
def mty_profile() -> dict:
    return load_city_profile("monterrey")


@pytest.fixture(scope="module")
def gdl_profile() -> dict:
    return load_city_profile("guadalajara")


@pytest.fixture(scope="module")
def mty(mty_profile: dict) -> fs.SupermarketClassifier:
    return fs.parse_classifier(mty_profile, "monterrey")


@pytest.fixture(scope="module")
def gdl(gdl_profile: dict) -> fs.SupermarketClassifier:
    return fs.parse_classifier(gdl_profile, "guadalajara")


def mty_payload() -> dict:
    return json.loads(MTY_PAYLOAD.read_text(encoding="utf-8"))


def slug_of(tags: dict, classifier: fs.SupermarketClassifier) -> str | None:
    family = fs.classify_tags(tags, classifier)
    return family.slug if family else None


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Legacy path (profiles without supermarket_classifier): only the tie-break changed
# ---------------------------------------------------------------------------

# The pre-fix implementation, verbatim, as the reference for "unchanged".
LEGACY_INFER_BRAND_SOURCE = """
def legacy_infer_brand(tags, brands):
    haystack = " ".join(str(tags.get(key, "")).lower() for key in ["brand", "operator", "name"])
    match = next(
        (brand for brand in sorted(brands, key=len, reverse=True) if brand in haystack),
        None,
    )
    return match.title() if match else "Unknown"
"""
_namespace: dict = {}
exec(LEGACY_INFER_BRAND_SOURCE, _namespace)  # fixed, test-local source
legacy_infer_brand = _namespace["legacy_infer_brand"]

CDMX_BRANDS = {"costco", "walmart"}
MORELIA_BRANDS = {"aurrera", "aurrerá", "walmart", "soriana", "chedraui"}
NORWAY_BRANDS = {"rema", "kiwi", "coop", "extra", "meny", "joker", "bunnpris"}

NO_TIE_CASES: list[tuple[set[str], dict]] = [
    (CDMX_BRANDS, {"name": "Costco Polanco", "shop": "wholesale"}),
    (CDMX_BRANDS, {"name": "Walmart Express", "operator": "Walmart de México"}),
    (CDMX_BRANDS, {"brand": "Costco", "name": "Costco Gasolinera"}),
    (CDMX_BRANDS, {"name": "Superama"}),
    (CDMX_BRANDS, {"name": "Bodega Aurrera", "operator": "Walmart"}),
    (MORELIA_BRANDS, {"name": "Bodega Aurrerá"}),
    (MORELIA_BRANDS, {"name": "Mi Bodega Aurrera"}),
    (MORELIA_BRANDS, {"name": "Soriana Híper"}),
    (MORELIA_BRANDS, {"name": "Chedraui Selecto", "operator": "Walmart"}),
    (MORELIA_BRANDS, {"brand": "Walmart", "name": "Walmart Supercenter"}),
    (MORELIA_BRANDS, {"name": "Bodega Aurrera", "operator": "Nueva Wal Mart de México"}),
    (MORELIA_BRANDS, {"name": "Coppel"}),
    (NORWAY_BRANDS, {"name": "Rema 1000 Grünerløkka"}),
    (NORWAY_BRANDS, {"brand": "Coop Extra", "name": "Extra Storo"}),
    (NORWAY_BRANDS, {"name": "Kiwi Majorstuen"}),
    (NORWAY_BRANDS, {"name": "Bunnpris & Gourmet", "operator": "Bunnpris"}),
    (NORWAY_BRANDS, {"name": "Joker Nordstrand"}),
    (NORWAY_BRANDS, {"name": "Coop Prix"}),
    (NORWAY_BRANDS, {"name": "Meny Bryn"}),
]
# Several equally long tokens appear in one store's text: the old answer depended
# on PYTHONHASHSEED; the fix picks the alphabetically first one.
TIE_CASES: list[tuple[set[str], dict, str]] = [
    (MORELIA_BRANDS, {"name": "Bodega Aurrera", "operator": "Walmart de Mexico"}, "Aurrera"),
    (MORELIA_BRANDS, {"name": "Soriana", "operator": "Walmart"}, "Soriana"),
    (NORWAY_BRANDS, {"name": "Kiwi", "operator": "Rema"}, "Kiwi"),
]


def _longest_hits(brands: set[str], tags: dict) -> set[str]:
    haystack = " ".join(str(tags.get(key, "")).lower() for key in ["brand", "operator", "name"])
    hits = [brand for brand in brands if brand in haystack]
    if not hits:
        return set()
    longest = max(len(hit) for hit in hits)
    return {hit for hit in hits if len(hit) == longest}


@pytest.mark.parametrize(("brands", "tags"), NO_TIE_CASES)
def test_infer_brand_unchanged_without_ties(brands: set[str], tags: dict) -> None:
    assert len(_longest_hits(brands, tags)) <= 1, "case must not contain a tie"
    assert fs.infer_brand(tags, brands) == legacy_infer_brand(tags, brands)


@pytest.mark.parametrize(("brands", "tags", "expected"), TIE_CASES)
def test_infer_brand_breaks_ties_alphabetically(
    brands: set[str], tags: dict, expected: str
) -> None:
    tied = _longest_hits(brands, tags)
    assert len(tied) > 1, "case must contain a tie"
    assert fs.infer_brand(tags, brands) == expected
    # The new answer is one the old code could also give (it only removes the randomness).
    assert expected.lower() in tied


_SEED_PROBE = """
import json, sys
from cdmxmap.sources.fetch_supermarkets import infer_brand
cases = json.loads(sys.argv[1])
ns = {}
exec(sys.argv[2], ns)
print(json.dumps({
    "new": [infer_brand(tags, set(brands)) for brands, tags in cases],
    "old": [ns["legacy_infer_brand"](tags, set(brands)) for brands, tags in cases],
}))
"""
HASH_SEEDS = ["0", "1", "2", "3", "4", "5", "6", "7", "42", "123"]


def test_infer_brand_is_deterministic_across_hash_seeds() -> None:
    cases = [[sorted(brands), tags] for brands, tags, _ in TIE_CASES]
    new_results, old_results = set(), set()
    for seed in HASH_SEEDS:
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", _SEED_PROBE, json.dumps(cases), LEGACY_INFER_BRAND_SOURCE],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        out = json.loads(proc.stdout)
        new_results.add(tuple(out["new"]))
        old_results.add(tuple(out["old"]))
    assert new_results == {tuple(expected for _, _, expected in TIE_CASES)}
    # Sanity: the probe really exercises the bug (the old code flips with the seed).
    assert len(old_results) > 1


def test_legacy_query_is_unchanged() -> None:
    expected = """
[out:json][timeout:45];
(
  nwr["shop"~"supermarket|wholesale|department_store"]["brand"~"costco|walmart",i](19.04,-99.38,19.6,-98.9);
  nwr["shop"~"supermarket|wholesale|department_store"]["operator"~"costco|walmart",i](19.04,-99.38,19.6,-98.9);
  nwr["shop"~"supermarket|wholesale|department_store"]["name"~"costco|walmart",i](19.04,-99.38,19.6,-98.9);
);
out tags center;
"""  # noqa: E501
    assert fs.build_query("cdmx", set(CDMX_BRANDS)) == expected


LEGACY_PAYLOAD = {
    "elements": [
        {
            "type": "way",
            "id": 1,
            "center": {"lat": 19.44, "lon": -99.2},
            "tags": {"shop": "wholesale", "name": "Costco Polanco"},
        },
        {
            "type": "node",
            "id": 2,
            "lat": 19.37,
            "lon": -99.16,
            "tags": {"shop": "supermarket", "name": "Walmart Universidad"},
        },
        {
            "type": "node",
            "id": 2,
            "lat": 19.37,
            "lon": -99.16,
            "tags": {"shop": "supermarket", "name": "Walmart Universidad"},
        },
        {
            "type": "node",
            "id": 3,
            "lat": 19.3,
            "lon": -99.12,
            "tags": {"shop": "supermarket", "brand": "Walmart"},
        },
        {
            "type": "node",
            "id": 4,
            "lat": 19.31,
            "lon": -99.13,
            "tags": {"shop": "pharmacy", "name": "Farmacia Walmart"},
        },
        {
            "type": "node",
            "id": 5,
            "lat": 19.32,
            "lon": -99.14,
            "tags": {"shop": "supermarket", "name": "Bodega Aurrera", "operator": "Walmart"},
        },
        {
            "type": "node",
            "id": 6,
            "lat": 19.33,
            "lon": -99.15,
            "tags": {"shop": "wholesale", "name": "Costco Coapa", "brand": "Costco"},
        },
        {"type": "way", "id": 7, "tags": {"shop": "wholesale", "name": "Costco (no center)"}},
    ]
}
LEGACY_EXPECTED_CSV = (
    "name,brand,latitude,longitude,source\r\n"
    "Costco Polanco,Costco,19.44,-99.2,openstreetmap\r\n"
    "Walmart Universidad,Walmart,19.37,-99.16,openstreetmap\r\n"
    "Walmart,Walmart,19.3,-99.12,openstreetmap\r\n"
    "Bodega Aurrera,Walmart,19.32,-99.14,openstreetmap\r\n"
    "Costco Coapa,Costco,19.33,-99.15,openstreetmap\r\n"
)


def test_legacy_cdmx_main_output_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake(query: str, **kwargs: object) -> dict:
        calls.append((query, kwargs))
        return copy.deepcopy(LEGACY_PAYLOAD)

    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(fs, "retry_overpass", fake)
    fs.main(["--city", "cdmx"])
    written = (tmp_path / "supermarkets.csv").read_bytes().decode("utf-8")
    assert written == LEGACY_EXPECTED_CSV
    assert calls == [(fs.build_query("cdmx", set(CDMX_BRANDS)), {"attempts": 2, "timeout": 75})]


def test_legacy_morelia_main_uses_legacy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": i,
                "lat": 19.7 + i / 100,
                "lon": -101.2,
                "tags": {"shop": "supermarket", "name": name},
            }
            for i, name in enumerate(
                ["Bodega Aurrerá", "Mi Bodega Aurrera", "Soriana Híper", "Chedraui", "Walmart"]
            )
        ]
    }
    calls: list[dict] = []

    def fake(query: str, **kwargs: object) -> dict:
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(fs, "retry_overpass", fake)
    fs.main(["--city", "morelia"])
    rows = read_rows(tmp_path / "morelia" / "supermarkets.csv")
    assert [row["brand"] for row in rows] == [
        "Aurrerá",
        "Aurrera",
        "Soriana",
        "Chedraui",
        "Walmart",
    ]
    assert calls == [{"attempts": 2, "timeout": 75}]


def test_legacy_cdmx_falls_back_to_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(query: str, **kwargs: object) -> dict:
        raise RuntimeError("Overpass failed after 2 attempts")

    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(fs, "retry_overpass", failing)
    fs.main(["--city", "cdmx"])
    seed = sio.DATA_SEEDS / "supermarkets_seed.csv"
    assert (tmp_path / "supermarkets.csv").read_bytes() == seed.read_bytes()


def test_use_cache_needs_a_classifier_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path)
    with pytest.raises(SystemExit):
        fs.main(["--city", "morelia", "--use-cache"])


# ---------------------------------------------------------------------------
# v2 classifier: normalization and token matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bodega  Aurrerá", "bodega aurrera"),
        ("BODEGA AURRERÁ", "bodega aurrera"),  # decomposed accent
        ("Sam’s Club", "sam's club"),
        ("Sam´s Club", "sam's club"),
        ("SORIANA HÍPER", "soriana hiper"),
        ("  H-E-B\tPlus ", "h-e-b plus"),
        (None, ""),
    ],
)
def test_normalize_text(raw: str | None, expected: str) -> None:
    assert fs.normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("la comer", True),
        ("la comer universidad", True),
        ("la comercial", False),
        ("comercial mexicana", False),
        ("heb", True),
        ("hebe supermercado", False),
        ("super heb", True),
        ("h-e-b", False),  # a different token, not a substring hit on "heb"
        ("(heb)", True),
        ("heb2", False),
    ],
)
def test_token_pattern_respects_alphanumeric_boundaries(text: str, hit: bool) -> None:
    pattern = fs.token_pattern(["la comer", "heb"])
    assert pattern is not None
    assert bool(pattern.search(text)) is hit


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("s mart", True),
        ("s-mart el molinete", True),
        ("super s mart", True),
        ("(s mart)", True),
        # the possessive 's must not start a token
        ("waldo's mart", False),
        ("lupita's mart", False),
        ("waldos mart", False),
        # an apostrophe on the right still ends a token
        ("s mart's", True),
    ],
)
def test_token_pattern_never_starts_after_an_apostrophe(text: str, hit: bool) -> None:
    pattern = fs.token_pattern(["s-mart", "s mart", "smart"])
    assert pattern is not None
    assert bool(pattern.search(text)) is hit


# ---------------------------------------------------------------------------
# v2 classifier: families (real Monterrey / Guadalajara profiles)
# ---------------------------------------------------------------------------


def test_profiles_parse(mty: fs.SupermarketClassifier, gdl: fs.SupermarketClassifier) -> None:
    assert [f.slug for f in mty.families][:7] == [
        "sams",
        "costco",
        "aurrera",
        "walmart",
        "heb",
        "soriana",
        "s_mart",
    ]
    assert mty.shops == ("supermarket", "wholesale", "department_store")
    assert mty.dedupe_m == 150.0
    assert mty.extra_shops == ("convenience",)
    toggles = {f.slug for f in gdl.families if not f.pool_only}
    assert toggles == {"sams", "costco", "aurrera", "walmart", "soriana", "chedraui", "la_comer"}


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # operator is never read: Walmart de México operates Aurrerá and Sam's
        ({"shop": "supermarket", "name": "Bodega Aurrerá", "operator": "Walmart"}, "aurrera"),
        ({"shop": "supermarket", "name": "Mi Tienda", "operator": "Walmart de México"}, None),
        ({"shop": "wholesale", "name": "Sam's Club", "operator": "Walmart"}, "sams"),
        ({"shop": "wholesale", "brand": "Sam’s Club"}, "sams"),
        ({"shop": "wholesale", "name": "Sams Club Cumbres"}, "sams"),
        # walmart excludes sam's on brand + name, so a Walmart-branded Sam's stays sams
        ({"shop": "wholesale", "brand": "Walmart", "name": "Sam's Club"}, "sams"),
        ({"shop": "supermarket", "name": "Walmart Express"}, "walmart"),
        ({"shop": "supermarket", "name": "Superama"}, "walmart"),
        ({"shop": "supermarket", "name": "Farmacia Walmart"}, None),
        # brand beats name; walmart excludes bodega/aurrera on brand + name
        ({"shop": "supermarket", "name": "Walmart", "brand": "Bodega Aurrerá"}, "aurrera"),
        # S-Mart vs Smart & Final (pool family in Monterrey)
        ({"shop": "supermarket", "name": "Smart & Final"}, "smart_final"),
        ({"shop": "supermarket", "name": "Smart and Final Express"}, "smart_final"),
        ({"shop": "supermarket", "name": "S-Mart (El Molinete)"}, "s_mart"),
        ({"shop": "supermarket", "name": "SMART"}, "s_mart"),
        ({"shop": "supermarket", "name": "Smart Fit"}, None),
        ({"shop": "supermarket", "name": "S-Mart"}, "s_mart"),
        ({"shop": "supermarket", "name": "Smart"}, "s_mart"),
        ({"shop": "supermarket", "name": "S Mart"}, "s_mart"),
        # a possessive "'s" is not the start of "s mart" (OSM node 1859392044)
        ({"shop": "supermarket", "name": "Waldo's Mart"}, None),
        ({"shop": "supermarket", "name": "Waldo’s Mart"}, None),
        ({"shop": "supermarket", "name": "Sam's"}, "sams"),
        ({"shop": "wholesale", "name": "Sam's Club"}, "sams"),
        # La Comer vs La Comercial
        ({"shop": "supermarket", "name": "La Comer"}, "la_comer"),
        ({"shop": "supermarket", "name": "La Comercial"}, None),
        ({"shop": "supermarket", "name": "Comercial Mexicana"}, None),
        ({"shop": "supermarket", "name": "Fresko"}, "la_comer"),
        # accents and case
        ({"shop": "supermarket", "name": "BODEGA AURRERA"}, "aurrera"),
        ({"shop": "supermarket", "name": "Bodega Aurrerá Express"}, "aurrera"),
        ({"shop": "supermarket", "name": "SORIANA HÍPER"}, "soriana"),
        ({"shop": "supermarket", "name": "Soriana Súper"}, "soriana"),
        # H-E-B: boundary + exclude
        ({"shop": "supermarket", "name": "H-E-B", "operator": "Soriana"}, "heb"),
        ({"shop": "supermarket", "name": "Hebe Supermercado"}, None),
        (
            {"shop": "supermarket", "name": "Mi Tienda del Ahorro", "brand": "H-E-B"},
            "mi_tienda_ahorro",
        ),
        # Soriana excludes City Club (its own format), which is a pool family
        ({"shop": "wholesale", "name": "City Club Soriana"}, "city_club"),
        ({"shop": "wholesale", "name": "Costco Gasolinera"}, None),
        # shop values: extra_shops only for aurrera
        ({"shop": "convenience", "name": "Bodega Aurrerá Express"}, "aurrera"),
        ({"shop": "convenience", "name": "Soriana Express"}, None),
        ({"shop": "convenience", "name": "OXXO"}, None),
        ({"shop": "pharmacy", "name": "Farmacias Soriana"}, None),
        ({"shop": "department_store", "name": "Coppel"}, None),
        ({"name": "Soriana"}, None),
    ],
)
def test_classify_monterrey(
    mty: fs.SupermarketClassifier, tags: dict, expected: str | None
) -> None:
    assert slug_of(tags, mty) == expected


def test_brand_wikidata_comes_first(mty: fs.SupermarketClassifier) -> None:
    # brand:wikidata says Soriana; the name would match sams (earlier in profile order).
    tags = {"shop": "wholesale", "brand:wikidata": "Q735562", "name": "Sam's"}
    assert slug_of(tags, mty) == "soriana"
    # several ids, one of them a family's
    tags = {"shop": "supermarket", "brand:wikidata": "Q1; Q830621", "name": "Super"}
    assert slug_of(tags, mty) == "heb"


def test_first_family_in_profile_order_wins(mty_profile: dict) -> None:
    profile = copy.deepcopy(mty_profile)
    block = profile["supermarket_classifier"]
    block["families"] = [
        {"slug": "first", "match": ["mega"]},
        {"slug": "second", "match": ["mega"]},
    ]
    profile.pop("store_brands")
    classifier = fs.parse_classifier(profile, "test")
    assert slug_of({"shop": "supermarket", "name": "Mega"}, classifier) == "first"
    block["families"].reverse()
    classifier = fs.parse_classifier(profile, "test")
    assert slug_of({"shop": "supermarket", "name": "Mega"}, classifier) == "second"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Supercito Chedraui", "supercito"),
        ("Supercito", "supercito"),
        ("Chedraui Selecto", "chedraui"),
        ("Selecto Chedraui", "chedraui"),
        ("Super Che", "chedraui"),
        ("Farmacia Chedraui", None),
        ("La Comer", "la_comer"),
        ("City Market", "la_comer"),
        ("La Comercial Mexicana", None),
    ],
)
def test_classify_guadalajara(
    gdl: fs.SupermarketClassifier, name: str, expected: str | None
) -> None:
    assert slug_of({"shop": "supermarket", "name": name}, gdl) == expected


# ---------------------------------------------------------------------------
# v2: payload -> rows, dedupe, pool families, empty families
# ---------------------------------------------------------------------------

EXPECTED_KEPT = {
    "sams": [("way", 105), ("node", 106)],
    "costco": [("node", 121)],
    "aurrera": [("way", 101), ("node", 103), ("node", 128), ("node", 130)],
    "walmart": [("way", 107), ("node", 108)],
    "heb": [("node", 115)],
    "soriana": [("way", 120), ("node", 118)],
    "s_mart": [("node", 111)],
    "mi_tienda_ahorro": [("node", 117)],
    "city_club": [("node", 125)],
    "merco": [("node", 124)],
    "la_comer": [("node", 114)],
    "chedraui": [("node", 131)],
    "smart_final": [("way", 110)],
}


def test_classify_and_dedupe_fixture(mty: fs.SupermarketClassifier) -> None:
    stores = fs.classify_elements(mty_payload()["elements"], mty)
    # 22 classified: way 127 has no center, the repeated way 101 counts once.
    assert len(stores) == 22
    kept = fs.dedupe_stores(stores, mty)
    by_family: dict[str, list[tuple[str, int]]] = {}
    for store in kept:
        by_family.setdefault(store.family.slug, []).append((store.osm_type, store.osm_id))
    assert by_family == EXPECTED_KEPT
    # output order: profile family order, then ways before nodes, then id
    assert [s.family.slug for s in kept] == [
        slug for slug in [f.slug for f in mty.families] for _ in EXPECTED_KEPT.get(slug, [])
    ]


def test_dedupe_keeps_ways_and_only_merges_same_family(mty: fs.SupermarketClassifier) -> None:
    def element(kind: str, osm_id: int, lat: float, name: str) -> dict:
        base: dict = {"type": kind, "id": osm_id, "tags": {"shop": "supermarket", "name": name}}
        if kind == "node":
            base.update(lat=lat, lon=-100.3)
        else:
            base["center"] = {"lat": lat, "lon": -100.3}
        return base

    elements = [
        element("node", 1, 25.7, "Bodega Aurrera"),  # 33 m from way 9 -> dropped
        element("way", 9, 25.7003, "Bodega Aurrera Centro"),
        element("node", 2, 25.7, "Soriana"),  # same spot, other family -> kept
        element("node", 3, 25.71, "Bodega Aurrera"),  # 1.1 km away -> kept
        element("node", 4, 25.7101, "Bodega Aurrera"),  # 11 m from node 3 -> dropped
    ]
    kept = fs.dedupe_stores(fs.classify_elements(elements, mty), mty)
    assert [(s.family.slug, s.osm_type, s.osm_id) for s in kept] == [
        ("aurrera", "way", 9),
        ("aurrera", "node", 3),
        ("soriana", "node", 2),
    ]
    no_dedupe = fs.SupermarketClassifier(shops=mty.shops, dedupe_m=0.0, families=mty.families)
    assert len(fs.dedupe_stores(fs.classify_elements(elements, mty), no_dedupe)) == 5


def test_osm_data_age_days() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 11, 25, tzinfo=UTC)
    assert fs.osm_data_age_days("2026-11-24T00:00:00Z", now=now) == 1.0
    age = fs.osm_data_age_days("2026-05-31T22:37:44Z", now=now)
    assert age is not None and age > fs.OSM_STALE_AFTER_DAYS
    assert fs.osm_data_age_days("unknown", now=now) is None
    assert fs.osm_data_age_days(None, now=now) is None


def test_haversine_scale() -> None:
    assert fs.haversine_m((25.7, -100.3), (25.7, -100.3)) == 0.0
    assert 110_000 < fs.haversine_m((25.0, -100.0), (26.0, -100.0)) < 112_000


def run_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    city: str = "monterrey",
    extra_args: tuple[str, ...] = (),
) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def fake(query: str, **kwargs: object) -> dict:
        calls.append((query, kwargs))
        return copy.deepcopy(payload)

    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(fs, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(fs, "retry_overpass", fake)
    fs.main(["--city", city, *extra_args])
    return calls


def test_v2_main_writes_family_slugs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = run_v2(tmp_path, monkeypatch, mty_payload())
    assert len(calls) == 1
    query, kwargs = calls[0]
    assert "[timeout:180]" in query
    assert int(str(kwargs["attempts"])) >= 4
    assert int(str(kwargs["timeout"])) > 180
    # only the v2 path rotates mirrors, and it always rejects stale ones
    assert kwargs["endpoints"] == sio.OVERPASS_ENDPOINTS
    assert kwargs["max_osm_age_days"] == fs.OSM_STALE_AFTER_DAYS

    target = tmp_path / "processed" / "monterrey" / "supermarkets.csv"
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "name,brand,latitude,longitude,source"
    rows = read_rows(target)
    assert len(rows) == 19
    assert {row["source"] for row in rows} == {"openstreetmap"}
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["brand"]] = counts.get(row["brand"], 0) + 1
    assert counts == {slug: len(ids) for slug, ids in EXPECTED_KEPT.items()}
    # pool_only families are written too (they feed the overall supermarket score)
    assert {"merco", "city_club", "smart_final", "mi_tienda_ahorro"} <= set(counts)
    first = rows[0]
    assert first == {
        "name": "Sam's Club",
        "brand": "sams",
        "latitude": "25.6",
        "longitude": "-100.4",
        "source": "openstreetmap",
    }
    assert {row["name"] for row in rows if row["brand"] == "aurrera"} >= {"Bodega Aurrerá"}

    out = capsys.readouterr().out
    assert "OSM data as of 2026-11-24T00:00:00Z" in out
    assert "aurrera" in out and "merco [pool]" in out
    assert "Classified 22 stores; 3 same-family duplicates within 150 m dropped; 19 kept" in out
    # raw payload cached for --use-cache / provenance
    cached = json.loads((tmp_path / "raw" / "monterrey" / fs.RAW_CACHE_NAME).read_text("utf-8"))
    assert cached == mty_payload()


def test_v2_use_cache_reclassifies_without_overpass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_v2(tmp_path, monkeypatch, mty_payload())
    target = tmp_path / "processed" / "monterrey" / "supermarkets.csv"
    first = target.read_bytes()
    target.unlink()

    def refuse(*args: object, **kwargs: object) -> dict:
        raise AssertionError("--use-cache must not query Overpass")

    monkeypatch.setattr(fs, "retry_overpass", refuse)
    fs.main(["--city", "monterrey", "--use-cache"])
    assert target.read_bytes() == first


def test_v2_use_cache_without_cache_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(fs, "DATA_RAW", tmp_path / "raw")
    with pytest.raises(FetchError, match="No cached Overpass payload"):
        fs.main(["--city", "monterrey", "--use-cache"])


def test_v2_empty_toggle_family_fails_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = mty_payload()
    payload["elements"] = [
        e for e in payload["elements"] if "costco" not in json.dumps(e["tags"]).lower()
    ]
    with pytest.raises(FetchError, match=r"no OSM points for monterrey: \['costco'\]"):
        run_v2(tmp_path, monkeypatch, payload)
    assert not (tmp_path / "processed" / "monterrey" / "supermarkets.csv").exists()


def test_v2_empty_pool_family_is_fine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = mty_payload()
    payload["elements"] = [
        e for e in payload["elements"] if e["tags"].get("name") not in {"Merco", "Chedraui"}
    ]
    run_v2(tmp_path, monkeypatch, payload)
    rows = read_rows(tmp_path / "processed" / "monterrey" / "supermarkets.csv")
    assert "merco" not in {row["brand"] for row in rows}
    assert len(rows) == 17


def test_v2_rejects_payload_without_elements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(FetchError, match="no 'elements' list"):
        run_v2(tmp_path, monkeypatch, {"remark": "nothing"})


def test_v2_flags_store_brand_tokens_matching_other_slugs(gdl_profile: dict) -> None:
    # A "chedraui" toggle token would also match a pool family slug such as
    # "chedraui_supercito"; the detector must flag that configuration.
    conflicting = copy.deepcopy(gdl_profile)
    for family in conflicting["supermarket_classifier"]["families"]:
        if family["slug"] == "supercito":
            family["slug"] = "chedraui_supercito"
    classifier = fs.parse_classifier(conflicting, "guadalajara")
    conflicts = fs._brand_toggle_conflicts(conflicting, classifier)
    assert conflicts == [
        "store_brands 'chedraui' token 'chedraui' also matches family slug(s) "
        "['chedraui_supercito'], so the chedraui toggle will include their points"
    ]


@pytest.mark.parametrize("city", ["monterrey", "guadalajara"])
def test_committed_profiles_have_no_store_brand_conflicts(city: str) -> None:
    profile = load_city_profile(city)
    classifier = fs.parse_classifier(profile, city)
    assert fs._brand_toggle_conflicts(profile, classifier) == []


# ---------------------------------------------------------------------------
# v2: Overpass query
# ---------------------------------------------------------------------------


def test_v2_query_shape(mty_profile: dict, mty: fs.SupermarketClassifier) -> None:
    bbox = mty_profile["bbox"]
    query = fs.build_classified_query(bbox, mty)
    box = f"({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']})"
    lines = query.splitlines()
    assert lines[0] == "[out:json][timeout:180];"
    assert lines[-1] == "out tags center;"
    assert f'  nwr["shop"~"^(supermarket|wholesale|department_store)$"]{box};' in lines
    assert f'  nwr["shop"="convenience"]["brand:wikidata"~"(^|;)(Q3365858)(;|$)"]{box};' in lines
    assert sum('nwr["shop"="convenience"]["name"~' in line for line in lines) == 1
    assert sum('nwr["shop"="convenience"]["brand"~' in line for line in lines) == 1
    assert "operator" not in query


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Bodega Aurrerá Express", True),
        ("BODEGA AURRERÁ", True),
        ("Mi Bodeguita", True),
        ("OXXO", False),
        ("Bodega Comercial", False),
    ],
)
def test_overpass_text_pattern_is_an_accent_tolerant_superset(
    mty: fs.SupermarketClassifier, text: str, hit: bool
) -> None:
    import re

    aurrera = next(f for f in mty.families if f.slug == "aurrera")
    pattern = fs.overpass_text_pattern(aurrera.match)
    assert '"' not in pattern and "\\" not in pattern
    assert bool(re.search(pattern, text, re.IGNORECASE)) is hit


def test_overpass_text_pattern_short_words() -> None:
    import re

    pattern = fs.overpass_text_pattern(["h e b"])
    for text in ["H-E-B", "heb", "H E B"]:
        assert re.search(pattern, text, re.IGNORECASE)


# ---------------------------------------------------------------------------
# v2: profile validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b.update(version=1), "version must be 2"),
        (lambda b: b.update(shops=[]), "at least one OSM shop"),
        (lambda b: b.update(shops=['supermarket"]; out;']), "invalid values"),
        (lambda b: b.update(dedupe_m=-1), "dedupe_m"),
        (lambda b: b.update(dedupe_m="150"), "dedupe_m must be a number"),
        (lambda b: b.update(families=[]), "non-empty list"),
        (lambda b: b["families"][0].update(slug="Sam's"), "invalid slug"),
        (lambda b: b["families"][1].update(slug="sams"), "declared twice"),
        (lambda b: b["families"][0].update(wikidata=["Q1x"]), "invalid wikidata"),
        (lambda b: b["families"][0].update(match=[]), "match must list"),
        (lambda b: b["families"][0].update(match=["!!"]), "match must list"),
        (lambda b: b["families"][0].update(exclude=[" "]), "empty token"),
        (lambda b: b["families"][0].update(pool_only="yes"), "pool_only"),
        (lambda b: b["families"][2].update(extra_shops=["Convenience"]), "invalid values"),
        (lambda b: b["families"][0].update(pool_only=True), r"store_brands \['sams'\]"),
    ],
)
def test_parse_classifier_rejects_bad_config(
    mty_profile: dict, mutate: Callable[[dict], object], message: str
) -> None:
    profile = copy.deepcopy(mty_profile)
    mutate(profile["supermarket_classifier"])
    with pytest.raises(ConfigError, match=message):
        fs.parse_classifier(profile, "monterrey")


def test_parse_classifier_needs_a_toggle_family() -> None:
    profile = {
        "supermarket_classifier": {
            "version": 2,
            "shops": ["supermarket"],
            "families": [{"slug": "merco", "match": ["merco"], "pool_only": True}],
        }
    }
    with pytest.raises(ConfigError, match="not pool_only"):
        fs.parse_classifier(profile, "x")
    with pytest.raises(ConfigError, match="must be an object"):
        fs.parse_classifier({}, "x")


# ---------------------------------------------------------------------------
# DENUE gyms
# ---------------------------------------------------------------------------

DENUE_HEADER = (
    "id,clee,nom_estab,raz_social,codigo_act,nombre_act,per_ocu,tipo_vial,nom_vial,tipo_v_e_1,"
    "nom_v_e_1,tipo_v_e_2,nom_v_e_2,tipo_v_e_3,nom_v_e_3,numero_ext,letra_ext,edificio,"
    "edificio_e,numero_int,letra_int,tipo_asent,nomb_asent,tipoCenCom,nom_CenCom,num_local,"
    "cod_postal,cve_ent,entidad,cve_mun,municipio,cve_loc,localidad,ageb,manzana,telefono,"
    "correoelec,www,tipoUniEco,latitud,longitud,fecha_alta"
).split(",")
MTY_BBOX = {"south": 25.22, "west": -100.87, "north": 26.4, "east": -99.91}


def denue_record(row_id: int, name: str, **overrides: str) -> dict[str, str]:
    record = {column: "" for column in DENUE_HEADER}
    record.update(
        id=str(row_id),
        nom_estab=name,
        raz_social="",
        codigo_act="713943",
        nombre_act="Centros de acondicionamiento físico del sector privado",
        per_ocu="0 a 5 personas",
        cve_ent="19",
        entidad="Nuevo León",
        cve_mun="039",
        municipio="Monterrey",
        latitud=f"{25.60 + row_id / 1000:.8f}",
        longitud="-100.30000000",
        fecha_alta="2024-11",
    )
    record.update(overrides)
    return record


def valid_records(count: int = 22) -> list[dict[str, str]]:
    records = [denue_record(i, f"GIMNASIO NUMERO {i}") for i in range(1, max(count, 5) + 1)]
    records[0]["nom_estab"] = "GOLD'S GYM"
    records[1]["nom_estab"] = "GIMNASIO MUNICIPAL DE ZUÑIGA"
    records[2]["nom_estab"] = "YMCA   MONTERREY"
    records[3]["nom_estab"] = "SMART FIT SECTOR III"
    records[4]["codigo_act"] = "713944"
    records[4]["nom_estab"] = "UNIDAD DEPORTIVA DEL DIF"
    return records[:count]


def build_denue_zip(
    path: Path,
    records: list[dict[str, str]],
    *,
    header: list[str] | None = None,
    member: str = "conjunto_de_datos/denue_inegi_71_.csv",
    extra_members: dict[str, bytes] | None = None,
) -> Path:
    columns = header or DENUE_HEADER
    lines = [",".join(columns)]
    for record in records:
        lines.append(",".join(record.get(column, "") for column in columns))
    body = ("\r\n".join(lines) + "\r\n").encode("latin-1")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, body)
        archive.writestr(
            "metadatos/metadatos_denue.txt",
            "﻿Identifier: TEST\n\nTitle: DENUE de prueba 05_2026\n".encode(),
        )
        for name, data in (extra_members or {}).items():
            archive.writestr(name, data)
    return path


@pytest.fixture
def denue_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "raw"
    target.mkdir()
    monkeypatch.setattr(mc, "DATA_RAW", target)
    return target


def serve_zip(monkeypatch: pytest.MonkeyPatch, source: Path) -> list[str]:
    calls: list[str] = []

    def fake(url: str, path: Path, *, timeout: int = 300) -> None:
        calls.append(url)
        path.write_bytes(source.read_bytes())

    monkeypatch.setattr(mc, "stream_download", fake)
    return calls


def test_parse_gyms_source_from_profiles(mty_profile: dict, gdl_profile: dict) -> None:
    mty_source = fdg.parse_gyms_source(mty_profile, "monterrey")
    assert mty_source.url.endswith("/denue_00_71_csv.zip")
    assert mty_source.activity_codes == {"713943", "713944"}
    assert mty_source.state_codes == {"19"}
    assert fdg.parse_gyms_source(gdl_profile, "guadalajara").state_codes == {"14"}
    assert fdg.denue_cache_path(mty_source.url).name == "mx_inegi_denue_00_71_csv.zip"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.pop("gyms_source"), "must be an object"),
        (lambda p: p["gyms_source"].update(type="osm"), "type must be"),
        (lambda p: p["gyms_source"].update(url="http://x/denue.zip"), "https"),
        (lambda p: p["gyms_source"].update(activity_codes=[]), "non-empty"),
        (lambda p: p["gyms_source"].update(activity_codes=["71394"]), "invalid codes"),
        (lambda p: p["gyms_source"].update(state_codes=["NL"]), "invalid codes"),
    ],
)
def test_parse_gyms_source_rejects_bad_config(
    mty_profile: dict, mutate: Callable[[dict], object], message: str
) -> None:
    profile = copy.deepcopy(mty_profile)
    mutate(profile)
    with pytest.raises(ConfigError, match=message):
        fdg.parse_gyms_source(profile, "monterrey")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GIMNASIO MUNICIPAL DE APODACA", "Gimnasio Municipal de Apodaca"),
        ("GOLD'S GYM", "Gold's Gym"),
        ("YMCA   MONTERREY", "YMCA Monterrey"),
        ("SMART FIT SECTOR III", "Smart Fit Sector III"),
        ("CENTRO DEPORTIVO UANL", "Centro Deportivo UANL"),
        ("110 CLUB DE ENTRENAMIENTO", "110 Club de Entrenamiento"),
        ("Station 24", "Station 24"),
        ("   ", "Unnamed gym"),
    ],
)
def test_format_gym_name(raw: str, expected: str) -> None:
    assert fdg.format_gym_name(raw) == expected


def test_denue_gyms_filters_and_dedupes(
    tmp_path: Path, denue_raw: Path, monkeypatch: pytest.MonkeyPatch, mty_profile: dict
) -> None:
    records = valid_records()
    records += [
        denue_record(901, "GIMNASIO NUMERO 7", latitud=records[6]["latitud"]),  # exact duplicate
        denue_record(902, "CLUB DEPORTIVO", codigo_act="713941"),  # other activity
        denue_record(903, "GYM JALISCO", cve_ent="14", entidad="Jalisco"),  # other state
        denue_record(904, "GYM NORTE", latitud="26.90000000"),  # outside bbox
        denue_record(905, "GYM SIN COORDENADAS", latitud=""),  # bad coordinates
        denue_record(906, "GYM MAL", longitud="nan"),  # bad coordinates
    ]
    calls = serve_zip(monkeypatch, build_denue_zip(tmp_path / "src.zip", records))
    target = tmp_path / "processed" / "monterrey" / "gyms.csv"
    rows = fdg.fetch_denue_gyms("monterrey", mty_profile, target=target)

    assert len(calls) == 1 and calls[0].endswith("denue_00_71_csv.zip")
    assert (denue_raw / "mx_inegi_denue_00_71_csv.zip").exists()
    assert len(rows) == 22
    written = read_rows(target)
    assert list(written[0]) == ["name", "latitude", "longitude", "source"]
    assert len(written) == 22
    assert {row["source"] for row in written} == {"inegi_denue"}
    names = {row["name"] for row in written}
    assert {
        "Gold's Gym",
        "Gimnasio Municipal de Zuñiga",  # latin-1 decoded
        "YMCA Monterrey",
        "Smart Fit Sector III",
        "Unidad Deportiva del DIF",  # public-sector code 713944 kept
    } <= names
    assert not names & {"Club Deportivo", "Gym Jalisco", "Gym Norte", "Gym Sin Coordenadas"}
    # deterministic order (by name, then coordinates)
    assert [row["name"].casefold() for row in written] == sorted(
        row["name"].casefold() for row in written
    )


def test_denue_main_uses_cache_on_second_run(
    tmp_path: Path, denue_raw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = serve_zip(monkeypatch, build_denue_zip(tmp_path / "src.zip", valid_records()))
    monkeypatch.setattr(fdg, "DATA_PROCESSED", tmp_path / "processed")
    fdg.main(["--city", "monterrey"])
    fdg.main(["--city", "monterrey"])
    assert len(calls) == 1
    fdg.main(["--city", "monterrey", "--force"])
    assert len(calls) == 2
    assert len(read_rows(tmp_path / "processed" / "monterrey" / "gyms.csv")) == 22


def test_denue_too_few_rows_fails(
    tmp_path: Path, denue_raw: Path, monkeypatch: pytest.MonkeyPatch, mty_profile: dict
) -> None:
    serve_zip(monkeypatch, build_denue_zip(tmp_path / "src.zip", valid_records(19)))
    target = tmp_path / "gyms.csv"
    with pytest.raises(FetchError, match="Only 19 DENUE gyms"):
        fdg.fetch_denue_gyms("monterrey", mty_profile, target=target)
    assert not target.exists()


def test_denue_bbox_and_state_come_from_profile(
    tmp_path: Path, denue_raw: Path, monkeypatch: pytest.MonkeyPatch, gdl_profile: dict
) -> None:
    # Monterrey rows are neither in Jalisco nor in the Guadalajara bbox.
    serve_zip(monkeypatch, build_denue_zip(tmp_path / "src.zip", valid_records()))
    with pytest.raises(FetchError, match="Only 0 DENUE gyms for guadalajara"):
        fdg.fetch_denue_gyms("guadalajara", gdl_profile, target=tmp_path / "gyms.csv")


def _bad_zip(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.zip"
    if kind == "not_zip":
        path.write_bytes(b"<html>Servicio no disponible</html>")
    elif kind == "no_csv":
        build_denue_zip(path, valid_records(), member="conjunto_de_datos/otro.txt")
    elif kind == "two_csv":
        build_denue_zip(
            path,
            valid_records(),
            extra_members={"conjunto_de_datos/denue_inegi_72_.csv": b"id\r\n"},
        )
    elif kind == "unsafe":
        build_denue_zip(path, valid_records(), extra_members={"../evil.csv": b"x"})
    elif kind == "missing_column":
        header = [column for column in DENUE_HEADER if column != "latitud"]
        build_denue_zip(path, valid_records(), header=header)
    elif kind == "no_rows":
        build_denue_zip(path, [])
    return path


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("not_zip", "not a zip"),
        ("no_csv", "exactly one"),
        ("two_csv", "exactly one"),
        ("unsafe", "unsafe member"),
        ("missing_column", r"missing columns \['latitud'\]"),
        ("no_rows", "no data rows"),
    ],
)
def test_denue_download_is_validated_before_caching(
    tmp_path: Path,
    denue_raw: Path,
    monkeypatch: pytest.MonkeyPatch,
    mty_profile: dict,
    kind: str,
    message: str,
) -> None:
    serve_zip(monkeypatch, _bad_zip(tmp_path, kind))
    with pytest.raises(FetchError, match=message):
        fdg.fetch_denue_gyms("monterrey", mty_profile, target=tmp_path / "gyms.csv")
    assert list(denue_raw.iterdir()) == []  # nothing promoted, temp file removed


def test_denue_edition_line(tmp_path: Path) -> None:
    path = build_denue_zip(tmp_path / "src.zip", valid_records(1))
    assert fdg.denue_edition(path) == "DENUE de prueba 05_2026"
