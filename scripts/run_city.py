from __future__ import annotations

import argparse
import subprocess
import sys


FETCH_SEQUENCE = [
    "fetch_postal_codes.py",
    "fetch_colonias.py",
    "fetch_transit.py",
    "fetch_supermarkets.py",
    "fetch_gyms.py",
    "fetch_crime.py",
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run city pipeline with shared --city propagation.")
    parser.add_argument("--city", default="cdmx", help="City profile id (default: cdmx)")
    parser.add_argument("--area-unit", default="postal_code", help="Area unit for build_scores")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetch scripts and only build scores")
    args = parser.parse_args()

    if args.city != "cdmx":
        print(
            "Note: only OSM-based fetchers are city-aware today. "
            "CDMX-specific source fetchers still require city adapters.",
            file=sys.stderr,
        )

    if not args.skip_fetch:
        for script in FETCH_SEQUENCE:
            cmd = [sys.executable, f"scripts/{script}"]
            if script in {"fetch_supermarkets.py", "fetch_gyms.py"}:
                cmd.extend(["--city", args.city])
            run(cmd)

    run([sys.executable, "scripts/build_scores.py", "--area-unit", args.area_unit])


if __name__ == "__main__":
    main()
