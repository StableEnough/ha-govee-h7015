# Common commands for the Govee H7015 project.
# Install: https://github.com/casey/just#installation
# Usage:   just <recipe>

default:
    @just --list

# One-time setup: install uv + sync all deps
setup:
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv sync --all-extras

# Run the protocol test suite
test:
    PYTHONPATH=custom_components/govee_h7015_ble:standalone uv run pytest tests/ -v

# Run tests including Hypothesis property-based fuzzing (slow)
test-fuzz:
    PYTHONPATH=custom_components/govee_h7015_ble:standalone uv run pytest tests/ -v --hypothesis-show-statistics

# Lint + format
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint issues
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Type-check with mypy --strict
typecheck:
    uv run mypy --strict standalone custom_components

# Run all CI checks locally
ci: lint typecheck test
    @echo "✓ All CI checks passed"

# Install pre-commit hooks
hooks:
    uv run pre-commit install

# Run pre-commit on all files
precommit:
    uv run pre-commit run --all-files

# Scan for nearby H7015 devices
scan:
    uv run python standalone/scan.py --name H7015

# Probe a device (usage: just probe AA:BB:CC:DD:EE:FF)
probe address:
    uv run python standalone/probe.py {{address}}

# Run the MQTT bridge
bridge:
    uv run python standalone/mqtt_bridge.py

# Build the Docker image
docker:
    cd docker && docker compose build

# Validate HACS + hassfest (requires network)
validate-hacs:
    act -W .github/workflows/validate.yml

# Clean build artifacts
clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    rm -rf .pytest_cache .mypy_cache .ruff_cache
    rm -f *.egg-info dist build
