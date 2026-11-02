#!/usr/bin/env python3
"""Has every scheduled workflow succeeded recently?

A scheduled check that stops running looks exactly like one that passes:
nothing is red, nothing is filed. A workflow disabled by hand, a schedule that
was edited away, or a job whose condition now skips it all go quiet. This
reads each workflow's last successful *scheduled* run and reports the ones
older than their allowed age.

It can't see GitHub stopping every schedule at once (it disables them in a
public repository after 60 days without activity, and a billing problem stops
all runs): this check is one of those schedules. ``liveness.yml`` can ping an
outside heartbeat for that case.

    python scripts/liveness.py --last-runs last_runs.json \
        --max-age "secrets.yml=8d,evals-nightly.yml=2d"

``last_runs.json`` maps a workflow file to the ISO time of its last successful
scheduled run, null for never, or ``{"error": "..."}`` when its runs could not
be read (``liveness.yml`` builds it with ``gh``). An unreadable workflow is a
finding, never "fresh". Exit codes: 0 all fresh, 1 overdue, never ran or
unreadable, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_UNITS = {"h": "hours", "d": "days"}


@dataclass(frozen=True)
class Finding:
    workflow: str
    reason: str


def parse_max_age(spec: str) -> dict[str, timedelta]:
    """``"a.yml=8d,b.yml=12h"`` -> {workflow: max age}."""
    ages: dict[str, timedelta] = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        name, _, age = item.partition("=")
        unit = _UNITS.get(age[-1:].lower())
        if not name or unit is None or not age[:-1].isdigit():
            raise ValueError(f"bad max-age entry {item!r}; use name.yml=8d or name.yml=12h")
        ages[name.strip()] = timedelta(**{unit: int(age[:-1])})
    if not ages:
        raise ValueError("no workflows to check")
    return ages


def _short(age: timedelta) -> str:
    hours = int(age.total_seconds() // 3600)
    return f"{hours // 24}d" if hours % 24 == 0 else f"{hours}h"


def find_overdue(
    last_runs: dict[str, object], max_age: dict[str, timedelta], now: datetime
) -> list[Finding]:
    findings = []
    for workflow, allowed in sorted(max_age.items()):
        stamp = last_runs.get(workflow)
        if isinstance(stamp, dict):
            error = str(stamp.get("error") or "unknown error").strip()
            findings.append(Finding(workflow, f"could not read its runs: {error}"))
            continue
        if not stamp:
            findings.append(Finding(workflow, "no successful scheduled run on record"))
            continue
        try:
            last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            findings.append(Finding(workflow, f"could not read its runs: bad time {stamp!r}"))
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = now - last
        if age > allowed:
            hours = int(age.total_seconds() // 3600)
            findings.append(
                Finding(workflow, f"last success {hours}h ago, allowed {_short(allowed)}")
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--last-runs", required=True)
    parser.add_argument("--max-age", required=True)
    parser.add_argument("--now", help="ISO time, for tests")
    args = parser.parse_args(argv)
    try:
        last_runs = json.loads(Path(args.last_runs).read_text(encoding="utf-8"))
        max_age = parse_max_age(args.max_age)
        if not isinstance(last_runs, dict):
            raise ValueError(f"{args.last_runs} is not a JSON object")
    except (OSError, ValueError) as exc:
        print(f"liveness: could not run: {exc}", file=sys.stderr)
        return 2
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    findings = find_overdue(last_runs, max_age, now)
    for finding in findings:
        print(f"- **{finding.workflow}**: {finding.reason}")
    if not findings:
        print(f"All {len(max_age)} scheduled workflow(s) succeeded recently.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
