#!/bin/bash
set -e

# Remove stale Xvfb lock file left over from a previous container run
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# xvfb-run -a auto-selects a free display and exports DISPLAY for all child
# processes (including the forked RQ job subprocesses via fork inheritance)
exec xvfb-run -a --server-args="-screen 0 1920x1080x24 -ac +extension GLX +render -noreset" \
    rq worker --url "${REDIS_URL:-redis://redis:6379}" default
