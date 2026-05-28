#!/bin/bash
set -e

rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &

for i in $(seq 1 10); do
    [ -S /tmp/.X11-unix/X99 ] && break
    sleep 0.5
done

export DISPLAY=:99

exec rq worker --url "${REDIS_URL:-redis://redis:6379}" default
