"""Tests for GAM floor waterfall analyzer."""
import pytest
from analyzers.gam_floor_waterfall import GAMFloorWaterfallAnalyzer, _extract_tier, _parse_tier

# Euronews/Connatix-style iu= values
_EURONEWS_IUS = [
    "/107430338,6458/CNX_VIDEO/12345-8",
    "/107430338,6458/CNX_VIDEO/1234-4",
    "/107430338,6458/CNX_VIDEO/1234-2",
    "/107430338,6458/CNX_VIDEO/1234-1.5",
    "/107430338,6458/CNX_VIDEO/1234-1",
    "/107430338,6458/CNX_VIDEO/1234-0.5",
    "/107430338,6458/CNX_VIDEO/1234-0025",
    "/6458/connatix/news",  # no tier suffix
]


def _make_gam_url(iu: str) -> str:
    from urllib.parse import quote
    return f"https://pubads.g.doubleclick.net/gampad/ads?iu={quote(iu, safe='')}&sz=640x480"


def _session_from_ius(ius: list[str]) -> list[dict]:
    entries = [
        {
            "request": {"method": "GET", "url": _make_gam_url(iu), "headers": [], "postData": None},
            "response": {"status": 200, "headers": [], "content": {"mimeType": "text/xml", "size": 0, "text": ""}},
            "startedDateTime": "2026-05-27T10:00:00.000Z",
            "time": 150,
        }
        for iu in ius
    ]
    return [{"har": {"log": {"entries": entries}}, "globals_snapshots": [], "vast_responses": []}]


# --- tier parsing unit tests ---

def test_parse_tier_simple():
    assert _parse_tier("8") == 8.0
    assert _parse_tier("1.5") == 1.5
    assert _parse_tier("0.5") == 0.5

def test_parse_tier_cents_leading_zero():
    assert _parse_tier("0025") == 0.25
    assert _parse_tier("050") == 0.5
    assert _parse_tier("010") == 0.1

def test_parse_tier_discards_too_large():
    assert _parse_tier("150") is None
    assert _parse_tier("0") is None

def test_extract_tier_dash_decimal():
    tier, method = _extract_tier("1234-8")
    assert tier == 8.0
    assert method == "dash_suffix_decimal"

def test_extract_tier_dash_float():
    tier, method = _extract_tier("video-1.5")
    assert tier == 1.5

def test_extract_tier_underscore():
    tier, method = _extract_tier("video_4")
    assert tier == 4.0
    assert method == "underscore_suffix_decimal"

def test_extract_tier_no_match():
    tier, method = _extract_tier("connatix")
    assert tier is None
    assert method is None

def test_extract_tier_cents():
    tier, method = _extract_tier("1234-0025")
    assert tier == 0.25


# --- analyzer integration tests ---

def test_euronews_waterfall_detected():
    sessions = _session_from_ius(_EURONEWS_IUS)
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)

    assert result.raw["floor_waterfall_detected"] is True
    assert result.raw["summary"]["uses_floor_waterfall_strategy"] is True
    assert result.raw["summary"]["strategy_strength"] == "strong"


def test_euronews_base_path_and_tiers():
    sessions = _session_from_ius(_EURONEWS_IUS)
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)

    waterfalls = result.raw["waterfalls"]
    # Find the 1234-base waterfall (may be consolidated with 12345)
    cnx_wf = next(
        (w for w in waterfalls if "CNX_VIDEO/1234" in w["base_ad_unit"] and w["tier_count"] >= 3),
        None,
    )
    assert cnx_wf is not None, f"Expected CNX_VIDEO/1234 waterfall, got: {[w['base_ad_unit'] for w in waterfalls]}"
    assert 0.25 in cnx_wf["tiers_observed"]
    assert 4.0 in cnx_wf["tiers_observed"]
    assert cnx_wf["tier_count"] >= 6


def test_euronews_includes_tier_8_via_consolidation():
    """12345-8 should consolidate into the 1234 base."""
    sessions = _session_from_ius(_EURONEWS_IUS)
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)

    all_tiers = []
    for w in result.raw["waterfalls"]:
        if "CNX_VIDEO/1234" in w["base_ad_unit"]:
            all_tiers.extend(w["tiers_observed"])

    assert 8.0 in all_tiers, "Tier 8.0 from 12345-8 should consolidate into /1234 waterfall"


def test_euronews_score_is_high():
    sessions = _session_from_ius(_EURONEWS_IUS)
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)
    # 7 tiers with max/min = 8/0.25 = 32 ≥ 16 → score 10
    assert result.raw["their_score"] >= 9


def test_connatix_news_not_flagged():
    """Pure content path without tier suffix must not be a waterfall."""
    sessions = _session_from_ius(["/6458/connatix/news"])
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)
    assert result.raw["floor_waterfall_detected"] is False


def test_no_gam_requests_returns_not_detected():
    sessions = [{"har": {"log": {"entries": []}}, "globals_snapshots": [], "vast_responses": []}]
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)
    assert result.raw["floor_waterfall_detected"] is False
    assert result.raw["their_score"] == 0


def test_two_tier_not_a_waterfall():
    """Only 2 distinct tiers on a base should not trigger — needs 3+."""
    sessions = _session_from_ius([
        "/network/video-4",
        "/network/video-2",
    ])
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)
    assert result.raw["floor_waterfall_detected"] is False


def test_multi_session_aggregation():
    """Tiers seen across different sessions should aggregate into one waterfall."""
    s1 = _session_from_ius(["/net/vid-8", "/net/vid-4"])
    s2 = _session_from_ius(["/net/vid-2", "/net/vid-1", "/net/vid-0.5"])
    sessions = s1[0:1] + s2[0:1]
    sessions[0]["har"]["log"]["entries"] += sessions[1]["har"]["log"]["entries"]
    result = GAMFloorWaterfallAnalyzer().analyze([sessions[0]])
    wf = next((w for w in result.raw["waterfalls"] if w["tier_count"] >= 3), None)
    assert wf is not None


def test_tier_ratio_computed():
    sessions = _session_from_ius(_EURONEWS_IUS)
    result = GAMFloorWaterfallAnalyzer().analyze(sessions)
    best = max(result.raw["waterfalls"], key=lambda w: w["tier_count"])
    assert best["tier_ratio_max_to_min"] is not None
    assert best["tier_ratio_max_to_min"] >= 16
