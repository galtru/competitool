#!/bin/bash
set -e

rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

exec xvfb-run -a --server-args="-screen 0 1920x1080x24 -ac +extension GLX +render -noreset" \
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
