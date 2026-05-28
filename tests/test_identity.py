"""Tests for Identity analyzer."""
import json
from pathlib import Path

from analyzers.identity import IdentityAnalyzer

FIXTURES = Path(__file__).parent / "fixtures"


def _session_with_har(har: dict) -> list[dict]:
    return [{"har": har, "globals_snapshots": [], "console_log": []}]


def test_detects_eids_from_openrtb():
    har = json.loads((FIXTURES / "sample_har.json").read_text())
    sessions = _session_with_har(har)
    result = IdentityAnalyzer().analyze(sessions)

    assert result.raw["eid_count"] >= 3
    assert "sharedid" in result.raw["eids_observed"]
    assert "id5" in result.raw["eids_observed"]
    assert "uid2" in result.raw["eids_observed"]
    assert "liveramp" in result.raw["eids_observed"]


def test_detects_id5_from_script_url():
    har = {
        "log": {
            "entries": [{
                "request": {
                    "method": "GET",
                    "url": "https://id5-sync.com/api/id?lib=prebid",
                    "headers": [],
                    "postData": None,
                },
                "response": {"status": 200, "headers": [], "content": {"mimeType": "text/html", "size": 0, "text": ""}},
                "startedDateTime": "2026-05-27T10:00:00Z",
                "time": 30,
            }]
        }
    }
    sessions = _session_with_har(har)
    result = IdentityAnalyzer().analyze(sessions)
    assert "id5" in result.raw["eids_observed"]


def test_no_identity_zero_count():
    sessions = _session_with_har({"log": {"entries": []}})
    result = IdentityAnalyzer().analyze(sessions)
    assert result.raw["eid_count"] == 0
    assert result.raw["eids_observed"] == []
