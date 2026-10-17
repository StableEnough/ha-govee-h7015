# Contributing to Govee H7015 BLE

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

```bash
# Set REPOSITORY_URL to the clone URL from your forge
git clone "$REPOSITORY_URL" ha-govee-h7015
cd ha-govee-h7015

# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install locked development dependencies (matching Forgejo CI)
uv sync --locked --extra dev --extra test-ha --extra analyze

# Install pre-commit hooks
uv run pre-commit install

# Verify everything works
just ci
```

Do not install `--all-extras`: `bridge` and `test-ha` have conflicting MQTT
dependencies. Use a separate bridge environment when running the real daemon.

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

- Python 3.13+ — use `T | None`, `match`, `@dataclass(frozen=True, slots=True)`, `@override`
- `ruff` for linting and formatting (enforced via pre-commit)
- `mypy --strict` for type checking (best-effort on HA code)
- No `Optional[T]`, `Union[A, B]`, or `from typing import List` — use modern syntax
- Every public function needs a docstring
- Every BLE operation needs `asyncio.timeout()` — no hangs

## Pull Request Process

1. Fork the repo and create a feature branch
2. Write tests first (TDD), then implement
3. Run `just ci` and report any failures; standalone mypy is currently non-blocking
   in Forgejo CI, while lint, formatting, tests, Hassfest, and secret scans must pass.
4. Update `CHANGELOG.md` under `[Unreleased]`
5. Open a PR with a clear description of what changed and why

## Forgejo CI

`.forgejo/workflows/ci.yml` runs on pull requests, pushes to `main`, `v*` tags,
and manual dispatch. Enable Actions in the repository settings and provide a
runner with the `docker` label (Node 22). Python jobs use the uv Python 3.13
container and install Node for checkout. No long-lived CI secrets are needed.

Checks include Ruff lint/format, best-effort standalone mypy, Lovelace JavaScript
syntax, the full pytest suite with Hypothesis statistics, Hassfest integration
validation, and Gitleaks scans of current files and Git history with redacted
output. Mypy remains non-blocking, matching the previous CI policy.

HACS's GitHub repository validator is not run against Forgejo. HACS distribution
requires a separately maintained public GitHub mirror; Forgejo releases support
manual installation. HACS metadata remains for compatibility, but no mirror is
configured by this migration.

### Privacy

Keep personal identifiers, private infrastructure URLs, local filesystem paths,
real device addresses, and credentials out of committed files and examples.
Inspect Git author/committer identity before committing: file cleanup does not
anonymize history. Gitleaks detects secrets, not arbitrary usernames or emails.
The manifest's required legacy documentation URL is the only retained
owner-specific project link, pending a real project-only HTTPS documentation URL.
Do not replace it with a fake address or remove upstream license attribution.

## Protocol Reverse Engineering

If you have an H7015 and want to help capture protocol bytes:

1. See `standalone/analyze_hci.py` for extracting packets from HCI snoop logs
2. The most needed capture: per-bulb segment encoding (the `0x0B` sub-mode)
3. Capture guide: enable Bluetooth HCI snoop log on Android → use Govee app → pull log → analyze

## Releasing

1. Update `CHANGELOG.md` with the new version
2. Bump version in `manifest.json` and `pyproject.toml`
3. Tag: `git tag v1.2.0 && git push --tags`
4. Forgejo CI runs tests, Hassfest, and secret scans before publishing a release.
5. The release job checks tag/manifest/project versions and uploads an integration
   ZIP for manual installation using the repository-scoped automatic token.
6. HACS updates require a separate GitHub mirror; they do not follow Forgejo tags.
