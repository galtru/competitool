"""Identity analyzer — detects EIDs and identity providers."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from analyzers.base import AnalyzerResult

_IDENTITY_PATTERNS = {
    "uid2": {
        "url_patterns": ["uid2.com", "uid2-sdk", "unified-id"],
        "globals": ["__uid2"],
        "eid_source": ["uidapi.com", "uid2"],
    },
    "id5": {
        "url_patterns": ["id5-sync.com", "id5.io"],
        "globals": ["ID5", "__id5"],
        "eid_source": ["id5-sync.com", "id5"],
    },
    "liveramp": {
        "url_patterns": ["launchpad-wrapper.liveramp.com", "liveramp.com", "ats.js"],
        "globals": ["LiveRampATSEmail", "idl_env"],
        "eid_source": ["liveramp.com", "identitylink"],
    },
    "sharedid": {
        "url_patterns": ["pubcid.org", "sharedid"],
        "globals": ["pubcid"],
        "eid_source": ["pubcid.org", "sharedid"],
    },
    "connectid": {
        "url_patterns": ["connectid.yahoo.com", "yahoo.com/adtech"],
        "globals": [],
        "eid_source": ["yahoo.com", "connectid"],
    },
    "criteo": {
        "url_patterns": ["criteo.com/userid", "gum.criteo.com"],
        "globals": [],
        "eid_source": ["criteo.com"],
    },
    "pubprovided": {
        "url_patterns": [],
        "globals": [],
        "eid_source": ["pubProvidedId", "firstparty"],
    },
    "topics_api": {
        "url_patterns": [],
        "globals": [],
        "script_patterns": ["browsingTopics"],
    },
}


class IdentityAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        detected: dict[str, set[str]] = {}  # provider -> set of detection signals
        eids_per_bidder: dict[str, set[str]] = {}

        for session in sessions:
            # Check network for identity script loads
            har = session.get("har", {})
            for entry in har.get("log", {}).get("entries", []):
                url = entry.get("request", {}).get("url", "")
                host = ""
                try:
                    host = urlparse(url).hostname or ""
                except Exception:
                    pass

                for provider, config in _IDENTITY_PATTERNS.items():
                    for pattern in config.get("url_patterns", []):
                        if pattern in url or pattern in host:
                            detected.setdefault(provider, set()).add(f"script:{pattern}")

                # Look for EIDs in OpenRTB bid request bodies
                post_data = entry.get("request", {}).get("postData", {})
                body = post_data.get("text", "") if post_data else ""
                if body and ("eids" in body or "uids" in body):
                    try:
                        data = json.loads(body)
                        _extract_eids(data, provider=None, detected=detected, eids_per_bidder=eids_per_bidder, url=url)
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Check JS globals from probe log
            for snap in session.get("globals_snapshots", []):
                probe_log = snap.get("data", {}).get("probe_log", [])
                for entry in probe_log:
                    if entry.get("type") == "identity_globals":
                        globals_found = entry.get("data", {})
                        for provider, config in _IDENTITY_PATTERNS.items():
                            for g in config.get("globals", []):
                                if g in globals_found:
                                    detected.setdefault(provider, set()).add(f"global:{g}")

        eids_observed = sorted(detected.keys())

        # Build bidder EID coverage
        bidder_coverage = {}
        for bidder, eids in eids_per_bidder.items():
            bidder_coverage[bidder] = sorted(eids)

        return AnalyzerResult(
            analyzer="identity",
            raw={
                "eids_observed": eids_observed,
                "eid_count": len(eids_observed),
                "provider_signals": {k: sorted(v) for k, v in detected.items()},
                "eids_per_bidder": bidder_coverage,
                "bidders_receiving_eids_pct": _compute_eid_coverage(bidder_coverage),
            },
        )


def _extract_eids(
    data: Any,
    provider: str | None,
    detected: dict[str, set[str]],
    eids_per_bidder: dict[str, set[str]],
    url: str,
) -> None:
    """Recursively search for EID arrays in OpenRTB data."""
    if isinstance(data, dict):
        eids = data.get("eids") or data.get("uids")
        bidder = data.get("bidder") or data.get("bidderCode")

        if isinstance(eids, list):
            for eid in eids:
                source = eid.get("source", "") if isinstance(eid, dict) else ""
                for pname, config in _IDENTITY_PATTERNS.items():
                    for pattern in config.get("eid_source", []):
                        if pattern.lower() in source.lower():
                            detected.setdefault(pname, set()).add(f"eid:{source}")
                            if bidder:
                                eids_per_bidder.setdefault(bidder, set()).add(pname)

        for v in data.values():
            _extract_eids(v, provider, detected, eids_per_bidder, url)

    elif isinstance(data, list):
        for item in data:
            _extract_eids(item, provider, detected, eids_per_bidder, url)


def _compute_eid_coverage(eids_per_bidder: dict[str, list[str]]) -> float:
    if not eids_per_bidder:
        return 0.0
    with_eids = sum(1 for eids in eids_per_bidder.values() if eids)
    return round(with_eids / len(eids_per_bidder) * 100, 1)
