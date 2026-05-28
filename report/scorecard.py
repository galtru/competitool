"""Scorecard builder — scores each factor 0–10 and assigns weights."""
from __future__ import annotations

from analyzers.base import AnalyzerResult


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> int:
    return max(0, min(10, round(value)))


def build_scorecard(
    prebid: AnalyzerResult,
    ima: AnalyzerResult,
    identity: AnalyzerResult,
    floor_waterfall: AnalyzerResult,
    contextual: AnalyzerResult,
) -> list[dict]:
    """Return list of yield gap driver dicts, sorted by weight desc."""
    drivers = []

    # 1. Prebid ↔ IMA integration (most important signal)
    hb_integrated = ima.raw.get("header_bidding_integrated", False)
    drivers.append({
        "factor": "prebid_to_ima_integration",
        "their_score": 10 if hb_integrated else 0,
        "your_score": 0,
        "weight": "very_high",
        "detail": "hb_pb/hb_bidder present in GAM cust_params" if hb_integrated
                  else "No Prebid keys in GAM ad request — demand NOT flowing through",
    })

    # 2. Identity richness
    eid_count = identity.raw.get("eid_count", 0)
    their_identity_score = _clamp(eid_count * 2.5)
    drivers.append({
        "factor": "identity_richness",
        "their_score": their_identity_score,
        "your_score": 2,
        "weight": "high",
        "detail": f"{eid_count} identity providers detected: {identity.raw.get('eids_observed', [])}",
    })

    # 3. Bidder count
    bidder_count = prebid.raw.get("bidder_count", 0)
    their_bidder_score = _clamp(bidder_count * 1.2)
    drivers.append({
        "factor": "bidder_count",
        "their_score": their_bidder_score,
        "your_score": 5,
        "weight": "high",
        "detail": f"{bidder_count} bidders detected: {prebid.raw.get('bidders', [])}",
    })

    # 4. GAM floor waterfall
    wf_score = floor_waterfall.raw.get("their_score", 0)
    wf_detected = floor_waterfall.raw.get("floor_waterfall_detected", False)
    wf_detail = _waterfall_detail(floor_waterfall)
    drivers.append({
        "factor": "gam_floor_waterfall",
        "their_score": wf_score,
        "your_score": 0,
        "weight": "high",
        "detail": wf_detail,
    })

    # 5. Contextual signal richness
    ctx_score = contextual.raw.get("richness_score", 0)
    ctx_keys = contextual.raw.get("total_cust_params_keys", 0)
    ctx_hv = contextual.raw.get("high_value_signal_count", 0)
    ctx_band = contextual.raw.get("richness_band", "none")
    drivers.append({
        "factor": "contextual_signal_richness",
        "their_score": ctx_score,
        "your_score": 4,  # rough baseline — our stack sends ~6 keys
        "weight": "high",
        "detail": f"{ctx_keys} cust_params keys, {ctx_hv} high-value ({ctx_band}). "
                  f"Categories: {contextual.raw.get('high_value_signal_categories_present', [])}",
    })

    # 6. Floor strategy (Prebid floors module)
    floors_active = prebid.raw.get("floors_module_loaded", False)
    drivers.append({
        "factor": "floor_strategy",
        "their_score": 8 if floors_active else 0,
        "your_score": 0,
        "weight": "medium",
        "detail": "Dynamic Prebid floors module active" if floors_active else "No Prebid floors module detected",
    })

    # 7. Ad pod / midroll
    pod = ima.raw.get("ad_pod_requested", False)
    drivers.append({
        "factor": "ad_pod_midroll",
        "their_score": 7 if pod else 0,
        "your_score": 0,
        "weight": "medium",
        "detail": f"Pod params: max_ads={ima.raw.get('pod_max_ads')}, max_duration={ima.raw.get('pod_max_duration_s')}s"
                  if pod else "No ad pod detected",
    })

    return drivers


def _waterfall_detail(floor_waterfall: AnalyzerResult) -> str:
    if not floor_waterfall.raw.get("floor_waterfall_detected"):
        return "No GAM floor waterfall detected — competitor uses static ad unit paths"
    best = max(
        floor_waterfall.raw.get("waterfalls", []),
        key=lambda w: w.get("tier_count", 0),
        default=None,
    )
    if not best or best.get("tier_count", 0) < 3:
        return "No significant floor waterfall detected"
    tiers = best.get("tiers_observed", [])
    return (
        f"{best['tier_count']}-tier floor waterfall on {best['base_ad_unit']} "
        f"(${min(tiers):.2f}–${max(tiers):.2f}). Your ad server uses static floors."
    )
