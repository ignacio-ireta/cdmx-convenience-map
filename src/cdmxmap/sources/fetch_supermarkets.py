"""Supermarket points from OpenStreetMap (Overpass), by city profile.

Two classification paths, chosen by the profile:

- **Legacy** (no ``supermarket_classifier``: CDMX, Morelia, the Norwegian cities).
  One Overpass query on brand/operator/name regexes, then ``infer_brand`` picks the
  longest ``amenity_brands.supermarkets`` token found in the tags. Unchanged except
  that equal-length tokens now break ties alphabetically, so the result no longer
  depends on set iteration order (``PYTHONHASHSEED``).
- **v2** (``supermarket_classifier.version == 2``: Monterrey, Guadalajara). One
  superset Overpass query (the profile's shop values, plus each family's
  ``extra_shops`` narrowed by brand:wikidata / brand / name), classified in Python:

  1. Text is NFKD accent-stripped, case-folded, with typographic apostrophes
     turned into ``'`` (``normalize_text``).
  2. Fields are tried in order brand:wikidata, then brand, then name; within a
     field the first family in profile order wins. ``operator`` is never read
     (Walmart de México operates Bodega Aurrerá, Sam's Club and Walmart).
  3. Tokens match only at alphanumeric boundaries ("la comer" never matches
     "la comercial"), and never right after an apostrophe, so a possessive "'s"
     cannot start one ("Waldo's Mart" is not "s mart"); a family's ``exclude``
     tokens are checked on brand + name.
  4. Same-family points closer than ``dedupe_m`` collapse to one, preferring a
     building way/relation over a node.

  ``brand`` in the CSV is the family slug (``pool_only`` families included: they
  count towards the overall supermarket score but have no toggle). The fetch
  fails if any non-``pool_only`` family ends up with no rows.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cdmxmap.errors import ConfigError, FetchError

from .io import (
    DATA_PROCESSED,
    DATA_RAW,
    OVERPASS_ENDPOINTS,
    city_bbox,
    city_data_dir,
    copy_seed,
    element_center,
    load_city_profile,
    retry_overpass,
    write_csv,
)

ALLOWED_SHOPS = {"supermarket", "wholesale", "department_store"}


def build_query(city: str, brands: set[str]) -> str:
    bbox_data = city_bbox(city)
    bbox = f"{bbox_data['south']},{bbox_data['west']},{bbox_data['north']},{bbox_data['east']}"
    pattern = "|".join(sorted(brands))
    return f"""
