"""Report renderer — assembles the final JSON report."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from analyzers.base import AnalyzerResult


def render_report(
    job_id: str,
    url: str,
    session_count: int,
    prebid: AnalyzerResult,
    ima: AnalyzerResult,
    identity: AnalyzerResult,
    vast: AnalyzerResult,
    timing: AnalyzerResult,
    floor_waterfall: AnalyzerResult,
    contextual: AnalyzerResult,
    session_stats: dict[str, Any],
    scorecard: list[dict],
    delta: dict[str, Any],
    artifact_store,
) -> dict[str, Any]:
    har_paths = [artifact_store.har_path(job_id, i) for i in range(session_count)]
    console_paths = [artifact_store.console_path(job_id, i) for i in range(session_count)]

    return {
        "id": job_id,
        "target": url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "session_count": session_count,
        "session_stats": session_stats,
        "summary": {
            "estimated_yield_gap_drivers": scorecard,
        },
        "demand_stack": {
            "prebid": prebid.raw,
            "ima": ima.raw,
        },
        "identity": identity.raw,
        "orchestration": timing.raw,
        "creative": vast.raw,
        "floor_waterfall": floor_waterfall.raw,
        "contextual_signal": contextual.raw,
        "pod_strategy": {
            "pod_used": ima.raw.get("ad_pod_requested", False),
            "max_ads_per_pod": ima.raw.get("pod_max_ads"),
            "max_pod_duration_s": ima.raw.get("pod_max_duration_s"),
        },
        "floors": {
            "floors_module_active": prebid.raw.get("floors_module_loaded", False),
        },
        "your_implementation_delta": delta,
        "raw_artifacts": {
            "har_paths": har_paths,
            "console_paths": console_paths,
            "screenshots": [],
        },
    }
