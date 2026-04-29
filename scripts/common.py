from __future__ import annotations

import csv
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_CONFIG = ROOT / "data" / "config"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_SEEDS = ROOT / "data" / "seeds"
FRONTEND_PUBLIC_DATA = ROOT / "frontend" / "public" / "data"

CDMX_BBOX = {
    "south": 19.04,
    "west": -99.38,
    "north": 19.60,
    "east": -98.90,
}

USER_AGENT = "cdmx-postal-code-convenience-map/0.1"


def ensure_dirs() -> None:
    for path in [
        DATA_RAW,
        DATA_CONFIG,
        DATA_PROCESSED,
        DATA_SEEDS,
        FRONTEND_PUBLIC_DATA,
    ]:
        path.mkdir(parents=True, exist_ok=True)


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


def post_overpass(query: str, *, timeout: int = 90) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
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


def retry_overpass(query: str, *, attempts: int = 2, timeout: int = 90) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return post_overpass(query, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"Overpass attempt {attempt} failed: {exc}")
            if attempt < attempts:
                time.sleep(3)
    raise RuntimeError(f"Overpass failed after {attempts} attempts") from last_error


def element_center(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None