[out:json][timeout:45];
(
  nwr["shop"~"supermarket|wholesale|department_store"]["brand"~"{pattern}",i]({bbox});
  nwr["shop"~"supermarket|wholesale|department_store"]["operator"~"{pattern}",i]({bbox});
  nwr["shop"~"supermarket|wholesale|department_store"]["name"~"{pattern}",i]({bbox});
);
out tags center;
"""


def infer_brand(tags: dict, brands: set[str]) -> str:
    haystack = " ".join(str(tags.get(key, "")).lower() for key in ["brand", "operator", "name"])
    # Longest token first; equal lengths break alphabetically, so the answer never
    # depends on set iteration order (which follows PYTHONHASHSEED per process).
    match = next(
        (brand for brand in sorted(brands, key=lambda b: (-len(b), b)) if brand in haystack),
        None,
    )
    return match.title() if match else "Unknown"


def is_store(tags: dict) -> bool:
    shop = str(tags.get("shop", "")).lower()
    name = str(tags.get("name", "")).lower()
    if shop in ALLOWED_SHOPS:
        return True
    if "costco" in name:
        return True
    if "walmart" in name and not any(blocked in name for blocked in ["banco", "farmacia"]):
        return True
    return False


# ---------------------------------------------------------------------------
# v2: profile-driven store-family classifier
# ---------------------------------------------------------------------------

CLASSIFIER_KEY = "supermarket_classifier"
CLASSIFIER_VERSION = 2
OSM_SOURCE = "openstreetmap"
OUTPUT_FIELDS = ["name", "brand", "latitude", "longitude", "source"]
RAW_CACHE_NAME = "supermarkets_overpass.json"
DEFAULT_DEDUPE_M = 150.0
# Server-side Overpass budget for the superset query; the HTTP timeout must outlast it.
OVERPASS_QUERY_TIMEOUT_S = 180
OVERPASS_HTTP_TIMEOUT_S = 240
OVERPASS_ATTEMPTS = 5
EARTH_RADIUS_M = 6371008.8
# Mirrors can lag months behind OSM (overpass.private.coffee served 2026-05-31 data on
# 2026-11-25). A live fetch rotates mirrors and rejects (retries past) any reply whose
# data is older than this; with --use-cache an older cached payload is only reported.
OSM_STALE_AFTER_DAYS = 30

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")  # family slugs and OSM shop values
_WIKIDATA_ID = re.compile(r"Q[1-9][0-9]*")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "´": "'", "`": "'"})
# Accented spellings a Spanish (or Latin-script) store name may carry for each base
# letter; used only to widen the Overpass prefilter, never for classification.
_ACCENT_VARIANTS = {
    "a": "aáàâäãå",
    "e": "eéèêë",
    "i": "iíìîï",
    "o": "oóòôöõ",
    "u": "uúùûü",
    "n": "nñ",
    "c": "cç",
    "y": "yýÿ",
}


def normalize_text(value: object) -> str:
    """Accent-free, case-folded, whitespace-collapsed text for brand matching.

    ``"Bodega  Aurrerá"`` -> ``"bodega aurrera"``; ``"Sam’s Club"`` -> ``"sam's club"``.
    Typographic apostrophes (and a spacing acute accent, as in ``"Sam´s"``) become
    ``'`` before NFKD so they do not decompose into a combining mark.
    """
    text = "" if value is None else str(value)
    decomposed = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES))
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.casefold().split())


def token_pattern(tokens: Iterable[str]) -> re.Pattern[str] | None:
    """A regex matching any of the (already normalized) tokens, but only where the
    token is not glued to another letter or digit on either side, and not right after
    an apostrophe (``normalize_text`` folds typographic ones to ``'``): the possessive
    ``'s`` in ``"waldo's mart"`` must not start the token ``"s mart"``."""
    alternatives = sorted({token for token in tokens if token}, key=lambda t: (-len(t), t))
    if not alternatives:
        return None
    body = "|".join(re.escape(token) for token in alternatives)
    return re.compile(rf"(?<![^\W_]|')(?:{body})(?![^\W_])")


@dataclass(frozen=True)
class StoreFamily:
    slug: str
    label: str
    pool_only: bool
    wikidata: frozenset[str]
    match: tuple[str, ...]  # normalized
    exclude: tuple[str, ...]  # normalized
    shops: frozenset[str]  # classifier shops plus this family's extra_shops
    extra_shops: tuple[str, ...]
    match_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)
    exclude_re: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    def matches(self, text: str) -> bool:
        return bool(text) and self.match_re is not None and bool(self.match_re.search(text))

    def excludes(self, text: str) -> bool:
        return self.exclude_re is not None and bool(self.exclude_re.search(text))


@dataclass(frozen=True)
class SupermarketClassifier:
    shops: tuple[str, ...]
    dedupe_m: float
    families: tuple[StoreFamily, ...]

    @property
    def extra_shops(self) -> tuple[str, ...]:
        """Shop values some family accepts beyond the classifier-wide ``shops``."""
        extra = {shop for family in self.families for shop in family.extra_shops}
        return tuple(sorted(extra - set(self.shops)))


def _string_list(value: object, *, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where} must be a list of strings")
    return [item.strip() for item in value]


def _identifiers(value: object, *, where: str) -> list[str]:
    items = _string_list(value, where=where)
    bad = [item for item in items if not _IDENTIFIER.fullmatch(item)]
    if bad:
        raise ConfigError(f"{where} has invalid values {bad} (lowercase a-z, 0-9, _)")
    return items


