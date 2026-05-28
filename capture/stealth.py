"""Browser stealth patches to reduce bot-detection fingerprinting."""
from __future__ import annotations

import random
from playwright.async_api import BrowserContext, Page

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

# Patches applied via addInitScript — run before any page JS
_STEALTH_SCRIPT = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Block WebRTC local IP leakage
if (window.RTCPeerConnection) {
    const _origRTC = window.RTCPeerConnection;
    window.RTCPeerConnection = function(config) {
        if (config && config.iceServers) {
            config.iceServers = config.iceServers.filter(s =>
                !s.urls || !('' + s.urls).includes('stun:')
            );
        }
        return new _origRTC(config);
    };
    Object.setPrototypeOf(window.RTCPeerConnection, _origRTC);
}

// Spoof plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ];
    arr.__proto__ = PluginArray.prototype;
    return arr;
  }
});

// Spoof languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Fix chrome object
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};

// Spoof permissions API
if (navigator.permissions) {
  const _query = navigator.permissions.query.bind(navigator.permissions);
  navigator.permissions.query = (params) => {
    if (params.name === 'notifications') {
      return Promise.resolve({ state: Notification.permission });
    }
    return _query(params);
  };
}
"""


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def random_viewport() -> dict:
    return random.choice(VIEWPORTS)


async def apply_stealth(context: BrowserContext) -> None:
    """Apply stealth patches to a browser context."""
    await context.add_init_script(_STEALTH_SCRIPT)


async def apply_page_stealth(page: Page) -> None:
    """Additional per-page patches if needed."""
    # Override canvas fingerprinting slightly
    await page.add_init_script("""
    const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        if (type === 'image/png' && this.width === 16 && this.height === 16) {
            return _toDataURL.apply(this, arguments);
        }
        return _toDataURL.apply(this, arguments);
    };
    """)
