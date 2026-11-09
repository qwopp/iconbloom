# Iconbloom

Restyles Windows desktop icons into one matching theme. Python 3.12, PySide6, managed with uv.

@docs/ARCHITECTURE.md
@CONTRIBUTING.md

## Working here

- Development happens in WSL. Everything runs on Linux except `tests/win/` and the app window;
  Windows behavior is covered by fakes in `tests/fakes.py`.
- Gate every commit, merge and tag on the check's own exit code. Never chain `&&` after a pipe
  such as `pytest | tail -1`. Merge only after `gh pr checks N --watch` passes.
- When goldens change, look at every changed PNG and a contact sheet before committing.
- Keep docs short. The README stays at 40 lines or fewer and free of version numbers (`test_docs`
  enforces both).
- One PR per change, each with a line under `## [Unreleased]` in `CHANGELOG.md`.
