"""Timing analyzer — latencies and parallel-vs-waterfall orchestration heuristic."""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from analyzers.base import AnalyzerResult

_GAM_DOMAINS = {
    "pubads.g.doubleclick.net",
    "securepubads.g.doubleclick.net",
    "googleads.g.doubleclick.net",
}

_BIDDER_PATH_HINTS = {
    "adnxs.com", "rubiconproject.com", "openx.net", "pubmatic.com",
    "indexexchange.com", "criteo.com", "media.net", "sovrn.com",
    "sharethrough.com", "triplelift.com",
}


class TimingAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        per_session: list[dict] = []

        for session in sessions:
            t = _analyze_session_timing(session)
            if t:
                per_session.append(t)

        if not per_session:
            return AnalyzerResult(analyzer="timing", raw={"available": False})

        def _median(key: str) -> float | None:
            vals = [s[key] for s in per_session if s.get(key) is not None]
            return round(statistics.median(vals), 1) if vals else None

        modes = [s["parallel_or_waterfall"] for s in per_session if s.get("parallel_or_waterfall")]
        dominant_mode = max(set(modes), key=modes.count) if modes else "unknown"

        return AnalyzerResult(
            analyzer="timing",
            raw={
                "available": True,
                "p50_page_load_to_first_ad_request_ms": _median("page_load_to_first_ad_request_ms"),
                "p50_first_ad_request_to_response_ms": _median("first_ad_request_to_response_ms"),
                "p50_prebid_auction_duration_ms": _median("prebid_auction_duration_ms"),
                "orchestration_mode": dominant_mode,
                "orchestration_mode_counts": {m: modes.count(m) for m in set(modes)},
                "per_session": per_session,
            },
        )


def _analyze_session_timing(session: dict[str, Any]) -> dict | None:
    har = session.get("har", {})
    entries = har.get("log", {}).get("entries", [])
    if not entries:
        return None

    nav_ts = _nav_start_ts(entries, session.get("url", ""))
    if nav_ts is None:
        return None

    first_bidder_ts = None
    first_gam_ts = None
    first_gam_end_ts = None

    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        ts = _entry_ts(entry)
        duration = entry.get("time", 0)
        if ts is None:
            continue

        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""

        if any(d in host for d in _GAM_DOMAINS):
            if first_gam_ts is None:
                first_gam_ts = ts
                first_gam_end_ts = ts + duration

        if any(d in host for d in _BIDDER_PATH_HINTS):
            if first_bidder_ts is None:
                first_bidder_ts = ts

    # Get auction timing from probe log
    auction_init_ts = None
    auction_end_ts = None
    for snap in session.get("globals_snapshots", []):
        for entry in snap.get("data", {}).get("probe_log", []):
            etype = entry.get("type", "")
            ets = entry.get("ts")  # epoch ms from Date.now()
            if etype == "pbjs_event_auctionInit" and auction_init_ts is None:
                auction_init_ts = ets
            elif etype == "pbjs_event_auctionEnd" and auction_end_ts is None:
                auction_end_ts = ets

    result: dict[str, Any] = {"session_index": session.get("session_index", 0)}

    if first_gam_ts is not None:
        result["page_load_to_first_ad_request_ms"] = round(first_gam_ts - nav_ts, 1)

    if first_gam_ts is not None and first_gam_end_ts is not None:
        # Response time = duration of the GAM request itself
        result["first_ad_request_to_response_ms"] = round(first_gam_end_ts - first_gam_ts, 1)

    if auction_init_ts and auction_end_ts:
        result["prebid_auction_duration_ms"] = round(auction_end_ts - auction_init_ts, 1)

    # Orchestration heuristic
    result["parallel_or_waterfall"] = _classify_orchestration(
        first_bidder_ts=first_bidder_ts,
        first_gam_ts=first_gam_ts,
        auction_end_ts=_ms_to_ts(auction_end_ts) if auction_end_ts else None,
    )

    return result


def _nav_start_ts(entries: list[dict], page_url: str) -> float | None:
    """Return epoch-ms of the first navigation request."""
    try:
        page_host = urlparse(page_url).hostname or ""
    except Exception:
        page_host = ""

    for entry in entries:
        url = entry.get("request", {}).get("url", "")
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            continue
        if page_host and host == page_host:
            return _entry_ts(entry)

    # Fallback: first entry
    for entry in entries:
        ts = _entry_ts(entry)
        if ts is not None:
            return ts
    return None


def _entry_ts(entry: dict) -> float | None:
    """Return epoch-ms from HAR startedDateTime."""
    started = entry.get("startedDateTime", "")
    if not started:
        return None
    try:
        dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return None


def _ms_to_ts(epoch_ms: float) -> float:
    return epoch_ms  # already epoch ms


def _classify_orchestration(
    first_bidder_ts: float | None,
    first_gam_ts: float | None,
    auction_end_ts: float | None,
) -> str:
    if first_gam_ts is None:
        return "unknown"

    if first_bidder_ts is None:
        return "direct_gam"  # no Prebid bidder requests seen

    gap = first_gam_ts - first_bidder_ts

    if abs(gap) < 100:
        # GAM fires at same time as bidders → no header bidding, waterfall
        return "parallel_no_hb"

    if auction_end_ts is not None:
        # Convert auction_end to same scale as HAR timestamps
        # HAR ts are in epoch ms, probe_log ts are also epoch ms (Date.now())
        if first_gam_ts >= auction_end_ts - 200:
            return "sequential_hb"  # correct: wait for bids then call GAM

    if gap > 1000:
        return "waterfall"  # GAM fires long after bidders → bid timeout then fallback

    return "unknown"
