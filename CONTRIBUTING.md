# Contributing to Ravelink

Thank you for helping improve Ravelink. Contributions are welcome through bug reports, feature requests, documentation updates, tests, and pull requests.

## Development Setup

1. Fork and clone the repository.
2. Create a virtual environment with Python 3.10 or newer.
3. Install the package in editable mode:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Pull Requests

- Keep changes focused and explain the motivation clearly.
- Add or update tests when behavior changes.
- Update documentation and examples when public APIs change.
- Run local checks before opening a pull request.

## Issues

Use the issue templates when reporting bugs or requesting features. Include versions, reproduction steps, expected behavior, and relevant logs for bug reports.

## Code Style

Ravelink targets typed, readable Python. Prefer clear async control flow, small public APIs, and compatibility with the supported Python versions listed in `pyproject.toml`.
