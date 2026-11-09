# Changelog

All notable changes to Iconbloom are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-11-09

### Changed

- Update checks are on by default, with no first-run question. Iconbloom asks GitHub for
  the latest version when it opens, and still installs nothing unless you click
  **Update now**. Anyone who already said no keeps it off; untick **Check for updates** to
  turn it off.

## [0.3.0] - 2026-11-09

### Added

- Game and web shortcuts (`.url` files, which Steam and Epic use for desktop shortcuts).
- Folders on the desktop, through the same hidden `desktop.ini` Windows uses.
- The Recycle Bin (with styled empty and full versions), This PC, Network and your user
  folder, through the same per-user setting as Windows' Desktop icon settings.
- A picture of each item's original icon is saved when it's first styled, so previews and
  Reapply still work for items whose original Windows can no longer show (Store apps,
  folders, the Recycle Bin).
- The detail line says where a style applies (Desktop, Taskbar, Start menu).

### Changed

- Shortcuts that run the same program and have the same name are one app, even when their
  arguments differ (Discord's desktop and Start menu shortcuts, for example). Different
  Chrome profiles, web apps and games launched through one program stay separate.
- An app whose shortcuts are only partly styled (an update recreated one of them) is marked
  "needs reapply".

### Fixed

- **Use my own image…** failed with "'bool' object has no attribute 'read'". Every button
  and menu item now ignores the extra value Qt sends when clicked, and the test clicks the
  real button.
- Paths with non-English characters are written to `.url` and `desktop.ini` files in a form
  Windows reads correctly.

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

[Unreleased]: https://github.com/qwopp/iconbloom/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/qwopp/iconbloom/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/qwopp/iconbloom/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qwopp/iconbloom/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qwopp/iconbloom/releases/tag/v0.1.0
