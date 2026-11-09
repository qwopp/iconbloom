# Architecture

Iconbloom has three layers. Dependencies only point downward.

```
app/            Qt window, CLI, IconService (the only code that changes shortcuts)
  |
  +-- engine/         Pure image code: ops, recipes, themes, color analysis, .ico writer
  +-- platform_win/   Windows: shortcut scan, IShellLink, icon extraction, backup manifest
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
- `themes.py`: loads `themes/<id>/theme.json` and its PNG assets.
- `analyze.py`: colorfulness (Hasler-Suesstrunk) for recipe order, and dominant hue for
  `"auto"` colors.
- `ico.py`: multi-size `.ico` writer. The 16 and 24 px frames come from a simplified render.
- `sheet.py`: the contact sheet CLI.

## platform_win/

pywin32 is imported inside the functions that need it, so the data types and the backup logic
load and are tested on any OS.

- `shortcuts.py`: the data model and scanning. An item ("shortcut") is a `.lnk` or `.url`
  file, a desktop folder, or a Windows icon such as the Recycle Bin (`::{CLSID}`). Scanning
  uses the shell's known folders, filters out uninstallers and readmes, and groups items
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
  and a damaged file is refused rather than overwritten.
- `refresh.py`: tells Explorer which shortcuts changed, refreshes the icon cache for taskbar
  pins, and (only when asked) restarts Explorer.
- `elevate.py`: starts an elevated copy of the app through Windows' permission prompt.
- `fileio.py`: the one crash-safe write (temp file, fsync, rename) used for the manifest,
  restored shortcuts, choices and settings.

## app/

- `service.py`: `IconService`, used by both the UI and the CLI. `apply(group, choice)` renders
  the choice itself, and `apply_many` runs batches (Apply style to all, Reapply) with
  per-shortcut failures reported and one Explorer refresh at the end. Every change follows the
  same order: write the `.ico`, save the backup entry, point the shortcut at the `.ico`, then
  note the shortcut's new hash. Revert restores the original bytes if nothing else has touched
  the shortcut since, and otherwise only its icon field.
- `elevation.py`: changes to shortcuts every user shares. The app writes a request file and
  runs an elevated copy of itself, which validates every item on its own (only `.lnk` files
  inside the shared folders, only the icon field, only Iconbloom's icons or the recorded
  original) before touching anything.
- `choices.py`: which style each app got, keyed by target so it survives app updates. This
  is what powers **Reapply my icons**.
- `ui/`: the picker window. Scanning, icon extraction, rendering and batches run on a thread
  pool, so the window never freezes. Results for a selection the user has moved away from
  are dropped.
- `cli.py`, `main.py`: entry points.

## Runtime data

Everything lives in `%LOCALAPPDATA%\Iconbloom\`: `icons\` (generated `.ico` files),
`originals\` (byte copies of shortcuts), `backup.json`, `choices.json`, `settings.json`,
`custom\` (images from **Use my own image**) and `logs\`.

## Testing

- The `tests/goldens/` images pin every recipe's output on every sample icon.
- Hypothesis property tests check the op invariants.
- `tests/fakes.py` stands in for the user's shortcut folders (`FakeDesktop`) and for
  `IShellLink` (JSON files), so apply/revert, crash and corruption scenarios run on every OS.
- `tests/win/` repeats the key checks on real `.lnk` files in temp folders, on the Windows CI
  runner only.
- pytest-qt drives the real window offscreen.
