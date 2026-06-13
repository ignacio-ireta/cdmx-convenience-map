# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it is
published.

## [Unreleased]

### Added

- `pyproject.toml` + `uv.lock`: Python project migrated to `uv` with runtime,
  dev, and optional `transit` dependency groups; Python pinned to `>=3.11,<3.13`.
- Quality-gate configuration: `ruff`, `mypy`, and `pytest` settings in
  `pyproject.toml`; Prettier for the frontend.
- `docs/engineering-standards.md` — project-specific engineering standards (A–S).
- `CONTRIBUTING.md`, `.env.example`, and this changelog.

### Changed

- Frontend gains `typecheck` and `format` npm scripts.

[Unreleased]: https://github.com/ignacio-ireta/cdmx-convenience-map/commits/master
