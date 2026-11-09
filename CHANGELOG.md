# Changelog

All notable changes to Iconbloom are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-09

### Added

- Search box and Desktop / Taskbar / Start menu tabs above the shortcut list.
- Shortcuts shared by every user (the all-users Start menu and public desktop) can now be
  styled and reverted: Windows asks for administrator permission once per action, and you
  can choose to change only your own shortcuts instead.
- Select several shortcuts with Ctrl or Shift to preview a style on all of them and apply
  it together.
- A banner offering to refresh Windows' icons after a taskbar pin changes.
- Hover text on every button.
- One-click updates: after asking once whether to check for new versions, Iconbloom
  offers **Update now**, which downloads the installer, verifies its SHA-256 checksum and
  upgrades in place.

### Changed

- Desktop shortcuts are listed first, then taskbar pins, then the Start menu, with
  Windows' own tools last.
- Explorer is told exactly which shortcuts changed, and taskbar changes also refresh the
  icon cache, so icons update more reliably.
- Less common actions (Reapply my icons, Refresh Windows icons, Delete unused icon files)
  moved into a More menu.
- Hovering a style compares it with the original at one desktop size instead of two.

## [0.1.0] - 2026-11-09

First release.

### Added

- Picker window: your shortcuts on the left; twelve styled versions of the selected one
  on the right, with the best fits for that icon first; hover to compare at 32 and
  48 px; Apply, Skip and Revert.
- Kawaii Pink theme with 12 styles: pastel tint, soft tint, pastel recolor (on its own
  and on a cream tile), pink and cream bubble tiles, sticker, sticker with blush face,
  tile with bow, mono rose, pink-to-lavender tile, and tint with sparkle.
- Shuffle, Use my own image, Apply style to all, and Reapply my icons after app
  updates.
- Backups of every shortcut before its first change, Revert all, and an uninstaller
  that offers to restore every original icon.
- Multi-size `.ico` output (16 to 256 px) with simplified small sizes.
- `iconbloom-cli` (`python -m app.cli`) with `scan`, `apply`, `revert`, `revert-all`,
  `cleanup` and `reapply`; every changing command accepts `--dry-run`.
- Contact sheet renderer for previewing themes: `python -m engine.sheet`.
- Opt-in update check, off by default.
- Per-user installer and portable zip, with SHA-256 checksums.

[Unreleased]: https://github.com/qwopp/iconbloom/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/qwopp/iconbloom/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qwopp/iconbloom/releases/tag/v0.1.0
