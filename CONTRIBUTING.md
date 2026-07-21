# Contributing to Govee H7015 BLE

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/StableEnough/ha-govee-h7015
cd ha-govee-h7015

# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all deps including dev
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Verify everything works
just ci
```

## Project Structure

```
custom_components/govee_h7015_ble/  ← HA integration (HACS-installable)
standalone/                         ← MQTT bridge + CLI tools (non-HA)
frontend/                           ← Lovelace card (HACS frontend module)
tests/                              ← 220+ tests (pytest + Hypothesis + HA)
```

## Running Tests

```bash
just test                              # run all 220 tests
just test-fuzz                         # run with Hypothesis statistics
uv run pytest tests/test_protocol.py   # run just protocol tests
uv run pytest -k "color_temp"          # run tests matching a keyword
```

## Code Style

- Python 3.12+ — use `T | None`, `match`, `@dataclass(frozen=True, slots=True)`, `@override`
- `ruff` for linting and formatting (enforced via pre-commit)
- `mypy --strict` for type checking (best-effort on HA code)
- No `Optional[T]`, `Union[A, B]`, or `from typing import List` — use modern syntax
- Every public function needs a docstring
- Every BLE operation needs `asyncio.timeout()` — no hangs

## Pull Request Process

1. Fork the repo and create a feature branch
2. Write tests first (TDD), then implement
3. Run `just ci` — all checks must pass
4. Update `CHANGELOG.md` under `[Unreleased]`
5. Open a PR with a clear description of what changed and why

## Protocol Reverse Engineering

If you have an H7015 and want to help capture protocol bytes:

1. See `standalone/analyze_hci.py` for extracting packets from HCI snoop logs
2. The most needed capture: per-bulb segment encoding (the `0x0B` sub-mode)
3. Capture guide: enable Bluetooth HCI snoop log on Android → use Govee app → pull log → analyze

## Releasing

1. Update `CHANGELOG.md` with the new version
2. Bump version in `manifest.json` and `pyproject.toml`
3. Tag: `git tag v1.2.0 && git push --tags`
4. GitHub Actions will validate (HACS + hassfest + tests)
5. HACS users get the update automatically
