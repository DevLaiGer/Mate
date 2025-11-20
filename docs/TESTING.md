# Testing guide

Mate ships lightweight smoke tests to keep the base engine healthy while we iterate on UI/ML features.

## Tooling

- **pytest** for unit tests
- **pytest-qt** reserved for future UI interaction tests
- **coverage** configured via `pyproject.toml`
- **ruff / black / mypy** guard style and type safety

## Commands

```powershell
poetry run pytest
poetry run ruff check .
poetry run mypy src/mate
```

## Adding tests

- Prefer pure functions or service layers (event bus, settings, engines) for unit coverage.
- For Qt widgets, leverage `pytest-qt` fixtures once behaviors solidify.
- Mock OS-level primitives (`keyboard`, `sounddevice`) for deterministic runs.
