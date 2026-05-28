#!/bin/bash
set -e

# Start virtual display so Playwright can launch headful Chromium
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99

exec rq worker --url "${REDIS_URL:-redis://redis:6379}" default
