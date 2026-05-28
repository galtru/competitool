"""Prebid analyzer — detects version, bidders, mode, timeout, floors."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from analyzers.base import AnalyzerResult

_PREBID_SERVER_HOSTS = [
    "prebid-server", "prebid.appnexus.com", "prebid.openx.net",
    "prebid.rubicon", "pbs.", "/openrtb2/auction",
]

_S2S_PATH_PATTERN = re.compile(r"/openrtb2/auction|/pbs/|prebid-server")

# Video players that manage their own ad orchestration (Prebid events may not fire)
# Note: sdkv= is the IMA SDK version param used by many players (incl. Truvid), NOT Connatix-specific
_WRAPPED_PLAYER_SIGNALS = {
    "truvid": ["truvidplayer.com", "mpt=truvid"],
    "connatix": ["connatix.com", "connatix_insights"],
    "jwplayer": ["jwpltx.com", "jwplayer.com/libraries"],
    "brightcove": ["brightcove.com/v1/accounts"],
    "ooyala": ["player.ooyala.com"],
    "dailymotion": ["dmxleo.com", "dailymotion.com/player"],
}


class PrebidAnalyzer:
    def analyze(self, sessions: list[dict[str, Any]]) -> AnalyzerResult:
        version = None
        timeout_ms = None
        mode = "unknown"
        all_bidders: set[str] = set()
        responding_bidders_per_session: list[set[str]] = []
        auction_counts: list[int] = []
        floors_module_loaded = False
        s2s_endpoints: list[str] = []
        wrapped_player: str | None = None

        for session in sessions:
            session_bidders: set[str] = set()
            auction_count = 0

            for snap in session.get("globals_snapshots", []):
                data = snap.get("data", {})

                if not version and data.get("pbjs_version"):
                    version = data["pbjs_version"]

                cfg = data.get("pbjs_config", {})
                if not timeout_ms and cfg.get("bidderTimeout"):
                    timeout_ms = cfg["bidderTimeout"]

                if cfg.get("floors") or cfg.get("priceFloors"):
                    floors_module_loaded = True

                # S2S detection
                s2s_cfg = cfg.get("s2sConfig") or cfg.get("s2sBidders")
                if s2s_cfg:
                    mode = "s2s"

            # Extract from probe log embedded in globals
            probe_log = []
            for snap in session.get("globals_snapshots", []):
                probe_log.extend(snap.get("data", {}).get("probe_log", []))

            for entry in probe_log:
                etype = entry.get("type", "")
                edata = entry.get("data") or {}

                if etype == "pbjs_loaded":
                    version = version or edata.get("version")

                elif etype == "pbjs_config":
                    timeout_ms = timeout_ms or edata.get("bidderTimeout")
                    if edata.get("floors") or edata.get("priceFloors"):
                        floors_module_loaded = True
                    s2s = edata.get("s2sConfig")
                    if s2s:
                        mode = "s2s"

                elif etype == "pbjs_event_auctionInit":
                    auction_count += 1
                    bidders = _extract_bidders_from_auction(edata)
                    all_bidders.update(bidders)

                elif etype == "pbjs_event_bidResponse":
                    bidder = edata.get("bidderCode") or edata.get("bidder")
                    if bidder:
                        session_bidders.add(bidder)
                        all_bidders.add(bidder)

                elif etype == "pbjs_event_bidRequested":
                    bidder = edata.get("bidderCode") or edata.get("bidder")
                    if bidder:
                        all_bidders.add(bidder)

            # Detect bidders from HAR (OpenRTB requests to known bidder endpoints)
            har_bidders, har_s2s = _detect_bidders_from_har(session.get("har", {}))
            all_bidders.update(har_bidders)
            if har_s2s:
                s2s_endpoints.extend(har_s2s)
                if mode == "unknown":
                    mode = "s2s"

            # Detect wrapped video players that manage their own ad orchestration
            if not wrapped_player:
                wrapped_player = _detect_wrapped_player(session.get("har", {}))

            responding_bidders_per_session.append(session_bidders)
            auction_counts.append(auction_count)

        if mode == "unknown" and all_bidders:
            mode = "client_side"

        avg_responding = (
            sum(len(b) for b in responding_bidders_per_session) / len(responding_bidders_per_session)
            if responding_bidders_per_session else 0
        )
        avg_auctions = (
            sum(auction_counts) / len(auction_counts) if auction_counts else 0
        )

        # If no pbjs auction events fired but bidders were found via HAR, note the detection method
        bidder_detection = "probe_log" if any(auction_counts) else "har_network_patterns"

        return AnalyzerResult(
            analyzer="prebid",
            raw={
                "present": bool(version or all_bidders),
                "version": version,
                "mode": mode,
                "timeout_ms": timeout_ms,
                "bidders": sorted(all_bidders),
                "bidder_count": len(all_bidders),
                "bidder_detection_method": bidder_detection,
                "wrapped_player": wrapped_player,
                "avg_bidders_responding_per_session": round(avg_responding, 1),
                "avg_auctions_per_session": round(avg_auctions, 1),
                "floors_module_loaded": floors_module_loaded,
                "s2s_endpoints": s2s_endpoints,
            },
        )


def _extract_bidders_from_auction(data: dict) -> set[str]:
    bidders: set[str] = set()
    for key in ("bidderRequests", "adUnitCodes", "bidsReceived"):
        items = data.get(key, [])
        for item in items:
            b = item.get("bidderCode") or item.get("bidder")
            if b:
                bidders.add(b)
    return bidders


_KNOWN_BIDDER_DOMAINS = {
    "appnexus.com": "appnexus",
    "adnxs.com": "appnexus",
    "rubiconproject.com": "rubicon",
    "openx.net": "openx",
    "pubmatic.com": "pubmatic",
    "indexexchange.com": "ix",
    "criteo.com": "criteo",
    "amazon-adsystem.com": "amazon",
    "media.net": "medianet",
    "sovrn.com": "sovrn",
    "sharethrough.com": "sharethrough",
    "triplelift.com": "triplelift",
    "teads.tv": "teads",
    "33across.com": "33across",
    "spotx.tv": "spotx",
    "smartadserver.com": "smartadserver",
    "emxdgt.com": "emx_digital",
    "openauction.co": "openauction",
    "the-trade-desk.com": "ttd",
    "tapad.com": "tapad",
    "yieldmo.com": "yieldmo",
    "rhythmone.com": "rhythmone",
}


def _detect_bidders_from_har(har: dict | None) -> tuple[set[str], list[str]]:
    bidders: set[str] = set()
    s2s_urls: list[str] = []
    if not har:
        return bidders, s2s_urls

    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            continue

        for domain, bidder in _KNOWN_BIDDER_DOMAINS.items():
            if domain in host:
                bidders.add(bidder)

        if _S2S_PATH_PATTERN.search(url):
            s2s_urls.append(url)

    return bidders, s2s_urls


def _detect_wrapped_player(har: dict | None) -> str | None:
    """Return the name of a known wrapped video player if detected in HAR."""
    if not har:
        return None
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        for player, signals in _WRAPPED_PLAYER_SIGNALS.items():
            if any(sig in url for sig in signals):
                return player
    return None
