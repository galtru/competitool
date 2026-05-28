"""Contextual signal analyzer — quantifies first-party signal density in cust_params."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

import yaml

from analyzers.base import AnalyzerResult

_TAXONOMY_PATH = Path(__file__).parent / "contextual_taxonomy.yaml"

_HIGH_VALUE_CATEGORIES = {
    "content_identity",
    "content_taxonomy",
    "content_attributes",
    "brand_safety",
    "audience_signal",
}

_NOTABLE_MISSING: dict[str, str] = {
    "brand_safety": "Premium buyers require brand safety scores — absence likely suppresses bid prices",
    "content_taxonomy": "Content categorization is a major buyer targeting signal",
    "content_identity": "Without content IDs, buyers cannot frequency-cap or retarget at content level",
}

_RICHNESS_BANDS = [
    (20, 10, "exceptional"),
    (15, 9, "very_rich"),
    (10, 7, "rich"),
    (6, 5, "moderate"),
    (3, 3, "minimal"),
    (0, 0, "none"),
]

_GAM_DOMAINS = {
    "pubads.g.doubleclick.net",
    "securepubads.g.doubleclick.net",
}


def _load_taxonomy() -> dict[str, dict[str, list[str]]]:
    with open(_TAXONOMY_PATH) as f:
        return yaml.safe_load(f)


class ContextualSignalAnalyzer:
    def __init__(self) -> None:
        self._taxonomy = _load_taxonomy()
        self._exact_lookup: dict[str, str] = {}   # lowercase key → category
        self._prefix_rules: list[tuple[str, str]] = []  # (prefix, category)
        self._suffix_rules: list[tuple[str, str]] = []  # (suffix, category)
        self._build_lookup()

    def _build_lookup(self) -> None:
        for category, rules in self._taxonomy.items():
            for key in rules.get("exact", []):
                self._exact_lookup[key.lower()] = category
            for prefix in rules.get("prefix_patterns", []):
                self._prefix_rules.append((prefix.lower(), category))
            for suffix in rules.get("suffix_patterns", []):
                self._suffix_rules.append((suffix.lower(), category))

    def classify(self, key: str) -> str:
        lk = key.lower()
        if lk in self._exact_lookup:
            return self._exact_lookup[lk]
        for prefix, cat in self._prefix_rules:
            if lk.startswith(prefix):
                return cat
        for suffix, cat in self._suffix_rules:
            if lk.endswith(suffix):
                return cat
        return "other"

    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        # Aggregate all cust_params keys across all GAM requests, all sessions
        all_keys: dict[str, list[str]] = {}  # original_key → list of non-empty values

        for session in sessions:
            for entry in session.get("har", {}).get("log", {}).get("entries", []):
                url = entry.get("request", {}).get("url", "")
                try:
                    host = urlparse(url).hostname or ""
                except Exception:
                    continue

                if host not in _GAM_DOMAINS:
                    continue

                qs = parse_qs(urlparse(url).query)
                cust_raw = qs.get("cust_params", [None])[0]
                if not cust_raw:
                    continue

                # Double URL-decode
                inner = parse_qs(unquote(unquote(cust_raw)))
                for k, vals in inner.items():
                    if k not in all_keys:
                        all_keys[k] = []
                    for v in vals:
                        if v and v.lower() not in ("null", "undefined", "none", ""):
                            if v not in all_keys[k]:
                                all_keys[k].append(v)

        total_keys = len(all_keys)
        keys_with_values = sum(1 for vs in all_keys.values() if vs)

        # Classify each key
        categories: dict[str, dict[str, Any]] = {cat: {"count": 0, "keys": []} for cat in self._taxonomy}
        categories["other"] = {"count": 0, "keys": []}

        for key, values in all_keys.items():
            cat = self.classify(key)
            if cat not in categories:
                categories[cat] = {"count": 0, "keys": []}
            categories[cat]["count"] += 1
            categories[cat]["keys"].append(key)

        # Score: count non-empty keys in high-value categories only
        high_value_count = sum(
            sum(1 for k in categories[cat]["keys"] if all_keys[k])
            for cat in _HIGH_VALUE_CATEGORIES
            if cat in categories
        )

        score, band = _richness_score(high_value_count)

        # Missing high-value categories
        missing = []
        for cat, note in _NOTABLE_MISSING.items():
            if categories.get(cat, {}).get("count", 0) == 0:
                missing.append({"category": cat, "note": note})

        present_hv = [
            cat for cat in _HIGH_VALUE_CATEGORIES
            if categories.get(cat, {}).get("count", 0) > 0
        ]

        return AnalyzerResult(
            analyzer="contextual_signal",
            raw={
                "total_cust_params_keys": total_keys,
                "keys_with_non_empty_values": keys_with_values,
                "categories": categories,
                "richness_score": score,
                "richness_band": band,
                "high_value_signal_count": high_value_count,
                "high_value_signal_categories_present": sorted(present_hv),
                "missing_categories_of_note": missing,
            },
        )


def _richness_score(count: int) -> tuple[int, str]:
    for threshold, score, band in _RICHNESS_BANDS:
        if count >= threshold:
            return score, band
    return 0, "none"
