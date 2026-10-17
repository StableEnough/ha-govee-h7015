# =============================================================================
# Docker image for the Govee H7015 MQTT bridge (uses uv).
# =============================================================================

FROM python:3.13-slim-bookworm

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
RUN uv sync --frozen --no-dev --extra bridge --no-install-project

# Copy source (respects .dockerignore)
COPY . .

# Install the project after its README and source files are available.
RUN uv sync --frozen --no-dev --extra bridge

# Default to running the installed bridge command.
CMD ["uv", "run", "--no-sync", "govee-h7015-bridge"]
