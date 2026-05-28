"""GAM floor waterfall analyzer — detects CPM-floor-stepped ad unit paths."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

from analyzers.base import AnalyzerResult

_GAM_DOMAINS = {
    "pubads.g.doubleclick.net",
    "securepubads.g.doubleclick.net",
}

# Patterns tried in order; first match wins.
# Each is (compiled_regex, method_name, is_cents_candidate)
_TIER_PATTERNS: list[tuple[re.Pattern, str]] = [
    # dash-suffix decimal: /1234-8, /1234-1.5, /1234-0.5
    (re.compile(r"^(.+)-([0-9]+(?:\.[0-9]+)?)$"), "dash_suffix_decimal"),
    # underscore-suffix decimal: video_8, cpm_4
    (re.compile(r"^(.+)_([0-9]+(?:\.[0-9]+)?)$"), "underscore_suffix_decimal"),
    # explicit floor keyword anywhere: floor=8, floor_8, cpm-floor=4
    (re.compile(r"^(.*?)(?:floor|cpm)[=_-]([0-9]+(?:\.[0-9]+)?)"), "floor_keyword"),
]

_MAX_VALID_TIER = 100.0
_PREFIX_CONSOLIDATION_MAX_EXTRA_CHARS = 2  # merge bases that differ by ≤ N trailing chars


class GAMFloorWaterfallAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        # Aggregate (base_path, tier, detection_method, url) across all sessions
        base_tier_map: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "tiers": set(),
            "method": None,
            "request_count": 0,
            "example_urls": [],
        })
        total_gam = 0
        with_tier = 0

        for session in sessions:
            for entry in session.get("har", {}).get("log", {}).get("entries", []):
                req_url = entry.get("request", {}).get("url", "")
                try:
                    host = urlparse(req_url).hostname or ""
                except Exception:
                    continue

                if host not in _GAM_DOMAINS:
                    continue

                total_gam += 1
                qs = parse_qs(urlparse(req_url).query)
                iu_enc = qs.get("iu", [None])[0]
                if not iu_enc:
                    continue

                iu = unquote(iu_enc)
                last_segment = iu.rsplit("/", 1)[-1]
                prefix = iu.rsplit("/", 1)[0] if "/" in iu else ""

                tier, method = _extract_tier(last_segment)
                if tier is not None:
                    with_tier += 1
                    # Reconstruct canonical base path
                    base = _canonical_base(iu, last_segment, tier, method)
                    rec = base_tier_map[base]
                    rec["tiers"].add(tier)
                    rec["method"] = method
                    rec["request_count"] += 1
                    if len(rec["example_urls"]) < 3:
                        rec["example_urls"].append(req_url)

        # Prefix consolidation: merge bases where one is a prefix of another
        base_tier_map = _consolidate_prefixes(base_tier_map)

        # Build waterfall descriptors
        waterfalls = []
        for base, rec in sorted(base_tier_map.items()):
            tiers = sorted(rec["tiers"])
            tier_count = len(tiers)
            waterfall: dict[str, Any] = {
                "base_ad_unit": base,
                "tiers_observed": tiers,
                "tier_count": tier_count,
                "min_tier": min(tiers) if tiers else None,
                "max_tier": max(tiers) if tiers else None,
                "tier_ratio_max_to_min": round(max(tiers) / min(tiers), 1) if tiers and min(tiers) > 0 else None,
                "request_count": rec["request_count"],
                "tier_detection_method": rec["method"],
                "example_request_urls": rec["example_urls"],
            }
            if tier_count == 0:
                waterfall["_note"] = "No floor tier suffix detected for this base path"
            waterfalls.append(waterfall)

        # Score and classify
        valid_waterfalls = [w for w in waterfalls if w["tier_count"] >= 3]
        detected = len(valid_waterfalls) > 0
        strength = _strategy_strength(valid_waterfalls)
        their_score = _score(valid_waterfalls)

        return AnalyzerResult(
            analyzer="gam_floor_waterfall",
            raw={
                "floor_waterfall_detected": detected,
                "waterfall_count": len(valid_waterfalls),
                "waterfalls": waterfalls,
                "summary": {
                    "total_gam_requests": total_gam,
                    "requests_with_floor_tier": with_tier,
                    "requests_without_floor_tier": total_gam - with_tier,
                    "uses_floor_waterfall_strategy": detected,
                    "strategy_strength": strength,
                },
                "their_score": their_score,
            },
        )


def _extract_tier(last_segment: str) -> tuple[float | None, str | None]:
    for pattern, method in _TIER_PATTERNS:
        m = pattern.match(last_segment)
        if not m:
            continue

        raw = m.group(2)
        tier = _parse_tier(raw)
        if tier is None:
            continue
        return tier, method

    return None, None


def _parse_tier(raw: str) -> float | None:
    """Parse a raw tier string, handling cents-with-leading-zero convention."""
    try:
        # Cents heuristic: 3+ digits, starts with 0 (e.g. "0025" → 0.25)
        if re.match(r"^0[0-9]{2,}$", raw):
            value = float(raw) / 100.0
        else:
            value = float(raw)
    except ValueError:
        return None

    if value <= 0 or value > _MAX_VALID_TIER:
        return None
    return round(value, 4)


def _canonical_base(iu: str, last_segment: str, tier: float, method: str) -> str:
    """Reconstruct the base ad unit path after stripping the tier suffix."""
    if method == "dash_suffix_decimal":
        # Find the last dash before the tier
        raw_tier_str = str(tier) if "." not in str(tier) else str(tier)
        # Just strip the last -<tier_part>
        idx = iu.rfind("-")
        return iu[:idx] if idx != -1 else iu

    elif method == "underscore_suffix_decimal":
        idx = iu.rfind("_")
        return iu[:idx] if idx != -1 else iu

    elif method == "floor_keyword":
        m = re.search(r"(?:floor|cpm)[=_-][0-9]+(?:\.[0-9]+)?", iu)
        return iu[: m.start()].rstrip("-_=") if m else iu

    return iu


def _consolidate_prefixes(
    base_map: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge bases where one is a prefix of another (len diff ≤ threshold)."""
    bases = sorted(base_map.keys(), key=len)  # shortest first
    merged: dict[str, str] = {}  # longer_base → canonical_shorter_base

    for i, short in enumerate(bases):
        for long in bases[i + 1:]:
            if (
                long.startswith(short)
                and len(long) - len(short) <= _PREFIX_CONSOLIDATION_MAX_EXTRA_CHARS
            ):
                merged[long] = short

    if not merged:
        return base_map

    result: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "tiers": set(), "method": None, "request_count": 0, "example_urls": []
    })
    for base, rec in base_map.items():
        canonical = merged.get(base, base)
        result[canonical]["tiers"].update(rec["tiers"])
        result[canonical]["request_count"] += rec["request_count"]
        result[canonical]["method"] = result[canonical]["method"] or rec["method"]
        for url in rec["example_urls"]:
            if url not in result[canonical]["example_urls"] and len(result[canonical]["example_urls"]) < 3:
                result[canonical]["example_urls"].append(url)

    return dict(result)


def _strategy_strength(valid_waterfalls: list[dict]) -> str:
    if not valid_waterfalls:
        return "none"
    max_tiers = max(w["tier_count"] for w in valid_waterfalls)
    if max_tiers >= 3:
        if len(valid_waterfalls) == 1 and max_tiers <= 2:
            return "weak"
        if max_tiers >= 5:
            return "strong"
        if max_tiers >= 3:
            return "moderate"
    if len(valid_waterfalls) > 1:
        return "moderate"
    return "weak"


def _score(valid_waterfalls: list[dict]) -> int:
    if not valid_waterfalls:
        return 0
    max_tiers = max(w["tier_count"] for w in valid_waterfalls)
    best = max(valid_waterfalls, key=lambda w: w["tier_count"])
    ratio = best.get("tier_ratio_max_to_min") or 0

    if max_tiers >= 7 and ratio >= 16:
        return 10
    if max_tiers >= 7:
        return 9
    if max_tiers >= 5:
        return 7
    if max_tiers >= 3:
        return 5
    return 3
