"""Tests for contextual signal analyzer."""
from urllib.parse import urlencode, quote
from analyzers.contextual_signal import ContextualSignalAnalyzer, _richness_score

# Euronews/Connatix observed cust_params
_EURONEWS_CUST_PARAMS = {
    "ABS": "51009287",
    "AnonymisedClientId": "MjI5MA==",
    "AnonymisedSignalLift": "0",
    "BSC": "87012038,84031001",
    "CMP_accepted": "1",
    "IDS": "0",
    "api_key": "1feb6d34",
    "article_id": "2639152332249831",
    "article_type": "normal",
    "commit": "8bd06ac9",
    "country": "IL",
    "device": "Desktop",
    "domains": "www.euronews.com",
    "geo": "IL",
    "isArticleBrandSafe": "null",
    "isBreakingNews": "false",
    "isSponsored": "false",
    "itr": "1",
    "lng": "en",
    "nws_id": "2896499",
    "nwsctr_id": "9771983",
    "od_ccd": "0",
    "od_pf_nr": "1",
    "od_pfs": "1",
    "odtag_status": "1",
    "order": "7",
    "page": "article",
    "program": "europe-news",
    "qt_loaded": "abs,bsc,ids",
    "source": "euronews",
    "source_id": "4688598004011344",
    "tags": "competitiveness,eu-policy",
    "technical_tags": "features.textToSpeech.disable",
    "themes": "europe-news",
    "unblockia": "0",
    "url": "https://www.euronews.com/article",
    "vertical": "my-europe",
    "video": "false",
    "words": "my,europe,2026",
}


def _make_gam_url_with_cust(params: dict) -> str:
    inner = urlencode(params)
    outer = urlencode({"iu": "/123/test", "cust_params": inner})
    return f"https://pubads.g.doubleclick.net/gampad/ads?{outer}"


def _session_with_cust(params: dict) -> list[dict]:
    url = _make_gam_url_with_cust(params)
    return [{
        "har": {"log": {"entries": [{
            "request": {"method": "GET", "url": url, "headers": [], "postData": None},
            "response": {"status": 200, "headers": [], "content": {"mimeType": "text/xml", "size": 0, "text": ""}},
            "startedDateTime": "2026-05-27T10:00:00.000Z",
            "time": 150,
        }]}},
        "globals_snapshots": [],
        "vast_responses": [],
    }]


# --- richness scoring unit tests ---

def test_richness_score_exceptional():
    score, band = _richness_score(21)
    assert score == 10
    assert band == "exceptional"

def test_richness_score_very_rich():
    score, band = _richness_score(17)
    assert score == 9
    assert band == "very_rich"

def test_richness_score_none():
    score, band = _richness_score(0)
    assert score == 0
    assert band == "none"


# --- analyzer integration tests ---

def test_euronews_total_key_count():
    sessions = _session_with_cust(_EURONEWS_CUST_PARAMS)
    result = ContextualSignalAnalyzer().analyze(sessions)
    assert result.raw["total_cust_params_keys"] >= 28


def test_euronews_brand_safety_detected():
    sessions = _session_with_cust(_EURONEWS_CUST_PARAMS)
    result = ContextualSignalAnalyzer().analyze(sessions)
    bs = result.raw["categories"].get("brand_safety", {})
    assert bs["count"] >= 2
    keys_lower = [k.upper() for k in bs["keys"]]
    assert "ABS" in keys_lower
    assert "BSC" in keys_lower


def test_euronews_content_identity_detected():
    sessions = _session_with_cust(_EURONEWS_CUST_PARAMS)
    result = ContextualSignalAnalyzer().analyze(sessions)
    ci = result.raw["categories"].get("content_identity", {})
    assert ci["count"] >= 4


def test_euronews_richness_band():
    sessions = _session_with_cust(_EURONEWS_CUST_PARAMS)
    result = ContextualSignalAnalyzer().analyze(sessions)
    assert result.raw["richness_band"] in ("very_rich", "exceptional")
    assert result.raw["richness_score"] >= 9


def test_empty_value_null_excluded_from_scoring():
    """isArticleBrandSafe=null should count as a key but not toward high-value score."""
    sessions = _session_with_cust({"isArticleBrandSafe": "null", "ABS": "123"})
    result = ContextualSignalAnalyzer().analyze(sessions)
    # ABS is present and non-null; isArticleBrandSafe is null → only 1 brand_safety key scores
    assert result.raw["keys_with_non_empty_values"] == 1


def test_minimal_params_low_richness():
    sessions = _session_with_cust({"pos": "1", "sz": "300x250"})
    result = ContextualSignalAnalyzer().analyze(sessions)
    assert result.raw["richness_band"] == "none"
    assert result.raw["richness_score"] == 0


def test_missing_brand_safety_flagged():
    """If brand_safety is absent, it should appear in missing_categories_of_note."""
    sessions = _session_with_cust({"article_id": "123", "vertical": "tech"})
    result = ContextualSignalAnalyzer().analyze(sessions)
    missing_cats = [m["category"] for m in result.raw["missing_categories_of_note"]]
    assert "brand_safety" in missing_cats


def test_technical_keys_not_in_high_value():
    """Technical keys should not contribute to high-value scoring."""
    sessions = _session_with_cust({
        "commit": "abc", "api_key": "xyz", "qt_loaded": "abs",
        "od_ccd": "0", "od_pf_nr": "1", "CMP_accepted": "1",
        "itr": "1", "technical_tags": "foo", "unblockia": "0",
    })
    result = ContextualSignalAnalyzer().analyze(sessions)
    assert result.raw["high_value_signal_count"] == 0
    assert result.raw["richness_band"] == "none"


def test_multi_request_key_aggregation():
    """Keys from multiple GAM requests in the same session should be merged."""
    url1 = _make_gam_url_with_cust({"article_id": "123", "vertical": "tech"})
    url2 = _make_gam_url_with_cust({"tags": "ai,ml", "ABS": "999"})
    sessions = [{
        "har": {"log": {"entries": [
            {"request": {"method": "GET", "url": url1, "headers": [], "postData": None},
             "response": {"status": 200, "headers": [], "content": {"mimeType": "text/xml", "size": 0}},
             "startedDateTime": "2026-05-27T10:00:00.000Z", "time": 100},
            {"request": {"method": "GET", "url": url2, "headers": [], "postData": None},
             "response": {"status": 200, "headers": [], "content": {"mimeType": "text/xml", "size": 0}},
             "startedDateTime": "2026-05-27T10:00:01.000Z", "time": 100},
        ]}},
        "globals_snapshots": [],
        "vast_responses": [],
    }]
    result = ContextualSignalAnalyzer().analyze(sessions)
    assert result.raw["total_cust_params_keys"] == 4
    assert "brand_safety" in result.raw["high_value_signal_categories_present"]
    assert "content_taxonomy" in result.raw["high_value_signal_categories_present"]