def parse_classifier(profile: Mapping[str, object], city: str) -> SupermarketClassifier:
    """Validate the profile's ``supermarket_classifier`` block (version 2)."""
    where = f"City profile '{city}' {CLASSIFIER_KEY}"
    block = profile.get(CLASSIFIER_KEY)
    if not isinstance(block, dict):
        raise ConfigError(f"{where} must be an object")
    if block.get("version") != CLASSIFIER_VERSION:
        raise ConfigError(
            f"{where} version must be {CLASSIFIER_VERSION}, got {block.get('version')!r}"
        )
    shops = _identifiers(block.get("shops"), where=f"{where}.shops")
    if not shops:
        raise ConfigError(f"{where}.shops must list at least one OSM shop value")
    dedupe_raw = block.get("dedupe_m", DEFAULT_DEDUPE_M)
    if isinstance(dedupe_raw, bool) or not isinstance(dedupe_raw, int | float):
        raise ConfigError(f"{where}.dedupe_m must be a number")
    dedupe_m = float(dedupe_raw)
    if not math.isfinite(dedupe_m) or dedupe_m < 0:
        raise ConfigError(f"{where}.dedupe_m must be a finite number >= 0")

    raw_families = block.get("families")
    if not isinstance(raw_families, list) or not raw_families:
        raise ConfigError(f"{where}.families must be a non-empty list")
    families: list[StoreFamily] = []
    for position, raw in enumerate(raw_families):
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}.families[{position}] must be an object")
        slug = raw.get("slug")
        if not isinstance(slug, str) or not _IDENTIFIER.fullmatch(slug):
            raise ConfigError(f"{where}.families[{position}] has an invalid slug {slug!r}")
        fwhere = f"{where} family '{slug}'"
        if any(family.slug == slug for family in families):
            raise ConfigError(f"{fwhere} is declared twice")
        label = raw.get("label", slug)
        if not isinstance(label, str) or not label.strip():
            raise ConfigError(f"{fwhere} label must be a non-empty string")
        pool_only = raw.get("pool_only", False)
        if not isinstance(pool_only, bool):
            raise ConfigError(f"{fwhere} pool_only must be true or false")
        wikidata = _string_list(raw.get("wikidata"), where=f"{fwhere} wikidata")
        bad_ids = [qid for qid in wikidata if not _WIKIDATA_ID.fullmatch(qid)]
        if bad_ids:
            raise ConfigError(f"{fwhere} has invalid wikidata ids {bad_ids}")
        match = [normalize_text(t) for t in _string_list(raw.get("match"), where=f"{fwhere} match")]
        if not match or not all(re.search(r"[^\W_]", token) for token in match):
            raise ConfigError(f"{fwhere} match must list tokens with a letter or digit")
        exclude = [
            normalize_text(t) for t in _string_list(raw.get("exclude"), where=f"{fwhere} exclude")
        ]
        if not all(exclude):
            raise ConfigError(f"{fwhere} exclude has an empty token")
        extra_shops = _identifiers(raw.get("extra_shops"), where=f"{fwhere} extra_shops")
        families.append(
            StoreFamily(
                slug=slug,
                label=label.strip(),
                pool_only=pool_only,
                wikidata=frozenset(wikidata),
                match=tuple(match),
                exclude=tuple(exclude),
                shops=frozenset(shops) | frozenset(extra_shops),
                extra_shops=tuple(extra_shops),
                match_re=token_pattern(match),
                exclude_re=token_pattern(exclude),
            )
        )
    toggles = {family.slug for family in families if not family.pool_only}
    if not toggles:
        raise ConfigError(f"{where} needs at least one family that is not pool_only")
    declared = profile.get("store_brands")
    if isinstance(declared, list):
        slugs = [str(item.get("slug")) for item in declared if isinstance(item, dict)]
        missing = [slug for slug in slugs if slug not in toggles]
        if missing:
            raise ConfigError(
                f"City profile '{city}' store_brands {missing} are not non-pool_only "
                f"{CLASSIFIER_KEY} families"
            )
    return SupermarketClassifier(shops=tuple(shops), dedupe_m=dedupe_m, families=tuple(families))


def classify_tags(
    tags: Mapping[str, object], classifier: SupermarketClassifier
) -> StoreFamily | None:
    """The store family of one OSM element's tags, or None.

    Field priority is brand:wikidata, then brand, then name; within a field the
    first family in profile order wins. ``operator`` is ignored on purpose.
    """
    shop = str(tags.get("shop", "")).strip().lower()
    allowed = [family for family in classifier.families if shop in family.shops]
    if not allowed:
        return None
    wikidata = {
        qid.strip() for qid in str(tags.get("brand:wikidata", "")).split(";") if qid.strip()
    }
    brand = normalize_text(tags.get("brand"))
    name = normalize_text(tags.get("name"))
    exclusion_text = f"{brand} | {name}"
    allowed = [family for family in allowed if not family.excludes(exclusion_text)]
    for family in allowed:
        if wikidata & family.wikidata:
            return family
    for text in (brand, name):
        for family in allowed:
            if family.matches(text):
                return family
    return None


