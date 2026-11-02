from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import smoke  # noqa: E402
from app.server import serve  # noqa: E402

CHECKS = str(ROOT / "smoke" / "checks.json")


@pytest.fixture
def base_url() -> Iterator[str]:
    server = serve(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_the_example_checks_pass_against_the_example_app(
    base_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert smoke.main(["--base-url", base_url, "--checks", CHECKS]) == 0
    assert "| health | pass | 200 |" in capsys.readouterr().out


def test_a_wrong_answer_fails(base_url: str, tmp_path: Path) -> None:
    checks = tmp_path / "checks.json"
    checks.write_text(
        json.dumps(
            {
                "checks": [
                    {"name": "health", "path": "/healthz", "expect_json": {"status": "degraded"}},
                    {"name": "missing", "path": "/nope"},
                ]
            }
        )
    )
    results = [smoke.run_check(base_url, c) for c in smoke.load_checks(checks)]
    assert [r.ok for r in results] == [False, False]
    assert "status='ok', expected 'degraded'" in results[0].problem
    assert results[1].problem == "status 404, expected 200"


def test_a_slow_answer_fails(base_url: str) -> None:
    result = smoke.run_check(base_url, smoke.Check(name="health", path="/healthz", max_ms=-1))
    assert not result.ok
    assert "budget -1 ms" in result.problem


def test_a_dead_deploy_fails_rather_than_errors() -> None:
    result = smoke.run_check("http://127.0.0.1:9", smoke.Check(name="x", path="/"), timeout=1)
    assert not result.ok
    assert result.problem.startswith("could not connect")


def test_could_not_run_is_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMOKE_BASE_URL", raising=False)
    assert smoke.main(["--checks", CHECKS]) == 2
    (tmp_path / "empty.json").write_text('{"checks": []}')
    assert smoke.main(["--base-url", "http://x", "--checks", str(tmp_path / "empty.json")]) == 2
    assert smoke.main(["--base-url", "http://x", "--checks", str(tmp_path / "none.json")]) == 2


class _Bouncer(BaseHTTPRequestHandler):
    """Sends every page but the sign-in page to the sign-in page."""

    def do_GET(self) -> None:
        if self.path == "/sign-in":
            body = b"<!doctype html><title>Sign in</title>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(302)
            self.send_header("Location", "/sign-in")
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def bouncing_url() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Bouncer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_redirects_are_reported_not_followed(bouncing_url: str) -> None:
    # Followed, this would pass: the sign-in page has a <title> too.
    home = smoke.run_check(bouncing_url, smoke.Check(name="home", path="/", expect_text="<title>"))
    assert not home.ok
    assert home.status == 302
    assert "status 302 (redirect to /sign-in), expected 200" in home.problem
    # A redirect you expect is a check that can pass.
    bounce = smoke.run_check(bouncing_url, smoke.Check(name="bounce", path="/", expect_status=302))
    assert bounce.ok, bounce.problem


@pytest.mark.parametrize("url", ["app.example.com", "ftp://app.example.com", "http://", "https:/x"])
def test_a_base_url_that_is_not_http_could_not_run(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert smoke.main(["--base-url", url, "--checks", CHECKS]) == 2
    assert "could not run" in capsys.readouterr().err
