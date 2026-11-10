# Contributing

Thanks for helping! Bug reports, theme ideas and pull requests are all welcome.

## Setup

```bash
uv sync
uv run pre-commit install
```

The pre-commit hooks run the same checks as CI: `ruff check`, `ruff format` and `pyright`.

## Handy commands

```bash
uv run python -m app.main                  # the app
uv run python -m app.cli scan              # list what Iconbloom sees, changing nothing
uv run python -m app.cli revert-all        # undo everything (every changing command takes --dry-run)
uv run python -m engine.sheet tests/samples --theme mint_matcha -o sheet.png   # preview a theme, any OS
uv run python -m scripts.render_assets     # re-render decorations after editing an SVG or decor colors
QT_QPA_PLATFORM=offscreen uv run python -m scripts.make_screenshots --icons DIR   # README images
```

To build the installer locally, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then:

```powershell
uv sync --group release
uv run pyinstaller installer/iconbloom.spec --noconfirm
iscc /DAppVersion=0.0.0 installer\iconbloom.iss
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

- `engine/` is type-checked in strict mode and must stay OS-free (a test enforces it).
- `engine/` and `platform_win/backup.py` must keep at least 90% test coverage.
- Tests that need real Windows shortcuts go in `tests/win/`. They only run on Windows and must
  only create shortcuts inside a temp folder, never on a real desktop.
- The installer build runs only on pull requests that touch packaging. A file the app reads
  at runtime must be in `installer/iconbloom.spec` (theme files come from `scripts/bundle.py`).

## Changing how a recipe looks

Recipe output is pinned by golden images. If you change an op or a theme on purpose,
regenerate the goldens and review every changed PNG in your diff:

```bash
uv run pytest tests/test_goldens.py --update-goldens
```

Also look at a contact sheet: `uv run python -m engine.sheet tests/samples`.

## Adding a bundled theme

[docs/THEMES.md](docs/THEMES.md) explains the format. A theme that ships with Iconbloom also
follows the house rules, which a test checks: 20 styles with a `recolor` first and never two
of the same family side by side, then the library's eight `cutout` styles as the last row. Then:

1. Render its decorations: `uv run python -m scripts.render_assets my_theme`.
2. Look at contact sheets of the samples and some real app icons, at full and taskbar size.
3. Add its goldens: `uv run pytest tests/test_goldens.py --update-goldens`.

## Pull requests

- Keep commits small, with messages that explain why.
- Comments explain why, not what.
- Add or update tests with every behavior change, and add a line under `## [Unreleased]` in
  `CHANGELOG.md`.
- Artwork must be your own or clearly licensed for redistribution. No third-party icon packs
  or copyrighted characters.

## Releasing

1. Update the version in `pyproject.toml` and `app/__init__.py` (a test checks they match),
   and move the Unreleased notes into a new section in `CHANGELOG.md`.
2. Run every check again after the bump, then merge only once CI passes.
3. Tag the merge: `git tag -a vX.Y.Z -m "Iconbloom X.Y.Z" && git push origin vX.Y.Z`.
4. The release workflow builds and smoke-tests the installer and portable zip, writes
   checksums, and publishes the GitHub release with that version's CHANGELOG notes. Check it
   finished: `gh run watch --exit-status`.
