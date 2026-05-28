"""Tests for Prebid analyzer."""
import json
from pathlib import Path

import pytest

from analyzers.prebid import PrebidAnalyzer

FIXTURES = Path(__file__).parent / "fixtures"


def _session_with_har(har: dict, probe_log: list | None = None) -> dict:
    snaps = []
    if probe_log is not None:
        snaps = [{"t": 5, "data": {"probe_log": probe_log}}]
    return {"har": har, "globals_snapshots": snaps, "console_log": []}


def test_detects_bidder_from_har():
    har = json.loads((FIXTURES / "sample_har.json").read_text())
    sessions = [_session_with_har(har)]
    result = PrebidAnalyzer().analyze(sessions)

    assert result.raw["present"] is True
    assert "appnexus" in result.raw["bidders"]


def test_detects_bidder_from_probe_log():
    probe_log = [
        {"type": "pbjs_loaded", "ts": 1000, "data": {"version": "8.25.0"}},
        {"type": "pbjs_event_bidResponse", "ts": 1200, "data": {"bidderCode": "rubicon", "cpm": 2.5}},
        {"type": "pbjs_event_auctionInit", "ts": 1100, "data": {
            "bidderRequests": [
                {"bidderCode": "rubicon"},
                {"bidderCode": "pubmatic"},
            ]
        }},
    ]
    sessions = [_session_with_har({"log": {"entries": []}}, probe_log=probe_log)]
    result = PrebidAnalyzer().analyze(sessions)

    assert result.raw["version"] == "8.25.0"
    assert "rubicon" in result.raw["bidders"]
    assert "pubmatic" in result.raw["bidders"]


def test_floors_detected():
    probe_log = [
        {"type": "pbjs_config", "ts": 1000, "data": {
            "bidderTimeout": 2000,
            "floors": {"enforcement": {"enforceJS": True}},
        }},
    ]
    sessions = [_session_with_har({"log": {"entries": []}}, probe_log=probe_log)]
    result = PrebidAnalyzer().analyze(sessions)

    assert result.raw["floors_module_loaded"] is True
    assert result.raw["timeout_ms"] == 2000


def test_empty_sessions_returns_not_present():
    sessions = [_session_with_har({"log": {"entries": []}})]
    result = PrebidAnalyzer().analyze(sessions)
    assert result.raw["present"] is False
