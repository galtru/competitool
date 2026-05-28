"""Session lifecycle: scroll video into view and trigger playback."""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

_SHADOW_TRAVERSAL_JS = """
    // Recursively search for video elements, piercing open shadow roots
    function findAllVideos(root) {
        const found = [];
        try {
            found.push(...Array.from(root.querySelectorAll('video')));
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) found.push(...findAllVideos(el.shadowRoot));
            }
        } catch(e) {}
        return found;
    }
    function findVisibleVideo(root) {
        for (const v of findAllVideos(root)) {
            const r = v.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return v;
        }
        return null;
    }
"""

_PLAY_SCRIPT = """
async () => {
""" + _SHADOW_TRAVERSAL_JS + """
    const visible = findVisibleVideo(document);
    if (visible) {
        visible.muted = false;
        try { await visible.play(); } catch(e) {}
        return { found: true, src: visible.src || visible.currentSrc };
    }
    return { found: false };
}
"""

_SCROLL_TO_VIDEO_SCRIPT = """
() => {
""" + _SHADOW_TRAVERSAL_JS + """
    const video = findVisibleVideo(document);
    if (video) {
        video.scrollIntoView({ behavior: 'instant', block: 'center' });
        return true;
    }
    // Also try common video container selectors
    const containers = [
        '.video-player', '.player-wrapper', '[class*="video"]',
        '[id*="video"]', '[class*="player"]', '[id*="player"]'
    ];
    for (const sel of containers) {
        const el = document.querySelector(sel);
        if (el) {
            el.scrollIntoView({ behavior: 'instant', block: 'center' });
            return true;
        }
    }
    return false;
}
"""

_SNAPSHOT_GLOBALS_SCRIPT = """
() => {
    const snap = {};
    try { snap.pbjs_config = pbjs.getConfig(); } catch(e) {}
    try { snap.pbjs_bid_responses = pbjs.getBidResponses(); } catch(e) {}
    try { snap.pbjs_version = pbjs.version; } catch(e) {}
    try { snap.pbjs_bidder_settings = pbjs.bidderSettings; } catch(e) {}
    try {
        if (window.googletag) {
            snap.gpt_slots = googletag.pubads().getSlots().map(s => ({
                adUnitPath: s.getAdUnitPath(),
                sizes: s.getSizes(),
                targeting: s.getTargetingKeys().reduce((acc, k) => {
                    acc[k] = s.getTargeting(k);
                    return acc;
                }, {})
            }));
        }
    } catch(e) {}
    try { snap.probe_log = window.__probe_log || []; } catch(e) {}
    return snap;
}
"""


_SCROLL_DOWN_SCRIPT = """
async ([stepPx, pauseMs, maxScrollPx]) => {
    // Scroll the page incrementally, letting IntersectionObservers fire at each step.
    // Returns { videoFound: bool, videoY: int, stoppedAt: int }
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let scrolled = 0;
    let videoFoundAt = null;

    function findAllVideos(root) {
        const found = [];
        try {
            found.push(...Array.from(root.querySelectorAll('video')));
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) found.push(...findAllVideos(el.shadowRoot));
            }
        } catch(e) {}
        return found;
    }

    const findVisibleVideo = () => {
        for (const v of findAllVideos(document)) {
            const r = v.getBoundingClientRect();
            if (r.width > 10 && r.height > 10) return v;
        }
        // Also check common player container selectors that may wrap a not-yet-initialised <video>
        const selectors = [
            '.video-player', '.player-wrapper', '[class*="video-container"]',
            '[class*="player-container"]', '.jwplayer', '.connatix-player',
            '[data-player]', '[class*="brightcove"]',
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.width > 10 && r.height > 10 && r.top >= -50 && r.top < window.innerHeight + 50)
                    return el;
            }
        }
        return null;
    };

    while (scrolled < maxScrollPx) {
        window.scrollBy({ top: stepPx, behavior: 'instant' });
        scrolled += stepPx;
        await sleep(pauseMs);

        const el = findVisibleVideo();
        if (el) {
            el.scrollIntoView({ behavior: 'instant', block: 'center' });
            await sleep(pauseMs);
            videoFoundAt = window.scrollY;
            break;
        }
    }

    return {
        videoFound: videoFoundAt !== null,
        videoY: videoFoundAt,
        stoppedAt: window.scrollY,
        pageHeight: document.body.scrollHeight,
    };
}
"""

_SCROLL_PARAMS = {
    "step_px": 400,      # scroll this many pixels per step
    "pause_ms": 300,     # wait between steps to let lazy content render
    "max_scroll_px": 12000,  # don't scroll more than this (handles very long pages)
}


async def scroll_page_to_bottom(page: Page) -> dict:
    """Scroll the page incrementally to expose lazy-loaded video players.

    Stops as soon as a video (or player container) enters the viewport and
    centres it. Falls through silently if the page has no scrollable content.
    """
    try:
        result = await page.evaluate(
            _SCROLL_DOWN_SCRIPT,
            [_SCROLL_PARAMS["step_px"], _SCROLL_PARAMS["pause_ms"], _SCROLL_PARAMS["max_scroll_px"]],
        )
        found = result.get("videoFound", False)
        logger.info(
            "Page scroll complete — video_found=%s stopped_at=%s page_height=%s",
            found,
            result.get("stoppedAt"),
            result.get("pageHeight"),
        )
        return result
    except Exception as exc:
        logger.warning("scroll_page_to_bottom failed: %s", exc)
        return {"videoFound": False}


async def scroll_to_video(page: Page) -> bool:
    try:
        result = await page.evaluate(_SCROLL_TO_VIDEO_SCRIPT)
        return bool(result)
    except Exception:
        return False


async def trigger_video_play(page: Page) -> dict:
    try:
        result = await page.evaluate_handle(_PLAY_SCRIPT)
        return await result.json_value()
    except Exception as exc:
        logger.warning("Could not trigger video play: %s", exc)
        return {"found": False, "error": str(exc)}


async def snapshot_globals(page: Page) -> dict:
    try:
        result = await page.evaluate(_SNAPSHOT_GLOBALS_SCRIPT)
        return result or {}
    except Exception as exc:
        logger.warning("Could not snapshot globals: %s", exc)
        return {}


async def wait_for_video_content(page: Page, duration_s: int = 30) -> None:
    """Wait while video plays, periodically re-triggering play if needed."""
    for tick in range(duration_s // 5):
        await asyncio.sleep(5)
        # Re-trigger play in case it stopped
        if tick % 6 == 0:  # every 30s
            await trigger_video_play(page)