@dataclass(frozen=True)
class ClassifiedStore:
    family: StoreFamily
    osm_type: str
    osm_id: int
    name: str
    latitude: float
    longitude: float
    shop: str


def classify_elements(
    elements: Iterable[object], classifier: SupermarketClassifier
) -> list[ClassifiedStore]:
    """Classify Overpass elements; unclassified, centerless and repeated ones are skipped."""
    stores: list[ClassifiedStore] = []
    seen: set[tuple[str, int]] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue
        family = classify_tags(tags, classifier)
        if family is None:
            continue
        center = element_center(element)
        if center is None or not all(math.isfinite(value) for value in center):
            continue
        osm_type = str(element.get("type", ""))
        try:
            osm_id = int(element.get("id", ""))
        except (TypeError, ValueError):
            continue
        if (osm_type, osm_id) in seen:
            continue
        seen.add((osm_type, osm_id))
        name = str(tags.get("name") or "").strip() or family.label
        stores.append(
            ClassifiedStore(
                family=family,
                osm_type=osm_type,
                osm_id=osm_id,
                name=name,
                latitude=center[0],
                longitude=center[1],
                shop=str(tags.get("shop", "")),
            )
        )
    return stores


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    d_lat, d_lon = lat2 - lat1, lon2 - lon1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))


def dedupe_stores(
    stores: Sequence[ClassifiedStore], classifier: SupermarketClassifier
) -> list[ClassifiedStore]:
    """Drop same-family points within ``dedupe_m`` of one already kept.

    Greedy and deterministic: families in profile order; within a family,
    ways/relations (building outlines) before nodes, then by OSM type and id.
    """
    order = {family.slug: index for index, family in enumerate(classifier.families)}
    ranked = sorted(
        stores,
        key=lambda s: (order[s.family.slug], s.osm_type == "node", s.osm_type, s.osm_id),
    )
    kept: list[ClassifiedStore] = []
    kept_by_family: dict[str, list[tuple[float, float]]] = {}
    for store in ranked:
        bucket = kept_by_family.setdefault(store.family.slug, [])
        point = (store.latitude, store.longitude)
        if classifier.dedupe_m > 0 and any(
            haversine_m(other, point) < classifier.dedupe_m for other in bucket
        ):
            continue
        bucket.append(point)
        kept.append(store)
    return kept


def _overpass_word(word: str) -> str:
    parts: list[str] = []
    for char in word:
        variants = _ACCENT_VARIANTS.get(char)
        if variants:
            # Literal alternatives (not a bracket class) so a byte-oriented regex
            # engine still matches multi-byte accented letters.
            parts.append("(" + "|".join(variants + variants.upper()) + ")")
        else:
            parts.append(char)
    return "".join(parts)


def overpass_text_pattern(tokens: Iterable[str]) -> str:
    """A case-insensitive Overpass regex that every name/brand containing one of the
    (normalized) tokens satisfies, accents included: a prefilter, not the classifier.

    Each token contributes its longest ASCII word (``"bodega aurrera"`` ->
    ``aurrera``); a token made only of 1-2 character words (``"h e b"``) contributes
    the words joined by up to 3 arbitrary characters.
    """
    alternatives: set[str] = set()
    for token in tokens:
        words = re.findall(r"[a-z0-9]+", token)
        if not words:
            continue
        longest = max(words, key=len)
        if len(longest) >= 3:
            alternatives.add(_overpass_word(longest))
        else:
            alternatives.add(".{0,3}".join(_overpass_word(word) for word in words))
    if not alternatives:
        raise ConfigError("Cannot build an Overpass name filter from tokens without letters")
    return "|".join(sorted(alternatives))


