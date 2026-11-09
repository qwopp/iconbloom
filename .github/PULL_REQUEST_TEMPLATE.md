## What and why

## How it was checked

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- [ ] Goldens regenerated and reviewed (only if a recipe's look changed on purpose)
- [ ] CHANGELOG.md updated under Unreleased
