# Bloch Trace SDK

Python client for Bloch Trace.

## Development

Use Python 3.12 and Poetry 2.4.3. CI checks Python 3.11 through 3.14 on Linux.
See [CONTRIBUTING.md](CONTRIBUTING.md) for complete setup, verification and release
instructions.

```bash
poetry env use python3.12
poetry sync --with dev
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy
poetry run pytest
poetry build
poetry run python scripts/smoke_package.py
```

## Package identity

- Repository: `trace-sdk`
- Distribution name: `bloch-trace`
- Python import: `bloch_trace`

The distribution can be built and installed locally without being published.
After installing with Poetry:

```python
import bloch_trace

print(bloch_trace.__version__)
```
