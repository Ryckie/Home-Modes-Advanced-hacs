# Contributing

Thanks for helping. This is a fully local Home Assistant custom integration; keep it that way:
no cloud calls and no external Python dependencies.

## Ground rules

- English only for code, comments, docs and issues.
- Python: full type hints, async only, no blocking calls on the event loop.
- Do not hard-code role *names* in logic or docs; use role ids (`night`, `away`, …).
- A new behaviour needs a test. A new option needs translations in
  `custom_components/home_modes/translations/en.json` and a line in the docs.
- Safety rules are not negotiable: Alarmo is never disarmed automatically, permissions are
  checked on the server, and no secret, code or message body is stored or logged.

## Development setup

```
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements_test.txt
ruff format --check . && ruff check . && mypy custom_components
pytest                                    # Home Assistant 2026.10.4 (required)
python tests/run_pytest_ha2611.py         # Home Assistant 2026.11.x (best effort)
(cd tests/js && npm ci && npm test)       # card checks, Node 22
```

Python 3.14.2 or newer is required by the tested Home Assistant versions. Use the latest 3.14.x:
Python 3.14.2 itself fails one recorder test (`tests/test_vacation_recorder.py`), 3.14.6 passes.

## Pull requests

1. Open an issue first for anything bigger than a fix.
2. One topic per pull request; keep the diff small.
3. Run the commands above. CI runs hassfest, the HACS check, lint, mypy, the JS checks and
   the test matrix.
4. Update `CHANGELOG.md` under `[Unreleased]`.
5. Describe what you tested and what you could not test (real Alarmo, real phone, …).

## Reporting bugs

Use the bug report template. Attach the **diagnostics download**
(Settings → Devices & services → Home Modes Advanced → ⋮ → Download diagnostics) and a debug
log (see [docs/debug-logging.md](docs/debug-logging.md)). Both are redacted by design, but look
through them before posting.

## Security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).