def build_classified_query(bbox: Mapping[str, float], classifier: SupermarketClassifier) -> str:
    """The v2 superset query: every element whose shop is in ``classifier.shops``, plus
    elements of each extra shop value that carry a family's brand:wikidata, or a
    brand or name containing one of its tokens."""
    box = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"
    statements = [f'nwr["shop"~"^({"|".join(classifier.shops)})$"]({box});']
    for shop in classifier.extra_shops:
        families = [family for family in classifier.families if shop in family.extra_shops]
        qids = sorted({qid for family in families for qid in family.wikidata})
        if qids:
            statements.append(
                f'nwr["shop"="{shop}"]["brand:wikidata"~"(^|;)({"|".join(qids)})(;|$)"]({box});'
            )
        pattern = overpass_text_pattern(token for family in families for token in family.match)
        for key in ("brand", "name"):
            statements.append(f'nwr["shop"="{shop}"]["{key}"~"{pattern}",i]({box});')
    body = "\n".join(f"  {statement}" for statement in statements)
    return f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_S}];\n(\n{body}\n);\nout tags center;\n"


def _bbox_from_profile(profile: Mapping[str, object], city: str) -> dict[str, float]:
    bbox = profile.get("bbox")
    keys = ("south", "west", "north", "east")
    if not isinstance(bbox, dict) or not all(key in bbox for key in keys):
        raise ConfigError(f"City profile '{city}' is missing bbox keys {list(keys)}")
    return {key: float(bbox[key]) for key in keys}


def _check_payload(payload: object, *, origin: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise FetchError(f"Overpass payload from {origin} has no 'elements' list")
    return payload


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.part")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _brand_toggle_conflicts(
    profile: Mapping[str, object], classifier: SupermarketClassifier
) -> list[str]:
    """store_brands match tokens that are substrings of *other* family slugs.

    The engine selects a toggle's points with ``brand.str.contains(token)``, so
    such a token would pull the other family's rows into that toggle.
    """
    declared = profile.get("store_brands")
    if not isinstance(declared, list):
        return []
    slugs = [family.slug for family in classifier.families]
    conflicts: list[str] = []
    for item in declared:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", ""))
        tokens = [str(token).lower() for token in (item.get("match") or [slug])]
        for token in tokens:
            others = [other for other in slugs if other != slug and token in other]
            if others:
                conflicts.append(
                    f"store_brands '{slug}' token '{token}' also matches family slug(s) "
                    f"{others}, so the {slug} toggle will include their points"
                )
    return conflicts


def osm_data_age_days(osm_base: object, *, now: datetime) -> float | None:
    """Age in days of an Overpass ``osm3s.timestamp_osm_base`` (None if unparseable)."""
    if not isinstance(osm_base, str):
        return None
    try:
        stamp = datetime.fromisoformat(osm_base.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp).total_seconds() / 86400


