# Contributing

## Development Workflow

1. Create and activate a local virtual environment.
2. Install development dependencies with `pip install -e ".[dev]"`.
3. Keep changes scoped to a single feature or fix.
4. Run formatting, linting, type checks, and tests before opening a pull request.

```bash
black .
ruff check .
mypy src scripts
pytest
```

## Configuration

Copy `.env.example` to `.env` and keep secrets out of version control.

## Trading Safety

Use paper trading and backtests before live execution. Live trading code should include explicit risk limits and logging.
