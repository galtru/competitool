FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Xvfb provides a virtual display so Chromium runs headful on a headless server
RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer is cached unless pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Sync the Chromium binary to match the installed playwright version
RUN playwright install chromium

# Copy source
COPY . .

RUN chmod +x entrypoints/*.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
