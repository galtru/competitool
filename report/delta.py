"""Delta engine — diffs competitor stack against our_stack.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from analyzers.base import AnalyzerResult

_OUR_STACK_PATH = Path(__file__).parent.parent / "our_stack.yaml"


def _load_our_stack() -> dict[str, Any]:
    with open(_OUR_STACK_PATH) as f:
        return yaml.safe_load(f)


def build_delta(
    prebid: AnalyzerResult,
    ima: AnalyzerResult,
    identity: AnalyzerResult,
) -> dict[str, Any]:
    our = _load_our_stack()

    our_bidders = set(our.get("prebid", {}).get("bidders", []))
    their_bidders = set(prebid.raw.get("bidders", []))
    missing_bidders = sorted(their_bidders - our_bidders)

    our_eids = set(our.get("identity", {}).get("eids", []))
    their_eids = set(identity.raw.get("eids_observed", []))
    missing_identity = sorted(their_eids - our_eids)

    hb_integrated = ima.raw.get("header_bidding_integrated", False)
    our_hb = our.get("ima", {}).get("header_bidding_integrated", False)

    hb_status = "INTEGRATED" if hb_integrated else "NOT_INTEGRATED"
    if hb_integrated and not our_hb:
        hb_note = "Competitor has it; we don't — likely largest single gap"
    elif not hb_integrated and not our_hb:
        hb_note = "Neither side sends hb_pb keys to GAM — both use direct ad calls or a wrapped player (e.g. Connatix, JW, Brightcove managed ads)"
    elif not hb_integrated and our_hb:
        hb_note = "We have it; competitor doesn't"
    else:
        hb_note = "Both integrated"

    # Build prioritized actions
    actions: list[str] = []
    rank = 1

    if hb_integrated and not our_hb:
        actions.append(
            f"{rank}. Wire Prebid → IMA via cust_params (hb_pb, hb_bidder, hb_size, hb_uuid). "
            "Estimated 30–60% eCPM lift."
        )
        rank += 1

    if missing_identity:
        actions.append(
            f"{rank}. Add identity modules: {', '.join(missing_identity[:5])}. "
            "Estimated 15–30% eCPM lift."
        )
        rank += 1

    if missing_bidders:
        actions.append(
            f"{rank}. Add missing demand partners: {', '.join(missing_bidders[:8])}."
        )
        rank += 1

    if prebid.raw.get("floors_module_loaded") and not our.get("floors", {}).get("active"):
        actions.append(
            f"{rank}. Enable Prebid floors module with dynamic floors endpoint."
        )
        rank += 1

    if ima.raw.get("ad_pod_requested") and not our.get("pod", {}).get("midroll"):
        actions.append(
            f"{rank}. Enable ad pods and mid-roll breaks (competitor uses them)."
        )
        rank += 1

    if not actions:
        actions.append("No significant gaps detected — stacks appear comparable.")

    return {
        "missing_bidders": missing_bidders,
        "missing_identity": missing_identity,
        "header_bidding_to_ima": f"{hb_status} — {hb_note}",
        "prioritized_actions": actions,
    }
