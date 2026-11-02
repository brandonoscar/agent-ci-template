#!/usr/bin/env python3
"""Post-deploy smoke checks: is the deployed app up, answering correctly, and
fast enough? Standard library only.

    python scripts/smoke.py --base-url https://app.example.com --checks smoke/checks.json

``checks.json``:

    {"checks": [
      {"name": "health", "path": "/healthz", "expect_status": 200,
       "expect_json": {"status": "ok"}, "max_ms": 2000},
      {"name": "home", "path": "/", "expect_text": "<title>"}
    ]}

Redirects are not followed: a check sees the status the app sent. Expect the
30x itself, or point the check at the final path. Following them would let a
page that bounces every request to a sign-in page pass a check for ``/``.

Exit codes: 0 every check passed, 1 a check failed, 2 could not run (no base
URL or one that isn't http(s), unreadable checks). 2 is not a pass: a smoke
test that did not run says nothing about the deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Any


@dataclass
class Check:
    name: str
    path: str
    method: str = "GET"
    expect_status: int = 200
    expect_json: dict[str, Any] = field(default_factory=dict)
    expect_text: str = ""
    max_ms: int = 5000
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Result:
    check: Check
    ok: bool
    status: int | None
    elapsed_ms: int
    problem: str = ""


def load_checks(path: Path) -> list[Check]:
    data = json.loads(path.read_text(encoding="utf-8"))
    checks = [Check(**item) for item in data["checks"]]
    if not checks:
        raise ValueError("no checks defined")
    return checks


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Report a 30x as it is instead of following it."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def _fetch(url: str, check: Check, timeout: float) -> tuple[int, bytes, str]:
    """(status, body, Location header or "")."""
    request = urllib.request.Request(url, method=check.method, headers=check.headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read(1_000_000), ""
    except urllib.error.HTTPError as exc:  # a status code is an answer, not a failure to run
        location = exc.headers.get("Location", "") if exc.headers else ""
        return exc.code, exc.read(1_000_000), location


def run_check(base_url: str, check: Check, *, timeout: float = 15.0, retries: int = 1) -> Result:
    """One check. A connection error is retried once: a deploy that is still
    warming up should not page anyone, a deploy that is down still fails."""
    url = base_url.rstrip("/") + "/" + check.path.lstrip("/")
    last_error = ""
    for _ in range(retries + 1):
        started = time.monotonic()
        try:
            status, body, location = _fetch(url, check, timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
            time.sleep(1)
            continue
        elapsed = int((time.monotonic() - started) * 1000)
        problems = []
        if status != check.expect_status:
            moved = f" (redirect to {location})" if location else ""
            problems.append(f"status {status}{moved}, expected {check.expect_status}")
        if check.expect_json:
            try:
                payload = json.loads(body or b"null")
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                problems.append("expected a JSON object")
            else:
                for key, want in check.expect_json.items():
                    if payload.get(key) != want:
                        problems.append(f"{key}={payload.get(key)!r}, expected {want!r}")
        if check.expect_text and check.expect_text not in body.decode("utf-8", "replace"):
            problems.append(f"body does not contain {check.expect_text!r}")
        if elapsed > check.max_ms:
            problems.append(f"took {elapsed} ms, budget {check.max_ms} ms")
        return Result(check, not problems, status, elapsed, "; ".join(problems))
    return Result(check, False, None, 0, f"could not connect: {last_error}")


def markdown(results: list[Result], base_url: str) -> str:
    lines = [f"### Smoke: {base_url}", "", "| Check | Result | Status | ms | Problem |"]
    lines.append("|---|---|---|---|---|")
    for r in results:
        mark = "pass" if r.ok else "**FAIL**"
        lines.append(
            f"| {r.check.name} | {mark} | {r.status or '-'} | {r.elapsed_ms} | {r.problem} |"
        )
    return "\n".join(lines) + "\n"


def base_url_problem(base_url: str) -> str:
    """Why ``base_url`` can't be checked, or "" when it can."""
    if not base_url:
        return "no --base-url or SMOKE_BASE_URL"
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"base URL {base_url!r} is not an http(s) URL with a host"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL", ""))
    parser.add_argument("--checks", default="smoke/checks.json")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    problem = base_url_problem(args.base_url)
    if problem:
        print(f"smoke: could not run: {problem}. Not a pass.", file=sys.stderr)
        return 2
    try:
        checks = load_checks(Path(args.checks))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"smoke: could not run: {args.checks}: {exc}", file=sys.stderr)
        return 2
    results = [run_check(args.base_url, c, timeout=args.timeout) for c in checks]
    report = markdown(results, args.base_url)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
