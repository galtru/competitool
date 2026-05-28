"""Tests for IMA analyzer."""
import json
from pathlib import Path

import pytest

from analyzers.ima import IMAAnalyzer

FIXTURES = Path(__file__).parent / "fixtures"


def _session_with_har(har: dict) -> list[dict]:
    return [{"har": har, "globals_snapshots": [], "console_log": []}]


def test_detects_hb_integration():
    har = json.loads((FIXTURES / "sample_har.json").read_text())
    sessions = _session_with_har(har)
    result = IMAAnalyzer().analyze(sessions)

    assert result.raw["present"] is True
    assert result.raw["header_bidding_integrated"] is True
    assert result.raw["gam_network_id"] == "12345"
    assert "hb_pb" in result.raw["cust_params_keys"]
    assert "hb_bidder" in result.raw["cust_params_keys"]


def test_detects_ad_pod():
    har = json.loads((FIXTURES / "sample_har.json").read_text())
    sessions = _session_with_har(har)
    result = IMAAnalyzer().analyze(sessions)

    assert result.raw["ad_pod_requested"] is True
    assert result.raw["pod_max_ads"] == 4
    assert result.raw["pod_max_duration_s"] == 120


def test_no_ima_returns_not_present():
    sessions = _session_with_har({"log": {"entries": []}})
    result = IMAAnalyzer().analyze(sessions)
    assert result.raw["present"] is False
    assert result.raw["header_bidding_integrated"] is False


def test_hb_pb_value_extracted():
    har = json.loads((FIXTURES / "sample_har.json").read_text())
    sessions = _session_with_har(har)
    result = IMAAnalyzer().analyze(sessions)
    assert "3.50" in result.raw["hb_pb_values"]
