"""Tests for timing analyzer."""
from analyzers.timing import TimingAnalyzer, _classify_orchestration


def _make_session(entries: list[dict], probe_log: list[dict] | None = None) -> dict:
    snaps = []
    if probe_log:
        snaps = [{"t": 5, "data": {"probe_log": probe_log}}]
    return {
        "url": "https://example.com/article",
        "session_index": 0,
        "har": {"log": {"entries": entries}},
        "globals_snapshots": snaps,
    }


def _entry(url: str, started: str, duration_ms: float = 100) -> dict:
    return {
        "request": {"method": "GET", "url": url, "headers": [], "postData": None},
        "response": {"status": 200, "headers": [], "content": {"mimeType": "text/html", "size": 0}},
        "startedDateTime": started,
        "time": duration_ms,
    }


def test_page_load_to_ad_request():
    entries = [
        _entry("https://example.com/article", "2026-05-27T10:00:00.000Z", 500),
        _entry("https://pubads.g.doubleclick.net/gampad/ads?iu=/123/vid", "2026-05-27T10:00:02.000Z", 150),
    ]
    session = _make_session(entries)
    result = TimingAnalyzer().analyze([session])

    assert result.raw["available"] is True
    assert result.raw["p50_page_load_to_first_ad_request_ms"] == 2000.0


def test_prebid_auction_duration_from_probe_log():
    entries = [
        _entry("https://example.com/article", "2026-05-27T10:00:00.000Z"),
    ]
    # Probe log timestamps in epoch ms
    t0 = 1748340000000  # arbitrary epoch ms
    probe_log = [
        {"type": "pbjs_event_auctionInit", "ts": t0, "data": {}},
        {"type": "pbjs_event_auctionEnd", "ts": t0 + 800, "data": {}},
    ]
    session = _make_session(entries, probe_log=probe_log)
    result = TimingAnalyzer().analyze([session])

    assert result.raw["p50_prebid_auction_duration_ms"] == 800.0


def test_orchestration_sequential_hb():
    # Bidder fires at T+500ms, GAM fires at T+1400ms (after auction ends ~T+1200ms)
    t0_ms = 1748340000000
    result = _classify_orchestration(
        first_bidder_ts=500,
        first_gam_ts=1400,
        auction_end_ts=t0_ms + 1200 if False else 1200,  # same scale
    )
    assert result == "sequential_hb"


def test_orchestration_parallel_no_hb():
    result = _classify_orchestration(
        first_bidder_ts=500,
        first_gam_ts=550,
        auction_end_ts=None,
    )
    assert result == "parallel_no_hb"


def test_no_har_entries_returns_unavailable():
    session = _make_session([])
    result = TimingAnalyzer().analyze([session])
    assert result.raw["available"] is False


def test_multi_session_median():
    def _session_with_gap(gap_ms: float) -> dict:
        return _make_session([
            _entry("https://example.com/article", "2026-05-27T10:00:00.000Z"),
            _entry(
                "https://pubads.g.doubleclick.net/gampad/ads",
                f"2026-05-27T10:00:{gap_ms/1000:06.3f}Z".replace(":", ":", 2),
            ),
        ])

    # Build sessions with known page-load-to-ad gaps of 1000, 2000, 3000ms
    sessions = [
        _make_session([
            _entry("https://example.com/article", "2026-05-27T10:00:00.000Z"),
            _entry("https://pubads.g.doubleclick.net/gampad/ads", "2026-05-27T10:00:01.000Z"),
        ]),
        _make_session([
            _entry("https://example.com/article", "2026-05-27T10:00:00.000Z"),
            _entry("https://pubads.g.doubleclick.net/gampad/ads", "2026-05-27T10:00:02.000Z"),
        ]),
        _make_session([
            _entry("https://example.com/article", "2026-05-27T10:00:00.000Z"),
            _entry("https://pubads.g.doubleclick.net/gampad/ads", "2026-05-27T10:00:03.000Z"),
        ]),
    ]
    result = TimingAnalyzer().analyze(sessions)
    assert result.raw["p50_page_load_to_first_ad_request_ms"] == 2000.0
