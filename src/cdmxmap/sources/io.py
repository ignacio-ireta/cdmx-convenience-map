from __future__ import annotations

import csv
import http.client
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

# src/cdmxmap/sources/io.py -> repo root is three parents up.
ROOT = Path(__file__).resolve().parents[3]
DATA_RAW = ROOT / "data" / "raw"
DATA_CONFIG = ROOT / "data" / "config"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_SEEDS = ROOT / "data" / "seeds"
DATA_CITIES = ROOT / "data" / "cities"
FRONTEND_PUBLIC_DATA = ROOT / "frontend" / "public" / "data"

CDMX_BBOX = {
    "south": 19.04,
    "west": -99.38,
    "north": 19.60,
    "east": -98.90,
}

USER_AGENT = "cdmx-postal-code-convenience-map/0.1"

# Overpass mirrors, tried in this order (one per attempt) by ``retry_overpass`` callers
# that opt into rotation; the default is the first one only.
OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OVERPASS_BACKOFF_S = 30.0
OVERPASS_MAX_WAIT_S = 300.0

# Injectable for tests (monkeypatch ``io._sleep``) so retries never really wait.
_sleep: Callable[[float], None] = time.sleep


def ensure_dirs() -> None:
    for path in [
        DATA_RAW,
        DATA_CONFIG,
        DATA_PROCESSED,
        DATA_SEEDS,
        DATA_CITIES,
        FRONTEND_PUBLIC_DATA,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def load_city_profile(city: str = "cdmx") -> dict:
    from cdmxmap.schema import validate_city_profile

    profile_path = DATA_CITIES / city / "city.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing city profile: {profile_path}")
    with profile_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return validate_city_profile(data, city=city)


def city_bbox(city: str = "cdmx") -> dict[str, float]:
    profile = load_city_profile(city)
    bbox = profile.get("bbox") or {}
    required = ["south", "west", "north", "east"]
    if not all(key in bbox for key in required):
        raise ValueError(f"City profile {city} is missing bbox keys: {required}")
    return {key: float(bbox[key]) for key in required}


def city_data_dir(base: Path, city: str) -> Path:
    """Return the legacy flat CDMX directory or a city-scoped directory."""
    return base if city == "cdmx" else base / city


def download(url: str, target: Path, *, force: bool = False, timeout: int = 90) -> Path:
    ensure_dirs()
    if target.exists() and not force:
        print(f"Using cached {target}")
        return target

    print(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        target.write_bytes(response.read())
    print(f"Wrote {target}")
    return target


def post_overpass(query: str, *, timeout: int = 90, endpoint: str = OVERPASS_ENDPOINTS[0]) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    ensure_dirs()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    print(f"Wrote {path}")


def copy_seed(seed_name: str, target: Path) -> None:
    seed_path = DATA_SEEDS / seed_name
    shutil.copyfile(seed_path, target)
    print(f"Used fallback seed {seed_path} -> {target}")


def _overpass_host(endpoint: str) -> str:
    return urllib.parse.urlsplit(endpoint).netloc or endpoint


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float:
    header = exc.headers.get("Retry-After") if exc.headers is not None else None
    try:
        return max(0.0, float(header)) if header is not None else 0.0
    except ValueError:
        return 0.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def overpass_data_age_days(payload: dict, *, now: datetime) -> float | None:
    """Age in days of a reply's ``osm3s.timestamp_osm_base`` (None if absent/unparseable)."""
    stamp_text = (payload.get("osm3s") or {}).get("timestamp_osm_base")
    if not isinstance(stamp_text, str):
        return None
    try:
        stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp).total_seconds() / 86400


def _overpass_runtime_error(payload: dict) -> str | None:
    """Overpass answers HTTP 200 with a ``remark`` when the query timed out or ran
    out of memory; the elements are then partial, so treat it as a failure."""
    remark = payload.get("remark") if isinstance(payload, dict) else None
    if isinstance(remark, str) and "runtime error" in remark.lower():
        return remark
    return None


def retry_overpass(
    query: str,
    *,
    attempts: int = 2,
    timeout: int = 90,
    endpoints: Sequence[str] = OVERPASS_ENDPOINTS[:1],
    backoff_s: float = OVERPASS_BACKOFF_S,
    max_osm_age_days: float | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """POST an Overpass query, rotating mirrors with a backoff between attempts.

    Attempt ``n`` (1-based) goes to ``endpoints[(n - 1) % len(endpoints)]``. The default
    is overpass-api.de alone (every attempt goes there, as legacy callers always did);
    callers that opt into mirror rotation pass ``endpoints=OVERPASS_ENDPOINTS`` (order
    overpass-api.de, overpass.kumi.systems, overpass.private.coffee) together with
    ``max_osm_age_days``, because the mirrors can lag OpenStreetMap by months.
    Retryable failures: connection/URL errors, timeouts, HTTP 429 and 5xx, a body
    that is not (UTF-8) JSON, truncated reads and a 200 response whose ``remark`` reports
    an Overpass runtime error (partial result). Any other HTTP status (e.g. 400 for
    a malformed query) fails at once. Between attempts it waits
    ``max(backoff_s * n, Retry-After)`` seconds (at least ``OVERPASS_BACKOFF_S``),
    through the module-level ``_sleep`` so tests can replace it.

    With ``max_osm_age_days`` set, a reply whose ``osm3s.timestamp_osm_base`` is older
    than that (some mirrors lag OpenStreetMap by months) is a retryable failure too, so
    a stale mirror can never stand in for current data. Unset, as for every legacy
    caller (which also stays on the single default endpoint), any reply is accepted.
    """
    if attempts < 1:
        raise ValueError("retry_overpass needs attempts >= 1")
    if not endpoints:
        raise ValueError("retry_overpass needs at least one endpoint")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        endpoint = endpoints[(attempt - 1) % len(endpoints)]
        wait = max(float(backoff_s), OVERPASS_BACKOFF_S) * attempt
        try:
            payload = post_overpass(query, timeout=timeout, endpoint=endpoint)
            remark = _overpass_runtime_error(payload)
            if remark is not None:
                raise RuntimeError(f"Overpass runtime error: {remark}")
            if max_osm_age_days is not None:
                age = overpass_data_age_days(payload, now=(now or _utc_now)())
                if age is None or age > max_osm_age_days:
                    shown = "unknown" if age is None else f"{age:.0f} days"
                    raise RuntimeError(
                        f"stale mirror: OSM data age {shown} exceeds {max_osm_age_days:g} days"
                    )
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError(
                    f"Overpass at {_overpass_host(endpoint)} rejected the query (HTTP {exc.code})"
                ) from exc
            last_error = exc
            wait = max(wait, min(_retry_after_seconds(exc), OVERPASS_MAX_WAIT_S))
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,
            json.JSONDecodeError,
            UnicodeDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
        host = _overpass_host(endpoint)
        print(f"Overpass attempt {attempt}/{attempts} via {host} failed: {last_error}")
        if attempt < attempts:
            next_endpoint = endpoints[attempt % len(endpoints)]
            print(f"Retrying in {wait:.0f}s via {_overpass_host(next_endpoint)}")
            _sleep(wait)
    raise RuntimeError(f"Overpass failed after {attempts} attempts") from last_error


def element_center(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None
