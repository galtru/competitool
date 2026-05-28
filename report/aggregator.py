"""Session-level statistics aggregated across N sessions."""
from __future__ import annotations

import statistics
from typing import Any


def aggregate_session_stats(session_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute cross-session summary stats from raw artifacts."""
    bidder_response_counts: list[int] = []
    auction_counts: list[int] = []
    js_exception_counts: list[int] = []  # page JS errors, not our errors
    durations: list[float] = []

    bidder_appearances: dict[str, int] = {}

    for session in session_artifacts:
        responding: set[str] = set()
        auctions = 0

        for snap in session.get("globals_snapshots", []):
            for entry in snap.get("data", {}).get("probe_log", []):
                etype = entry.get("type", "")
                edata = entry.get("data") or {}

                if etype == "pbjs_event_bidResponse":
                    b = edata.get("bidderCode") or edata.get("bidder")
                    if b:
                        responding.add(b)
                        bidder_appearances[b] = bidder_appearances.get(b, 0) + 1

                elif etype == "pbjs_event_auctionInit":
                    auctions += 1

        bidder_response_counts.append(len(responding))
        auction_counts.append(auctions)
        js_exception_counts.append(len(session.get("errors", [])))
        d = session.get("duration_s")
        if d:
            durations.append(d)

    n = len(session_artifacts)

    def _pct(vals: list[int | float]) -> dict:
        if not vals:
            return {}
        return {
            "min": min(vals),
            "max": max(vals),
            "median": round(statistics.median(vals), 1),
            "mean": round(statistics.mean(vals), 1),
        }

    # Bidder consistency: fraction of sessions where each bidder responded
    bidder_consistency = {
        b: round(count / n, 2)
        for b, count in sorted(bidder_appearances.items(), key=lambda x: -x[1])
    }

    return {
        "session_count": n,
        "bidder_response_counts": _pct(bidder_response_counts),
        "auction_counts_per_session": _pct(auction_counts),
        "session_durations_s": _pct(durations),
        "bidder_consistency": bidder_consistency,
        "low_session_count_warning": n < 5,
        # Informational only — these are page-level JS exceptions from third-party scripts
        "page_js_exception_counts": _pct(js_exception_counts),
    }
