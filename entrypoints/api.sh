#!/bin/bash
set -e

# Remove stale lock files from a previous container run
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &

# Wait until the X socket is ready (up to 5 seconds)
for i in $(seq 1 10); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.5
done

export DISPLAY=:99

exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