def fetch_classified_supermarkets(
    city: str,
    profile: Mapping[str, object],
    *,
    target: Path,
    raw_cache: Path,
    use_cache: bool = False,
) -> list[dict]:
    """Run the v2 classifier for ``city`` and write ``target`` (supermarkets.csv).

    Raises ``FetchError`` (nothing written) when the payload is malformed or a
    non-``pool_only`` family has no rows.
    """
    classifier = parse_classifier(profile, city)
    for conflict in _brand_toggle_conflicts(profile, classifier):
        print(f"Warning: {conflict}")
    if use_cache:
        if not raw_cache.exists():
            raise FetchError(f"No cached Overpass payload at {raw_cache}")
        payload = _check_payload(
            json.loads(raw_cache.read_text(encoding="utf-8")), origin=str(raw_cache)
        )
        print(f"Using cached Overpass payload {raw_cache}")
    else:
        query = build_classified_query(_bbox_from_profile(profile, city), classifier)
        payload = _check_payload(
            retry_overpass(
                query,
                attempts=OVERPASS_ATTEMPTS,
                timeout=OVERPASS_HTTP_TIMEOUT_S,
                endpoints=OVERPASS_ENDPOINTS,
                max_osm_age_days=OSM_STALE_AFTER_DAYS,
            ),
            origin="Overpass",
        )
        _write_json_atomic(raw_cache, payload)
        print(f"Cached raw Overpass payload at {raw_cache}")

    osm_base = (payload.get("osm3s") or {}).get("timestamp_osm_base", "unknown")
    elements = payload["elements"]
    stores = classify_elements(elements, classifier)
    kept = dedupe_stores(stores, classifier)

    raw_counts = Counter(store.family.slug for store in stores)
    kept_counts = Counter(store.family.slug for store in kept)
    print(
        f"Supermarket families for {city} ({len(elements)} Overpass elements, "
        f"OSM data as of {osm_base}):"
    )
    age = osm_data_age_days(osm_base, now=datetime.now(UTC))
    if age is not None and age > OSM_STALE_AFTER_DAYS:
        print(
            f"Warning: this Overpass mirror's OSM data is {age:.0f} days old; store counts "
            "may lag OpenStreetMap (re-run later to reach an up-to-date mirror)"
        )
    print(f"  {'family':<26}{'raw':>6}{'kept':>6}")
    for family in classifier.families:
        label = family.slug + (" [pool]" if family.pool_only else "")
        print(f"  {label:<26}{raw_counts[family.slug]:>6}{kept_counts[family.slug]:>6}")
    dropped = len(stores) - len(kept)
    print(
        f"Classified {len(stores)} stores; {dropped} same-family duplicates within "
        f"{classifier.dedupe_m:g} m dropped; {len(kept)} kept"
    )

    empty = [
        family.slug
        for family in classifier.families
        if not family.pool_only and kept_counts[family.slug] == 0
    ]
    if empty:
        raise FetchError(
            f"Supermarket families with no OSM points for {city}: {empty} "
            "(drop them from store_brands or mark them pool_only)"
        )

    rows = [
        {
            "name": store.name,
            "brand": store.family.slug,
            "latitude": store.latitude,
            "longitude": store.longitude,
            "source": OSM_SOURCE,
        }
        for store in kept
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    write_csv(target, rows, OUTPUT_FIELDS)
    print(f"Fetched {len(rows)} classified supermarket points")
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch supermarket points from OSM by city profile."
    )
    parser.add_argument("--city", default="cdmx", help="City profile id (default: cdmx).")
    parser.add_argument("--seed-only", action="store_true", help="Skip Overpass and use seed CSV.")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help=(
            f"Profiles with {CLASSIFIER_KEY} only: classify the raw Overpass payload "
            f"cached in data/raw/<city>/{RAW_CACHE_NAME} instead of querying Overpass."
        ),
    )
    args = parser.parse_args(argv)

    target = city_data_dir(DATA_PROCESSED, args.city) / "supermarkets.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.seed_only:
        if args.city != "cdmx":
            raise ValueError("Seed data is only valid for CDMX")
        copy_seed("supermarkets_seed.csv", target)
        return

    if args.city != "cdmx":
        city_profile = load_city_profile(args.city)
        if city_profile.get(CLASSIFIER_KEY) is not None:
            fetch_classified_supermarkets(
                args.city,
                city_profile,
                target=target,
                raw_cache=city_data_dir(DATA_RAW, args.city) / RAW_CACHE_NAME,
                use_cache=args.use_cache,
            )
            return
    if args.use_cache:
        parser.error(f"--use-cache needs a city profile with {CLASSIFIER_KEY}")

    try:
        profile = load_city_profile(args.city)
        brands = {
            brand.lower()
            for brand in profile.get("amenity_brands", {}).get(
                "supermarkets", ["costco", "walmart"]
            )
        }
        payload = retry_overpass(build_query(args.city, brands), attempts=2, timeout=75)
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for element in payload.get("elements", []):
            center = element_center(element)
            if not center:
                continue
            tags = element.get("tags", {})
            brand = infer_brand(tags, brands)
            if brand == "Unknown" or brand.lower() not in brands or not is_store(tags):
                continue
            key = (element.get("type", ""), str(element.get("id", "")))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "name": tags.get("name", brand),
                    "brand": brand,
                    "latitude": center[0],
                    "longitude": center[1],
                    "source": "openstreetmap",
                }
            )
        if len(rows) < 5:
            raise ValueError(f"Only found {len(rows)} matching supermarket rows")
        write_csv(target, rows, ["name", "brand", "latitude", "longitude", "source"])
        print(f"Fetched {len(rows)} matching supermarket points")
    except Exception as exc:
        if args.city != "cdmx":
            raise RuntimeError(f"Could not fetch supermarkets for {args.city}: {exc}") from exc
        print(f"Falling back to seed supermarkets because Overpass failed: {exc}")
        copy_seed("supermarkets_seed.csv", target)


if __name__ == "__main__":
    main()
