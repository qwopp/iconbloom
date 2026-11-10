# Architecture

Iconbloom has three layers. Dependencies only point downward.

```
app/            Qt window, CLI, IconService (the only code that changes shortcuts)
  |
  +-- engine/         Pure image code: ops, recipes, themes, color analysis, .ico writer
  +-- platform_win/   Windows: shortcut scan, IShellLink, icon extraction, backup manifest

themes/         Data: one folder per theme, plus _library/ (shared recipes and drawings)
scripts/        Developer tools; never imported by the app
```

## engine/ (OS-free)

`engine/` never touches the operating system. A test fails the build if it imports anything
Windows- or Qt-specific, and the Ubuntu CI job runs its tests. That keeps it reusable for a
future macOS port.

- `ops.py`: pure `Image -> Image` functions such as `tint`, `tile`, `sticker_outline` and
  `badge`. Every op keeps the image size and leaves a 2 px transparent border.
- `recipes.py`: the op registry, parameter checking, and `render()`. Theme-level values (palette
  names, asset names, shuffle choices) are turned into concrete values here, so ops stay pure.
  Seed 0 always renders the default look.
- `themes.py`: loads `themes/<id>/theme.json` and its PNG assets, resolving recipes listed
  by id from the shared `themes/_library/recipes.json`.
- `families.py`: the kinds of recipe (recolor, tile, sticker, tint...). Themes keep two of a
  kind apart, and color-flattening ones move last for colorful icons.
- `analyze.py`: colorfulness (Hasler-Suesstrunk) for recipe order, and dominant hue for
  `"auto"` colors.
- `ico.py`: multi-size `.ico` writer. The 16 and 24 px frames come from a simplified render.
- `sheet.py`: the contact sheet CLI.
- `taskbar.py`: taskbar looks worked out from a theme's palette (dark enough for white text),
  and a picture of the taskbar with them. `python -m engine.taskbar` draws a sheet of them.

Decorations are SVG templates in `themes/_library/decorations/`, colored per theme by
`scripts/render_assets.py` into committed PNGs; the app never renders SVG.

## platform_win/

pywin32 is imported inside the functions that need it, so the data types and the backup logic
load and are tested on any OS.

- `shortcuts.py`: the data model and scanning. An item ("shortcut") is a `.lnk` or `.url`
  file, a desktop folder, or a Windows icon such as the Recycle Bin (`::{CLSID}`). Scanning
  uses the shell's known folders (and up to three folders deep on the desktop), never
  reads OneDrive online-only files, filters out uninstallers and readmes, and groups items
  that run the same program with the same arguments or the same name.
- `item_io.py`: one `ItemIO` per kind of item. Each reads and sets the icon, and saves or
  restores the full state that decides it, so backups work the same way for all of them:
  `ShellLinkIO` (IShellLink), `UrlFileIO` (INI), `FolderIO` (`desktop.ini` plus the
  folder's read-only bit) and `ItemRouter`, which picks one by path.
- `shell_icons.py`: Windows' own desktop icons, through the per-user
  `Explorer\CLSID\{...}\DefaultIcon` registry key behind a small `Registry` interface.
- `ini.py`: edits `.url` and `desktop.ini` files line by line, keeping everything else.
- `extract.py`: gets the original icon at full size. It reads the shortcut's icon location
  first (including system icons that moved to `SystemResources\*.mun`), then the target
  executable. It falls back to the shell's own rendering, which covers Store apps.
- `backup.py`: the manifest of originals (each item's saved state, where "nothing there"
  is a valid original). Writes are atomic, the previous generation is kept,
  and a damaged file is refused rather than overwritten. `TaskbarBackup` keeps the same
  promises for `taskbar.json`.
- `taskbar.py`: the taskbar's per-user settings (accent color, frosted glass, alignment,
  buttons, auto-hide): reading them, planning only the writes a change needs, and saving
  and restoring them. All of them apply live; no Explorer restart.
- `refresh.py`: tells Explorer which shortcuts changed, refreshes the icon cache for taskbar
  pins, and (only when asked) restarts Explorer with its icon cache files deleted, since
  the taskbar otherwise redraws long-standing pins from pictures saved there.
