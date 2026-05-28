"""IMA analyzer — detects Google IMA, header bidding integration, ad pods."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote

from analyzers.base import AnalyzerResult

_GAM_DOMAINS = [
    "pubads.g.doubleclick.net",
    "securepubads.g.doubleclick.net",
    "googleads.g.doubleclick.net",
    "pagead2.googlesyndication.com",
]

_HB_KEYS = {"hb_pb", "hb_bidder", "hb_size", "hb_uuid", "hb_adid", "hb_deal"}

_AD_POD_PARAMS = {"pmad", "pmnd", "pmxd", "ad_pod_id"}


class IMAAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        present = False
        gam_network_id = None
        ad_unit_path = None
        header_bidding_integrated = False
        hb_pb_values: list[str] = []
        ad_pod_requested = False
        pod_max_duration_s = None
        pod_max_ads = None
        all_targeting_params: dict[str, set[str]] = {}
        gam_requests: list[dict] = []

        for session in sessions:
            for entry in _iter_har_entries(session.get("har", {})):
                url = entry.get("request", {}).get("url", "")
                try:
                    parsed = urlparse(url)
                except Exception:
                    continue

                host = parsed.hostname or ""
                if not any(d in host for d in _GAM_DOMAINS):
                    continue

                present = True
                qs = parse_qs(parsed.query)

                # GAM network ID and ad unit path
                iu = qs.get("iu", [None])[0]
                if iu and not ad_unit_path:
                    ad_unit_path = iu
                    parts = iu.strip("/").split("/")
                    if parts:
                        gam_network_id = parts[0]

                # Custom params (header bidding keys land here)
                cust_raw = qs.get("cust_params", [None])[0]
                if cust_raw:
                    cust = parse_qs(unquote(cust_raw))
                    for k, v in cust.items():
                        all_targeting_params.setdefault(k, set()).update(v)
                        if k in _HB_KEYS:
                            header_bidding_integrated = True
                        if k == "hb_pb":
                            hb_pb_values.extend(v)

                # Ad pod params
                for param in _AD_POD_PARAMS:
                    if param in qs:
                        ad_pod_requested = True
                        if param == "pmxd" and not pod_max_duration_s:
                            try:
                                # pmxd is in milliseconds per IMA spec; store as seconds
                                pod_max_duration_s = int(qs[param][0]) // 1000
                            except (ValueError, IndexError):
                                pass
                        if param == "pmad" and not pod_max_ads:
                            try:
                                pod_max_ads = int(qs[param][0])
                            except (ValueError, IndexError):
                                pass

                gam_requests.append({"url": url, "iu": iu})

        # Flatten targeting params for output
        targeting_flat = {k: list(v) for k, v in all_targeting_params.items()}

        return AnalyzerResult(
            analyzer="ima",
            raw={
                "present": present,
                "gam_network_id": gam_network_id,
                "ad_unit_path": ad_unit_path,
                "header_bidding_integrated": header_bidding_integrated,
                "hb_pb_values": sorted(set(hb_pb_values)),
                "hb_pb_max": max(hb_pb_values, default=None),
                "cust_params_keys": sorted(all_targeting_params.keys()),
                "ad_pod_requested": ad_pod_requested,
                "pod_max_duration_s": pod_max_duration_s,
                "pod_max_ads": pod_max_ads,
                "targeting_params": targeting_flat,
                "gam_request_count": len(gam_requests),
            },
        )


def _iter_har_entries(har: dict | None):
    if not har:
        return
    yield from har.get("log", {}).get("entries", [])
