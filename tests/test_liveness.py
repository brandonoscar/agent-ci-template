from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import liveness

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_parse_max_age() -> None:
    assert liveness.parse_max_age("a.yml=8d, b.yml=12h") == {
        "a.yml": timedelta(days=8),
        "b.yml": timedelta(hours=12),
    }
    for bad in ("a.yml=8", "a.yml=xd", "=8d", ""):
        with pytest.raises(ValueError, match=r"max-age entry|no workflows"):
            liveness.parse_max_age(bad)


def test_overdue_and_never_ran_are_findings() -> None:
    last = {
        "fresh.yml": "2026-11-02T06:00:00Z",
        "stale.yml": "2026-10-20T06:00:00Z",
        "never.yml": None,
    }
    ages = liveness.parse_max_age("fresh.yml=1d,stale.yml=8d,never.yml=2d,missing.yml=1d")
    findings = {f.workflow: f.reason for f in liveness.find_overdue(last, ages, NOW)}
    assert findings == {
        "stale.yml": "last success 318h ago, allowed 8d",
        "never.yml": "no successful scheduled run on record",
        "missing.yml": "no successful scheduled run on record",
    }


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps({"a.yml": "2026-11-02T11:00:00Z"}))
    now = NOW.isoformat()
    assert liveness.main(["--last-runs", str(runs), "--max-age", "a.yml=1d", "--now", now]) == 0
    assert liveness.main(["--last-runs", str(runs), "--max-age", "a.yml=0h", "--now", now]) == 1
    assert "**a.yml**" in capsys.readouterr().out
    assert liveness.main(["--last-runs", str(tmp_path / "x"), "--max-age", "a.yml=1d"]) == 2
    assert liveness.main(["--last-runs", str(runs), "--max-age", "nonsense"]) == 2


def test_a_workflow_whose_runs_could_not_be_read_is_a_finding_not_fresh() -> None:
    # A typo in LIVENESS_MAX_AGE, or an API error, must not read as "never ran"
    # or, worse, as fresh.
    last = {
        "typo.yml": {"error": "HTTP 404: workflow typo.yml not found on the default branch"},
        "garbled.yml": "yesterday-ish",
        "naive.yml": "2026-11-02T11:00:00",
    }
    ages = liveness.parse_max_age("typo.yml=1d,garbled.yml=1d,naive.yml=1d")
    findings = {f.workflow: f.reason for f in liveness.find_overdue(last, ages, NOW)}
    assert findings == {
        "typo.yml": "could not read its runs: HTTP 404: workflow typo.yml not found on the "
        "default branch",
        "garbled.yml": "could not read its runs: bad time 'yesterday-ish'",
    }


def test_last_runs_that_is_not_an_object_could_not_run(tmp_path: Path) -> None:
    runs = tmp_path / "runs.json"
    runs.write_text("[]")
    assert liveness.main(["--last-runs", str(runs), "--max-age", "a.yml=1d"]) == 2
