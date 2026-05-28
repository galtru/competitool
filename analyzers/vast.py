"""VAST XML analyzer — wrapper depth, VPAID, skip, tracker count."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from analyzers.base import AnalyzerResult

_VAST_CONTENT_TYPES = {"text/xml", "application/xml", "text/plain"}


class VASTAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        all_chains: list[dict] = []

        for session in sessions:
            seen_urls: set[str] = set()

            # Prefer explicitly-captured VAST bodies (added by worker in Phase 2)
            for vast in session.get("vast_responses", []):
                url = vast.get("url", "")
                seen_urls.add(url)
                chain = _parse_vast_chain(vast.get("body", ""), url)
                if chain:
                    all_chains.append(chain)

            # Fallback: mine HAR response bodies (skip URLs already captured above)
            for entry in session.get("har", {}).get("log", {}).get("entries", []):
                content = entry.get("response", {}).get("content", {})
                mime = content.get("mimeType", "")
                body = content.get("text", "")
                url = entry.get("request", {}).get("url", "")

                if not body or url in seen_urls:
                    continue
                is_xml_mime = any(t in mime for t in _VAST_CONTENT_TYPES)
                if is_xml_mime and "<VAST" in body:
                    chain = _parse_vast_chain(body, url)
                    if chain:
                        all_chains.append(chain)

        if not all_chains:
            return AnalyzerResult(
                analyzer="vast",
                raw={"vast_found": False},
            )

        avg_depth = round(sum(c["wrapper_depth"] for c in all_chains) / len(all_chains), 1)
        max_depth = max(c["wrapper_depth"] for c in all_chains)
        vpaid = any(c["vpaid"] for c in all_chains)
        skippable = any(c["skippable"] for c in all_chains)
        avg_trackers = round(sum(c["tracker_count"] for c in all_chains) / len(all_chains), 1)
        durations = [c["creative_duration_s"] for c in all_chains if c["creative_duration_s"] is not None]

        return AnalyzerResult(
            analyzer="vast",
            raw={
                "vast_found": True,
                "chain_count": len(all_chains),
                "avg_wrapper_depth": avg_depth,
                "max_wrapper_depth": max_depth,
                "vpaid": vpaid,
                "skippable": skippable,
                "avg_tracker_count": avg_trackers,
                "avg_creative_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
                "per_chain": all_chains,
            },
        )


def _parse_vast_chain(body: str, url: str) -> dict | None:
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        return None

    # Normalise namespace away
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag != "VAST":
        return None

    wrapper_depth = 0
    vpaid = False
    skippable = False
    creative_duration_s = None
    tracker_count = 0
    advertiser_domain = None

    # Require at least one <Ad> element — skip empty no-fill VAST
    has_ad = any(
        (e.tag.split("}")[-1] if "}" in e.tag else e.tag) == "Ad"
        for e in root
    )
    if not has_ad:
        return None

    # Walk all elements
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if local == "VASTAdTagURI":
            wrapper_depth += 1

        elif local == "SkipOffset":
            skippable = True

        elif local == "Linear":
            # VAST 3+: skipoffset as attribute
            if elem.get("skipoffset"):
                skippable = True

        elif local == "MediaFile":
            api = elem.get("apiFramework", "").upper()
            mime = elem.get("type", "").lower()
            if api == "VPAID" or "shockwave" in mime or "javascript" in mime:
                vpaid = True

        elif local == "Duration":
            text = (elem.text or "").strip()
            creative_duration_s = _parse_duration(text)

        elif local in ("Impression", "Tracking", "ClickTracking", "Error"):
            if elem.text and elem.text.strip():
                tracker_count += 1

        elif local == "Advertiser":
            advertiser_domain = (elem.text or "").strip()

    return {
        "source_url": url,
        "wrapper_depth": wrapper_depth,
        "vpaid": vpaid,
        "skippable": skippable,
        "creative_duration_s": creative_duration_s,
        "tracker_count": tracker_count,
        "advertiser_domain": advertiser_domain,
    }


def _parse_duration(text: str) -> float | None:
    """Parse HH:MM:SS or SS into seconds."""
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 1:
            return float(text)
    except (ValueError, TypeError):
        pass
    return None
