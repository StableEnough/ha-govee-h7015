# =============================================================================
# Docker image for the Govee H7015 MQTT bridge (uses uv).
# =============================================================================

FROM python:3.12-slim-bookworm

# BlueZ is required by bleak for BLE access on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bluez \
        bluez-hcidump \
        tshark \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy lockfile + pyproject first for better layer caching
COPY pyproject.toml uv.lock ./

# Sync deps using the committed lockfile (fail if out of date)
RUN uv sync --frozen --no-dev

# Copy source (respects .dockerignore)
COPY . .

# Default to running the bridge.
CMD ["uv", "run", "python", "standalone/mqtt_bridge.py"]