- `elevate.py`: starts an elevated copy of the app through Windows' permission prompt.
- `fileio.py`: the one crash-safe write (temp file, fsync, rename) used for the manifest,
  restored shortcuts, choices and settings.

## app/

- `service.py`: `IconService`, used by both the UI and the CLI: scanning, status, apply,
  revert and reapply. Every change follows the same order: write the `.ico`, save the backup
  entry, point the item at the `.ico`, then note the item's new state. Revert restores the
  saved state if nothing else has touched the item since, and otherwise only its icon.
  Revert all also reverts the taskbar.
- `taskbar.py`: `TaskbarService`, the taskbar's apply and revert, in the same order as
  icons (save the originals, write, note what was applied). Revert puts back only settings
  still as Iconbloom left them, so ones the user changed in Settings since stay theirs.
- `styles.py`: themes, rendering a choice, and the files that come out of it (generated
  icons, variants such as the Recycle Bin's "full", and saved pictures of originals).
- `changes.py`: `ChangeReport` (what a change did) and `Status` (original, themed, skipped,
  needs reapply).
- `elevation.py`: changes to shortcuts every user shares. The app writes a request file and
  runs an elevated copy of itself, which validates every item on its own (only shortcut
  files inside the shared folders, only the icon, only Iconbloom's icons or the recorded
  original) before touching anything.
- `choices.py`, `settings.py`: which style each app got (powers **Reapply my icons**) and
  which own image it uses, and the user's preferences.
- `updates.py`: the update check and the checksum-verified download.
- `cli.py`, `main.py`: entry points.

### app/ui/

One module per part of the window. Panels talk to `MainWindow` through signals, and every
slow step runs on `JobRunner`'s thread pool, so the window never freezes.

- `main_window.py`: assembles the panels, the top bar (with the Icons | Taskbar switch) and
  the More menu, and turns button presses into changes.
- `shortcut_list.py`: the left panel: search, place tabs, tiles and selection.
- `style_picker.py`: the right panel: previews, the hover comparison, the multi-select strip
  and the action buttons.
- `taskbar_page.py`: the Taskbar page: a live picture of the taskbar, the theme's looks and
  the layout switches. Controls only redraw the picture; Apply and Revert go through
  `TaskbarService`.
- `change_runner.py`: runs a change in the background with a progress dialog, asks about
  shared shortcuts, and reports skipped items.
- `update_flow.py`, `notice.py`: the update banner and the banner widget itself.
- `jobs.py`, `controls.py`, `widgets.py`: background jobs, shared helpers, and the painted
  tiles, cards and popup.
- `palette.py`: every UI color by name, light and dark. `style.qss` is a template that
  uses those names, so switching modes is one restyle.

## scripts/

- `render_assets.py`: fills each decoration template with a theme's `decor` colors and
  writes the PNGs the app loads.
- `bundle.py`: the theme files the packaged app ships, used by the PyInstaller spec.
- `make_screenshots.py`: the README images, from the real window offscreen.
- `make_samples.py`, `make_app_icon.py`: the test sample icons and Iconbloom's own icon.
- `release_notes.py`: a version's CHANGELOG section, for the GitHub release.

## Runtime data

Everything lives in `%LOCALAPPDATA%\Iconbloom\`: `icons\` (generated `.ico` files),
`originals\` (byte copies of shortcuts), `backup.json`, `taskbar.json`, `choices.json`,
`settings.json`, `custom\` (images from **Use my own image**) and `logs\`.

## Testing

- The `tests/goldens/` images pin every recipe's output: Kawaii Pink on every sample icon,
  the other themes on five representative ones. A rules test checks every bundled theme
  (20 styles, a recolor first, no two neighbors of the same family, then the cut-out row).
- Hypothesis property tests check the op invariants.
- `tests/fakes.py` stands in for the user's shortcut folders (`FakeDesktop`) and for
  `IShellLink` (JSON files), so apply/revert, crash and corruption scenarios run on every OS.
- `tests/win/` repeats the key checks on real `.lnk` files in temp folders, on the Windows CI
  runner only.
- pytest-qt drives the real window offscreen.
- Other tests keep the edges honest: every theme loads from exactly the files the installer
  ships, committed PNGs match their SVGs, docs links resolve, the theme guide's example
  works, and the version matches everywhere.
