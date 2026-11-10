# Changelog

All notable changes to Iconbloom are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Store apps** such as the new Outlook, Game Bar and Calculator are in the list now.
  Styling one puts a themed copy on your desktop and shows how to pin it in place of the
  old taskbar icon, since Windows only lets you pin things yourself. Its open window joins
  that pin. **Revert** removes the desktop copy, and a pin you made keeps working with the
  app's own icon, even after uninstalling.

## [0.7.0] - 2026-11-09

### Added

- A **Taskbar** page (switch at the top of the window) gives the taskbar itself your theme's
  look, with a live preview: a soft or deep theme color or Windows' own, frosted glass,
  centered or left, smaller buttons, the search box, Task view and hiding automatically.
  Everything changes instantly through Windows' own settings, with no Explorer restart.
  Colors are darkened just enough for the white clock to stay readable.
  The preview uses your own taskbar icons, and your wallpaper when Windows has a picture of it.
- **Revert** on the page, **Revert all** and uninstalling put the taskbar back the way it was.
  Anything you changed yourself in Windows' Settings since stays as you set it.
- From the command line: `iconbloom-cli taskbar apply --look deep --frosted --left`,
  `iconbloom-cli taskbar revert`, and `python -m engine.taskbar` to preview a theme's looks.

## [0.6.1] - 2026-11-09

### Fixed

- **Use my own image** is remembered for each app, so its styles keep coming from your
  image after clicking another icon or restarting, until you choose **Use the app's icon**.

## [0.6.0] - 2026-11-09

### Added

- Four more cut-out styles: colors swapped (a white logo with pink lines turns pink with white
  lines), two-tone, tint and sticker.

## [0.5.2] - 2026-11-09

### Fixed

- **Refresh icons** no longer puts the old icon back on taskbar pins. Windows saves each
  pin's picture in an icon cache on disk, and after Explorer restarted the taskbar used that
  old picture. The refresh now deletes the cache while Explorer is closed, so every icon is
  drawn fresh.

## [0.5.1] - 2026-11-09

### Changed

- Switching back to Iconbloom picks up shortcuts added, removed or changed since it opened,
  without restarting it.

## [0.5.0] - 2026-11-09

### Added

- **Use my own image…** now shows every style of the theme on your picture, not just the
  picture as it is. **Use the app's icon** goes back.
- A **Cut out** row of four styles that removes a plain background (like a colored square
  behind a logo) and keeps the logo, as it is, recolored, in one color or on a new theme
  tile. It shows up for icons and images that have such a background.

### Changed

- After **Apply**, Iconbloom stays on the icon you just styled, with that style still
  picked, instead of jumping to the next one. **Skip** still moves on.

## [0.4.1] - 2026-11-09

### Fixed

- Updating Iconbloom put its shortcut back on the desktop every time, even after you moved
  or deleted it, and reset a restyled Start menu shortcut. Updates now leave Iconbloom's own
  shortcuts as you left them, starting with this update.
- A styled folder could keep showing the plain yellow folder, even after **Refresh Windows
  icons**: Explorer kept an old thumbnail of it. Iconbloom now sets folder icons through
  Windows' own Change Icon call too, which replaces that thumbnail.

## [0.4.0] - 2026-11-09

### Added

- Four new themes: **Mint Matcha**, **Lavender Dream**, **Peach Sunset** and
  **Midnight Neon**.
- 20 styles per theme (up from 12), including polka-dot, gingham and striped tiles and new
  hand-drawn stars, flowers, clouds, moons, leaves and suns.
- **More → Dark mode**. Until you choose, Iconbloom follows Windows' app mode.
- Shortcuts inside folders on your desktop (up to three folders deep). A copy of an app
  that's already on your desktop joins its tile and is styled with it.

### Changed

- Styles appear in a curated order: the biggest color changes first, and never two of the
  same kind side by side. Colorful icons still get their tints last.

### Fixed

- One corrupt or locked shortcut could stop the whole scan; it is now skipped like any
  unreadable file.
- The scan never opens OneDrive online-only files, which would download them.

## [0.3.2] - 2026-11-09

### Fixed

- A background task that finished very quickly could lose its result (an update notice or
  a shortcut scan, for example), because its result arrived before anything was listening.

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

[Unreleased]: https://github.com/qwopp/iconbloom/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/qwopp/iconbloom/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/qwopp/iconbloom/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/qwopp/iconbloom/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/qwopp/iconbloom/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/qwopp/iconbloom/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/qwopp/iconbloom/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/qwopp/iconbloom/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/qwopp/iconbloom/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/qwopp/iconbloom/compare/v0.3.0...v0.3.2
[0.3.0]: https://github.com/qwopp/iconbloom/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qwopp/iconbloom/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qwopp/iconbloom/releases/tag/v0.1.0
