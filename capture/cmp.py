"""Consent Management Platform (CMP) auto-accept handlers."""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Ordered by market share — try these selectors in order
_ACCEPT_SELECTORS = [
    # OneTrust
    "#onetrust-accept-btn-handler",
    ".onetrust-accept-btn-handler",
    # Quantcast
    ".qc-cmp2-summary-buttons button:last-child",
    "#qcCmpUi button[mode='primary']",
    # Sourcepoint
    ".sp-close-button",
    "[title='Accept All']",
    # Didomi
    "#didomi-notice-agree-button",
    ".didomi-continue-without-agreeing",
    # TrustArc
    ".truste_popframe",
    ".pdynamicbutton .call",
    # Generic patterns
    "button[id*='accept']",
    "button[class*='accept']",
    "button[data-testid*='accept']",
    "[aria-label*='Accept']",
    "[aria-label*='accept']",
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('Accept Cookies')",
    "button:has-text('I Accept')",
    "button:has-text('Agree')",
    "button:has-text('OK')",
    "button:has-text('Got it')",
]


async def dismiss_consent_banner(page: Page, timeout_ms: int = 5000) -> bool:
    """Try to auto-accept a consent banner. Returns True if one was dismissed."""
    for selector in _ACCEPT_SELECTORS:
        try:
            element = await page.wait_for_selector(
                selector,
                timeout=1000,
                state="visible",
            )
            if element:
                await element.click()
                logger.info("Dismissed CMP via selector: %s", selector)
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue

    # Try iframe-based CMPs
    for frame in page.frames:
        if "consent" in (frame.url or "").lower() or "cmp" in (frame.url or "").lower():
            for selector in _ACCEPT_SELECTORS[:8]:
                try:
                    element = await frame.wait_for_selector(selector, timeout=500, state="visible")
                    if element:
                        await element.click()
                        logger.info("Dismissed CMP in iframe via: %s", selector)
                        await asyncio.sleep(0.5)
                        return True
                except Exception:
                    continue

    return False
