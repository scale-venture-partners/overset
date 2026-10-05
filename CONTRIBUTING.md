# Contributing

```console
uv sync
uv run ruff format src tests
uv run ruff check src tests
uv run pytest -q --cov
```

Integration tests need LibreOffice and poppler and skip themselves without them; CI runs them.
A new rule needs a code in the README table, an `--explain` text, and a test that builds a small
deck (see `tests/conftest.py`) and asserts the finding. Rendering changes should be checked against
a real LibreOffice render, not only unit tests.
