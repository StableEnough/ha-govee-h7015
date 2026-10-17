# Agent instructions

## Scope and project

These instructions apply to the whole repository. This project controls Govee
H7015 outdoor string lights locally over BLE; it is not a Govee cloud or LAN API
integration. Keep changes focused on the requested behavior and reuse existing
helpers and patterns before adding dependencies or abstractions.

## Repository map

- `custom_components/govee_h7015_ble/`: HACS-installable Home Assistant
  integration. `coordinator.py` owns BLE communication and state;
  `light.py` exposes the string and bulb entities; `__init__.py` manages setup,
  teardown, and services. Config/options flows, diagnostics, translations, and
  integration metadata live here too.
- `standalone/`: independent BLE client, MQTT bridge, scan/probe CLIs, and HCI
  capture analyzer.
- `frontend/govee-h7015-bulb-card.js`: custom Lovelace card; installation and
  configuration are documented in `frontend/README.md`.
- `esphome/`, `homeassistant/`, `docker/`, `systemd/`: alternative bridge and
  deployment examples. Keep affected examples consistent with behavior changes.
- `tests/`: pytest, async Home Assistant tests, Hypothesis properties, and
  `mock_h7015.py` for simulated device behavior.
- `docs/HCI_CAPTURE_GUIDE.md`: workflow for obtaining real protocol evidence.

## Environment and commands

Use Python **3.13+** and `uv`. Treat `pyproject.toml`, `justfile`, and
`.forgejo/workflows/ci.yml` as authoritative when older prose disagrees.

```sh
# Development environment, matching CI
uv sync --locked --extra dev --extra test-ha --extra analyze

# Focused tests (substitute the relevant test file)
PYTHONPATH=standalone:. uv run pytest tests/test_protocol.py -v

# Full test suite
PYTHONPATH=standalone:. uv run pytest tests/ -v

# Lint, format check, and local strict type check
just lint
just typecheck

# All local checks
just ci
```

Without `just`, lint/format commands are `uv run ruff check .` and
`uv run ruff format --check .`; type checking is
`uv run mypy --strict standalone custom_components`. CI currently runs mypy on
`standalone` only and treats it as best-effort; do not confuse that with a clean
local strict check.

**Do not use `uv sync --all-extras`.** The `bridge` and `test-ha` extras conflict
through their MQTT dependencies. The test suite stubs `aiomqtt`; it does not need
the real bridge extra. To run the actual bridge, use
`uv run --extra bridge python standalone/mqtt_bridge.py` in an environment without
`test-ha`. Restore the development extras before running HA tests again.

## Change constraints

- `protocol.py`, `govee_types.py`, `exceptions.py`, and `models.py` exist in both
  `standalone/` and the integration. Keep matching behavior synchronized when
  changing them, preserving standalone versus relative import conventions.
  The HACS integration must remain usable without installing `standalone`.
  Run `tests/test_integration_protocol.py` when changing protocol behavior.
- Keep packet construction/decoding separate from BLE transport. Command packets
  are 20 bytes with zero-padding and an XOR checksum in the last byte. Preserve
  brightness-unit conversions, bulb bounds, and existing validation behavior.
- Do not invent protocol bytes or claim hardware support based solely on passing
  mocks. Segment encoding, DIY commands, and some scenes are derived from H6127
  captures and need H7015 verification. Retain those caveats unless real captures
  establish the behavior.
- Keep BLE operations asynchronous, timeout-bounded with `asyncio.timeout()`, and
  serialized using the existing locks. Preserve write pacing, reconnect guards,
  intentional-disconnect handling, and background-task cleanup.
- Use Home Assistant's Bluetooth/coordinator/entity lifecycle patterns in the
  integration. Preserve mode and last-commanded per-bulb state when polling cannot
  report them; do not present inferred state as hardware readback.
- Validate MQTT/config input with the existing Pydantic models. Never commit real
  credentials or unredacted device information; use `.env.example` for examples.
- Follow configured Ruff formatting (100 columns, double quotes), modern Python
  typing, and typed public APIs with docstrings. Avoid unrelated reformatting.
- When changing services or config flows, update affected schemas, `strings.json`,
  and `translations/en.json`; keep frontend callers consistent with service APIs.

## Privacy

- Do not commit personal names, email addresses, usernames, private hostnames,
  local home-directory paths, real device addresses, credentials, or captured
  logs containing them. Use generic examples and repository-relative paths.
- Workflows must use Forgejo context values for repository URLs and tokens,
  never hard-coded account names or infrastructure addresses. Gitleaks checks
  secrets in files and Git history; it does not recognize arbitrary personal
  identifiers. Review both file content and commit author/committer metadata.
- Keep the required legacy manifest documentation URL only until a real
  project-only HTTPS documentation URL is available. Do not invent a replacement
  or remove upstream license/attribution notices.
- Do not commit or push with a personal Git identity without explicit approval;
  use the user's chosen public pseudonym and no-reply address. Do not rewrite
  existing history or change Git identity settings without approval.

## Verification and handoff

- For bugs, add a focused failing regression test before fixing the root cause.
  Reuse existing mocks and fixtures; keep tests isolated from real BLE/MQTT.
- Run focused tests during development and the applicable full checks before
  handoff. Exercise the changed CLI, bridge, HA interaction, or card when the
  environment permits. Do not scan, connect to, or change real lights unless
  requested. Report missing hardware/runtime prerequisites explicitly.
- For card changes, verify the actual Lovelace UI when available; Python tests do
  not establish frontend correctness.
- Update affected user docs and add an `[Unreleased]` changelog entry for
  user-visible changes. Do not bump versions or create releases unless requested.
- Preserve unrelated user changes. Summarize the change, checks actually run, and
  any verification limits; never claim unrun checks or hardware confirmation.
