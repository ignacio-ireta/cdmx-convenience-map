"""Run manifest for resumability + traceability (standards §J/§S).

Each run writes ``runs/<run_id>/manifest.json`` (per-source/area status, source
SHA256, output paths, timings) and ``errors.json`` (failed/interrupted entries).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from cdmxmap.sources.io import ROOT

RUNS_DIR = ROOT / "runs"

# Per-entry status vocabulary (standards §J).
PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
WARNING = "warning"
FAILED = "failed"
SKIPPED = "skipped"
INTERRUPTED = "interrupted"


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


@dataclass
class ManifestEntry:
    name: str
    kind: str  # "source" | "area"
    status: str = PENDING
    sha256: str | None = None
    output: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "sha256": self.sha256,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class RunManifest:
    run_id: str
    command: str
    city: str
    started_at: str
    finished_at: str | None = None
    status: str = RUNNING
    entries: list[ManifestEntry] = field(default_factory=list)

    @property
    def run_dir(self) -> Path:
        return RUNS_DIR / self.run_id

    def entry(self, name: str, kind: str) -> ManifestEntry:
        for existing in self.entries:
            if existing.name == name and existing.kind == kind:
                return existing
        created = ManifestEntry(name=name, kind=kind)
        self.entries.append(created)
        return created

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "command": self.command,
            "city": self.city,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "summary": self.summary(),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def write(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "manifest.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def write_errors(self) -> Path:
        failures = [
            entry.to_dict() for entry in self.entries if entry.status in {FAILED, INTERRUPTED}
        ]
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "errors.json"
        path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        return path


def latest_manifest() -> RunManifest | None:
    """Load the most recent prior run manifest, if any (for --resume)."""
    if not RUNS_DIR.exists():
        return None
    candidates = sorted(RUNS_DIR.glob("*/manifest.json"))
    if not candidates:
        return None
    payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    manifest = RunManifest(
        run_id=payload["run_id"],
        command=payload.get("command", ""),
        city=payload.get("city", ""),
        started_at=payload.get("started_at", ""),
        finished_at=payload.get("finished_at"),
        status=payload.get("status", RUNNING),
    )
    for raw in payload.get("entries", []):
        manifest.entries.append(
            ManifestEntry(
                name=raw["name"],
                kind=raw["kind"],
                status=raw.get("status", PENDING),
                sha256=raw.get("sha256"),
                output=raw.get("output"),
                error=raw.get("error"),
                started_at=raw.get("started_at"),
                finished_at=raw.get("finished_at"),
            )
        )
    return manifest
