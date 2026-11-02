# Changelog

Notable changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-02

First release.

### Added

- Seven workflows: CI, secret scanning with gitleaks, the eval gate and nightly evals, RLS checks, post-deploy smoke tests, and a liveness check for scheduled workflows.
- The `file-issue` composite action: one issue per title, commented on after the first time.
- `scripts/smoke.py` and `scripts/liveness.py`, standard library only, with tests.
- Optional settings: `SMOKE_ENVIRONMENTS` (which deployments get smoke-tested) and a `LIVENESS_HEARTBEAT_URL` secret that pings an outside dead-man's-switch monitor.

[Unreleased]: https://github.com/brandonoscar/agent-ci-template/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/brandonoscar/agent-ci-template/releases/tag/v0.1.0
