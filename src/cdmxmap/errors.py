"""Domain-specific exceptions (engineering standards §H).

A typed hierarchy so failures are actionable and the runner can isolate a single
bad source instead of letting a broad ``except Exception`` swallow everything.
Each exception carries a process ``exit_code`` for the CLI (§H exit codes).
"""

from __future__ import annotations


class CdmxmapError(Exception):
    """Base class for all pipeline errors."""

    exit_code = 1


class ConfigError(CdmxmapError):
    """Invalid or missing configuration (city profile, places.json, CLI args)."""

    exit_code = 2


class SourceUnavailableError(CdmxmapError):
    """An open-data source could not be reached or returned no usable data."""

    exit_code = 1


class FetchError(CdmxmapError):
    """A source fetcher failed to download or normalize its data."""

    exit_code = 1


class ScoringError(CdmxmapError):
    """Scoring failed for an area unit."""

    exit_code = 1


class ValidationError(CdmxmapError):
    """Processed output did not satisfy the data contract."""

    exit_code = 1


class NoOutputError(CdmxmapError):
    """The run produced no output at all."""

    exit_code = 3
