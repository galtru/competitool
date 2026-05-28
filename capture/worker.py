"""Playwright capture worker — orchestrates a single browser session."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page

from capture.cmp import dismiss_consent_banner
from capture.lifecycle import scroll_page_to_bottom, scroll_to_video, snapshot_globals, trigger_video_play, wait_for_video_content
from capture.stealth import apply_stealth, apply_page_stealth, random_user_agent, random_viewport

logger = logging.getLogger(__name__)

_PROBE_JS = (Path(__file__).parent / "probe.js").read_text()

SESSION_DURATION_S = int(os.getenv("SESSION_DURATION_S", "90"))


async def run_capture_session(url: str, job_id: str, session_index: int = 0) -> dict[str, Any]:
    """Run one Playwright session and return raw artifacts dict."""
    viewport = random_viewport()
    user_agent = random_user_agent()
    artifacts: dict[str, Any] = {
        "url": url,
        "session_index": session_index,
        "user_agent": user_agent,
        "viewport": viewport,
        "started_at": time.time(),
        "har": None,
        "console_log": [],
        "screenshots": {},
        "globals_snapshots": [],
        "network_requests": [],
        "vast_responses": [],
        "errors": [],
    }

    har_path = Path(f"/tmp/competitool_{job_id}_session_{session_index}.har")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
            ],
        )

        context: BrowserContext = await browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            record_har_path=str(har_path),
            record_har_url_filter="**/*",
            ignore_https_errors=True,
            java_script_enabled=True,
        )

        await apply_stealth(context)
        await context.add_init_script(_PROBE_JS)

        page: Page = await context.new_page()
        await apply_page_stealth(page)

        # Capture console
        page.on("console", lambda msg: artifacts["console_log"].append({
            "type": msg.type,
            "text": msg.text,
            "ts": time.time(),
        }))
        page.on("pageerror", lambda err: artifacts["errors"].append({
            "message": str(err),
            "ts": time.time(),
        }))

        # Capture network requests for ad-related URLs
        ad_domains = [
            "doubleclick.net", "googlesyndication.com", "pubads.g.doubleclick.net",
            "prebid", "bidder", "openrtb", "ad.yaml", "ads?", "/bid",
            "uid2.com", "id5-sync.com", "liveramp.com", "criteo.com",
        ]

        async def on_request(req):
            url_lower = req.url.lower()
            if any(d in url_lower for d in ad_domains):
                try:
                    post_data = req.post_data  # raises UnicodeDecodeError for gzip bodies
                except UnicodeDecodeError:
                    post_data = None  # binary body — EID parsing uses HAR response instead
                artifacts["network_requests"].append({
                    "url": req.url,
                    "method": req.method,
                    "headers": dict(req.headers),
                    "post_data": post_data,
                    "ts": time.time(),
                })

        page.on("request", on_request)

        # Intercept VAST XML responses directly
        async def on_response(resp):
            content_type = resp.headers.get("content-type", "").lower()
            url_lower = resp.url.lower()
            is_xml = "xml" in content_type
            is_vast_url = "vast" in url_lower or "ad_type=video" in url_lower
            if is_xml or is_vast_url:
                try:
                    body = await resp.body()
                    text = body.decode("utf-8", errors="replace")
                    if "<VAST" in text:
                        artifacts["vast_responses"].append({
                            "url": resp.url,
                            "body": text,
                            "ts": time.time(),
                        })
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            logger.info("[session %d] Navigating to %s", session_index, url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Screenshot: page load
            try:
                artifacts["screenshots"]["page_load"] = await page.screenshot(type="png")
            except Exception:
                pass

            # Dismiss consent banner
            await dismiss_consent_banner(page)
            await asyncio.sleep(1)

            # Scroll down the page incrementally so lazy-loaded players enter the viewport.
            # scroll_page_to_bottom stops at the first visible player it finds.
            scroll_result = await scroll_page_to_bottom(page)

            # If the page scroll didn't land on a video, fall back to explicit scroll-to-video.
            if not scroll_result.get("videoFound"):
                await scroll_to_video(page)

            await asyncio.sleep(1)

            # Screenshot: pre-ad
            try:
                artifacts["screenshots"]["pre_ad"] = await page.screenshot(type="png")
            except Exception:
                pass

            # Trigger video play
            play_result = await trigger_video_play(page)
            logger.info("[session %d] Video play result: %s", session_index, play_result)

            # Wait for ad / content to begin and take screenshot
            await asyncio.sleep(3)
            try:
                artifacts["screenshots"]["ad_start"] = await page.screenshot(type="png")
            except Exception:
                pass

            # Snapshot globals after initial ad load
            snap1 = await snapshot_globals(page)
            artifacts["globals_snapshots"].append({"t": 5, "data": snap1})

            # Run for the session duration
            logger.info("[session %d] Running for %ds", session_index, SESSION_DURATION_S)
            await wait_for_video_content(page, SESSION_DURATION_S)

            # Final snapshots
            snap2 = await snapshot_globals(page)
            artifacts["globals_snapshots"].append({"t": SESSION_DURATION_S, "data": snap2})

            try:
                artifacts["screenshots"]["ad_end"] = await page.screenshot(type="png")
            except Exception:
                pass

        except Exception as exc:
            logger.error("[session %d] Capture error: %s", session_index, exc)
            artifacts["errors"].append({"message": str(exc), "ts": time.time()})
        finally:
            await context.close()
            await browser.close()

        artifacts["ended_at"] = time.time()
        artifacts["duration_s"] = artifacts["ended_at"] - artifacts["started_at"]

        # Load HAR
        if har_path.exists():
            with open(har_path) as f:
                artifacts["har"] = json.load(f)
            har_path.unlink(missing_ok=True)

    return artifacts
