# Contributing

Thanks for helping! Bug reports, theme ideas and pull requests are all welcome.

## Setup

```bash
uv sync
uv run pre-commit install
```

The pre-commit hooks run the same checks as CI: `ruff check`, `ruff format` and `pyright`.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

- `engine/` is type-checked in strict mode and must stay OS-free (a test enforces it).
- `engine/` and `platform_win/backup.py` must keep at least 90% test coverage.
- Tests that need real Windows shortcuts go in `tests/win/`. They only run on Windows and must
  only create shortcuts inside a temp folder, never on a real desktop.

## Changing how a recipe looks

Recipe output is pinned by golden images. If you change an op or a theme on purpose,
regenerate the goldens and review every changed PNG in your diff:

```bash
uv run pytest tests/test_goldens.py --update-goldens
```

Also look at a contact sheet: `uv run python -m engine.sheet tests/samples`.

## Pull requests

- Keep commits small, with messages that explain why.
- Comments explain why, not what.
- Add or update tests with every behavior change, and add a line under `## [Unreleased]` in
  `CHANGELOG.md`.
- Artwork must be your own or clearly licensed for redistribution. No third-party icon packs
  or copyrighted characters.

## Releasing

1. Update the version in `pyproject.toml` and `app/__init__.py`, and move the Unreleased
   notes into a new section in `CHANGELOG.md`.
2. Merge, then tag: `git tag v0.2.0 && git push origin v0.2.0`.
3. The release workflow builds the installer, portable zip and checksums, and publishes the
   GitHub release using that version's CHANGELOG notes.
