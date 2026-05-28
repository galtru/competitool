"""Tests for VAST analyzer."""
from pathlib import Path

from analyzers.vast import VASTAnalyzer, _parse_vast_chain, _parse_duration

FIXTURES = Path(__file__).parent / "fixtures"


def _session_with_vast(bodies: list[str]) -> list[dict]:
    return [{
        "har": {"log": {"entries": []}},
        "globals_snapshots": [],
        "vast_responses": [{"url": f"https://ads.example.com/vast{i}", "body": b}
                           for i, b in enumerate(bodies)],
    }]


def test_inline_no_wrapper():
    body = (FIXTURES / "sample_vast_inline.xml").read_text()
    result = VASTAnalyzer().analyze(_session_with_vast([body]))

    assert result.raw["vast_found"] is True
    assert result.raw["avg_wrapper_depth"] == 0
    assert result.raw["skippable"] is True
    assert result.raw["vpaid"] is False
    assert result.raw["avg_creative_duration_s"] == 30.0


def test_wrapper_depth_counted():
    body = (FIXTURES / "sample_vast_wrapper.xml").read_text()
    result = VASTAnalyzer().analyze(_session_with_vast([body]))

    assert result.raw["vast_found"] is True
    assert result.raw["avg_wrapper_depth"] == 1


def test_tracker_count():
    body = (FIXTURES / "sample_vast_inline.xml").read_text()
    chain = _parse_vast_chain(body, "https://test.com/vast")
    # 1 Impression + 3 Tracking events = 4
    assert chain["tracker_count"] == 4


def test_no_vast_empty_sessions():
    result = VASTAnalyzer().analyze([{
        "har": {"log": {"entries": []}},
        "globals_snapshots": [],
        "vast_responses": [],
    }])
    assert result.raw["vast_found"] is False


def test_parse_duration_hhmmss():
    assert _parse_duration("00:00:30") == 30.0
    assert _parse_duration("00:01:30") == 90.0


def test_parse_duration_invalid():
    assert _parse_duration("") is None
    assert _parse_duration("garbage") is None


def test_vast_in_har_response_body():
    body = (FIXTURES / "sample_vast_inline.xml").read_text()
    session = [{
        "har": {"log": {"entries": [{
            "request": {"method": "GET", "url": "https://ads.example.com/vast", "headers": [], "postData": None},
            "response": {
                "status": 200,
                "headers": [],
                "content": {"mimeType": "text/xml", "size": len(body), "text": body},
            },
            "startedDateTime": "2026-05-27T10:00:00.000Z",
            "time": 100,
        }]}},
        "globals_snapshots": [],
        "vast_responses": [],
    }]
    result = VASTAnalyzer().analyze(session)
    assert result.raw["vast_found"] is True
