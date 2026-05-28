FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Xvfb provides a virtual display so Chromium runs headful on a headless server
RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
# We don't install the package itself — PYTHONPATH=/app handles module resolution.
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.29" \
    "playwright>=1.44" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.0" \
    "pyyaml>=6.0" \
    "aiofiles>=23.0" \
    "httpx>=0.27" \
    "aiosqlite>=0.20" \
    "rq>=1.16" \
    "redis>=5.0"

# Sync the Chromium binary to match the installed playwright version
RUN playwright install chromium

# Copy source
COPY . .

RUN chmod +x entrypoints/*.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
